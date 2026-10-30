"""Asistencias (CU022): CP-ASI-01 a CP-ASI-13, adaptados a QA.

Diferencias con la ejecución local:
- Las fechas salen del calendario del colegio del caso (no hay fechas fijas).
- Lo que antes se leía en la base de datos se lee por la API (GET /asistencias, clases, operaciones).
- La "sesión expirada" se simula cerrando la sesión en el servidor (POST /logout con su token).
"""
import datetime as dt
import json
import re
import threading

from lib import api as A
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import caso
from lib.ui import (BASE, Nav, Run, cerrar_dialogos, cola_idb, con_actividad, filtros_ui, fila, idb_todo, ir,
                    llenar_login, login, opciones, poner, textos, toasts_txt, token_navegador)

C = None  # Docente A (se fija en cada caso)


def _c():
    return D.cuenta('docente-a')


def sup_ui():
    """Supervisora para la interfaz: la cuenta propia de la suite (la E2E queda para la API)."""
    return D.cuenta('supervisor-2')


def NX():
    return D.nombre_colegio('norte')


def abrir_asis(p, fecha, sub='Todos', grado='3.º', colegio=None):
    ir(p, 'Asistencias')
    p.wait_for_timeout(1800)
    if colegio:
        poner(p, 'Colegio', colegio)
    poner(p, 'Grado', grado)
    try:
        poner(p, 'Sección', 'Única')
    except Exception:
        pass
    poner(p, 'Subprograma', sub)
    p.locator('main input[type=date]').first.fill(A.iso(fecha))
    p.wait_for_timeout(2500)


def marcar_asis(p, nombre, estado, esperar=True):
    b = p.get_by_role('button', name=f'{estado}: {nombre}', exact=True)
    if not esperar:
        try:
            b.click(timeout=4000)
        except Exception as e:
            return 'no se pudo hacer clic: ' + str(e)[:50]
        p.wait_for_timeout(800)
        return None
    try:
        with p.expect_response(lambda r: '/api/asistencias' in r.url and r.request.method == 'PUT', timeout=8000) as ri:
            b.click()
        r = ri.value
        p.wait_for_timeout(800)
        bd = r.json() if r.status < 500 else r.text()[:200]
        return r.status, [(x.get('estado'), x.get('motivo')) for x in bd.get('resultados', [])] if isinstance(bd, dict) else bd
    except Exception as e:
        return 'sin petición', str(e)[:60]


def estado_asis(p, nombre):
    f = fila(p, nombre)
    if not f.count():
        return {'marcado': None, 'fila': 'no visible'}
    on = [b.get_attribute('title') for b in f.locator('button[aria-pressed=true]').all()]
    fondo = f.evaluate("e=>getComputedStyle(e).backgroundColor")
    pressed_bg = f.locator('button[aria-pressed=true]').evaluate_all("els=>els.map(e=>getComputedStyle(e).backgroundColor)")
    return {'marcado': on, 'fondo_fila': fondo, 'fondo_control': pressed_bg}


def get_asis(quien, fecha, grado=3, colegio=None):
    x = colegio or D.X()
    return A.api('GET', '/asistencias?' + A.q(id_colegio=x, id_grado=A.id_grado(grado), id_seccion=A.seccion(x, grado), fecha=A.iso(fecha)), quien)


def asis_api(fecha, grado=3, colegio=None):
    """Lo que antes se leía en la tabla asistencia: (alumno, estado, observación, versión) y la clase."""
    s, r = get_asis(A.sup(), fecha, grado, colegio)
    if s != 200:
        return {'http': s, 'detalle': r.get('detail') if isinstance(r, dict) else r}
    return {'clase': {k: (r.get('clase') or {}).get(k) for k in ('id_clase', 'tipo', 'etiqueta', 'fecha_original', 'fecha')},
            'marcados': [(a['nombre'], a['estado'], a.get('observacion'), a.get('version')) for a in r['alumnos'] if a.get('estado') or a.get('observacion')],
            'lista': len(r['alumnos'])}


def de_alumno(fecha, nombre, grado=3, colegio=None):
    s, r = get_asis(A.sup(), fecha, grado, colegio)
    if s != 200:
        return None
    return next(((a['estado'], a.get('observacion'), a.get('version')) for a in r['alumnos'] if a['nombre'].startswith(nombre.split(' ')[0] + ' ')), None)


def clases_api(fecha, grado=3, colegio=None):
    cid = colegio or D.X()
    return [(c.get('id_clase'), c['tipo'], c['fecha_original'], c['fecha'], c.get('tiene_asistencias'))
            for c in A.clases(cid, grado, fecha, fecha)]


def put_asis(quien, fecha, lst, act, grado=3, colegio=None, adicional=False):
    """lst: [(id_alumno, estado, observacion)]"""
    x = colegio or D.X()
    regs = []
    for a, e, o in lst:
        r_ = {'id_operacion': A.uid(), 'id_alumno': a, 'id_actividad': act}
        if e:
            r_['estado'] = e
        if o is not None:
            r_['observacion'] = o
        regs.append(r_)
    b = {'id_colegio': x, 'id_grado': A.id_grado(grado), 'id_seccion': A.seccion(x, grado), 'fecha': A.iso(fecha), 'registros': regs}
    if adicional:
        b['adicional'] = True
    s, r = A.api('PUT', '/asistencias', quien, b)
    return s, ([(z.get('estado'), z.get('motivo'), z.get('detail')) for z in r.get('resultados', [])] if isinstance(r, dict) else r)


def nueva_act(cuenta=None):
    cuenta = cuenta or _c()
    A.cerrar_abiertas(cuenta)
    return cuenta, A.iniciar_actividad(cuenta)


def act_de(cuenta=None):
    return A.actividad_en_curso(cuenta or _c())


def controles(p):
    b = p.get_by_role('button', name=re.compile('^(Presente|Tardanza|Ausente): '))
    return {'total': b.count(), 'deshabilitados': sum(b.evaluate_all("els=>els.map(e=>e.disabled||e.getAttribute('aria-disabled')==='true')"))}


def espiar_puts(p):
    lst = []
    p.on('request', lambda r: lst.append((A.ahora().strftime('%H:%M:%S'), r.method, r.url.split('/api')[-1][:60]))
         if '/api/asistencias' in r.url and r.method == 'PUT' else None)
    return lst


def aviso_sup(p):
    return [t for t in textos(p, 'actividad de trabajo', 'habilitación', 'solo lectura', 'Corrección excepcional', 'trasladada',
                              'No hay una clase', 'adicional') if len(t) < 300]


def ids_operacion(raw):
    return list(dict.fromkeys(re.findall(r'"id_?[oO]peracion"\s*:\s*"([0-9a-f-]{36})"', raw)))


def ops_api(cuenta, ids):
    out = []
    for i in ids[:6]:
        s, r = A.api('GET', f'/sincronizacion/operaciones/{i}', cuenta)
        out.append((i[:8], s, (r or {}).get('estado') if isinstance(r, dict) else r, (r or {}).get('motivo') if isinstance(r, dict) else None))
    return out


def fin_caso(R, chk, n):
    try:
        A.cerrar_abiertas(_c())
    except Exception:
        pass
    R.save(checks=chk)
    n.close()


def _f():
    """La última clase del 3.º en el PA vigente (puede ser hoy)."""
    f = FE.ultima_clase(3)
    if not f:
        raise RuntimeError('El colegio del caso no tiene clases del 3.º en el PA vigente (¿hoy es receso?).')
    return f


# ───────────────────────────────────────────────────────────────────────────────────

@caso('CP-ASI-01')
def cp_asi01():
    R = Run('CP-ASI-01'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    F = _f(); chk['fecha'] = A.iso(F)
    con_actividad(p, C); ir(p, 'Asistencias'); p.wait_for_timeout(2000)
    chk['filtros'] = filtros_ui(p) + [('FECHA', p.locator('main input[type=date]').first.input_value())]
    R.shot(p, f'Paso 1: filtros al entrar: {chk["filtros"]}')
    abrir_asis(p, F, sub='Comprensión Lectora'); m = p.locator('main')
    chk['etiqueta'] = textos(p, 'Clase programada', 'Clase reprogramada', 'Clase adicional')
    chk['ls'] = p.evaluate('JSON.stringify(localStorage)')[:400]
    chk['columnas'] = [x.strip() for x in m.locator('thead th').all_inner_texts()]
    chk['sin_marcar'] = m.locator('button[aria-pressed=true]').count(); chk['n'] = textos(p, 'alumno')[:1]
    R.shot(p, f'Pasos 2-3: {FE.dia_semana(F)} {FE.legible(F)} (día de clase del 3.º), Comprensión Lectora: etiqueta {chk["etiqueta"]}; columnas {chk["columnas"]}; controles marcados {chk["sin_marcar"]}', full=True)
    R.consola(ctx, 'Paso 2: Local Storage', [chk['ls']])
    chk['tardanza'] = marcar_asis(p, 'Ana Norte QA', 'Tardanza'); chk['ana'] = estado_asis(p, 'Ana Norte QA')
    R.shot(p, f'Paso 4: Ana en Tardanza → {chk["tardanza"]}; {chk["ana"]}')
    try:
        with p.expect_response(lambda r: '/api/asistencias' in r.url and r.request.method == 'PUT', timeout=8000) as ri:
            m.get_by_role('button', name='Marcar todos como presentes').click()
        chk['lote'] = (ri.value.status, len(json.loads(ri.value.request.post_data)['registros']))
    except Exception as e:
        chk['lote'] = str(e)[:60]
    p.wait_for_timeout(1500); chk['avisos_lote'] = toasts_txt(p)
    chk['tras_lote'] = {k: estado_asis(p, k)['marcado'] for k in ['Ana Norte QA', 'Beto Norte QA', 'Extra01 Rubrica QA']}
    R.shot(p, f'Paso 5: "Marcar todos como presentes" → {chk["lote"]}; {chk["tras_lote"]}; avisos {chk["avisos_lote"]}', full=True)
    chk['ausente'] = marcar_asis(p, 'Beto Norte QA', 'Ausente'); chk['beto'] = estado_asis(p, 'Beto Norte QA')
    chk['boton_guardar'] = m.get_by_role('button', name=re.compile('^Guardar')).count()
    R.shot(p, f'Pasos 6-7: Beto Ausente → {chk["ausente"]}; {chk["beto"]}; botón Guardar = {chk["boton_guardar"]}')
    poner(p, 'Subprograma', 'Alfabetización'); p.wait_for_timeout(2000)
    chk['alfa'] = (textos(p, 'Clase programada'), [estado_asis(p, f)['marcado'] for f in ['Alumno03 Volumen QA', 'Alumno06 Volumen QA']])
    R.shot(p, f'Paso 8: Alfabetización: {chk["alfa"]}', full=True)
    chk['api'] = {'clases': clases_api(F), 'asistencias': asis_api(F)}
    s, r = get_asis(A.sup(), F)
    progs = {}
    if s == 200:
        for a in r['alumnos']:
            if a.get('estado'):
                progs[a['id_programa']] = progs.get(a['id_programa'], 0) + 1
    chk['por_subprograma'] = {('Alfabetización' if k == A.ALFA() else 'Comprensión Lectora'): v for k, v in progs.items()}
    R.consola(ctx, 'Paso 9: lo guardado, por la API (en local se veía en la base de datos)',
              [f'Clases del {FE.legible(F)} (id | tipo | original | vigente | con asistencias): {chk["api"]["clases"]}',
               f'Alumnos marcados: {len(chk["api"]["asistencias"].get("marcados", []))} de {chk["api"]["asistencias"].get("lista")}',
               f'Marcados por subprograma: {chk["por_subprograma"]}'])
    fin_caso(R, chk, n)


@caso('CP-ASI-02')
def cp_asi02():
    R = Run('CP-ASI-02'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    F = _f()
    con_actividad(p, C); abrir_asis(p, F, sub='Comprensión Lectora')
    marcar_asis(p, 'Ana Norte QA', 'Presente')
    g = p.get_by_role('button', name='Añadir observación de Ana Norte QA')
    chk['globo'] = (g.get_attribute('title'), g.evaluate("e=>getComputedStyle(e).color")); g.hover(); p.wait_for_timeout(500)
    chk['ayuda'] = p.locator('[role=tooltip]').all_inner_texts()
    R.shot(p, f'Paso 1: globo sin observación: {chk["globo"]}; ayuda {chk["ayuda"]}')
    g.click(); p.wait_for_timeout(800); d = p.locator('[role=dialog]:visible').last
    chk['modal'] = (d.inner_text()[:250], d.get_by_role('button').all_inner_texts())
    d.locator('textarea').fill('Llegó con su cuaderno de lectura.')
    R.shot(p, f'Paso 2: modal {chk["modal"]}')
    try:
        with p.expect_response(lambda r: '/api/asistencias' in r.url and r.request.method == 'PUT', timeout=8000) as ri:
            d.get_by_role('button', name=re.compile('Guardar')).click()
        chk['guardar'] = ri.value.status
    except Exception as e:
        chk['guardar'] = str(e)[:60]
    p.wait_for_timeout(1200)
    g2 = p.get_by_role('button', name='Ver observación de Ana Norte QA')
    chk['tras'] = {'modal_abierto': p.locator('[role=dialog]:visible').count(),
                   'globo': (g2.count(), g2.first.get_attribute('title') if g2.count() else None, g2.first.evaluate("e=>getComputedStyle(e).color") if g2.count() else None)}
    R.shot(p, f'Paso 3: tras guardar: {chk["tras"]}')
    g2.first.click(); p.wait_for_timeout(800); d = p.locator('[role=dialog]:visible').last
    d.locator('textarea').fill('Llegó con su cuaderno de lectura y su libro.')
    try:
        with p.expect_response(lambda r: '/api/asistencias' in r.url and r.request.method == 'PUT', timeout=8000):
            d.get_by_role('button', name=re.compile('Guardar')).click()
    except Exception:
        pass
    p.wait_for_timeout(1000)
    chk['api'] = de_alumno(F, 'Ana Norte QA')
    R.consola(ctx, 'Paso 4: lo guardado tras modificar la observación (estado | observación | versión)', [str(chk['api'])])
    act = act_de(C); A.finalizar_actividad(C, act)
    p.reload(); p.wait_for_timeout(2500); abrir_asis(p, F, sub='Comprensión Lectora')
    b = p.get_by_role('button', name=re.compile('observación de Ana Norte QA')); b.first.click(); p.wait_for_timeout(800)
    d = p.locator('[role=dialog]:visible').last
    chk['solo_lectura'] = (d.inner_text()[:200], d.get_by_role('button').all_inner_texts(), d.locator('textarea').count())
    cerrar_dialogos(p)
    b = p.get_by_role('button', name=re.compile('observación de Beto Norte QA')).first
    chk['sin_obs'] = {'deshabilitado': b.is_disabled(), 'title': b.get_attribute('title'), 'clase': (b.get_attribute('class') or '')[-60:]}
    R.shot(p, f'Paso 5: sin actividad: {chk["solo_lectura"]}; sin observación: {chk["sin_obs"]}')
    n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    con_actividad(p, C); abrir_asis(p, F, sub='Comprensión Lectora')
    p.get_by_role('button', name=re.compile('observación de Beto Norte QA')).first.click(); p.wait_for_timeout(800)
    d = p.locator('[role=dialog]:visible').last
    d.locator('textarea').fill('Texto escrito antes de que termine la actividad.')
    A.finalizar_actividad(C, act_de(C))
    try:
        with p.expect_response(lambda r: '/api/asistencias' in r.url and r.request.method == 'PUT', timeout=8000) as ri:
            d.get_by_role('button', name=re.compile('Guardar')).click()
        chk['tras_fin'] = (ri.value.status, ri.value.json().get('resultados', [{}])[0].get('motivo') if ri.value.status == 200 else ri.value.text()[:150])
    except Exception as e:
        chk['tras_fin'] = str(e)[:60]
    p.wait_for_timeout(1500); dd = p.locator('[role=dialog]:visible')
    chk['tras_fin_ui'] = {'modal': dd.count(), 'texto': dd.locator('textarea').input_value() if dd.count() and dd.locator('textarea').count() else None,
                          'avisos': toasts_txt(p)}
    R.shot(p, f'Paso 6: guardar con la actividad finalizada en otra pestaña → {chk["tras_fin"]}; {chk["tras_fin_ui"]}')
    fin_caso(R, chk, n)


@caso('CP-ASI-03')
def cp_asi03():
    R = Run('CP-ASI-03'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    previa = FE.ultima_clase(3, incluir_hoy=False)
    con_actividad(p, C)
    if previa:
        abrir_asis(p, previa, sub='Comprensión Lectora')
        f = fila(p, 'Extra12'); chk['inactivo'] = f.inner_text().replace('\n', ' ')[:80] if f.count() else None
        chk['registrar'] = marcar_asis(p, 'Extra12 Rubrica QA', 'Presente')
        R.shot(p, f'Paso 1: clase del {FE.legible(previa)} (Extra12 inactivo desde hoy, perteneció ese día): {chk["inactivo"]}; marcar → {chk["registrar"]}', full=True)
    else:
        R.nota('Paso 1: no hay una clase anterior a hoy en el PA vigente; no se pudo probar el alumno hoy inactivo.')
    manana = A.hoy() + dt.timedelta(days=1)
    receso = FE.receso_pasado(); nolect, motivo = FE.no_lectivo_pasado(); fuera = FE.antes_del_anio()
    res = {}
    for k, fch in [(f'Paso 2: mañana ({FE.legible(manana)})', manana), (f'Paso 3: receso ({FE.legible(receso)})', receso),
                   (f'Paso 4: día no lectivo ({FE.legible(nolect)}, {motivo})', nolect), (f'Paso 5: fuera de todo PA ({FE.legible(fuera)})', fuera)]:
        if not fch:
            R.nota(f'{k}: no hay una fecha así en el calendario de QA.')
            continue
        p.locator('main input[type=date]').first.fill(A.iso(fch)); p.wait_for_timeout(2500)
        res[k] = (textos(p, 'fecha', 'lectivo', 'receso', 'periodo'), p.locator('main tbody tr').count(),
                  p.get_by_role('button', name='Marcar todos como presentes').count())
        R.shot(p, f'{k}: {res[k]}')
    chk['fechas'] = res
    chk['api_futura'] = put_asis(C, manana, [(D.alumno('Ana Norte QA'), 'presente', None)], act_de(C))
    R.consola(ctx, 'Paso 2: asistencia de mañana por la API', [f'PUT /api/asistencias ({FE.legible(manana)}) → {json.dumps(chk["api_futura"], ensure_ascii=False)[:300]}'])
    fin_caso(R, chk, n)


@caso('CP-ASI-04')
def cp_asi04():
    R = Run('CP-ASI-04'); chk = {}; C = _c(); F = _f()
    _, act = nueva_act(C)
    chk['prep'] = put_asis(C, F, [(D.alumno('Ana Norte QA'), 'presente', 'Trajo su libro de lectura.'), (D.alumno('Beto Norte QA'), 'ausente', None)], act)
    A.cerrar_abiertas(C)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); puts = espiar_puts(p)
    login(p, C); abrir_asis(p, F, sub='Comprensión Lectora'); m = p.locator('main')
    chk['controles'] = controles(p); chk['lote'] = m.get_by_role('button', name='Marcar todos como presentes').count()
    chk['marcas'] = {k: estado_asis(p, k)['marcado'] for k in ['Ana Norte QA', 'Beto Norte QA', 'Carla Norte QA']}
    chk['aviso'] = aviso_sup(p)
    R.shot(p, f'Paso 1: sin actividad, {FE.legible(F)}: controles {chk["controles"]}; "Marcar todos" = {chk["lote"]}; marcas {chk["marcas"]}')
    chk['orden'] = p.evaluate("""()=>{const t=[...document.querySelectorAll('main *')].find(e=>e.children.length===0&&/Inicia una actividad/.test(e.textContent));const tb=document.querySelector('main table');
        if(!t||!tb) return null; return (t.compareDocumentPosition(tb)&Node.DOCUMENT_POSITION_FOLLOWING)?'aviso antes de la tabla':'aviso después de la tabla'}""")
    R.shot(p, f'Paso 2: aviso {chk["aviso"]} ({chk["orden"]})')
    p.get_by_role('button', name='Ver observación de Ana Norte QA').click(); p.wait_for_timeout(700); d = p.locator('[role=dialog]:visible').last
    ta = d.locator('textarea')
    chk['modal'] = (d.inner_text()[:200], d.get_by_role('button').all_inner_texts(), ta.get_attribute('readonly') is not None if ta.count() else None)
    R.shot(p, f'Paso 3: observación de Ana en solo lectura: {chk["modal"]}'); cerrar_dialogos(p)
    for nom, est in [('Beto Norte QA', 'Presente'), ('Carla Norte QA', 'Tardanza')]:
        try:
            p.get_by_role('button', name=f'{est}: {nom}', exact=True).click(force=True, timeout=3000)
        except Exception:
            pass
    p.wait_for_timeout(2500); chk['puts'] = list(puts); chk['tras_clic'] = {k: estado_asis(p, k)['marcado'] for k in ['Beto Norte QA', 'Carla Norte QA']}
    R.consola(ctx, 'Paso 4: Network durante los clics en los controles deshabilitados',
              [f'Peticiones PUT /api/asistencias: {chk["puts"] or "ninguna"}', f'Marcas tras los clics: {chk["tras_clic"]}'])
    n.close()
    # Paso 5: grupo sin alumnos (2.º de Norte, con su único alumno inactivo desde el inicio del PA)
    pa = FE.pa_actual(); F2 = FE.ultima_clase(2)
    g2 = D.alumno('Grado2P2 Entrada QA')
    chk['inactivar'] = A.desactivar_alumno(g2, pa['fecha_inicio'])[0]
    D1 = D.cuenta('rv-uno')
    n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    con_actividad(p, D1); abrir_asis(p, F2, grado='2.º'); m = p.locator('main')
    chk['vacio'] = (textos(p, 'No hay alumnos', 'Sin alumnos'), m.locator('table').count(),
                    m.get_by_role('button', name='Marcar todos como presentes').count(), filtros_ui(p))
    R.shot(p, f'Paso 5: 2.º del colegio el {FE.legible(F2)}, sin alumnos activos: {chk["vacio"]}')
    A.cerrar_abiertas(D1); fin_caso(R, chk, n)


@caso('CP-ASI-05')
def cp_asi05():
    R = Run('CP-ASI-05'); chk = {}; C = _c(); F = _f(); S = sup_ui()
    _, act = nueva_act(C)
    chk['prep'] = put_asis(C, F, [(D.alumno('Ana Norte QA'), 'presente', 'Trajo su libro de lectura.'), (D.alumno('Beto Norte QA'), 'tardanza', None)], act)
    A.finalizar_actividad(C, act)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); puts = espiar_puts(p)
    login(p, S); ir(p, 'Asistencias'); p.wait_for_timeout(1500)
    chk['filtros_ini'] = filtros_ui(p)
    abrir_asis(p, F, colegio=NX()); m = p.locator('main')
    chk['controles'] = controles(p); chk['lote'] = m.get_by_role('button', name='Marcar todos como presentes').count(); chk['aviso'] = aviso_sup(p)
    chk['marcas'] = {k: estado_asis(p, k)['marcado'] for k in ['Ana Norte QA', 'Beto Norte QA']}
    R.shot(p, f'Paso 1: Supervisora en Asistencias, {NX()} 3.º {FE.legible(F)}: filtros {filtros_ui(p)}; controles {chk["controles"]}; "Marcar todos" = {chk["lote"]}; marcas {chk["marcas"]}')
    cols = opciones(p, 'Colegio') or []
    chk['colegios'] = len(cols)
    otro = next((c for c in cols if not c.startswith(NX()) and c.strip() and 'Seleccione' not in c), None)
    if otro:
        poner(p, 'Colegio', otro); p.wait_for_timeout(2000)
        chk['otro_colegio'] = (otro, filtros_ui(p), textos(p, 'alumno', 'No hay', 'Complete')[:2])
        R.shot(p, f'Paso 1: cambio a otro colegio ({otro}): {chk["otro_colegio"]}')
    ir(p, 'Seguimiento'); p.wait_for_timeout(2000)
    fd = p.locator('main tbody tr').filter(has_text='Docente A').first
    try:
        fd.get_by_role('button', name=re.compile('Ver detalle')).first.click(); p.wait_for_timeout(2000)
        b = p.get_by_role('button', name='Ver Asistencias').first; chk['atajo'] = b.count()
        b.click(); p.wait_for_timeout(2000); d = p.locator('[role=dialog]:visible').last
        chk['ver_asis'] = d.inner_text()[:500] if d.count() else textos(p, 'Asistencia')[:3]
        R.shot(p, f'Paso 2: Seguimiento → detalle de Docente A → "Ver Asistencias": {str(chk["ver_asis"])[:250]}', full=True)
        cerrar_dialogos(p)
    except Exception as e:
        chk['ver_asis'] = 'sin atajo: ' + str(e)[:80]; R.shot(p, f'Paso 2: {chk["ver_asis"]}', full=True)
    ir(p, 'Asistencias'); p.wait_for_timeout(1500); abrir_asis(p, F, colegio=NX())
    p.get_by_role('button', name='Ver observación de Ana Norte QA').click(); p.wait_for_timeout(700); d = p.locator('[role=dialog]:visible').last
    chk['modal'] = (d.inner_text()[:200], d.get_by_role('button').all_inner_texts())
    R.shot(p, f'Paso 3: observación en solo lectura: {chk["modal"]}'); cerrar_dialogos(p)
    for nom, est in [('Beto Norte QA', 'Presente'), ('Carla Norte QA', 'Ausente')]:
        try:
            p.get_by_role('button', name=f'{est}: {nom}', exact=True).click(force=True, timeout=3000)
        except Exception:
            pass
    p.wait_for_timeout(2000); chk['puts'] = list(puts)
    chk['api_sup'] = put_asis(token_navegador(p), F, [(D.alumno('Carla Norte QA'), 'presente', None)], act)
    R.consola(ctx, 'Pasos 4-5: Network y API con el token de la Supervisora',
              [f'PUT /api/asistencias enviados por los clics: {chk["puts"] or "ninguno"}', f'PUT /api/asistencias con el token de la Supervisora → {chk["api_sup"]}'])
    n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    login(p, D.cuenta('directivo')); menu = p.locator('aside nav').inner_text()
    p.goto(BASE + '/asistencia'); p.wait_for_timeout(2000); url = p.url
    tkd = token_navegador(p)
    chk['directivo'] = ('Asistencia' in menu, url.replace(BASE, ''), get_asis(tkd, F)[0], put_asis(tkd, F, [(D.alumno('Carla Norte QA'), 'presente', None)], act))
    R.shot(p, f'Paso 6: Directivo: Asistencias en el menú = {chk["directivo"][0]}; /asistencia → {chk["directivo"][1]}; GET API → {chk["directivo"][2]}; PUT API → {chk["directivo"][3]}')
    R.save(checks=chk); n.close()


@caso('CP-ASI-06', modo='parcial', notas='La sesión expirada del paso 4 se simula cerrando la sesión en el servidor.')
def cp_asi06():
    R = Run('CP-ASI-06'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); F = _f()
    con_actividad(p, C); abrir_asis(p, F); chk['clase_antes'] = clases_api(F)
    ctx.set_offline(True); p.wait_for_timeout(800)
    for nom, est in [('Ana Norte QA', 'Presente'), ('Beto Norte QA', 'Tardanza')]:
        marcar_asis(p, nom, est, esperar=False)
    poner(p, 'Subprograma', 'Alfabetización'); p.wait_for_timeout(800); marcar_asis(p, 'Alumno03 Volumen QA', 'Ausente', esperar=False)
    chk['marcas'] = {'Alumno03 Volumen QA': (estado_asis(p, 'Alumno03 Volumen QA') or {}).get('marcado')}
    poner(p, 'Subprograma', 'Todos'); p.wait_for_timeout(1000)
    chk['marcas'].update({k: (estado_asis(p, k) or {}).get('marcado') for k in ['Ana Norte QA', 'Beto Norte QA']})
    chk['indicador'] = p.locator('header').first.inner_text().replace('\n', ' ')[:120]; chk['avisos'] = toasts_txt(p)
    raw = idb_todo(p); chk['cola'] = cola_idb(p)[:3]; ids = ids_operacion(raw)
    chk['lista_local'] = {'Alumno03 (Alfabetización)': raw.count('Alumno03'), 'Ana (Comprensión Lectora)': raw.count('Ana'), 'claves': [k for k in json.loads(raw)]}
    R.shot(p, f'Paso 1: sin conexión, tres marcas (dos subprogramas): {chk["marcas"]}; cabecera "{chk["indicador"]}"; avisos {chk["avisos"]}', full=True)
    R.consola(ctx, 'Paso 1: IndexedDB (cola de envíos)', [str(c)[:440] for c in chk['cola']] + [f'Apariciones en IndexedDB: {chk["lista_local"]}'])
    ir(p, 'Inicio'); p.wait_for_timeout(1500); chk['inicio'] = textos(p, 'pendiente', 'sin enviar', 'sincroniz')
    R.shot(p, f'Paso 2: Inicio sin conexión: {chk["inicio"]}', full=True)
    ctx.set_offline(False); p.wait_for_timeout(9000)
    chk['api'] = (asis_api(F), clases_api(F), ops_api(C, ids))
    chk['cabecera_sync'] = p.locator('header').first.inner_text().replace('\n', ' ')[:120]
    R.shot(p, f'Paso 3: reconectado: cabecera "{chk["cabecera_sync"]}"')
    R.consola(ctx, 'Paso 3: lo guardado tras reconectar (API)', [f'Asistencias del {FE.legible(F)}: {chk["api"][0]}', f'Clases (id | tipo | original | vigente | con asistencias): {chk["api"][1]}',
                                                              f'Operaciones de la cola (id | HTTP | estado | motivo): {chk["api"][2]}'])
    # Paso 4: sin conexión y con la sesión cerrada en el servidor
    ir(p, 'Asistencias'); p.wait_for_timeout(1500); abrir_asis(p, F)
    tk_ses = token_navegador(p)
    ctx.set_offline(True); p.wait_for_timeout(500); marcar_asis(p, 'Carla Norte QA', 'Presente', esperar=False); p.wait_for_timeout(1000)
    A.api('POST', '/logout', tk_ses)
    R.nota('Paso 4: en QA no se puede expirar la sesión desde la base de datos; se cerró en el servidor con POST /logout (el token deja de valer igual que al expirar).')
    chk['cola_exp'] = cola_idb(p)[:2]; ids2 = ids_operacion(idb_todo(p))
    ctx.set_offline(False); p.wait_for_timeout(9000)
    chk['tras_expirar'] = {'url': p.url.replace(BASE, ''), 'cola': len(cola_idb(p)), 'carla': de_alumno(F, 'Carla Norte QA'), 'texto': textos(p, 'sesión', 'expir', 'pendiente')}
    R.shot(p, f'Paso 4: sesión cerrada al reconectar: {chk["tras_expirar"]}', full=True)
    if '/login' in p.url:
        llenar_login(p, C.correo, C.clave); p.click('button[type=submit]'); p.wait_for_timeout(6000)
        C.usar_token(token_navegador(p))
    else:
        login(p, C)
    p.wait_for_timeout(6000)
    chk['tras_login'] = {'url': p.url.replace(BASE, ''), 'cola': len(cola_idb(p)), 'carla': de_alumno(F, 'Carla Norte QA'), 'ops': ops_api(C, ids2)}
    R.shot(p, f'Paso 4: tras volver a autenticarse: {chk["tras_login"]}', full=True)
    # Paso 5: sin la habilitación en IndexedDB
    n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C); abrir_asis(p, F)
    chk['borradas'] = p.evaluate("""(async()=>{const out=[];for(const d of await indexedDB.databases()){const db=await new Promise(r=>{const o=indexedDB.open(d.name);o.onsuccess=()=>r(o.result)});
        for(const s of db.objectStoreNames){const tx=db.transaction(s,'readwrite');const st=tx.objectStore(s);const ks=await new Promise(r=>{const q=st.getAllKeys();q.onsuccess=()=>r(q.result)});
          for(const k of ks){const v=await new Promise(r=>{const q=st.get(k);q.onsuccess=()=>r(q.result)});const t=JSON.stringify(v)||'';
            if(/habilitacion/i.test(String(k))||/habilitaciones/.test(t)){ if(String(k).includes('cache')&&v&&v.clientState){v.clientState.queries=v.clientState.queries.filter(qq=>!JSON.stringify(qq.queryKey).includes('habilitacion'));st.put(v,k);out.push('filtrada '+k)} else {st.delete(k);out.push('borrada '+k)}}}}}return out})()""")
    ctx.set_offline(True); ir(p, 'Inicio'); p.wait_for_timeout(1000); ir(p, 'Asistencias'); p.wait_for_timeout(2000); abrir_asis(p, F)
    chk['sin_hab'] = {'aviso': aviso_sup(p) + textos(p, 'No se puede verificar'), 'controles': controles(p)}
    chk['sin_hab']['clic'] = marcar_asis(p, 'Dante Norte QA', 'Presente', esperar=False); chk['sin_hab']['dante'] = estado_asis(p, 'Dante Norte QA')
    R.shot(p, f'Paso 5: sin la habilitación en IndexedDB ({chk["borradas"]}) y sin conexión: {chk["sin_hab"]}', full=True)
    ctx.set_offline(False); p.wait_for_timeout(3000)
    fin_caso(R, chk, n)


@caso('CP-ASI-07')
def cp_asi07():
    R = Run('CP-ASI-07'); chk = {}; C = _c(); F = _f()
    _, act0 = nueva_act(C)
    put_asis(C, F, [(D.alumno('Ana Norte QA'), 'presente', None), (D.alumno('Beto Norte QA'), 'presente', None)], act0); A.cerrar_abiertas(C)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); puts = espiar_puts(p)
    con_actividad(p, C); abrir_asis(p, F, sub='Comprensión Lectora')
    p.evaluate("""()=>{window.__putOrig=IDBObjectStore.prototype.put;IDBObjectStore.prototype.put=function(){throw new DOMException('Simulado por QA','QuotaExceededError')}}""")
    ctx.set_offline(True); p.wait_for_timeout(500)
    antes = estado_asis(p, 'Ana Norte QA')['marcado']; marcar_asis(p, 'Ana Norte QA', 'Tardanza', esperar=False); p.wait_for_timeout(300)
    chk['idb_falla'] = {'antes': antes, 'despues': estado_asis(p, 'Ana Norte QA')['marcado'], 'avisos': toasts_txt(p)}
    R.shot(p, f'Paso 1: error de IndexedDB simulado, sin conexión: {chk["idb_falla"]}')
    p.evaluate("()=>{IDBObjectStore.prototype.put=window.__putOrig}"); ctx.set_offline(False); p.wait_for_timeout(2500)
    otro = D.alumno('Grado4P2 Entrada QA')

    def alterar(route):
        b = json.loads(route.request.post_data)
        for r_ in b.get('registros', []):
            r_['id_alumno'] = otro
        route.continue_(post_data=json.dumps(b))
    p.route('**/api/asistencias', lambda route: alterar(route) if route.request.method == 'PUT' else route.continue_())
    ctx.set_offline(True); p.wait_for_timeout(400)
    marcar_asis(p, 'Beto Norte QA', 'Ausente', esperar=False); p.wait_for_timeout(600)
    chk['cola_alterada'] = cola_idb(p)[:1]; ids = ids_operacion(idb_todo(p))
    ctx.set_offline(False); p.wait_for_timeout(6000)
    chk['rechazo'] = {'avisos': toasts_txt(p), 'fila_beto': fila(p, 'Beto Norte QA').inner_text().replace('\n', ' ')[:120], 'marca': estado_asis(p, 'Beto Norte QA')['marcado'],
                      'cola': cola_idb(p)[:1], 'cabecera': p.locator('header').first.inner_text().replace('\n', ' ')[:100], 'ops': ops_api(C, ids)}
    R.shot(p, f'Paso 2: operación de un alumno fuera de la lista (Grado4P2) al reconectar: {chk["rechazo"]}', full=True)
    p.unroute('**/api/asistencias'); n1 = len(puts); p.wait_for_timeout(10000)
    chk['reenvio'] = {'puts_en_10s': len(puts) - n1, 'beto': de_alumno(F, 'Beto Norte QA'), 'marca_ui': estado_asis(p, 'Beto Norte QA')['marcado']}
    try:
        p.locator('header').get_by_role('button').filter(has_text=re.compile('pendiente|error|sincroniz', re.I)).first.click(timeout=3000); p.wait_for_timeout(800)
        chk['panel'] = p.locator('[role=dialog]:visible').last.inner_text()[:400]
    except Exception as e:
        chk['panel'] = str(e)[:60]
    R.shot(p, f'Paso 3: sin reenvío automático y fila con la última asistencia confirmada: {chk["reenvio"]}; panel: {chk["panel"][:200]}')
    cerrar_dialogos(p)
    # Paso 4: revocación del permiso que habilita (Asistencias del último PA culminado)
    pa_ant = FE.pa_anterior()
    clases_ant = FE.clases_del_pa(3, pa_ant['numero']) if pa_ant else []
    if not clases_ant:
        R.nota('Paso 4: no hay un PA culminado con clases del 3.º; no se pudo probar la revocación.')
    else:
        F12 = clases_ant[-1]; uid = D.id_usuario('docente-a')
        s, pr = A.permiso(uid, D.X(), 3, pa_ant['id_periodo_academico'], 'asistencias', A.ahora() + dt.timedelta(days=30))
        chk['permiso'] = (s, pr.get('id') if isinstance(pr, dict) else pr)
        abrir_asis(p, F12, sub='Comprensión Lectora')
        chk['pa_ant_antes'] = (aviso_sup(p), marcar_asis(p, 'Ana Norte QA', 'Presente'))
        chk['revocar'] = A.api('POST', f'/usuarios/{uid}/permisos/{chk["permiso"][1]}/revocar', A.sup(), {'motivo': 'Prueba QA de revocación'})[0]
        chk['tras_revocar'] = marcar_asis(p, 'Beto Norte QA', 'Presente'); p.wait_for_timeout(1200)
        chk['tras_revocar_ui'] = {'avisos': toasts_txt(p), 'beto': estado_asis(p, 'Beto Norte QA')['marcado'], 'controles': controles(p)}
        chk['tras_revocar_api'] = {'beto': de_alumno(F12, 'Beto Norte QA'),
                                   'permiso': (lambda r: (r.get('estado'), r.get('revocado_en')))(A.api('GET', f'/usuarios/{uid}/permisos/{chk["permiso"][1]}', A.sup())[1])}
        R.consola(ctx, 'Paso 4: tras la revocación (API)', [f'{k}: {v}' for k, v in chk['tras_revocar_api'].items()])
        R.shot(p, f'Paso 4: PA{pa_ant["numero"]} {FE.legible(F12)} con permiso: {chk["pa_ant_antes"]}; revocado ({chk["revocar"]}) → {chk["tras_revocar"]}; {chk["tras_revocar_ui"]}')
        p.reload(); p.wait_for_timeout(2500); abrir_asis(p, F12, sub='Comprensión Lectora')
        chk['tras_recargar'] = {'aviso': aviso_sup(p), 'controles': controles(p)}
        R.shot(p, f'Paso 4: tras recargar: {chk["tras_recargar"]}')
    # Paso 5: corte de red justo después de marcar
    abrir_asis(p, F, sub='Comprensión Lectora')
    p.route('**/api/asistencias', lambda route: route.abort('internetdisconnected') if route.request.method == 'PUT' else route.continue_())
    marcar_asis(p, 'Carla Norte QA', 'Tardanza', esperar=False); p.wait_for_timeout(2500)
    chk['corte'] = {'cola': cola_idb(p)[:1], 'cabecera': p.locator('header').first.inner_text().replace('\n', ' ')[:100], 'avisos': toasts_txt(p),
                    'marca': estado_asis(p, 'Carla Norte QA')['marcado']}
    R.shot(p, f'Paso 5: corte de red al enviar: {chk["corte"]}')
    p.unroute('**/api/asistencias'); p.wait_for_timeout(8000)
    chk['corte_despues'] = de_alumno(F, 'Carla Norte QA')
    R.consola(ctx, 'Paso 5: Carla tras restablecer la red (estado | observación | versión)', [str(chk['corte_despues'])])
    fin_caso(R, chk, n)


@caso('CP-ASI-08')
def cp_asi08():
    R = Run('CP-ASI-08'); n = Nav(); chk = {}; C = _c(); F = _f()
    ctxA = n.ctx(); pA = ctxA.new_page(); con_actividad(pA, C)
    ss = pA.evaluate('JSON.stringify(Object.entries(sessionStorage))'); st = ctxA.storage_state()
    ctxB = n.ctx(storage_state=st); ctxB.add_init_script(f"if(!sessionStorage.getItem('sicedu.token')){{for(const [k,v] of {ss}) sessionStorage.setItem(k,v)}}")
    pB = ctxB.new_page(); pB.goto(BASE + '/inicio'); pB.wait_for_timeout(2500)
    abrir_asis(pA, F, sub='Comprensión Lectora'); abrir_asis(pB, F, sub='Comprensión Lectora')
    chk['B_sesion'] = (pB.url.replace(BASE, ''), pB.locator('header').first.inner_text().replace('\n', ' ')[:80])
    ctxA.set_offline(True); ctxB.set_offline(True); pA.wait_for_timeout(400)
    marcar_asis(pA, 'Carla Norte QA', 'Presente', esperar=False); marcar_asis(pB, 'Dante Norte QA', 'Presente', esperar=False)
    ctxA.set_offline(False); ctxB.set_offline(False); pA.wait_for_timeout(9000)
    chk['clase_nueva'] = (clases_api(F), asis_api(F).get('marcados'))
    R.shot(pA, f'Paso 4: A y B sin conexión marcan a Carla y a Dante en la clase nueva del {FE.legible(F)}; al reconectar: clases {chk["clase_nueva"][0]}')
    R.consola(ctxA, 'Paso 4: lo guardado (API)', [f'Clases (id | tipo | original | vigente | con asistencias): {chk["clase_nueva"][0]}', f'Asistencias (alumno | estado | obs. | versión): {chk["clase_nueva"][1]}'])
    chk['A_presente'] = marcar_asis(pA, 'Ana Norte QA', 'Presente'); chk['B_ausente'] = marcar_asis(pB, 'Ana Norte QA', 'Ausente')
    chk['api_ana'] = de_alumno(F, 'Ana Norte QA')
    R.shot(pB, f'Pasos 1-2: A marca Presente {chk["A_presente"]}, B (sin recargar) Ausente {chk["B_ausente"]}; API: {chk["api_ana"]}')
    ctxB.set_offline(True); pB.wait_for_timeout(300); marcar_asis(pB, 'Ana Norte QA', 'Tardanza', esperar=False); pB.wait_for_timeout(1500)
    idsB = ids_operacion(idb_todo(pB))
    chk['A_tardanza_presente'] = (marcar_asis(pA, 'Ana Norte QA', 'Tardanza'), marcar_asis(pA, 'Ana Norte QA', 'Presente'))
    ctxB.set_offline(False); pB.wait_for_timeout(9000)
    chk['tras_B'] = {'api': de_alumno(F, 'Ana Norte QA'), 'B_ui': estado_asis(pB, 'Ana Norte QA')['marcado'], 'B_avisos': toasts_txt(pB), 'ops': ops_api(C, idsB)}
    R.shot(pB, f'Paso 3: B sin conexión marca Tardanza; luego A (que veía Presente) marca Tardanza y Presente {chk["A_tardanza_presente"]}; B reconecta: {chk["tras_B"]}')
    for e in ['Presente', 'Tardanza', 'Ausente', 'Presente', 'Tardanza']:
        marcar_asis(pA, 'Elsa Norte QA', e); pA.wait_for_timeout(300)
    chk['elsa'] = de_alumno(F, 'Elsa Norte QA')
    R.shot(pA, f'Paso 5: Elsa marcada cinco veces: API {chk["elsa"]}')
    act = act_de(C); ctxB.close()
    b = pA.get_by_role('button', name='Finalizar actividad'); b.first.click(); pA.wait_for_timeout(800)
    d = pA.locator('[role=dialog]:visible')
    if d.count():
        d.last.get_by_role('button', name=re.compile('Finalizar')).last.click(); pA.wait_for_timeout(2500)
    ir(pA, 'Sesiones'); pA.wait_for_timeout(2000)
    chk['sesiones'] = pA.locator('main tbody tr').first.inner_text().replace('\n', ' | ')[:200] if pA.locator('main tbody tr').count() else textos(pA, 'Asistencia')
    try:
        pA.locator('main tbody tr').first.get_by_role('button', name=re.compile('Ver detalle')).click(); pA.wait_for_timeout(1500)
        chk['sesion_detalle'] = pA.locator('[role=dialog]:visible').last.inner_text()[:500]
    except Exception as e:
        chk['sesion_detalle'] = str(e)[:60]
    R.shot(pA, f'Paso 6: Sesiones: {chk["sesiones"]}; detalle: {str(chk["sesion_detalle"])[:300]}', full=True)
    ctxS = n.ctx(); pS = ctxS.new_page(); login(pS, sup_ui()); ir(pS, 'Seguimiento'); pS.wait_for_timeout(2000)
    try:
        pS.locator('main tbody tr').filter(has_text='Docente A').first.get_by_role('button', name=re.compile('Ver detalle')).first.click(); pS.wait_for_timeout(2000)
        chk['productividad'] = pS.locator('main tbody tr').first.inner_text().replace('\n', ' | ')[:250]
    except Exception as e:
        chk['productividad'] = str(e)[:60]
    did = D.id_docente('docente-a')
    chk['api_prod'] = (A.api('GET', f'/seguimiento/docentes/{did}/actividades', A.sup())[1] or {}).get('items', [{}])[0]
    chk['api_registros'] = A.api('GET', f'/seguimiento/docentes/{did}/actividades/{act}/registros?modulo=asistencias', A.sup())
    R.shot(pS, f'Paso 6: Seguimiento (Supervisora), productividad de la actividad: {chk["productividad"]}', full=True)
    R.consola(ctxS, 'Paso 6: productividad por la API', [json.dumps(chk['api_prod'], ensure_ascii=False)[:900], json.dumps(chk['api_registros'], ensure_ascii=False)[:900]])
    R.save(checks=chk); n.close()


@caso('CP-ASI-09')
def cp_asi09():
    R = Run('CP-ASI-09'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); F = _f()
    con_actividad(p, C); abrir_asis(p, F)
    chk['alfa'] = marcar_asis(p, 'Alumno03 Volumen QA', 'Presente'); chk['cl'] = marcar_asis(p, 'Ana Norte QA', 'Presente')
    R.shot(p, f'Paso 1: 3.º, Alfabetización (Alumno03) → {chk["alfa"]}; Comprensión Lectora (Ana) → {chk["cl"]}')
    chk['grados'] = [s.locator('option').all_inner_texts() for s in p.locator('main select').all()][:3]
    R.shot(p, f'Paso 2: opciones de los filtros del Docente (colegio, grado, sección): {chk["grados"]}')
    act = act_de(C); F4 = FE.ultima_clase(4); sur = D.Y()
    chk['api_4'] = put_asis(C, F4, [(D.alumno('Grado4P2 Entrada QA'), 'presente', None)], act, grado=4)
    chk['api_sur'] = put_asis(C, FE.ultima_clase(3, cid=sur), [(D.alumno('Kira Sur QA'), 'presente', None)], act, grado=3, colegio=sur)
    g4 = get_asis(C, F4, grado=4); chk['get_4'] = (g4[0], g4[1].get('motivo') if isinstance(g4[1], dict) else None)
    R.consola(ctx, 'Paso 3: asistencias fuera de su asignación por la API',
              [f'PUT 4.º del colegio ({FE.legible(F4)}) → {chk["api_4"]}', f'PUT del colegio Sur → {chk["api_sur"]}', f'GET 4.º del colegio → {chk["get_4"]}'])
    pa_ant = FE.pa_anterior()
    if not pa_ant:
        R.nota('Paso 4: no hay un PA culminado para otorgar el permiso.')
    else:
        uid = D.id_usuario('docente-a')
        s, pr = A.permiso(uid, D.X(), 4, pa_ant['id_periodo_academico'], 'asistencias', A.ahora() + dt.timedelta(days=30)); chk['permiso'] = s
        p.reload(); p.wait_for_timeout(2500); ir(p, 'Asistencias'); p.wait_for_timeout(1500)
        chk['grados_con_permiso'] = [s_.locator('option').all_inner_texts() for s_ in p.locator('main select').all()][:2]
        F4a = (FE.clases_del_pa(4, pa_ant['numero']) or [None])[-1]
        if poner(p, 'Grado', '4.º') and F4a:
            p.locator('main input[type=date]').first.fill(A.iso(F4a)); p.wait_for_timeout(2500)
            chk['ui_4_pa_ant'] = (aviso_sup(p), controles(p), marcar_asis(p, 'Grado4P2 Entrada QA', 'Presente'))
            p.locator('main input[type=date]').first.fill(A.iso(F4)); p.wait_for_timeout(2500)
            chk['ui_4_pa_actual'] = (aviso_sup(p), controles(p))
        R.shot(p, f'Paso 4: con permiso de Asistencias del 4.º en PA{pa_ant["numero"]}: grados {chk["grados_con_permiso"]}; UI PA{pa_ant["numero"]} {chk.get("ui_4_pa_ant")}; UI PA vigente {chk.get("ui_4_pa_actual")}', full=True)
        chk['api_4_pa_ant'] = put_asis(C, F4a, [(D.alumno('Grado4P1 Entrada QA'), 'presente', None)], act, grado=4) if F4a else None
        chk['api_4_pa_actual'] = put_asis(C, F4, [(D.alumno('Grado4P1 Entrada QA'), 'presente', None)], act, grado=4)
        R.consola(ctx, 'Paso 4: con el permiso, por la API', [f'PUT 4.º PA{pa_ant["numero"]} ({FE.legible(F4a)}) → {chk["api_4_pa_ant"]}', f'PUT 4.º PA vigente ({FE.legible(F4)}) → {chk["api_4_pa_actual"]}'])
    fin_caso(R, chk, n)


@caso('CP-ASI-10')
def cp_asi10():
    R = Run('CP-ASI-10'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    x = D.X(); sec = A.seccion(x, 3)
    F = FE.ultima_clase(3, incluir_hoy=False)
    if not F:
        R.nota('No hay una clase del 3.º anterior a hoy en el PA vigente: no se puede reprogramar a una fecha pasada.')
        R.save(checks=chk); n.close(); return
    nueva = F + dt.timedelta(days=1)
    while nueva <= A.hoy() and (nueva.isoweekday() > 5 or not A.es_lectivo(x, nueva)):
        nueva += dt.timedelta(days=1)
    chk['reprogramar'] = A.api('POST', f'/colegios/{x}/clases/reprogramaciones', A.sup(), {'id_grado': A.id_grado(3), 'id_seccion': sec, 'fecha_original': A.iso(F),
                                                                                      'fecha_nueva': A.iso(nueva), 'motivo': 'Actividad del colegio (QA)'})
    con_actividad(p, C); abrir_asis(p, nueva)
    chk['nueva'] = textos(p, 'Clase ', 'trasladada')
    R.shot(p, f'Paso 1: {FE.dia_semana(nueva)} {FE.legible(nueva)} (fecha vigente; original {FE.legible(F)}): {chk["nueva"]}')
    chk['marcar'] = [marcar_asis(p, 'Ana Norte QA', 'Presente'), marcar_asis(p, 'Alumno03 Volumen QA', 'Tardanza')]
    chk['api'] = (clases_api(F) + clases_api(nueva), asis_api(nueva))
    R.shot(p, f'Paso 2: registro en la clase reprogramada: {chk["marcar"]}')
    R.consola(ctx, 'Paso 2: lo guardado (API)', [f'Clases del {FE.legible(F)} y del {FE.legible(nueva)} (id | tipo | original | vigente | con asistencias): {chk["api"][0]}',
                                               f'Asistencias: {chk["api"][1]}', f'Reprogramación: HTTP {chk["reprogramar"][0]} {str(chk["reprogramar"][1])[:200]}'])
    abrir_asis(p, F); chk['original'] = (textos(p, 'Clase ', 'trasladada', 'adicional'), p.locator('main tbody tr').count(), controles(p))
    R.shot(p, f'Paso 3: {FE.legible(F)} (fecha original): {chk["original"]}', full=True)
    fin_caso(R, chk, n)


@caso('CP-ASI-11')
def cp_asi11():
    R = Run('CP-ASI-11'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    F = FE.lectivo_sin_clase(3)
    if not F:
        R.nota('No hay un día lectivo sin clase del 3.º en el PA vigente.'); R.save(checks=chk); n.close(); return
    con_actividad(p, C); abrir_asis(p, F); m = p.locator('main')
    chk['ui'] = {'textos': textos(p, 'Clase ', 'No hay una clase', 'adicional'), 'boton': m.get_by_role('button', name=re.compile('clase adicional', re.I)).count(),
                 'controles': controles(p), 'lote': m.get_by_role('button', name='Marcar todos como presentes').count()}
    chk['get'] = (get_asis(C, F)[1] or {}).get('clase')
    R.shot(p, f'Paso 1: {FE.dia_semana(F)} {FE.legible(F)} (día lectivo sin clase del 3.º): {chk["ui"]}', full=True)
    chk['antes'] = clases_api(F)
    R.consola(ctx, 'Pasos 1-2: lo que responde GET /api/asistencias y las clases del día', [f'clase: {chk["get"]}', f'Clases del {FE.legible(F)}: {chk["antes"]}'])
    chk['marcar'] = marcar_asis(p, 'Ana Norte QA', 'Presente'); chk['despues'] = (clases_api(F), asis_api(F)); chk['etiqueta_tras'] = textos(p, 'Clase ')
    R.shot(p, f'Paso 3: marcar a Ana → {chk["marcar"]}; clase {chk["despues"][0]}; etiqueta {chk["etiqueta_tras"]}')
    act = act_de(C); res = []
    F2 = FE.lectivo_sin_clase(3, hasta=F - dt.timedelta(days=1)) or F
    def env(a):
        res.append(put_asis(C, F2, [(D.alumno(a), 'presente', None)], act, adicional=True))
    hs = [threading.Thread(target=env, args=(a,)) for a in ('Beto Norte QA', 'Carla Norte QA')]
    [h.start() for h in hs]; [h.join() for h in hs]
    chk['concurrente'] = (res, clases_api(F2))
    R.consola(ctx, f'Paso 4: dos clases adicionales simultáneas del {FE.legible(F2)}', [f'Respuestas: {res}', f'Clases del {FE.legible(F2)}: {chk["concurrente"][1]}'])
    s, r = A.api('GET', '/inicio/supervisor', A.sup()); chk['resumen'] = json.dumps(r, ensure_ascii=False)[:1200]
    cS = n.ctx(); pS = cS.new_page(); login(pS, sup_ui()); pS.wait_for_timeout(2500)
    R.shot(pS, 'Paso 5: Inicio de la Supervisora (vencidos de Asistencias)', full=True)
    R.consola(ctx, 'Paso 5: GET /api/inicio/supervisor', [chk['resumen']])
    beto = D.alumno('Beto Norte QA'); chk['detalle'] = json.dumps(A.api('GET', f'/alumnos/{beto}/resumen', A.sup())[1], ensure_ascii=False)[:800]
    pS.goto(BASE + f'/estudiantes/{beto}'); pS.wait_for_timeout(3000)
    chk['detalle_ui'] = textos(pS, 'asistencia', '%')
    R.shot(pS, f'Paso 6: detalle de Beto (presente en la clase adicional del {FE.legible(F2)}): {chk["detalle_ui"]}', full=True)
    R.consola(ctx, 'Paso 6: GET /api/alumnos/{id}/resumen', [chk['detalle']])
    fin_caso(R, chk, n)


@caso('CP-ASI-12')
def cp_asi12():
    R = Run('CP-ASI-12'); chk = {}; C = _c(); x = D.X()
    F = FE.ultima_clase(3, incluir_hoy=False)
    if not F or (A.hoy() - F).days < 3:
        R.nota('Se necesita una clase del 3.º de hace al menos 3 días en el PA vigente; no la hay.'); R.save(checks=chk); return
    d_nuevo = F + dt.timedelta(days=3); d_cambio = F + dt.timedelta(days=2)
    chk['prep_nuevo'] = A.crear_alumno('Nuevo', 'Lista QA', x, 3, A.CL(), d_nuevo)
    elsa = D.alumno('Elsa Norte QA')
    chk['prep_cambio'] = A.api('PATCH', f'/alumnos/{elsa}', A.sup(), {'id_grado': A.id_grado(4), 'id_programa': A.CL(), 'cambio_grupo_desde': A.iso(d_cambio)})[0]
    n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    con_actividad(p, C); abrir_asis(p, F)
    chk['lista'] = {f'Nuevo (desde {FE.legible(d_nuevo)})': fila(p, 'Nuevo Lista QA').count(), f'Elsa (pasó a 4.º el {FE.legible(d_cambio)})': fila(p, 'Elsa Norte QA').count(),
                    'total': textos(p, 'alumnos')[:1], 'clases': clases_api(F)}
    R.shot(p, f'Paso 1: clase del {FE.legible(F)} sin lista guardada: {chk["lista"]}', full=True)
    chk['marcar'] = marcar_asis(p, 'Elsa Norte QA', 'Presente')
    s, r = get_asis(A.sup(), F)
    progs = {}
    for a in (r.get('alumnos', []) if s == 200 else []):
        progs[a['id_programa']] = progs.get(a['id_programa'], 0) + 1
    chk['congelada'] = (clases_api(F), {('Alfabetización' if k == A.ALFA() else 'Comprensión Lectora'): v for k, v in progs.items()})
    R.consola(ctx, 'Paso 2: lista histórica guardada al marcar la primera asistencia (API)', [f'Clase: {chk["congelada"][0]}', f'Alumnos de la lista por subprograma: {chk["congelada"][1]}'])
    pa = FE.pa_actual(); d_tardio = max(A.fecha(pa['fecha_inicio']), F - dt.timedelta(days=7))
    s_, r_ = A.api('POST', '/alumnos', A.sup(), {'nombres': 'Tardio', 'apellidos': 'Lista QA', 'id_colegio': x, 'id_grado': A.id_grado(3), 'id_programa': A.CL(), 'pertenece_desde': A.iso(d_tardio)})
    chk['prep_tardio'] = (s_, r_.get('motivo') if isinstance(r_, dict) else r_, (r_ or {}).get('detail') if isinstance(r_, dict) else None)
    R.consola(ctx, f'Paso 3: alta de un alumno con pertenencia desde el {FE.legible(d_tardio)} (anterior a la clase del {FE.legible(F)})', [f'POST /api/alumnos → HTTP {s_} {json.dumps(r_, ensure_ascii=False)[:600]}'])
    p.reload(); p.wait_for_timeout(2500); abrir_asis(p, F)
    s2, r2 = get_asis(A.sup(), F)
    chk['tras_alta'] = {'Tardio en la pantalla': fila(p, 'Tardio Lista QA').count(), 'lista_api': len(r2.get('alumnos', [])) if s2 == 200 else s2, 'total': textos(p, 'alumnos')[:1]}
    R.shot(p, f'Paso 3: alta de un alumno con pertenencia anterior a la clase: {chk["tras_alta"]}', full=True)
    F4 = FE.ultima_clase(4)
    chk['elsa_4'] = de_alumno(F4, 'Elsa Norte QA', grado=4) if F4 else None
    n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); login(p, sup_ui()); ir(p, 'Asistencias'); p.wait_for_timeout(1500)
    if F4:
        abrir_asis(p, F4, grado='4.º', colegio=NX())
        chk['grupo_nuevo'] = {'fila_elsa': fila(p, 'Elsa Norte QA').inner_text().replace('\n', ' ')[:100] if fila(p, 'Elsa Norte QA').count() else None,
                              'marca': (estado_asis(p, 'Elsa Norte QA') or {}).get('marcado')}
        R.shot(p, f'Paso 4: 4.º el {FE.legible(F4)} (Supervisora): {chk["grupo_nuevo"]}; API de Elsa en 4.º {chk["elsa_4"]}', full=True)
    fin_caso(R, chk, n)


@caso('CP-ASI-13')
def cp_asi13():
    R = Run('CP-ASI-13'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); x = D.X()
    pa1 = FE.pa(1); clases1 = FE.clases_del_pa(3, 1)
    if not clases1:
        R.nota('No hay clases del 3.º en el PA1.'); R.save(checks=chk); n.close(); return
    F = clases1[0]; uid = D.id_usuario('docente-a')
    s, pr = A.permiso(uid, x, 3, pa1['id_periodo_academico'], 'asistencias', A.ahora() + dt.timedelta(days=30)); chk['permiso'] = (s, pr.get('id') if isinstance(pr, dict) else pr)
    _, act = nueva_act(C); chk['prep'] = put_asis(C, F, [(D.alumno('Ana Norte QA'), 'presente', None)], act); A.cerrar_abiertas(C)
    con_actividad(p, C); abrir_asis(p, F, sub='Comprensión Lectora')
    chk['aviso'] = aviso_sup(p); chk['controles'] = controles(p)
    R.shot(p, f'Paso 1: {FE.dia_semana(F)} {FE.legible(F)} (PA1) con permiso: {chk["aviso"]}; controles {chk["controles"]}')
    chk['cambio'] = marcar_asis(p, 'Ana Norte QA', 'Ausente')
    s_, r_ = get_asis(A.sup(), F)
    chk['api'] = (de_alumno(F, 'Ana Norte QA'), (r_ or {}).get('escritura') if isinstance(r_, dict) else None)
    hist = A.api('GET', f'/alumnos/{D.alumno("Ana Norte QA")}/historial', A.sup())[1]
    chk['historial'] = json.dumps((hist or {}).get('items', [])[:2], ensure_ascii=False)[:700] if isinstance(hist, dict) else hist
    R.shot(p, f'Paso 2: Ana de Presente a Ausente → {chk["cambio"]}')
    R.consola(ctx, 'Paso 2: lo guardado (API)', [f'Ana (estado | observación | versión): {chk["api"][0]}', f'Historial del alumno (lo más reciente): {chk["historial"]}'])
    R.nota('Paso 2: la auditoría con id_permiso solo se ve en la base de datos; en QA se muestra el historial del alumno.')
    nolect, motivo = FE.no_lectivo_pasado(en_pa=1)
    if nolect:
        p.locator('main input[type=date]').first.fill(A.iso(nolect)); p.wait_for_timeout(2500)
        chk['no_lectivo'] = (textos(p, 'fecha', 'lectivo', motivo.split(':')[-1].strip()[:10]), controles(p))
        R.shot(p, f'Paso 3: {FE.legible(nolect)} ({motivo}, PA1): {chk["no_lectivo"]}')
        chk['api_no_lectivo'] = put_asis(C, nolect, [(D.alumno('Beto Norte QA'), 'presente', None)], act_de(C))
        R.consola(ctx, f'Paso 3: PUT del {FE.legible(nolect)} por la API con el permiso', [str(chk['api_no_lectivo'])])
    otro = FE.lectivo_sin_clase_en(3, 1)
    if otro:
        p.locator('main input[type=date]').first.fill(A.iso(otro)); p.wait_for_timeout(2500)
        chk['otro_dia'] = (textos(p, 'Clase ', 'No hay una clase', 'Corrección'), controles(p))
        R.shot(p, f'Paso 3: {FE.dia_semana(otro)} {FE.legible(otro)} (día lectivo del PA1 sin clase del 3.º) con el permiso: {chk["otro_dia"]}')
    fin_caso(R, chk, n)
