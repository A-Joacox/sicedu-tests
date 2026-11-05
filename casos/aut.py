"""Autenticación (CU001 a CU007): CP01 a CP25, adaptados a QA. CP22 queda solo en local.

- Los casos que cambian contraseñas, bloquean o inactivan una cuenta usan las cuentas de Autenticación
  de la suite (…+sicedu-aut-…), que no se usan en ningún otro módulo. Su contraseña vigente queda en
  estado/claves.json: así no hay que volver a la clave original después de cada caso.
- Los PIN y las contraseñas temporales llegan a tu correo: la suite se detiene y pide pegarlos. Si en
  QA_ESPERA_CORREO minutos (10 por defecto) no se pega nada, el paso queda como NOTA y el caso sigue.
- Lo que en local se veía en la base de datos (sesiones, hash) se verifica por la API o queda como NOTA.
"""
import base64
import datetime as dt
import json
import re
import time

from lib import api as A
from lib import config
from lib import correo as CO
from lib import datos as D
from lib.catalogo import SOLO_LOCAL, caso
from lib.ui import (BASE, Nav, Run, cola_idb, con_actividad, idb_todo, ir, ir_login, llenar_login, login, logout, main_txt,
                    toasts_txt, token_navegador)

from casos._comun import fin, hhmmss, menu, sup_ui, visitar

SOLO_LOCAL['CP22'] = ('Necesita cambiar la contraseña del servicio de correo en el .env del backend y reiniciarlo, y leer '
                      'sus logs (docker logs).')


# ── Ayudas ──────────────────────────────────────────────────────────────────────────

def storage(p):
    try:
        ls = p.evaluate('JSON.stringify(localStorage)')
        ss = p.evaluate('JSON.stringify(Object.keys(sessionStorage))')
    except Exception as e:
        ls, ss = str(e)[:60], ''
    try:
        idb = list(json.loads(idb_todo(p)).keys())
    except Exception as e:
        idb = str(e)[:60]
    return {'localStorage': ls[:600], 'sessionStorage (claves)': ss, 'cookies': [c['name'] for c in p.context.cookies()], 'IndexedDB (almacenes)': idb}


def lineas(d):
    return [f'{k}: {v}' for k, v in d.items()]


def alerta(p):
    try:
        return [t.strip() for t in p.locator('[role=alert]').all_inner_texts() if t.strip()]
    except Exception:
        return []


def intentar_login(p, correo, clave):
    """Envía el formulario de login y devuelve (HTTP, mensajes, URL)."""
    ir_login(p)
    llenar_login(p, correo, clave)
    st = None
    try:
        with p.expect_response(lambda r: r.url.endswith('/api/login') and r.request.method == 'POST', timeout=8000) as ri:
            p.click('button[type=submit]')
        st = ri.value.status
    except Exception:
        pass
    p.wait_for_timeout(1500)
    return st, alerta(p) + toasts_txt(p), p.url.replace(BASE, '')


def jwt(tk):
    try:
        cuerpo = tk.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(cuerpo + '=' * (-len(cuerpo) % 4)))
    except Exception:
        return {}


def cuenta_aut(et):
    """Cuenta de Autenticación lista y activa (la crea si falta: pide su contraseña temporal)."""
    uid = D.id_usuario(et)
    if not uid:
        asg = A.asignacion([(D.Y(), [1])]) if D._def(et)[0] == 'Docente' else None
        uid = D.asegurar_cuenta(et, asg)
    return D.cuenta(et), uid


def activar(uid, valor=True):
    return A.api('PATCH', f'/usuarios/{uid}/{"activar" if valor else "desactivar"}', A.sup(), {})[0]


def abrir_recuperar(p, correo=None):
    ir_login(p)
    p.get_by_role('button', name=re.compile('¿Olvid(ó su|aste tu) contraseña?')).click()
    p.locator('[role=dialog]').wait_for()
    if correo is not None:
        p.locator('[role=dialog] input[type=email]').fill(correo)


def pedir_pin(p):
    p.locator('[role=dialog]').get_by_role('button', name='Enviarme el PIN').click(); p.wait_for_timeout(1800)
    d = p.locator('[role=dialog]:visible')
    return toasts_txt(p) + ([d.last.inner_text()[:300].replace('\n', ' | ')] if d.count() else [])


def ingresar_pin(p, pin):
    d = p.locator('[role=dialog]:visible').last
    d.locator('input[inputmode=numeric]').fill(pin)
    b = d.get_by_role('button', name='Verificar y continuar')
    if b.count() and b.is_enabled():
        b.click()
    p.wait_for_timeout(1500)
    d = p.locator('[role=dialog]:visible')
    return toasts_txt(p), (d.last.inner_text()[:500].replace('\n', ' | ') if d.count() else '')


def nueva_clave_ui(p, nueva, conf=None):
    d = p.locator('[role=dialog]:visible').last; pw = d.locator('input[type=password]')
    pw.nth(0).fill(nueva); pw.nth(1).fill(nueva if conf is None else conf); p.wait_for_timeout(400)
    b = d.get_by_role('button', name='Cambiar contraseña')
    return b


def flujo_pin(R, p, correo_, etiqueta, chk):
    """Pide un PIN desde la pantalla y lo obtiene del correo. Devuelve el PIN o None."""
    t0 = time.time() - 2
    abrir_recuperar(p, correo_)
    R.shot(p, f'{etiqueta}: "¿Olvidaste tu contraseña?" con {correo_}')
    chk[f'{etiqueta}_mensaje'] = pedir_pin(p)
    R.shot(p, f'{etiqueta}: mensaje tras pedir el PIN: {chk[f"{etiqueta}_mensaje"]}')
    pin = CO.pin(correo_, t0)
    if not pin:
        R.nota(f'{etiqueta}: no se obtuvo el PIN enviado a {correo_}; los pasos que lo necesitan no se ejecutaron.')
    return pin


def verificar_api(correo_, pin):
    return A.api('POST', '/password/verificar-codigo', body={'correo': correo_, 'codigo': pin})


# ── Inicio de sesión ────────────────────────────────────────────────────────────────

@caso('CP01')
def cp01():
    R = Run('CP01'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a')
    A.cerrar_abiertas(C)
    ir_login(p); R.shot(p, 'Pasos 1-2: formulario de inicio de sesión')
    login(p, C)
    chk['url'] = p.url.replace(BASE, ''); chk['main'] = main_txt(p)[:600]
    b = p.get_by_role('button', name='Iniciar actividad')
    chk['iniciar'] = (b.count(), b.first.is_enabled() if b.count() else None)
    chk['asignaciones_api'] = A.api('GET', '/me/asignaciones', token_navegador(p))[1]
    chk['menu'] = menu(p)
    R.shot(p, f'Pasos 3-5: Docente A entra a {chk["url"]}; "Iniciar actividad" (cantidad, habilitado) {chk["iniciar"]}', full=True)
    R.consola(ctx, 'Paso 5: asignaciones del Docente (GET /api/me/asignaciones)', [json.dumps(chk['asignaciones_api'], ensure_ascii=False)[:900]])
    R.shot(p, f'Paso 6: barra lateral: {chk["menu"]}')
    fin(R, chk, n, C)


@caso('CP02')
def cp02():
    R = Run('CP02'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; S = sup_ui()
    st403 = []
    p.on('response', lambda r: st403.append(r.url.split('/api')[-1]) if r.status == 403 else None)
    ir_login(p); R.shot(p, 'Pasos 1-2: formulario de inicio de sesión')
    login(p, S)
    chk['url'] = p.url.replace(BASE, ''); chk['main'] = main_txt(p)[:700]; chk['iniciar'] = p.get_by_role('button', name='Iniciar actividad').count()
    chk['api'] = A.api('GET', '/inicio/supervisor', token_navegador(p))[1]
    R.shot(p, f'Pasos 3-6: la Supervisora entra a {chk["url"]}; "Iniciar actividad": {chk["iniciar"]} botones', full=True)
    R.consola(ctx, 'Paso 5: resumen operativo (GET /api/inicio/supervisor)', [json.dumps(chk['api'], ensure_ascii=False)[:1200]])
    urls = []
    for _ in range(2):
        logout(p); login(p, S); urls.append(p.url.replace(BASE, ''))
    chk['reintentos'] = urls; chk['403'] = st403
    R.shot(p, f'Paso 7: dos inicios de sesión más: {urls}; respuestas 403: {st403}')
    fin(R, chk, n)


@caso('CP03')
def cp03():
    R = Run('CP03'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; Dr = D.cuenta('directivo')
    st403 = []
    p.on('response', lambda r: st403.append(r.url.split('/api')[-1]) if r.status == 403 else None)
    ir_login(p); R.shot(p, 'Pasos 1-2: formulario de inicio de sesión')
    login(p, Dr)
    chk['url'] = p.url.replace(BASE, ''); t = main_txt(p); chk['main'] = t[:700]
    chk['menu'] = menu(p); chk['iniciar'] = p.get_by_role('button', name='Iniciar actividad').count()
    chk['inputs'] = p.locator('main input, main select, main textarea').count()
    chk['graficos'] = p.locator('main svg, main canvas').count()
    chk['api'] = A.api('GET', '/inicio/directivo', token_navegador(p))[1]
    R.shot(p, f'Pasos 3-6: el Directivo entra a {chk["url"]} (403: {st403}); menú {chk["menu"]}; formularios {chk["inputs"]}; '
              f'"Iniciar actividad" {chk["iniciar"]}; gráficos {chk["graficos"]}', full=True)
    nombres = [k for k in D.estado()['alumnos']]
    chk['nombres_visibles'] = [x for x in nombres if x in p.locator('body').inner_text()]
    R.consola(ctx, 'Pasos 5 y 7: tarjetas (GET /api/inicio/directivo) y nombres de alumnos en pantalla',
              [json.dumps(chk['api'], ensure_ascii=False)[:600], f'Alumnos del caso buscados en la pantalla: {len(nombres)}; encontrados: {chk["nombres_visibles"] or "ninguno"}'])
    fin(R, chk, n)


@caso('CP04')
def cp04():
    R = Run('CP04'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    ir_login(p); R.shot(p, 'Pasos 1-2: formulario de inicio de sesión')
    chk['no_registrado'] = intentar_login(p, config.correo_de(f'no-existe-{hhmmss()}'), 'ClaveQueNoEs#2026')
    R.shot(p, f'Pasos 3-6: correo no registrado: {chk["no_registrado"]}')
    chk['clave_mala'] = intentar_login(p, D.cuenta('docente-a').correo, 'ClaveIncorrecta#9')
    R.shot(p, f'Pasos 3-6: correo registrado con contraseña incorrecta: {chk["clave_mala"]}')
    chk['mismo_mensaje'] = chk['no_registrado'][1] == chk['clave_mala'][1]
    R.consola(ctx, 'Pasos 5-6', [f'Mismo mensaje en los dos casos: {chk["mismo_mensaje"]}', f'Token en el navegador: {token_navegador(p)}'])
    fin(R, chk, n)


@caso('CP05')
def cp05():
    R = Run('CP05'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    C, uid = cuenta_aut('aut-inactivo')
    if not uid:
        R.nota('La cuenta aut-inactivo no existe y no se pudo crear (falta su contraseña temporal).'); R.save(checks=chk); n.close(); return
    if (A.usuario_por_correo(C.correo) or {}).get('activo'):
        activar(uid, False)
    chk['estado'] = {k: (A.usuario_por_correo(C.correo) or {}).get(k) for k in ('activo', 'debe_cambiar_contrasena')}
    ir_login(p); R.shot(p, f'Pasos 1-2: formulario; la cuenta {C.correo} está inactiva {chk["estado"]}')
    chk['login'] = intentar_login(p, C.correo, C.clave)
    chk['storage'] = storage(p); chk['token'] = token_navegador(p)
    R.shot(p, f'Pasos 3-7: con la contraseña correcta: HTTP {chk["login"][0]}; mensaje {chk["login"][1]}; queda en {chk["login"][2]}')
    s, r = A.api('POST', '/login', body={'correo': C.correo, 'password': C.clave})
    R.consola(ctx, 'Pasos 7-8: respuesta y almacenamiento', [f'POST /api/login → HTTP {s} {json.dumps(r, ensure_ascii=False)[:250]}',
                                                           f'Token en el navegador: {chk["token"]}'] + lineas(chk['storage']))
    fin(R, chk, n)


@caso('CP06', notas='El tipo de cierre de la sesión (paso 9) está en la base de datos: queda como NOTA.')
def cp06():
    R = Run('CP06'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a')
    A.cerrar_abiertas(C)
    login(p, C); ir(p, 'Alumnos'); p.wait_for_timeout(1200)
    try:
        p.locator('main select').nth(1).select_option(index=1); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(800)
    except Exception as e:
        chk['filtro_alumnos'] = str(e)[:80]
    R.shot(p, 'Paso 1: Alumnos con un filtro aplicado')
    ir(p, 'Sesiones'); p.wait_for_timeout(1200)
    try:
        p.locator('main select').first.select_option(index=2); p.locator('main').get_by_role('button', name=re.compile('^(Filtrar|Buscar)')).first.click(); p.wait_for_timeout(800)
    except Exception as e:
        chk['filtro_sesiones'] = str(e)[:80]
    R.shot(p, 'Paso 1: Sesiones con un filtro de estado')
    tk = token_navegador(p); chk['antes'] = storage(p)
    R.consola(ctx, 'Paso 2: almacenamiento antes de cerrar sesión', [f'Token (copiado, no se muestra): {"sí" if tk else "no"}'] + lineas(chk['antes']))
    chk['hora'] = A.ahora().strftime('%H:%M:%S'); logout(p)
    chk['url'] = p.url.replace(BASE, '')
    R.shot(p, f'Pasos 3-4: "Cerrar sesión" a las {chk["hora"]}: queda en {chk["url"]}')
    chk['despues'] = storage(p); chk['token_tras'] = token_navegador(p)
    R.consola(ctx, 'Pasos 5-6: almacenamiento después de cerrar sesión', [f'Token en el navegador: {chk["token_tras"]}'] + lineas(chk['despues']))
    p.go_back(); p.wait_for_timeout(1500); chk['atras'] = p.url.replace(BASE, '')
    R.shot(p, f'Paso 7: botón "atrás": queda en {chk["atras"]}')
    chk['me'] = A.api('GET', '/me', tk) if tk else None
    R.consola(ctx, 'Paso 8: GET /api/me con el token anterior', [str(chk['me'])[:300]])
    R.nota('Paso 9: la hora de fin y el tipo de cierre "Manual" de la sesión están en la base de datos; en QA no hay una consulta para verlos.')
    p2 = n.ctx().new_page(); S = sup_ui(); login(p2, S); p2.wait_for_timeout(1500)
    chk['ls_sup'] = p2.evaluate('Object.keys(localStorage)')
    p2.evaluate("sessionStorage.removeItem('sicedu.token'); localStorage.removeItem('sicedu.token')"); p2.reload(); p2.wait_for_timeout(2000)
    chk['sup_sin_token'] = (p2.url.replace(BASE, ''), p2.evaluate('Object.keys(localStorage)'))
    login(p2, D.cuenta('directivo')); p2.wait_for_timeout(1500)
    chk['ls_directivo'] = p2.evaluate('Object.keys(localStorage)')
    chk['resumen_sup_visible'] = 'docentes' in main_txt(p2).lower() and 'vencidos' in main_txt(p2).lower()
    R.shot(p2, f'Paso 10: la Supervisora borra solo el token y recarga ({chk["sup_sin_token"]}); entra el Directivo: claves de Local Storage {chk["ls_directivo"]}')
    fin(R, chk, n, C)


# ── Recuperación de contraseña ───────────────────────────────────────────────────────

@caso('CP07')
def cp07():
    R = Run('CP07'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    for et, rol in [('aut-docente', 'Docente'), ('aut-supervisor', 'Supervisor')]:
        C, uid = cuenta_aut(et)
        if not uid:
            R.nota(f'{rol}: la cuenta {et} no está lista; se omite.'); continue
        anterior = C.clave
        pin = flujo_pin(R, p, C.correo, rol, chk)
        if not pin:
            continue
        t, txt = ingresar_pin(p, pin); chk[f'{rol}_tras_pin'] = txt[:300]
        R.shot(p, f'{rol} (pasos 5-6): PIN ingresado; segundo paso: {txt[:150]}')
        nueva = D.clave_nueva()
        b = nueva_clave_ui(p, nueva)
        b.click(); p.wait_for_timeout(2200)
        chk[f'{rol}_cambio'] = (toasts_txt(p), p.url.replace(BASE, ''))
        D.guardar_clave(et, nueva)
        R.shot(p, f'{rol} (pasos 7-8): nueva contraseña confirmada: {chk[f"{rol}_cambio"]}')
        login(p, A.Cuenta(C.correo, nueva)); chk[f'{rol}_login_nueva'] = p.url.replace(BASE, '')
        R.shot(p, f'{rol} (paso 9): con la nueva contraseña entra a {chk[f"{rol}_login_nueva"]}')
        logout(p)
        chk[f'{rol}_login_vieja'] = intentar_login(p, C.correo, anterior)
        R.shot(p, f'{rol} (paso 10): con la contraseña anterior: {chk[f"{rol}_login_vieja"][1]}')
        chk[f'{rol}_pin_reuso'] = verificar_api(C.correo, pin)
        R.consola(ctx, f'{rol}: reutilizar el PIN ya usado', [f'POST /api/password/verificar-codigo con el mismo PIN → {chk[f"{rol}_pin_reuso"]}'])
    # Paso 12: correo no registrado y cuenta desactivada
    Ci, ui = cuenta_aut('aut-inactivo')
    for etiqueta, correo_ in [('no registrado', config.correo_de(f'no-existe-{hhmmss()}')), ('cuenta desactivada', Ci.correo)]:
        abrir_recuperar(p, correo_); chk[f'pin_{etiqueta}'] = pedir_pin(p)
        R.shot(p, f'Paso 12: PIN para un correo {etiqueta}: {chk[f"pin_{etiqueta}"]}')
    if CO._buzon():
        chk['llego_desactivada'] = CO.llego_correo(Ci.correo, time.time() - 30)
        R.consola(ctx, 'Paso 12: ¿llegó un PIN a la cuenta desactivada?', [str(chk['llego_desactivada'])])
    else:
        R.nota(f'Paso 12: revisa en tu bandeja que NO llegó un PIN a {Ci.correo} (cuenta desactivada).')
    fin(R, chk, n)


@caso('CP08', modo='parcial', notas='La espera de 8 horas no se hace: se verifica la vigencia del token (exp - iat).')
def cp08():
    R = Run('CP08'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; S = sup_ui()
    login(p, S); t0 = A.ahora(); tk = token_navegador(p); cl = jwt(tk)
    chk['claims'] = {k: cl.get(k) for k in ('iat', 'exp')}; chk['vigencia_s'] = (cl.get('exp', 0) - cl.get('iat', 0)) if cl else None
    chk['me'] = A.api('GET', '/me', tk)[0]
    R.shot(p, f'Paso 1: sesión iniciada a las {t0:%H:%M:%S}')
    R.consola(ctx, 'Paso 2: token decodificado', [f'iat = {cl.get("iat")}, exp = {cl.get("exp")}; exp - iat = {chk["vigencia_s"]} s (se espera 28 800)',
                                                f'exp en hora del Perú: {dt.datetime.fromtimestamp(cl["exp"], A.LIMA):%d/%m/%Y %H:%M:%S}' if cl.get('exp') else '',
                                                f'GET /api/me → HTTP {chk["me"]}'])
    R.nota('Pasos 3-9: la suite no espera 8 horas. La expiración (mensaje, 401, auditoría y cierre de la actividad) se verifica en local adelantando el reloj del servidor.')
    fin(R, chk, n)


@caso('CP09', notas='El tipo de cierre de la sesión en la auditoría queda como NOTA.')
def cp09():
    from casos.rub import abrir_rubrica, elegir, rub_de
    from casos.ses import acts
    R = Run('CP09'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a')
    con_actividad(p, C); tk = token_navegador(p); act = A.actividad_en_curso(tk)
    abrir_rubrica(p); ctx.set_offline(True); p.wait_for_timeout(600)
    chk['elegir'] = [elegir(p, 'Carla Norte QA', 'Fluidez', 'Logrado')[:2], elegir(p, 'Carla Norte QA', 'Comprensión', 'Logrado')[:2]]
    chk['cola'] = cola_idb(p)[:2]
    R.shot(p, f'Pasos 1-3: actividad iniciada, sin conexión, evaluación de Carla en Rúbrica: {chk["elegir"]}')
    R.consola(ctx, 'Paso 4: IndexedDB (cola)', [str(c)[:420] for c in chk['cola']] or ['(vacía)'])
    chk['hora'] = A.ahora().strftime('%H:%M:%S'); logout(p)
    chk['tras_logout'] = (p.url.replace(BASE, ''), len(cola_idb(p)), alerta(p) + toasts_txt(p))
    R.shot(p, f'Pasos 5-6: "Cerrar sesión" sin conexión a las {chk["hora"]}: {chk["tras_logout"]}')
    ctx.set_offline(False); p.wait_for_timeout(120000)
    chk['antes_login'] = rub_de('Carla Norte QA')
    R.consola(ctx, 'Paso 7: con conexión y sin iniciar sesión, 2 minutos después', [f'Rúbrica de Carla según la API: {chk["antes_login"]}'])
    login(p, C); p.wait_for_timeout(10000)
    chk['tras_login'] = (rub_de('Carla Norte QA'), len(cola_idb(p)))
    a = next((x for x in acts(token_navegador(p)) if x['id'] == act), None)
    chk['actividad'] = {k: a.get(k) for k in ('inicio', 'fin', 'tipo_cierre', 'sincronizacion')} if a else None
    R.shot(p, f'Pasos 8-9: tras volver a entrar: rúbrica {chk["tras_login"][0]}; cola {chk["tras_login"][1]}')
    R.consola(ctx, 'Pasos 8-9: la evaluación y la actividad por la API', [f'Rúbrica de Carla: {chk["tras_login"][0]}', f'Actividad del paso 1: {chk["actividad"]}'])
    R.nota('Paso 9: el cierre de la sesión en la auditoría (hora y causa) está en la base de datos; en QA no hay una consulta para verlo.')
    # Paso 10: recarga sin conexión antes de cerrar sesión
    A.cerrar_abiertas(C)
    ctx = n.ctx(); p = ctx.new_page()
    con_actividad(p, C); act2 = A.actividad_en_curso(token_navegador(p)); abrir_rubrica(p)
    ctx.set_offline(True); p.wait_for_timeout(500)
    elegir(p, 'Dante Norte QA', 'Fluidez', 'Logrado')
    p.reload(); p.wait_for_timeout(3000); chk['recarga_offline'] = p.locator('body').inner_text()[:250]
    R.shot(p, f'Paso 10: recarga sin conexión: {chk["recarga_offline"][:150]}')
    try:
        logout(p)
    except Exception as e:
        chk['logout_tras_recarga'] = str(e)[:80]
    ctx.set_offline(False); p.wait_for_timeout(1500)
    p.goto(BASE + '/inicio'); p.wait_for_timeout(3000); chk['tras_reconectar'] = p.url.replace(BASE, '')
    R.shot(p, f'Paso 10: con conexión otra vez, SICEDU abre {chk["tras_reconectar"]}')
    if '/login' not in p.url:
        try:
            logout(p)
        except Exception as e:
            chk['logout_con_conexion'] = str(e)[:80]
    login(p, C); p.wait_for_timeout(8000)
    a2 = next((x for x in acts(token_navegador(p)) if x['id'] == act2), None)
    chk['actividad2'] = {k: a2.get(k) for k in ('inicio', 'fin', 'tipo_cierre', 'sincronizacion')} if a2 else None
    det = A.api('GET', f'/actividades/{act2}', token_navegador(p))[1] if act2 else None
    R.consola(ctx, 'Paso 10: la actividad con recarga sin conexión', [f'Lista: {chk["actividad2"]}', f'Detalle: {json.dumps(det, ensure_ascii=False)[:500]}'])
    fin(R, chk, n, C)


@caso('CP10')
def cp10():
    R = Run('CP10'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a')
    login(p, C); logout(p); ir_login(p)
    ctx.set_offline(True); p.wait_for_timeout(1200)
    ing = p.locator('button[type=submit]'); olv = p.get_by_role('button', name=re.compile('Olvid'))
    chk['offline'] = {'ingresar_deshabilitado': ing.is_disabled(), 'olvide_deshabilitado': olv.first.is_disabled() if olv.count() else None,
                      'mensaje': [l for l in p.locator('body').inner_text().split('\n') if 'conexión' in l.lower()][:3]}
    R.shot(p, f'Pasos 1-3: login sin conexión: {chk["offline"]}')
    llenar_login(p, C.correo, C.clave); p.keyboard.press('Enter'); p.wait_for_timeout(1500)
    chk['enter'] = (p.url.replace(BASE, ''), token_navegador(p), storage(p))
    R.shot(p, f'Paso 4: Enter con credenciales válidas sin conexión: queda en {chk["enter"][0]}; token {chk["enter"][1]}')
    R.consola(ctx, 'Paso 4: almacenamiento', lineas(chk['enter'][2]))
    ctx.set_offline(False); p.wait_for_timeout(1500)
    chk['online'] = {'ingresar_habilitado': p.locator('button[type=submit]').is_enabled(), 'olvide_habilitado': olv.first.is_enabled() if olv.count() else None}
    login(p, C); chk['online']['entra'] = p.url.replace(BASE, '')
    R.shot(p, f'Paso 5: con conexión: {chk["online"]}')
    fin(R, chk, n, C)


@caso('CP11')
def cp11():
    R = Run('CP11'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    C, uid = cuenta_aut('aut-docente')
    if not uid:
        R.nota('La cuenta aut-docente no está lista.'); R.save(checks=chk); n.close(); return
    mala = 'ClaveIncorrecta#9'
    chk['intentos'] = [intentar_login(p, C.correo, mala)[:2] for _ in range(4)]
    R.shot(p, f'Paso 1: 4 intentos fallidos: {[x[1] for x in chk["intentos"]]}')
    chk['quinto'] = intentar_login(p, C.correo, mala); t5 = A.ahora()
    R.shot(p, f'Paso 2: quinto intento a las {t5:%H:%M:%S}: {chk["quinto"][:2]}')
    chk['correcta_bloqueada'] = intentar_login(p, C.correo, C.clave)
    R.shot(p, f'Paso 3: con la contraseña correcta: {chk["correcta_bloqueada"][:2]}')
    chk['sigue_activa'] = (A.usuario_por_correo(C.correo) or {}).get('activo')
    R.consola(ctx, 'Paso 4: la cuenta en Usuarios (API de la Supervisora)', [f'activo = {chk["sigue_activa"]}'])
    while A.ahora() < t5 + dt.timedelta(minutes=14):
        time.sleep(10)
    chk['minuto_14'] = intentar_login(p, C.correo, C.clave)
    R.shot(p, f'Paso 5: a los 14 minutos: {chk["minuto_14"][:2]}')
    while A.ahora() < t5 + dt.timedelta(minutes=15, seconds=20):
        time.sleep(5)
    chk['minuto_15'] = intentar_login(p, C.correo, C.clave)
    R.shot(p, f'Paso 6: pasados los 15 minutos: {chk["minuto_15"]}')
    if '/login' not in chk['minuto_15'][2]:
        logout(p)
    r7 = [intentar_login(p, C.correo, mala)[1] for _ in range(4)]
    ok7 = intentar_login(p, C.correo, C.clave)
    if '/login' not in ok7[2]:
        logout(p)
    r7b = [intentar_login(p, C.correo, mala)[1] for _ in range(4)]
    chk['reinicio'] = {'4_fallidos': r7, 'correcto': ok7[:2], '4_fallidos_otra_vez': r7b}
    R.shot(p, f'Paso 7: 4 fallidos, uno correcto y otros 4 fallidos: último mensaje {r7b[-1]}')
    intentar_login(p, C.correo, C.clave)
    if '/login' not in p.url:
        logout(p)
    Ci, _ = cuenta_aut('aut-inactivo')
    chk['no_registrado'] = [intentar_login(p, config.correo_de(f'no-existe-{hhmmss()}'), mala)[1] for _ in range(5)][-1]
    chk['desactivada'] = [intentar_login(p, Ci.correo, mala)[1] for _ in range(5)][-1]
    chk['estado_final'] = {'aut-docente': (A.usuario_por_correo(C.correo) or {}).get('activo'), 'aut-inactivo': (A.usuario_por_correo(Ci.correo) or {}).get('activo')}
    R.shot(p, f'Paso 8: quinto intento con un correo no registrado {chk["no_registrado"]} y con la cuenta desactivada {chk["desactivada"]}; estados {chk["estado_final"]}')
    fin(R, chk, n)


@caso('CP13')
def cp13():
    R = Run('CP13'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a')
    A.cerrar_abiertas(C); login(p, C)
    chk['inicio_usable'] = p.get_by_role('button', name='Iniciar actividad').count()
    R.shot(p, f'Paso 1: Inicio mientras se descargan los datos: "Iniciar actividad" visible = {chk["inicio_usable"]}')
    p.wait_for_timeout(5000); raw = idb_todo(p)
    norte = [k for k in D.estado()['alumnos'] if 'Sur QA' not in k][:60]; sur = [k for k in D.estado()['alumnos'] if 'Sur QA' in k]
    chk['idb'] = {'almacenes': list(json.loads(raw).keys()), 'alumnos_propios': sum(1 for x in norte if x.split(' ')[0] in raw),
                  'alumnos_ajenos': [x for x in sur if x.split(' ')[0] in raw], 'tiene_usuarios': '"correo"' in raw and 'sicedu-supervisor' in raw,
                  'hash': bool(re.search(r'\$2[aby]\$', raw)), 'password': 'password' in raw.lower() or 'contraseña' in raw.lower(),
                  'colegio_norte': D.nombre_colegio('norte') in raw, 'colegio_sur': D.nombre_colegio('sur') in raw}
    ls = p.evaluate('JSON.stringify(localStorage)')
    chk['ls_hash'] = bool(re.search(r'\$2[aby]\$', ls))
    R.consola(ctx, 'Pasos 2-3: IndexedDB del Docente', lineas(chk['idb']) + [f'Hash bcrypt en Local Storage: {chk["ls_hash"]}'])
    nuevo = f'Ana Renombrada {hhmmss()}'
    chk['patch'] = A.api('PATCH', f'/alumnos/{D.alumno("Ana Norte QA")}', A.sup(), {'nombres': nuevo})[0]
    ir(p, 'Inicio'); p.wait_for_timeout(6000)
    chk['actualizado'] = nuevo in idb_todo(p)
    R.consola(ctx, 'Paso 4: cambio de nombre de un alumno (por la API de la Supervisora; en local se hacía en la base de datos)',
              [f'PATCH /api/alumnos → HTTP {chk["patch"]}', f'IndexedDB tiene el nombre nuevo al volver a Inicio: {chk["actualizado"]}'])
    logout(p)
    chk['tras_logout'] = (p.evaluate('Object.keys(localStorage)'), list(json.loads(idb_todo(p)).keys()))
    p2 = n.ctx().new_page(); login(p2, D.cuenta('directivo')); p2.wait_for_timeout(5000); raw2 = idb_todo(p2)
    chk['directivo'] = {'almacenes': list(json.loads(raw2).keys()), 'nombres_alumnos': [x for x in norte + sur if x.split(' ')[0] in raw2][:5]}
    R.consola(ctx, 'Pasos 5-6: Directivo y cierre de sesión', [f'IndexedDB del Directivo: {chk["directivo"]}',
                                                            f'Docente tras cerrar sesión: Local Storage {chk["tras_logout"][0]}; IndexedDB {chk["tras_logout"][1]}'])
    fin(R, chk, n, C)


@caso('CP14', modo='parcial', notas='La espera hasta la expiración (8 horas) no se hace.')
def cp14():
    R = Run('CP14'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a')
    con_actividad(p, C); tk = token_navegador(p); exp1 = jwt(tk).get('exp')
    R.shot(p, f'Paso 1: sesión iniciada; exp del token {exp1}')
    ctx.set_offline(True); p.wait_for_timeout(600)
    ir(p, 'Rúbrica'); ir(p, 'Alumnos'); p.wait_for_timeout(1000)
    ag = p.get_by_role('button', name='Agregar')
    chk['alumnos_offline'] = {'url': p.url.replace(BASE, ''), 'agregar_deshabilitado': ag.first.is_disabled() if ag.count() else None,
                              'aviso': [l for l in p.locator('body').inner_text().split('\n') if 'sin conexión' in l.lower()][:2]}
    R.shot(p, f'Pasos 2-3: sin conexión en Rúbrica y Alumnos: {chk["alumnos_offline"]}')
    p.reload(); p.wait_for_timeout(4000)
    chk['recarga'] = (p.url.replace(BASE, ''), p.locator('body').inner_text()[:250])
    R.shot(p, f'Paso 4: recarga sin conexión: {chk["recarga"][0]} {chk["recarga"][1][:120]}', full=True)
    ctx.set_offline(False); p.reload(); p.wait_for_timeout(3000)
    ir(p, 'Rúbrica'); ir(p, 'Inicio')
    chk['online'] = (p.url.replace(BASE, ''), p.get_by_role('button', name=re.compile('Finalizar actividad|Iniciar actividad')).all_inner_texts())
    tk2 = token_navegador(p); chk['exp'] = (exp1, jwt(tk2).get('exp'))
    R.shot(p, f'Paso 5: con conexión: {chk["online"]}')
    R.consola(ctx, 'Paso 6: exp del token antes y después', [f'{chk["exp"]} (iguales: {chk["exp"][0] == chk["exp"][1]})'])
    R.nota('Paso 7: la suite no espera la hora de expiración (8 horas) sin conexión.')
    fin(R, chk, n, C)


@caso('CP18')
def cp18():
    R = Run('CP18'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    C, uid = cuenta_aut('aut-pin')
    Co, _ = cuenta_aut('aut-limite')
    if not uid:
        R.nota('La cuenta aut-pin no está lista.'); R.save(checks=chk); n.close(); return
    pin1 = flujo_pin(R, p, C.correo, 'Paso 1', chk)
    if not pin1:
        R.save(checks=chk); n.close(); return
    malo = '000000' if pin1 != '000000' else '111111'
    msgs = []
    for i in range(1, 6):
        t, _ = ingresar_pin(p, malo); msgs.append(t)
        if i in (1, 4, 5):
            R.shot(p, f'Paso {2 if i < 5 else 3}: intento {i} con un PIN incorrecto: {t}')
    chk['mensajes'] = msgs
    inp = p.locator('[role=dialog] input[inputmode=numeric]')
    chk['campo_bloqueado'] = inp.first.is_disabled() if inp.count() else 'campo no visible'
    p.reload(); p.wait_for_load_state('networkidle')
    chk['pin_correcto_tras_5'] = verificar_api(C.correo, pin1)
    R.consola(ctx, 'Paso 4: el PIN correcto después del quinto fallo (por la API, la misma que usa la pantalla: al recargar el formulario vuelve al paso 1)',
              [str(chk['pin_correcto_tras_5'])[:300]])
    pin2 = flujo_pin(R, p, C.correo, 'Paso 5', chk)
    if pin2:
        t, _ = ingresar_pin(p, '999999' if pin2 != '999999' else '888888'); chk['nuevo_un_fallo'] = t
        R.shot(p, f'Paso 5: el PIN nuevo habilita el campo; un fallo muestra: {t}')
        t, txt = ingresar_pin(p, pin2); chk['nuevo_ok'] = txt[:300]
        R.shot(p, 'Paso 6: con el PIN nuevo correcto el sistema pasa al formulario de nueva contraseña')
        nueva = D.clave_nueva(); nueva_clave_ui(p, nueva).click(); p.wait_for_timeout(2000); D.guardar_clave('aut-pin', nueva)
        chk['cambio'] = toasts_txt(p)
        chk['pin_usado'] = verificar_api(C.correo, pin2)
        chk['pin_otra_cuenta'] = verificar_api(Co.correo, pin2)
        R.consola(ctx, 'Paso 8: PIN ya usado y PIN de otra cuenta', [f'Cambio de contraseña con el PIN 2: {chk["cambio"]}',
                                                                    f'PIN 2 otra vez → {chk["pin_usado"]}', f'PIN 2 con la cuenta aut-limite → {chk["pin_otra_cuenta"]}'])
    pin3 = flujo_pin(R, p, C.correo, 'Paso 8 (PIN que se reemplaza)', chk)
    pin4 = flujo_pin(R, p, C.correo, 'Paso 8 (PIN más reciente)', chk)
    if pin3 and pin4:
        chk['reemplazado'] = verificar_api(C.correo, pin3)
        chk['mas_reciente'] = verificar_api(C.correo, pin4)
        R.consola(ctx, 'Paso 8: PIN reemplazado por una solicitud más reciente', [f'PIN 3 → {chk["reemplazado"]}', f'PIN 4 → {chk["mas_reciente"]}'])
        t4 = time.time()
        while time.time() < t4 + 15 * 60 + 20:
            time.sleep(10)
        chk['expirado'] = verificar_api(C.correo, pin4)
        R.consola(ctx, 'Paso 7: PIN pasados sus 15 minutos de vigencia', [f'PIN 4 → {chk["expirado"]}'])
    fin(R, chk, n)


@caso('CP20')
def cp20():
    R = Run('CP20'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    C, uid = cuenta_aut('aut-docente')
    if not uid:
        R.nota('La cuenta aut-docente no está lista.'); R.save(checks=chk); n.close(); return
    pin = flujo_pin(R, p, C.correo, 'Paso 1', chk)
    if not pin:
        R.save(checks=chk); n.close(); return
    ingresar_pin(p, pin)
    res = {}
    for etiqueta, a, b in [('No coinciden', 'NuevaClave1#', 'NuevaClave2#'), ('7 caracteres', 'Clave1#', 'Clave1#'), ('Sin mayúscula', 'nuevaclave1#', 'nuevaclave1#'),
                           ('Sin minúscula', 'NUEVACLAVE1#', 'NUEVACLAVE1#'), ('Sin número', 'NuevaClave#', 'NuevaClave#'), ('Sin carácter especial', 'NuevaClave1', 'NuevaClave1')]:
        bt = nueva_clave_ui(p, a, b)
        d = p.locator('[role=dialog]:visible').last
        res[etiqueta] = {'boton_habilitado': bt.is_enabled(), 'mensajes': [l for l in d.inner_text().split('\n') if re.search(r'coincid|caracter|mayúscula|minúscula|número|especial', l, re.I)][:6]}
        if bt.is_enabled():
            bt.click(); p.wait_for_timeout(1500); res[etiqueta]['respuesta'] = toasts_txt(p)
    chk['invalidas'] = res
    R.shot(p, f'Paso 2: contraseñas inválidas: {json.dumps(res, ensure_ascii=False)[:600]}')
    bt = nueva_clave_ui(p, C.clave); bt.click() if bt.is_enabled() else None; p.wait_for_timeout(1800)
    chk['igual_anterior'] = (toasts_txt(p), [l for l in p.locator('[role=dialog]:visible').last.inner_text().split('\n') if 'diferente' in l] if p.locator('[role=dialog]:visible').count() else [])
    R.shot(p, f'Paso 2: igual a la contraseña actual: {chk["igual_anterior"]}')
    nueva = D.clave_nueva(); bt = nueva_clave_ui(p, nueva); bt.click(); p.wait_for_timeout(2200)
    chk['valida'] = (toasts_txt(p), p.url.replace(BASE, ''))
    if p.locator('[role=dialog]:visible').count() == 0 or '/login' in p.url:
        D.guardar_clave('aut-docente', nueva)
    R.shot(p, f'Paso 3: contraseña válida: {chk["valida"]}')
    login(p, A.Cuenta(C.correo, D.clave_de('aut-docente'))); chk['login'] = p.url.replace(BASE, '')
    R.shot(p, f'Paso 4: con la contraseña nueva entra a {chk["login"]}')
    fin(R, chk, n)


@caso('CP23', modo='parcial', notas='El paso 5 (una hora después) no se espera.')
def cp23():
    R = Run('CP23'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    C, uid = cuenta_aut('aut-limite')
    if not uid:
        R.nota('La cuenta aut-limite no está lista.'); R.save(checks=chk); n.close(); return
    t0 = time.time() - 2; chk['hora_primera'] = A.ahora().strftime('%H:%M:%S'); msgs = []
    for i in range(5):
        abrir_recuperar(p, C.correo); msgs.append(pedir_pin(p)); time.sleep(1)
    chk['cinco'] = msgs
    R.shot(p, f'Paso 1: 5 solicitudes para {C.correo} (la primera a las {chk["hora_primera"]}): {msgs[-1]}')
    pin5 = CO.pin(C.correo, time.time() - 20)
    t6 = time.time(); abrir_recuperar(p, C.correo); chk['sexta'] = pedir_pin(p)
    R.shot(p, f'Paso 2: sexta solicitud: {chk["sexta"]} (mismo mensaje: {chk["sexta"] == msgs[-1]})')
    if CO._buzon():
        time.sleep(3); chk['correos'] = (len(CO._correos_buzon(t0, C.correo)), len(CO._correos_buzon(t6, C.correo)))
        R.consola(ctx, 'Pasos 1-2: correos recibidos (buzón local)', [f'Después de las 5 solicitudes: {chk["correos"][0]}; después de la sexta: {chk["correos"][1]}'])
    else:
        R.nota(f'Pasos 1-2: revisa en tu bandeja que llegaron 5 correos con PIN a {C.correo} y que la sexta solicitud no envió otro.')
    if pin5:
        chk['quinto_valido'] = verificar_api(C.correo, pin5)
        R.consola(ctx, 'Paso 3: el quinto PIN (el último que llegó) sigue siendo válido', [str(chk['quinto_valido'])[:300]])
    otro = config.correo_de(f'no-existe-{hhmmss()}'); m2 = []
    for _ in range(6):
        abrir_recuperar(p, otro); m2.append(pedir_pin(p))
    chk['no_registrado'] = (len(set(json.dumps(x, ensure_ascii=False) for x in m2)), m2[-1])
    R.shot(p, f'Paso 4: 6 solicitudes con un correo no registrado: mensajes distintos {chk["no_registrado"][0]}; último {chk["no_registrado"][1]}')
    R.nota('Paso 2: que no se haya creado un PIN en la base de datos no se puede ver en QA. Paso 5: la suite no espera una hora.')
    fin(R, chk, n)


@caso('CP24', notas='El hash bcrypt y el tipo de cierre de la sesión (pasos 7-8) quedan como NOTA.')
def cp24():
    R = Run('CP24'); n = Nav(); chk = {}
    C, uid = cuenta_aut('aut-reset')
    if not uid:
        R.nota('La cuenta aut-reset no está lista.'); R.save(checks=n and chk); n.close(); return
    c1 = n.ctx(); p1 = c1.new_page(); login(p1, C); tk = token_navegador(p1); anterior = C.clave
    R.shot(p1, 'Paso 1: ventana normal con la sesión iniciada; token copiado')
    c2 = n.ctx(); p2 = c2.new_page()
    pin = flujo_pin(R, p2, C.correo, 'Paso 2 (ventana de incógnito)', chk)
    if not pin:
        R.save(checks=chk); n.close(); return
    ingresar_pin(p2, pin); nueva = D.clave_nueva(); nueva_clave_ui(p2, nueva).click(); p2.wait_for_timeout(2200)
    chk['exito'] = (toasts_txt(p2), p2.url.replace(BASE, ''))
    D.guardar_clave('aut-reset', nueva)
    R.shot(p2, f'Paso 3: la ventana de incógnito informa {chk["exito"]}')
    ir(p1, 'Inicio') if p1.locator('aside nav a').count() else None
    p1.reload(); p1.wait_for_timeout(3000); chk['url1'] = p1.url.replace(BASE, '')
    R.shot(p1, f'Paso 4: en la ventana normal, al navegar: {chk["url1"]}')
    chk['me'] = A.api('GET', '/me', tk)
    R.consola(c1, 'Paso 5: GET /api/me con el token del paso 1', [str(chk['me'])[:300]])
    p3 = c2.new_page(); chk['vieja'] = intentar_login(p3, C.correo, anterior)
    R.shot(p3, f'Paso 6: con la contraseña anterior: {chk["vieja"][:2]}')
    chk['nueva'] = intentar_login(p3, C.correo, nueva)
    R.shot(p3, f'Paso 6: con la nueva: {chk["nueva"][:2]} → {chk["nueva"][2]}')
    R.nota('Pasos 7-8: el hash bcrypt de la contraseña y el tipo de cierre "Invalidada por restablecimiento" de la sesión están en la base de datos; en QA no hay una consulta para verlos.')
    fin(R, chk, n)


@caso('CP25', notas='Pide pegar la contraseña temporal del usuario nuevo.')
def cp25():
    R = Run('CP25'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    cor = config.correo_de(f'aut25-{hhmmss()}'); t0 = time.time() - 2
    s, r = A.api('POST', '/usuarios', A.sup(), {'nombres': 'Docente', 'apellidos': f'Primer Ingreso QA {hhmmss()}', 'dni': D._dni(cor), 'correo': cor, 'id_rol': 1,
                                                 'asignacion': A.asignacion([(D.Y(), [2])])})
    temporal = (r or {}).get('contraseña_temporal') if isinstance(r, dict) else None
    if not temporal:
        temporal = CO.contrasena_temporal(cor, t0)
    R.consola(ctx, 'Precondición: usuario nuevo creado por la Supervisora (API)', [f'{cor} → HTTP {s}; correo enviado: {(r or {}).get("correo_enviado") if isinstance(r, dict) else None}',
                                                                                f'Contraseña temporal obtenida: {"sí" if temporal else "no"}'])
    if not temporal:
        R.nota('No se obtuvo la contraseña temporal del usuario nuevo; el caso no se puede ejecutar.'); R.save(checks=chk); n.close(); return
    st, msg, url = intentar_login(p, cor, temporal)
    chk['primer'] = (st, msg, url, p.locator('[role=dialog]:visible').count())
    R.shot(p, f'Pasos 1-2: con la contraseña temporal: HTTP {st}; {msg}; pantalla {url}; modal de cambio obligatorio {chk["primer"][3]}')
    rutas = {}
    for r_ in ['/inicio', '/alumnos']:
        rutas[r_] = visitar(p, r_)
    chk['rutas'] = rutas
    R.shot(p, f'Paso 3: /inicio y /alumnos escritas en la barra: {rutas}')
    R.nota('Paso 4: que todavía no exista una sesión de 8 horas está en la base de datos; en QA no se puede ver.')
    if not p.locator('[role=dialog]:visible').count():
        intentar_login(p, cor, temporal)
    d = p.locator('[role=dialog]:visible').last

    def intento(a, b):
        pw = d.locator('input[type=password]'); pw.nth(pw.count() - 2).fill(a); pw.nth(pw.count() - 1).fill(b); p.wait_for_timeout(500)
        btn = d.get_by_role('button', name=re.compile('Establecer|Guardar|Cambiar'))
        return [l for l in d.inner_text().split('\n') if re.search(r'coincid|caracter|mayúscula|minúscula|número|especial', l, re.I)][:5], btn.last.is_enabled() if btn.count() else None
    chk['debil'] = intento('Clave1#', 'Clave1#'); chk['sin_especial'] = intento('NuevaClave1', 'NuevaClave1'); chk['distinta'] = intento('DocenteQa2#2026', 'DocenteQa2#2027')
    R.shot(p, f'Paso 5: "Clave1#" {chk["debil"]}; sin especial {chk["sin_especial"]}; confirmación distinta {chk["distinta"]}')
    nueva = D.clave_nueva(); intento(nueva, nueva)
    d.get_by_role('button', name=re.compile('Establecer|Guardar|Cambiar')).last.click(); p.wait_for_timeout(3000)
    chk['tras'] = p.url.replace(BASE, '')
    R.shot(p, f'Paso 6: con una contraseña válida el sistema abre {chk["tras"]}')
    u = A.usuario_por_correo(cor) or {}; tk = token_navegador(p); cl = jwt(tk) if tk else {}
    chk['api'] = {'debe_cambiar_contrasena': u.get('debe_cambiar_contrasena'), 'vigencia_token_s': (cl.get('exp', 0) - cl.get('iat', 0)) if cl else None}
    R.consola(ctx, 'Paso 7: la cuenta y la sesión (API y token; el hash bcrypt queda en la base de datos)', lineas(chk['api']))
    logout(p); chk['nueva'] = intentar_login(p, cor, nueva)
    R.shot(p, f'Paso 8: con la contraseña nueva entra a {chk["nueva"][2]}')
    if '/login' not in p.url:
        logout(p)
    chk['temporal'] = intentar_login(p, cor, temporal)
    R.shot(p, f'Paso 8: con la temporal: {chk["temporal"][:2]}')
    fin(R, chk, n)
