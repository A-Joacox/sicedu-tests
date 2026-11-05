"""Sesiones (CU017 a CU019): CP-SES-01 a CP-SES-07, adaptados a QA.

- El Docente es Docente A. Antes de los casos que lo necesitan se le crean actividades por la API:
  ciclos iniciar → finalizar hasta pasar de 40, una forzada por cierre de sesión (POST /logout con la
  actividad abierta) y una con pendientes informados al servidor.
- La actividad "Automática por expiración de sesión" no se puede provocar en QA (en local se vencía
  la sesión en la base de datos): si Docente A no tiene una de corridas anteriores, queda como NOTA.
- Lo que en local se comparaba con la base de datos se compara con GET /api/actividades (con filtros).
- El backend detenido se simula cortando /api en el navegador.
"""
import datetime as dt
import json
import re

from lib import api as A
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import caso
from lib.ui import (Nav, Run, backend_caido, cerrar_dialogos, cola_idb, con_actividad, filtros_ui, idb_todo, ir, login,
                    logout, opciones, poner, textos, toasts_txt, token_navegador)

from casos._comun import fin, sup_ui, visitar
from casos.asi import abrir_asis, marcar_asis, put_asis
from casos.lec import Semanas, filas_put, prep_tabla, tabla_get, tabla_post, version_fila
from casos.rub import abrir_rubrica, elegir, mes_actual, rub_items, rub_put
from casos.rv import PA_ACT, rv_items, rv_put

MANUAL, FORZADO, EXPIRA = 'Manual por finalización de actividad', 'Forzado por cierre de sesión', 'Automático por expiración de sesión'


def _c():
    return D.cuenta('docente-a')


def ciclo(cuenta, pasos=None):
    act = A.iniciar_actividad(cuenta)
    if pasos:
        pasos(act)
    return act


def acts(cuenta, **filtros):
    """Todas las actividades de la cuenta por la API (lo que en local se leía en la tabla actividad)."""
    return A.todas_las_paginas('/actividades?' + A.q(**filtros) if filtros else '/actividades', cuenta)


def preparar_ses(R, ctx, minimo=41, cinco_modulos=False, avisar_expira=False):
    """Docente A con más de 40 actividades y los tipos de cierre del caso. Devuelve un resumen."""
    C = _c(); A.cerrar_abiertas(C); out = {}
    tot = (A.ok(A.api('GET', '/actividades', C), 'actividades') or {}).get('total', 0)
    for _ in range(max(0, minimo - tot)):
        A.finalizar_actividad(C, ciclo(C))
    out['creadas_manual'] = max(0, minimo - tot)
    # forzada por cierre de sesión
    act = ciclo(C); out['forzada'] = (A.api('POST', '/logout', C.tk())[0], act); C.olvidar()
    # con pendientes informados al servidor
    X = D.X(); F = FE.ultima_clase(3, X, incluir_hoy=True)
    act = ciclo(C)
    out['pendientes'] = A.api('POST', '/sincronizacion/pendientes', C, [{
        'id_operacion': A.uid(), 'id_dispositivo': 'tablet-qa', 'id_actividad': act, 'modulo': 'asistencias',
        'realizado_en': A.ahora().replace(microsecond=0).isoformat(),
        'registro': {'id_colegio': X, 'id_grado': A.id_grado(3), 'id_seccion': A.seccion(X, 3), 'fecha': A.iso(F), 'id_alumno': D.alumno('Carla Norte QA')}}])[0]
    A.finalizar_actividad(C, act); out['act_pendiente'] = act
    if cinco_modulos:
        S = Semanas(); a, b = D.alumno('Ana Norte QA'), D.alumno('Beto Norte QA')
        act = ciclo(C)
        out['asis'] = put_asis(C, S.F, [(a, 'presente', None), (b, 'tardanza', None)], act)
        s, t = tabla_post(C, act, S.ACT, S.mes_act); out['tabla'] = s
        out['lectura'] = filas_put(C, t['id'], act, [(a, version_fila(C, a, S.ACT, S.mes_act), {'cantidad_lsl': 2})]) if s == 201 else t
        out['rubrica'] = rub_put(C, rub_items([(a, 3, 3)], act))
        out['rv'] = rv_put(C, rv_items([(a, PA_ACT(X), {'id_nivel_colocado': A.niveles_rk()['K']})], act))
        out['alumno'] = A.api('PATCH', f'/alumnos/{D.alumno("Elsa Norte QA")}', C, {'nombres': 'Elsa Sofía'})[0]
        A.finalizar_actividad(C, act); out['act_cinco'] = act
    # otro Docente con actividades
    B = D.cuenta('docente-b'); A.cerrar_abiertas(B)
    for _ in range(2):
        A.finalizar_actividad(B, ciclo(B))
    todas = acts(C); cierres = {}
    for x in todas:
        cierres[x.get('tipo_cierre') or 'en curso'] = cierres.get(x.get('tipo_cierre') or 'en curso', 0) + 1
    out['total'] = len(todas); out['cierres'] = cierres
    lineas = [f'Actividades de Docente A: {len(todas)} (se crearon {out["creadas_manual"]} con iniciar → finalizar)',
              f'Forzada por cierre de sesión: POST /api/logout con la actividad abierta → HTTP {out["forzada"][0]}',
              f'Con pendientes informados: POST /api/sincronizacion/pendientes → HTTP {out["pendientes"]}',
              f'Por tipo de cierre: {cierres}']
    if cinco_modulos:
        lineas.append(f'Actividad con cambios en los cinco módulos: asistencias {out["asis"]}, tabla de lectura {out["tabla"]}, fila {out["lectura"]}, '
                      f'rúbrica {out["rubrica"]}, Registro de Vuelo {out["rv"]}, alumno {out["alumno"]}')
    if not cierres.get(EXPIRA) and avisar_expira:
        lineas.append('No hay actividades "Automático por expiración de sesión": en QA no se puede vencer una sesión (en local se hacía en la base de datos).')
        R.nota('Precondición: la actividad cerrada por expiración de sesión no se puede crear en QA (requiere vencer la sesión en la base de datos). '
               'Si Docente A tiene una de corridas anteriores, aparece en la tabla.')
    R.consola(ctx, 'Precondición (por la API)', lineas)
    return out


def filas_tabla(p):
    return [r.replace('\n', ' | ').replace('\t', ' | ')[:180] for r in p.locator('main tbody tr').all_inner_texts()]


def pie_txt(p):
    m = re.search(r'Mostrando[^\n]*', p.locator('main').inner_text())
    return m.group(0) if m else None


def filtrar(p):
    p.locator('main').get_by_role('button', name=re.compile('^(Filtrar|Buscar)')).first.click()
    p.wait_for_timeout(2000)


def poner_fecha(p, etiqueta, valor):
    p.get_by_label(etiqueta, exact=True).fill(valor)
    p.wait_for_timeout(300)


def detalle_txt(p):
    d = p.locator('[role=dialog]:visible').last
    return d.inner_text()[:900] if d.count() else None


def abrir_detalle(p, i=0):
    p.locator('main tbody tr').nth(i).get_by_role('button').last.click()
    p.wait_for_timeout(2000)


def _ls(p):
    try:
        return p.evaluate('JSON.stringify(localStorage)')
    except Exception:
        return ''


@caso('CP-SES-01', modo='parcial', notas='La actividad cerrada por expiración de sesión no se puede provocar en QA.')
def cp_ses01():
    R = Run('CP-SES-01'); chk = {}; n = Nav(); ctx = n.ctx(); p = ctx.new_page(); C = _c()
    chk['prep'] = preparar_ses(R, ctx, avisar_expira=True)
    con_actividad(p, C); ir(p, 'Sesiones'); p.wait_for_timeout(2500); m = p.locator('main')
    chk['columnas'] = [x.strip() for x in m.locator('thead th').all_inner_texts()]
    chk['filas'] = m.locator('tbody tr').count(); chk['pie'] = pie_txt(p); chk['primera'] = filas_tabla(p)[:2]
    R.shot(p, f'Pasos 1-2: columnas {chk["columnas"]}; primera fila {chk["primera"][:1]}')
    chk['paginacion'] = (chk['filas'], chk['pie'], m.get_by_role('button', name=re.compile('Siguiente|Anterior|^\\d+$')).all_inner_texts())
    R.shot(p, f'Paso 3: filas en la página {chk["filas"]}; pie "{chk["pie"]}"; botones {chk["paginacion"][2]}', full=True)
    filas_todas = filas_tabla(p)
    b = m.get_by_role('button', name='Siguiente')
    if b.count() and b.first.is_enabled():
        b.first.click(); p.wait_for_timeout(1500); chk['pagina2'] = (m.locator('tbody tr').count(), pie_txt(p)); filas_todas += filas_tabla(p)
        R.shot(p, f'Paso 3: página 2: {chk["pagina2"]}', full=True)
    tk = token_navegador(p)
    s, r = A.api('GET', '/actividades', tk); s2, r2 = A.api('GET', '/actividades?page=2', tk)
    chk['api'] = {'total': r.get('total'), 'paginas': r.get('total_pages'), 'p1': len(r.get('items', [])), 'p2': len(r2.get('items', []))}
    B = D.cuenta('docente-b'); ids_b = {x['id'] for x in acts(B)}
    ids_api = {x['id'] for x in acts(tk)}
    chk['ajenas'] = len(ids_api & ids_b)
    R.consola(ctx, 'Paso 4: API (en local se comparaba con la base de datos)',
              [f'GET /api/actividades con el token de Docente A → total {chk["api"]["total"]}, páginas {chk["api"]["paginas"]}, página 1: {chk["api"]["p1"]}, página 2: {chk["api"]["p2"]}',
               f'Actividades de Docente B (con su propio token): {len(ids_b)}; de ellas en la lista de Docente A: {chk["ajenas"]}',
               f'Páginas que muestra la interfaz: 1{" y 2 " + str(chk.get("pagina2")) if chk.get("pagina2") else " (sin página 2)"}'])
    cierres = {}
    for f in filas_todas:
        for t in ['Manual', FORZADO, 'Automático por expiración', 'En curso', 'Pendiente', 'Sincronizada', 'Error']:
            if t in f:
                cierres[t] = cierres.get(t, 0) + 1
    ba = m.get_by_role('button', name='Anterior')
    if ba.count() and ba.first.is_enabled():
        ba.first.click(); p.wait_for_timeout(1000)
    chk['textos_cierre'] = cierres
    chk['pendiente_finalizada'] = [f for f in filas_todas if 'Pendiente' in f and 'Finalizada' in f][:2]
    R.shot(p, f'Pasos 5-6: textos en la tabla: {cierres}; actividad en curso: {chk["primera"][:1]}; Finalizada y Pendiente: {chk["pendiente_finalizada"][:1]}', full=True)
    n.close()
    # Paso 7: un Docente de la suite sin actividades
    sin = None
    for et in ['sin-grupos', 'retro', 'rv-uno', 'docente-b']:
        idd = D.id_docente(et)
        if idd and (A.api('GET', f'/seguimiento/docentes/{idd}/actividades', A.sup())[1] or {}).get('total', 1) == 0:
            sin = et; break
    if sin:
        n = Nav(); ctx = n.ctx(); p = ctx.new_page()
        login(p, D.cuenta(sin)); ir(p, 'Sesiones'); p.wait_for_timeout(2500)
        chk['sin_actividades'] = (sin, textos(p, 'No existen', 'Todavía', 'Cuando inicie', 'No hay'))
        R.shot(p, f'Paso 7: Docente sin actividades ({sin}): {chk["sin_actividades"][1]}')
        n.close()
    else:
        R.nota('Paso 7: todas las cuentas Docente de la suite ya tienen actividades en QA; no hay un Docente sin actividades para este paso.')
    A.cerrar_abiertas(C); R.save(checks=chk)


@caso('CP-SES-02')
def cp_ses02():
    R = Run('CP-SES-02'); chk = {}; n = Nav(); ctx = n.ctx(); p = ctx.new_page(); C = _c()
    chk['prep'] = preparar_ses(R, ctx)
    con_actividad(p, C); ir(p, 'Sesiones'); p.wait_for_timeout(2500); m = p.locator('main'); tk = token_navegador(p)
    chk['criterios'] = {k: opciones(p, k) for k in ['Estado', 'Sincronización', 'Tipo de cierre']}
    H = A.hoy(); ayer = H - dt.timedelta(days=1)
    b = m.get_by_role('button', name='Siguiente')
    if b.count() and b.first.is_enabled():
        b.first.click(); p.wait_for_timeout(1200)
    poner_fecha(p, 'Desde', A.iso(ayer)); poner_fecha(p, 'Hasta', A.iso(H)); filtrar(p)
    chk['rango'] = (m.locator('tbody tr').count(), pie_txt(p), (A.api('GET', '/actividades?' + A.q(desde=A.iso(ayer), hasta=A.iso(H)), tk)[1] or {}).get('total'))
    R.shot(p, f'Pasos 1-2: rango {FE.legible(ayer)} a {FE.legible(H)} (buscado desde la página 2) → filas {chk["rango"][0]} | pie {chk["rango"][1]} | API {chk["rango"][2]}; criterios {chk["criterios"]}', full=True)
    poner_fecha(p, 'Desde', ''); poner_fecha(p, 'Hasta', '')
    poner(p, 'Estado', 'Finalizada'); poner(p, 'Sincronización', 'Pendiente'); poner(p, 'Tipo de cierre', 'Manual'); filtrar(p)
    chk['combinado'] = (filas_tabla(p)[:3], m.locator('tbody tr').count(),
                        (A.api('GET', '/actividades?' + A.q(estado='finalizada', sincronizacion='pendiente', tipo_cierre=MANUAL), tk)[1] or {}).get('total'))
    R.shot(p, f'Paso 3: Finalizada + Pendiente + Manual → {chk["combinado"][1]} filas (API: {chk["combinado"][2]}): {chk["combinado"][0][:2]}')
    ls = _ls(p); url = p.url.split('/', 3)[-1]
    ir(p, 'Inicio'); p.wait_for_timeout(1000); ir(p, 'Sesiones'); p.wait_for_timeout(2000)
    chk['persistencia'] = {'localStorage': ls[:400], 'url': url, 'al_volver': (filtros_ui(p), p.url.split('/', 3)[-1])}
    R.shot(p, f'Paso 4: filtros al volver de otro módulo: {chk["persistencia"]["al_volver"]}')
    R.consola(ctx, 'Paso 4: Local Storage y URL', [f'Local Storage: {ls[:700]}', f'URL con los filtros: /{url}'])
    poner(p, 'Sincronización', 'Error'); poner(p, 'Tipo de cierre', 'Forzado'); filtrar(p)
    chk['sin_coincidencias'] = (textos(p, 'No existen', 'No se encontraron', 'Cuando'), pie_txt(p), filtros_ui(p), m.locator('tbody tr').count())
    R.shot(p, f'Paso 5: sin coincidencias (Finalizada + Error + Forzado): {chk["sin_coincidencias"]}')
    poner_fecha(p, 'Desde', A.iso(H)); poner_fecha(p, 'Hasta', A.iso(H - dt.timedelta(days=5)))
    bf = m.get_by_role('button', name=re.compile('^(Filtrar|Buscar)')).first
    chk['rango_invalido'] = (textos(p, 'rango', 'posterior', 'anterior'), bf.is_enabled())
    R.shot(p, f'Paso 6: Desde posterior a Hasta: {chk["rango_invalido"]}')
    poner_fecha(p, 'Desde', ''); poner_fecha(p, 'Hasta', '')
    poner(p, 'Sincronización', 'Todos'); poner(p, 'Tipo de cierre', 'Todos'); poner(p, 'Estado', 'En curso')
    backend_caido(ctx, True); filtrar(p); p.wait_for_timeout(4000)
    chk['backend_caido'] = (textos(p, 'No se pudo', 'No fue posible', 'servidor', 'Reintentar', 'conectar'), m.get_by_role('button', name='Reintentar').count(), m.locator('tbody tr').count())
    R.shot(p, f'Paso 7: backend sin responder y Buscar: {chk["backend_caido"]}')
    backend_caido(ctx, False); p.wait_for_timeout(1000)
    if m.get_by_role('button', name='Reintentar').count():
        m.get_by_role('button', name='Reintentar').first.click()
    else:
        filtrar(p)
    p.wait_for_timeout(2000); chk['recuperado'] = (m.locator('tbody tr').count(), textos(p, 'No se pudo', 'No fue posible')[:1])
    R.shot(p, f'Paso 7: backend de vuelta y Reintentar: {chk["recuperado"]}')
    m.get_by_role('button', name=re.compile('^Limpiar')).first.click(); p.wait_for_timeout(2000)
    chk['limpiar'] = (filtros_ui(p), p.get_by_label('Desde', exact=True).input_value(), m.locator('tbody tr').count(), pie_txt(p), _ls(p)[:300], p.url.split('/', 3)[-1])
    R.shot(p, f'Paso 8: Limpiar: {chk["limpiar"]}', full=True)
    poner(p, 'Estado', 'Finalizada'); filtrar(p); logout(p); p.wait_for_timeout(1500)
    chk['tras_logout'] = _ls(p)[:400]
    R.consola(ctx, 'Paso 9: Local Storage tras cerrar sesión', [chk['tras_logout']])
    fin(R, chk, n, C)


@caso('CP-SES-03')
def cp_ses03():
    R = Run('CP-SES-03'); chk = {}; n = Nav(); ctx = n.ctx(); p = ctx.new_page(); C = _c()
    pre = preparar_ses(R, ctx, cinco_modulos=True); chk['prep'] = {k: v for k, v in pre.items() if k != 'cierres'}
    obj = pre.get('act_cinco')
    con_actividad(p, C); ir(p, 'Sesiones'); p.wait_for_timeout(2500); m = p.locator('main'); tk = token_navegador(p)
    poner(p, 'Estado', 'Finalizada'); filtrar(p)
    # La actividad objetivo es la finalizada más reciente: se busca por su hora de inicio.
    det = A.api('GET', f'/actividades/{obj}', tk)[1] if obj else None
    b = m.get_by_role('button', name='Siguiente'); chk['pagina2'] = bool(b.count() and b.first.is_enabled())
    if chk['pagina2']:
        b.first.click(); p.wait_for_timeout(1500)
    pie_antes = pie_txt(p)
    R.shot(p, f'Paso 1: Sesiones filtrado por Finalizada, página 2 disponible = {chk["pagina2"]} ({pie_antes})', full=True)
    ini = det['inicio'] if det else ''
    hh = dt.datetime.fromisoformat(ini).astimezone(A.LIMA).strftime('%H:%M') if ini else ''
    fila_obj = next((i for i, t in enumerate(m.locator('tbody tr').all_inner_texts()) if hh and hh in t), None)
    chk['en_pagina2'] = fila_obj is not None
    if fila_obj is None:
        R.nota('Paso 1: la actividad con cambios en los cinco módulos es la más reciente, así que está en la página 1. '
               'Se abre desde la página 2 una actividad cualquiera para el paso 5 y la de los cinco módulos desde la página 1.')
        abrir_detalle(p, 0); chk['detalle_pagina2'] = detalle_txt(p)
        R.shot(p, 'Paso 1: detalle de una actividad de la página 2', full=True)
        cerrar_dialogos(p); p.wait_for_timeout(800)
        chk['al_cerrar'] = (pie_txt(p), filtros_ui(p))
        R.shot(p, f'Paso 5: al cerrar el detalle: {chk["al_cerrar"]} (antes: {pie_antes})')
        ba = m.get_by_role('button', name='Anterior')
        if ba.count() and ba.first.is_enabled():
            ba.first.click(); p.wait_for_timeout(1500)
        fila_obj = next((i for i, t in enumerate(m.locator('tbody tr').all_inner_texts()) if hh and hh in t), 0)
    abrir_detalle(p, fila_obj); chk['detalle'] = detalle_txt(p)
    R.shot(p, 'Pasos 2-4: detalle de la actividad con cambios en los cinco módulos', full=True)
    chk['api'] = {k: det.get(k) for k in ['cambios', 'cambios_por_modulo', 'asignaciones', 'sincronizado_en', 'registros_pendientes']} if det else None
    if chk['api']:
        chk['suma'] = (sum(x.get('total', 0) for x in det.get('cambios_por_modulo', [])), det.get('cambios'))
    R.consola(ctx, 'Pasos 2-4: GET /api/actividades/{id} de esa actividad', [json.dumps(chk['api'], ensure_ascii=False)[:1500], f'Suma del desglose / total: {chk.get("suma")}'])
    cerrar_dialogos(p); p.wait_for_timeout(800)
    if 'al_cerrar' not in chk:
        chk['al_cerrar'] = (pie_txt(p), filtros_ui(p))
        R.shot(p, f'Paso 5: al cerrar el detalle: {chk["al_cerrar"]} (antes: {pie_antes})')
    m.get_by_role('button', name=re.compile('^Limpiar')).first.click(); p.wait_for_timeout(1800)
    abrir_detalle(p, 0); chk['en_curso'] = detalle_txt(p)
    R.shot(p, 'Paso 6: detalle de la actividad en curso', full=True); cerrar_dialogos(p)
    poner(p, 'Sincronización', 'Pendiente'); filtrar(p)
    if m.locator('tbody tr').count():
        abrir_detalle(p, 0)
    chk['pendiente'] = detalle_txt(p)
    chk['pendiente_api'] = {k: (A.api('GET', f'/actividades/{pre["act_pendiente"]}', tk)[1] or {}).get(k) for k in ['sincronizacion', 'registros_pendientes', 'cambios']}
    R.shot(p, f'Paso 7: detalle de una actividad Finalizada y Pendiente; API de la actividad con pendientes: {chk["pendiente_api"]}', full=True)
    fin(R, chk, n, C)


@caso('CP-SES-04')
def cp_ses04():
    R = Run('CP-SES-04'); chk = {}; n = Nav(); ctx = n.ctx(); p = ctx.new_page(); C = _c()
    chk['prep'] = preparar_ses(R, ctx, minimo=5)
    con_actividad(p, C); ir(p, 'Sesiones'); p.wait_for_timeout(2500); m = p.locator('main')
    ctx.set_offline(True); p.wait_for_timeout(1500)
    chk['offline'] = {'texto': m.inner_text()[:300], 'tabla': m.locator('table').count(), 'filtros': m.locator('select, input').count(),
                      'reintentar': m.get_by_role('button', name='Reintentar').count()}
    R.shot(p, f'Paso 1: sin conexión: {chk["offline"]}')
    if chk['offline']['reintentar']:
        m.get_by_role('button', name='Reintentar').click(); p.wait_for_timeout(1000)
    chk['reintentar_offline'] = m.inner_text()[:200]
    R.shot(p, 'Paso 2: Reintentar sin conexión')
    ctx.set_offline(False); p.wait_for_timeout(1500)
    p.reload(); p.wait_for_timeout(2500)
    abrir_detalle(p, 2)
    ctx.set_offline(True); p.wait_for_timeout(1500); chk['detalle_offline'] = (detalle_txt(p), m.inner_text()[:200])
    R.shot(p, 'Paso 3: detalle abierto y luego sin conexión', full=True)
    raw = idb_todo(p); ls = _ls(p)
    chk['local'] = {'idb_claves': list(json.loads(raw)), 'menciones_tipo_cierre': raw.count('tipo_cierre'), 'ls': ls[:300]}
    R.consola(ctx, 'Paso 4: IndexedDB y Local Storage', [f'IndexedDB (almacenes): {chk["local"]["idb_claves"]}',
                                                         f'Apariciones de "tipo_cierre" en IndexedDB: {chk["local"]["menciones_tipo_cierre"]}', f'Local Storage: {ls[:600]}'])
    cerrar_dialogos(p); ctx.set_offline(False); p.wait_for_timeout(1500)
    backend_caido(ctx, True); p.reload(); p.wait_for_timeout(4000)
    chk['caido_lista'] = (p.locator('body').inner_text()[:300], m.get_by_role('button', name='Reintentar').count() if m.count() else 0)
    R.shot(p, f'Paso 5: backend sin responder y recarga de Sesiones: {chk["caido_lista"]}', full=True)
    backend_caido(ctx, False); p.reload(); p.wait_for_timeout(3000)
    backend_caido(ctx, True)
    try:
        abrir_detalle(p, 2); p.wait_for_timeout(1500); chk['caido_detalle'] = detalle_txt(p)
    except Exception as e:
        chk['caido_detalle'] = str(e)[:80]
    R.shot(p, f'Paso 6: backend sin responder y abrir un detalle: {str(chk["caido_detalle"])[:200]}', full=True)
    backend_caido(ctx, False); p.wait_for_timeout(1000)
    d = p.locator('[role=dialog]:visible')
    if d.count() and d.last.get_by_role('button', name='Reintentar').count():
        d.last.get_by_role('button', name='Reintentar').click(); p.wait_for_timeout(2000)
    chk['recuperado'] = detalle_txt(p)
    R.shot(p, f'Paso 7: backend de vuelta: {str(chk["recuperado"])[:200]}', full=True)
    fin(R, chk, n, C)


@caso('CP-SES-05')
def cp_ses05():
    R = Run('CP-SES-05'); chk = {}; n = Nav(); ctx = n.ctx(); p = ctx.new_page(); C = _c()
    B = D.cuenta('docente-b'); A.cerrar_abiertas(B); A.finalizar_actividad(B, ciclo(B))
    otra = acts(B)[0]['id']; B.olvidar()
    con_actividad(p, C); ir(p, 'Sesiones'); p.wait_for_timeout(2500)
    url0 = p.url; abrir_detalle(p, 1)
    chk['url_detalle'] = (url0.split('/', 3)[-1], p.url.split('/', 3)[-1], bool(detalle_txt(p)))
    R.shot(p, f'Paso 1: detalle de una actividad propia; URL antes /{chk["url_detalle"][0]} y con el detalle abierto /{chk["url_detalle"][1]}')
    tk = token_navegador(p)
    p.goto(p.url.split('/sesiones')[0] + f'/sesiones/{otra}'); p.wait_for_timeout(2500)
    chk['url_ajena'] = (p.url.split('/', 3)[-1], textos(p, 'no está disponible', 'No se', 'Sesiones')[:3])
    R.shot(p, f'Pasos 2-3: URL con el id de una actividad de Docente B: /{chk["url_ajena"][0]} {chk["url_ajena"][1]}')
    import uuid
    p.goto(p.url.split('/', 3)[0] + '//' + p.url.split('/', 3)[2] + f'/sesiones/{uuid.uuid4()}'); p.wait_for_timeout(2000)
    chk['url_inexistente'] = (p.url.split('/', 3)[-1], textos(p, 'no está disponible', 'No se')[:2])
    R.shot(p, f'Paso 4: URL con un id inexistente: /{chk["url_inexistente"][0]} {chk["url_inexistente"][1]}')
    idb = D.id_docente('docente-b')
    chk['api'] = {'ajena': A.api('GET', f'/actividades/{otra}', tk), 'inexistente': A.api('GET', f'/actividades/{uuid.uuid4()}', tk),
                  'lista_otro': A.api('GET', f'/seguimiento/docentes/{idb}/actividades', tk)[0],
                  'lista_filtrada': (A.api('GET', f'/actividades?id_docente={idb}', tk)[1] or {}).get('total')}
    propias = (A.api('GET', '/actividades', tk)[1] or {}).get('total')
    R.consola(ctx, 'Pasos 4-5: API con el token de Docente A',
              [f'GET /api/actividades/{{id de Docente B}} → {chk["api"]["ajena"]}', f'GET /api/actividades/{{id inexistente}} → {chk["api"]["inexistente"]}',
               f'GET /api/seguimiento/docentes/{idb}/actividades (Docente B) → HTTP {chk["api"]["lista_otro"]}',
               f'GET /api/actividades?id_docente={idb} → total {chk["api"]["lista_filtrada"]} (las propias: {propias})'])
    fin(R, chk, n, C)


@caso('CP-SES-06')
def cp_ses06():
    R = Run('CP-SES-06'); chk = {}; n = Nav(); ctx = n.ctx(); p = ctx.new_page(); C = _c()
    S = Semanas(); chk['tabla_previa'] = prep_tabla(S)   # la tabla de la semana se crea en otra actividad
    a, b, c3 = D.alumno('Ana Norte QA'), D.alumno('Beto Norte QA'), D.alumno('Carla Norte QA')
    con_actividad(p, C); tk = token_navegador(p); act = A.actividad_en_curso(tk)
    abrir_asis(p, S.F, sub='Comprensión Lectora')
    chk['asis'] = [marcar_asis(p, 'Ana Norte QA', e) for e in ['Presente', 'Tardanza', 'Ausente']]
    chk['asis'] += [marcar_asis(p, 'Beto Norte QA', 'Presente'), marcar_asis(p, 'Carla Norte QA', 'Presente')]
    idt = (tabla_get(tk, S.ACT, S.mes_act)[1] or {}).get('id')
    chk['lectura'] = filas_put(tk, idt, act, [(b, version_fila(tk, b, S.ACT, S.mes_act), {'cantidad_lsl': 1})])
    abrir_rubrica(p)
    chk['rub'] = [elegir(p, 'Beto Norte QA', 'Fluidez', 'En proceso')[:2], elegir(p, 'Beto Norte QA', 'Fluidez', 'Logrado')[:2],
                  elegir(p, 'Beto Norte QA', 'Comprensión', 'Logrado')[:2]]
    chk['rv'] = rv_put(tk, rv_items([(c3, PA_ACT(), {'id_nivel_colocado': A.niveles_rk()['K']})], act))
    d_, x1 = D.alumno('Dante Norte QA'), D.alumno('Extra01 Rubrica QA')
    chk['alumnos'] = [A.api('PATCH', f'/alumnos/{d_}', tk, {'nombres': 'Dante José'})[0], A.api('PATCH', f'/alumnos/{d_}', tk, {'nombres': 'Dante'})[0],
                      A.api('PATCH', f'/alumnos/{x1}', tk, {'apellidos': 'Rubrica QA Dos'})[0]]
    R.shot(p, f'Pasos 1-3: rúbrica 3 veces {chk["rub"]}; lectura {chk["lectura"]}; vuelo {chk["rv"]}; alumnos {chk["alumnos"]}; asistencias {chk["asis"]}')
    p.get_by_role('button', name='Finalizar actividad').first.click(); p.wait_for_timeout(800)
    d = p.locator('[role=dialog]:visible')
    if d.count():
        d.last.get_by_role('button', name=re.compile('Finalizar')).last.click(); p.wait_for_timeout(2000)
    logout(p); p.wait_for_timeout(1000); login(p, C); ir(p, 'Sesiones'); p.wait_for_timeout(2500)
    chk['fila'] = filas_tabla(p)[:1]
    R.shot(p, f'Pasos 4-5: Sesiones tras volver a entrar: {chk["fila"]}')
    abrir_detalle(p, 0); chk['detalle'] = detalle_txt(p)
    tk2 = token_navegador(p); det = A.api('GET', f'/actividades/{act}', tk2)[1] or {}
    chk['api'] = {k: det.get(k) for k in ['cambios', 'cambios_por_modulo']}
    R.shot(p, 'Paso 6: detalle de esa actividad', full=True)
    R.consola(ctx, 'Paso 6: GET /api/actividades/{id}', [json.dumps(chk['api'], ensure_ascii=False)[:1200]])
    n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); login(p, sup_ui()); ir(p, 'Seguimiento'); p.wait_for_timeout(2000)
    try:
        from lib.ui import poner as _poner
        _poner(p, 'Colegio', D.nombre_colegio('norte'))
        b_ = p.locator('main').get_by_role('button', name=re.compile('^(Filtrar|Buscar)'))
        if b_.count():
            b_.first.click(); p.wait_for_timeout(1500)
    except Exception:
        pass
    f = p.locator('main tbody tr').filter(has_text='Docente A').first
    f.get_by_role('button', name=re.compile('Ver detalle|historial', re.I)).first.click(); p.wait_for_timeout(2500)
    chk['productividad'] = [r for r in filas_tabla(p) if 'Asistencia' in r][:2]
    idd = D.id_docente('docente-a')
    hist = A.api('GET', f'/seguimiento/docentes/{idd}/actividades', A.sup())[1] or {}
    chk['productividad_api'] = next((x.get('productividad_texto') for x in hist.get('items', []) if x['id'] == act), None)
    R.shot(p, f'Paso 7: Productividad en Seguimiento: {chk["productividad"]}; API: "{chk["productividad_api"]}"', full=True)
    fin(R, chk, n, C)


@caso('CP-SES-07')
def cp_ses07():
    R = Run('CP-SES-07'); chk = {}; n = Nav(); ctx = n.ctx(); p = ctx.new_page(); C = _c(); red = []
    p.on('request', lambda r: red.append((A.ahora().strftime('%H:%M:%S'), r.method)) if '/api/rubricas' in r.url and r.method == 'PUT' else None)
    con_actividad(p, C); abrir_rubrica(p)
    ctx.set_offline(True); p.wait_for_timeout(600)
    for nom in ['Carla Norte QA', 'Dante Norte QA']:
        try:
            elegir(p, nom, 'Fluidez', 'Logrado'); elegir(p, nom, 'Comprensión', 'Logrado')
        except Exception as e:
            chk.setdefault('elegir', []).append(str(e)[:60])
    chk['cola'] = cola_idb(p)[:2]; chk['cabecera'] = p.locator('header').first.inner_text().replace('\n', ' ')[:100]
    R.shot(p, f'Paso 1: dos evaluaciones sin conexión; cabecera "{chk["cabecera"]}"; avisos {toasts_txt(p)}', full=True)
    R.consola(ctx, 'Paso 2: IndexedDB (cola)', [str(c)[:430] for c in chk['cola']] or ['(vacía)'])
    hecho = []

    def alterar(route):
        try:
            b_ = json.loads(route.request.post_data)
            if isinstance(b_, list) and b_ and not hecho:
                b_[0]['id_alumno'] = 99999999; hecho.append(b_[0].get('id_operacion'))
            route.continue_(post_data=json.dumps(b_))
        except Exception:
            route.continue_()
    p.route('**/api/rubricas', lambda r: alterar(r) if r.request.method == 'PUT' else r.continue_())
    ctx.set_offline(False); p.wait_for_timeout(15000); p.unroute('**/api/rubricas')
    R.nota('Paso 3: el alumno de una evaluación se cambia por uno inexistente al enviarla (en la petición, no en IndexedDB), igual que en la ronda 6.')
    from casos.rub import rub_de
    chk['guardadas'] = {nom: rub_de(nom) for nom in ['Carla Norte QA', 'Dante Norte QA']}
    chk['op_rechazada'] = A.api('GET', f'/sincronizacion/operaciones/{hecho[0]}', token_navegador(p)) if hecho else None
    ir(p, 'Sesiones'); p.wait_for_timeout(2500); chk['fila'] = filas_tabla(p)[:1]
    R.shot(p, f'Pasos 3-4: Sesiones tras reconectar: {chk["fila"]}', full=True)
    abrir_detalle(p, 0); chk['detalle'] = detalle_txt(p)
    R.shot(p, 'Paso 5: detalle de la actividad', full=True); cerrar_dialogos(p)
    n0 = len(red); p.wait_for_timeout(60000); chk['reintentos_60s'] = len(red) - n0
    R.consola(ctx, 'Pasos 6-7: reintentos y lo guardado (por la API)',
              [f'PUT /api/rubricas en los 60 s siguientes al rechazo: {chk["reintentos_60s"]} (se esperó 1 minuto, no 5)', f'Peticiones PUT: {red}',
               f'Operación alterada: {str(chk["op_rechazada"])[:300]}', f'Rúbricas de Carla y Dante: {chk["guardadas"]}'])
    fin(R, chk, n, C)
