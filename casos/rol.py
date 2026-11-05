"""Roles y permisos: CP-ROL-01 a CP-ROL-04, adaptados a QA.

- Docente: Docente A (3.º del colegio Norte del caso). Supervisora en la interfaz: supervisor-2.
- Lo que en local se contaba en la base de datos (CP-ROL-04) se cuenta por la API.
- Los datos que crea el caso (un alumno de prueba) se inactivan al terminar.
"""
from lib import api as A
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import caso
from lib.ui import Nav, Run, login, token_navegador

from casos._comun import abrir_menu, estado_pantalla, fin, menu, sup_ui, visitar
from casos.asi import put_asis
from casos.rub import mes_actual, rub_items, rub_put
from casos.rv import PA_ACT, rv_items, rv_put

MENU_DOCENTE = ['Inicio', 'Alumnos', 'Asistencias', 'Seguimiento de Lectura', 'Rúbrica', 'Registro de Vuelo', 'Sesiones']
MENU_SUPERVISOR = ['Inicio', 'Colegios', 'Alumnos', 'Usuarios', 'Seguimiento', 'Asistencias', 'Seguimiento de Lectura',
                   'Rúbrica', 'Registro de Vuelo', 'Dashboard']


def _recorrer_menu(p):
    res = {}
    for nombre in menu(p):
        abrir_menu(p, nombre)
        res[nombre] = '/' + p.url.split('/', 3)[-1] + ' · ' + estado_pantalla(p)
    return res


def _clase_reciente(cid=None):
    return FE.ultima_clase(3, cid or D.X(), incluir_hoy=True)


@caso('CP-ROL-01')
def cp_rol01():
    R = Run('CP-ROL-01'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    C = D.cuenta('docente-a'); A.cerrar_abiertas(C)
    X = D.X(); ana = D.alumno('Ana Norte QA')
    login(p, C); R.shot(p, 'Paso 1: sesión iniciada como Docente A')
    chk['menu'] = menu(p)
    chk['faltan'] = [m for m in MENU_DOCENTE if m not in chk['menu']]
    chk['sobran'] = [m for m in chk['menu'] if m not in MENU_DOCENTE]
    R.shot(p, f'Paso 2: barra lateral: {", ".join(chk["menu"])} · faltan {chk["faltan"]} · sobran {chk["sobran"]}')
    chk['opciones'] = _recorrer_menu(p)
    R.consola(ctx, 'Paso 3: resultado de abrir cada opción de la barra lateral', [f'{k} → {v}' for k, v in chk['opciones'].items()])
    urls = {}
    for r_ in ['/rubrica', '/registro-vuelo', '/asistencia', f'/estudiantes/{ana}']:
        urls[r_] = visitar(p, r_) + ' · ' + estado_pantalla(p)
    chk['urls'] = urls
    R.shot(p, f'Paso 4: /estudiantes/{ana} (Ana Norte QA) → {urls[f"/estudiantes/{ana}"]}')
    R.consola(ctx, 'Paso 4: rutas escritas en la barra de direcciones', [f'{k} → {v}' for k, v in urls.items()])
    tk = token_navegador(p)
    F = _clase_reciente(); sec = A.seccion(X, 3); mes = mes_actual(); pa_n = PA_ACT(X)
    cons = {}
    for e in ['/colegios', '/alumnos?' + A.q(id_colegio=X),
              '/asistencias?' + A.q(id_colegio=X, id_grado=A.id_grado(3), id_seccion=sec, fecha=A.iso(F)),
              '/rubricas?' + A.q(id_colegio=X, id_programa=A.CL(), id_grado=A.id_grado(3), id_seccion=sec, id_anio_escolar=A.anio(), mes=mes),
              '/registro-vuelo?' + A.q(id_colegio=X, id_programa=A.CL(), id_grado=A.id_grado(3), id_seccion=sec, id_anio_escolar=A.anio())]:
        s, r = A.api('GET', e, tk); cons[e.split('?')[0]] = s
    chk['consultas'] = cons
    R.consola(ctx, 'Paso 5: consultas a la API con el token del Docente (su grupo: 3.º del colegio Norte)', [f'GET /api{e} → HTTP {s}' for e, s in cons.items()])
    visitar(p, '/inicio'); b = p.get_by_role('button', name='Iniciar actividad')
    if b.count():
        b.first.click(); p.wait_for_timeout(2000)
    R.shot(p, 'Paso 6: se selecciona "Iniciar actividad"')
    act = A.actividad_en_curso(tk)
    s1, r1 = A.api('POST', '/alumnos', tk, {'nombres': 'Alumno', 'apellidos': 'Prueba Rol QA', 'id_colegio': X, 'id_grado': A.id_grado(3),
                                             'id_programa': A.CL(), 'pertenece_desde': A.iso(FE.pa_actual(X)['fecha_inicio'])})
    nid = (r1 or {}).get('id_alumno') or (r1 or {}).get('id') if isinstance(r1, dict) else None
    s2, r2 = put_asis(tk, F, [(ana, 'presente', None)], act)
    s3, r3 = rub_put(tk, rub_items([(ana, 3, 3)], act, mes=mes))
    s4, r4 = rv_put(tk, rv_items([(ana, pa_n, {'id_nivel_colocado': A.niveles_rk()['C']})], act))
    chk['escrituras'] = {'alumno': (s1, str(r1)[:160]), 'asistencia': (s2, r2), 'rubrica': (s3, r3), 'registro_vuelo': (s4, r4)}
    s5 = A.api('PATCH', f'/alumnos/{nid}/desactivar', A.sup(), {'aplicar_desde': A.iso(A.hoy())})[0] if nid else None
    R.consola(ctx, 'Pasos 7-8: escrituras con el token del Docente y la actividad iniciada',
              [f'POST /api/alumnos (3.º del colegio Norte) → HTTP {s1} {str(r1)[:160]}',
               f'PUT /api/asistencias (clase del {FE.legible(F)}, Ana presente) → HTTP {s2} {r2}',
               f'PUT /api/rubricas ({FE.mes_nombre(mes)}) → HTTP {s3} {r3}',
               f'PUT /api/registro-vuelo (Nivel colocado C, PA{pa_n}) → HTTP {s4} {r4}',
               f'Limpieza: el alumno de prueba se inactiva desde hoy → HTTP {s5}'])
    fin(R, chk, n, C)


@caso('CP-ROL-02')
def cp_rol02():
    R = Run('CP-ROL-02'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    C = D.cuenta('docente-a'); X = D.X()
    login(p, C); R.shot(p, 'Paso 1: sesión iniciada como Docente A')
    did = D.id_usuario('docente-b')
    res = {}
    for r_ in ['/colegios', f'/colegios/{X}', '/colegios/calendario', '/usuarios', f'/usuarios/{did}', f'/usuarios/{did}/permisos', '/seguimiento', '/dashboard']:
        res[r_] = visitar(p, r_) + ' · ' + estado_pantalla(p)
        if r_ in ('/colegios', '/usuarios'):
            R.shot(p, f'Pasos 2-3: {r_} → {res[r_]}')
    chk['rutas'] = res
    R.consola(ctx, 'Pasos 2-3: rutas de la Supervisora escritas por el Docente', [f'{k} → {v}' for k, v in res.items()])
    tk = token_navegador(p)
    cal = A.calendario(X)
    cid = cal.get('id_calendario') or cal.get('id')
    F = FE.ultima_clase(3, X, incluir_hoy=True)
    pet = {
        'GET /calendarios': A.api('GET', '/calendarios?' + A.q(id_colegio=X), tk)[0],
        'PUT /calendarios/{id}': A.api('PUT', f'/calendarios/{cid}', tk, {'version': cal.get('version', 1), 'periodos': []})[0],
        'GET /usuarios/{id}/permisos': A.api('GET', f'/usuarios/{did}/permisos', tk)[0],
        'POST /usuarios/{id}/permisos': A.api('POST', f'/usuarios/{did}/permisos', tk, {
            'id_anio_escolar': A.anio(), 'id_colegio': X, 'id_grado': A.id_grado(4), 'id_periodo_academico': FE.pa_actual(X)['id_periodo_academico'],
            'modulo': 'asistencias', 'desde_ahora': True, 'fin': A.iso(A.ahora().replace(microsecond=0) + __import__('datetime').timedelta(days=2)), 'motivo': 'Prueba de rol QA'})[0],
        'POST /colegios/{id}/clases/reprogramaciones': A.api('POST', f'/colegios/{X}/clases/reprogramaciones', tk, {
            'id_grado': A.id_grado(3), 'id_seccion': A.seccion(X, 3), 'fecha_original': A.iso(F),
            'fecha_nueva': A.iso(F + __import__('datetime').timedelta(days=1)), 'motivo': 'Prueba de rol QA'})[0],
    }
    chk['api'] = pet
    chk['calendario_sin_cambios'] = A.calendario(X).get('version') == cal.get('version')
    R.consola(ctx, 'Pasos 4-5: peticiones de calendario, permisos y reprogramación con el token del Docente',
              [f'{k} → HTTP {v}' for k, v in pet.items()] + [f'Calendario del colegio sin cambios (versión): {chk["calendario_sin_cambios"]}'])
    fin(R, chk, n)


@caso('CP-ROL-03')
def cp_rol03():
    R = Run('CP-ROL-03'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    S = sup_ui(); NX = D.nombre_colegio('norte')
    login(p, S); R.shot(p, 'Paso 1: sesión iniciada como Supervisora (supervisor-2)')
    chk['menu'] = menu(p)
    chk['faltan'] = [m for m in MENU_SUPERVISOR if m not in chk['menu']]
    chk['sobran'] = [m for m in chk['menu'] if m not in MENU_SUPERVISOR]
    R.shot(p, f'Paso 2: barra lateral: {", ".join(chk["menu"])} · faltan {chk["faltan"]} · sobran {chk["sobran"]}')
    import re
    abrir_menu(p, 'Colegios')
    cal = p.get_by_role('button', name=re.compile('Calendario')).or_(p.get_by_role('link', name=re.compile('Calendario')))
    if cal.count():
        cal.first.click(); p.wait_for_timeout(2000)
    chk['calendario'] = p.url.split('/', 3)[-1] + ' · ' + estado_pantalla(p) + ' · ' + p.locator('main').inner_text()[:150].replace('\n', ' | ')
    R.shot(p, f'Paso 3: Colegios → "Calendario académico": {chk["calendario"][:120]}')
    visitar(p, '/colegios')
    try:
        p.locator('main input[type=search], main input[placeholder*="Buscar"]').first.fill(NX); p.wait_for_timeout(1200)
    except Exception:
        pass
    fila_c = p.locator('main tbody tr').filter(has_text=NX)
    vd = (fila_c if fila_c.count() else p.locator('main')).get_by_role('button', name=re.compile('Ver detalle'))
    if vd.count():
        vd.first.click(); p.wait_for_timeout(2000)
    pc = p.get_by_role('tab', name=re.compile('Programación')).or_(p.get_by_role('button', name=re.compile('Programación')))
    if pc.count():
        pc.first.click(); p.wait_for_timeout(2000)
    chk['programacion'] = p.url.split('/', 3)[-1] + ' · ' + estado_pantalla(p) + ' · ' + p.locator('main').inner_text()[:200].replace('\n', ' | ')
    R.shot(p, f'Paso 3: Colegios → "Ver detalle" → "Programación de clases": {chk["programacion"][:120]}')
    visitar(p, '/usuarios')
    correo_a = D.cuenta('docente-a').correo
    try:
        p.locator('main input[type=search], main input[placeholder*="Buscar"]').first.fill(correo_a)
        b = p.get_by_role('button', name='Filtrar')
        if b.count():
            b.first.click()
        p.wait_for_timeout(1500)
    except Exception:
        pass
    f = p.locator('main tbody tr').filter(has_text=correo_a)
    b = f.get_by_role('button', name=re.compile('detalle|Otorgar', re.I))
    if b.count():
        b.first.click(); p.wait_for_timeout(2000)
    pp = p.get_by_role('tab', name=re.compile('Permisos')).or_(p.get_by_role('button', name=re.compile('^Permisos')))
    if pp.count():
        pp.first.click(); p.wait_for_timeout(1500)
    chk['permisos'] = p.url.split('/', 3)[-1] + ' · ' + estado_pantalla(p) + ' · ' + p.locator('main').inner_text()[:200].replace('\n', ' | ')
    R.shot(p, f'Paso 4: Usuarios → Docente A → "Permisos de corrección": {chk["permisos"][:120]}')
    mods = {}
    for r_ in ['/asistencia', '/rubrica', '/registro-vuelo', '/seguimiento-lectura']:
        mods[r_] = visitar(p, r_) + ' · ' + estado_pantalla(p)
        t = p.locator('body').inner_text()
        mods[r_] += f' · botones de registro: {[x for x in ["Marcar todos como presentes", "Registrar evaluaciones", "Registrar niveles"] if x in t]}'
        mods[r_] += f' · pide actividad: {"Iniciar actividad" in t or "inicia una actividad" in t.lower()}'
    chk['modulos'] = mods
    R.shot(p, f'Paso 5: {list(mods)[-1]} como Supervisora')
    R.consola(ctx, 'Pasos 5-6: módulos operativos escritos en la barra de direcciones', [f'{k} → {v}' for k, v in mods.items()])
    # Paso 7: cada rol
    from lib.ui import logout
    try:
        logout(p)
    except Exception:
        pass
    por_rol = {}
    for et in ['docente-a', 'supervisor-2', 'directivo']:
        tras_salir = '/' + p.url.split('/', 3)[-1]
        c = D.cuenta(et); login(p, c); ini = p.url.split('/', 3)[-1]
        abre = _recorrer_menu(p)
        inex = visitar(p, '/ruta-inexistente')
        por_rol[et] = {'pantalla_antes_de_entrar': tras_salir, 'inicio': '/' + ini, 'menu': list(abre), 'abre': abre, 'ruta_inexistente': inex}
        R.shot(p, f'Paso 7 ({et}): antes de entrar {tras_salir}; llega a /{ini}; menú {list(abre)}; /ruta-inexistente → {inex}')
        try:
            logout(p)
        except Exception:
            pass
    chk['por_rol'] = por_rol
    R.consola(ctx, 'Paso 7: resumen por rol', [f'{r}: {v}' for r, v in por_rol.items()])
    fin(R, chk, n, D.cuenta('docente-a'))


@caso('CP-ROL-04')
def cp_rol04():
    import datetime as dt
    R = Run('CP-ROL-04'); n = Nav(); ctx = n.ctx(); chk = {}
    Cd, Cs, Cdir = D.cuenta('docente-a'), sup_ui(), D.cuenta('directivo')
    td, ts, tdir = Cd.login(), Cs.login(), Cdir.login()
    R.consola(ctx, 'Paso 1: tokens obtenidos con POST /api/login', ['Docente A, Supervisora (supervisor-2) y Directivo: HTTP 200 (tokens no mostrados)'])
    X = D.X(); ana = D.alumno('Ana Norte QA'); sec = A.seccion(X, 3); F = FE.ultima_clase(3, X, incluir_hoy=True)
    did = D.id_usuario('docente-b'); cal = A.calendario(X); cid = cal.get('id_calendario') or cal.get('id')
    pa_id = FE.pa_actual(X)['id_periodo_academico']; mes = mes_actual()

    def conteos():
        tot = lambda ruta: (A.api('GET', ruta, A.sup())[1] or {}).get('total')
        asis = A.api('GET', '/asistencias?' + A.q(id_colegio=X, id_grado=A.id_grado(3), id_seccion=sec, fecha=A.iso(F)), A.sup())[1] or {}
        return {'colegios activos': tot('/colegios?activo=true'), 'colegios inactivos': tot('/colegios?activo=false'),
                'usuarios': tot('/usuarios?activo=true'), 'permisos de Docente B': len((A.api('GET', f'/usuarios/{did}/permisos', A.sup())[1] or {}).get('items', [])),
                'asistencias marcadas (3.º Norte)': sum(1 for a in asis.get('alumnos', []) if a.get('estado')),
                'versión del calendario': A.calendario(X).get('version')}
    antes = conteos()
    fin_p = A.iso((A.ahora() + dt.timedelta(days=2)).replace(microsecond=0))
    PET = {
        'Docente': [('POST', '/colegios', {'nombre': 'QA ROL no debe crearse', 'departamento': 'Áncash', 'provincia': 'Huaraz', 'distrito': 'Huaraz',
                                           'nivel_educativo': 'Primaria', 'grados': [{'id_grado': A.id_grado(1), 'dia_clase': 1}], 'programas': [A.ALFA()]}),
                    ('POST', '/usuarios', {'nombres': 'No', 'apellidos': 'Debe Crearse', 'dni': '71234567', 'correo': 'no.debe.crearse.rol@sicedu.test', 'id_rol': 1}),
                    ('PUT', f'/calendarios/{cid}', {'version': cal.get('version', 1), 'periodos': []}),
                    ('POST', f'/usuarios/{did}/permisos', {'id_anio_escolar': A.anio(), 'id_colegio': X, 'id_grado': A.id_grado(4), 'id_periodo_academico': pa_id,
                                                          'modulo': 'asistencias', 'desde_ahora': True, 'fin': fin_p, 'motivo': 'x'})],
        'Supervisor': [('PUT', '/asistencias', {'id_colegio': X, 'id_grado': A.id_grado(3), 'id_seccion': sec, 'fecha': A.iso(F),
                                                'registros': [{'id_operacion': A.uid(), 'id_alumno': ana, 'estado': 'presente'}]}),
                       ('PUT', '/rubricas', rub_items([(ana, 3, 3)], None, mes=mes)),
                       ('PUT', '/registro-vuelo', rv_items([(ana, PA_ACT(X), {'id_nivel_colocado': A.niveles_rk()['C']})], None))],
        'Directivo': [('GET', '/alumnos?' + A.q(id_colegio=X), None),
                      ('GET', '/asistencias?' + A.q(id_colegio=X, id_grado=A.id_grado(3), id_seccion=sec, fecha=A.iso(F)), None),
                      ('GET', '/rubricas?' + A.q(id_colegio=X, id_programa=A.CL(), id_grado=A.id_grado(3), id_seccion=sec, id_anio_escolar=A.anio(), mes=mes), None),
                      ('GET', '/registro-vuelo?' + A.q(id_colegio=X, id_programa=A.CL(), id_grado=A.id_grado(3), id_seccion=sec, id_anio_escolar=A.anio()), None)],
    }
    tok = {'Docente': td, 'Supervisor': ts, 'Directivo': tdir}
    res = {}
    for rol, lst in PET.items():
        for m, e, b in lst:
            res[f'{rol}: {m} {e.split("?")[0]}'] = A.api(m, e, tok[rol], b)[0]
            res[f'Sin token: {m} {e.split("?")[0]}'] = A.api(m, e, None, b)[0]
    tm = td[:-4] + ('AAAA' if not td.endswith('AAAA') else 'BBBB')
    res['Token manipulado: GET /me'] = A.api('GET', '/me', tm)[0]
    chk['codigos'] = res
    despues = conteos(); chk['conteos'] = (antes, despues); chk['sin_cambios'] = antes == despues
    for rol in PET:
        R.consola(ctx, f'Pasos 2-5: peticiones con el token del {rol} y sin token',
                  [f'{m} {e.split("?")[0]}: con token → HTTP {res[f"{rol}: {m} {e.split(chr(63))[0]}"]} · sin token → HTTP {res[f"Sin token: {m} {e.split(chr(63))[0]}"]}' for m, e, b in PET[rol]])
    R.consola(ctx, 'Paso 6: conteos por la API antes y después (en local se contaba en la base de datos)',
              [f'{k}: {antes[k]} → {despues[k]}' for k in antes] + [f'Token manipulado: GET /api/me → HTTP {res["Token manipulado: GET /me"]}'])
    # Paso 7: rutas escritas por el Directivo y el Docente
    rutas = {}
    for et in ['directivo', 'docente-a']:
        p = n.ctx().new_page()
        c = D.cuenta(et); login(p, c); r_ = {}
        for ruta in ['/colegios', '/colegios/calendario', '/usuarios', '/seguimiento']:
            r_[ruta] = visitar(p, ruta) + ' · ' + estado_pantalla(p)
        visitar(p, '/inicio'); r_['menú'] = menu(p); rutas[et] = r_
        R.shot(p, f'Paso 7 ({et}): {r_}')
    chk['rutas'] = rutas
    R.consola(ctx, 'Paso 7: rutas escritas por el Directivo y el Docente', [f'{k}: {v}' for k, v in rutas.items()])
    fin(R, chk, n, Cd)
