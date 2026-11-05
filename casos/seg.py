"""Seguimiento (CU020, CU021): CP-SEG-01 a CP-SEG-04, adaptados a QA.

- Supervisora en la interfaz: supervisor-2. Docente con historial: Docente A.
- CP-SEG-01 necesita más de 40 Docentes activos. Si QA tiene menos, la suite crea una sola vez
  cuentas Docente "Seguimiento <nombre>" (alias …+sicedu-seg-NN) en colegios de volumen que después
  se inactivan. Esas cuentas nunca inician sesión ("Sin inicio de sesión registrado"). Al crearlas
  llega un correo de bienvenida por cada una: no hace falta pegar nada.
- Una cuenta Docente inactiva (…+sicedu-seg-inactivo) se crea una sola vez y se inactiva.
- Lo que en local se comparaba con la base de datos se compara con GET /api/seguimiento/docentes.
"""
import json
import re

from lib import api as A
from lib import config
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import caso
from lib.ui import (Nav, Run, backend_caido, cerrar_dialogos, filtros_ui, idb_todo, ir, login, opciones, poner, textos,
                    token_navegador)

from casos._comun import fin, sup_ui
from casos.asi import put_asis
from casos.rub import rub_items, rub_put
from casos.rv import PA_ACT, rv_items, rv_put
from casos.ses import ciclo, pie_txt, preparar_ses

NOMS = ['Abel', 'Berta', 'Ciro', 'Delia', 'Efraín', 'Fabiola', 'Gastón', 'Hilda', 'Iván', 'Julia', 'Kevin', 'Lidia', 'Mario', 'Nora',
        'Óscar', 'Paula', 'Quique', 'Rosa', 'Saúl', 'Tania', 'Ulises', 'Vilma', 'Walter', 'Ximena', 'Yuri', 'Zoila', 'Adán', 'Beatriz',
        'César', 'Dora', 'Elías', 'Flor', 'Gabino', 'Hortensia', 'Ismael', 'Juana', 'Kelly', 'Luis', 'Marta', 'Néstor']


def _docente_simple(etiqueta, nombres, cid, grado, log):
    correo = config.correo_de(etiqueta)
    u = A.usuario_por_correo(correo)
    if u:
        return u, False
    s, r = A.api('POST', '/usuarios', A.sup(), {'nombres': nombres, 'apellidos': 'QA Auto', 'dni': D._dni(correo), 'correo': correo, 'id_rol': 1,
                                                'asignacion': A.asignacion([(cid, [grado])])})
    if s != 201:
        log(f'No se pudo crear {correo}: {s} {str(r)[:160]}')
        return None, False
    return r['usuario'], True


def asegurar_docentes(minimo=41):
    """Más de 40 Docentes activos, uno que nunca entró y uno inactivo. Devuelve las líneas de la precondición."""
    lineas = []
    activos = (A.ok(A.api('GET', '/seguimiento/docentes', A.sup()), 'seguimiento') or {}).get('total', 0)
    lineas.append(f'Docentes activos en Seguimiento: {activos}')
    faltan = max(0, minimo - activos)
    # cuentas especiales (una sola vez): nunca inicia sesión e inactiva
    especiales = [('seg-sin-login', 'Seguimiento Sin Login', 1), ('seg-inactivo', 'Seguimiento Inactivo', 2)]
    creados, colegios_vol = 0, []
    for et, nom, g in especiales:
        u, nuevo = _docente_simple(et, nom, D.Y(), g, lineas.append)
        if u and nuevo:
            creados += 1
        if u and et == 'seg-inactivo' and u.get('activo', True):
            lineas.append(f'{nom}: inactivada → HTTP {A.api("PATCH", f"/usuarios/{u["id"]}/desactivar", A.sup(), {})[0]}')
    k = 0
    while faltan > 0 and k < len(NOMS):
        if k % 6 == 0:
            body = {'nombre': f'QA AUTO Volumen Docentes {A.ahora().strftime("%m%d-%H%M")} {k // 6 + 1}', 'departamento': 'Áncash', 'provincia': 'Huaraz',
                    'distrito': 'Independencia', 'nivel_educativo': 'Primaria', 'grados': [{'id_grado': A.id_grado(g), 'dia_clase': 1} for g in range(1, 7)],
                    'programas': [A.ALFA(), A.CL()]}
            colegios_vol.append(A.ok(A.api('POST', '/colegios', A.sup(), body), 'colegio de volumen')['id'])
        u, nuevo = _docente_simple(f'seg-{k + 1:02d}', f'Seguimiento {NOMS[k]}', colegios_vol[-1], k % 6 + 1, lineas.append)
        if u and nuevo:
            faltan -= 1; creados += 1
        k += 1
    for c in colegios_vol:
        A.api('PATCH', f'/colegios/{c}/desactivar', A.sup())
    if creados:
        lineas.append(f'Se crearon {creados} cuentas Docente de volumen (alias …+sicedu-seg-NN, sin primer ingreso) en {len(colegios_vol)} colegios de volumen ya inactivados.')
    lineas.append(f'Docentes activos ahora: {(A.api("GET", "/seguimiento/docentes", A.sup())[1] or {}).get("total")}')
    return lineas


def estados_sincronizacion():
    """Docente A con un rechazo (Error) y Docente RV con pendientes informados."""
    C = D.cuenta('docente-a'); X = D.X(); out = {}
    act = ciclo(C)
    futura = A.hoy() + __import__('datetime').timedelta(days=7)
    out['error'] = put_asis(C, futura, [(D.alumno('Ana Norte QA'), 'presente', None)], act)
    A.finalizar_actividad(C, act)
    RV = D.cuenta('rv-uno'); A.cerrar_abiertas(RV); act = ciclo(RV)
    F1 = FE.ultima_clase(1, X, incluir_hoy=True)
    out['pendiente'] = A.api('POST', '/sincronizacion/pendientes', RV, [{
        'id_operacion': A.uid(), 'id_dispositivo': 'tablet-qa', 'id_actividad': act, 'modulo': 'asistencias',
        'realizado_en': A.ahora().replace(microsecond=0).isoformat(),
        'registro': {'id_colegio': X, 'id_grado': A.id_grado(1), 'id_seccion': A.seccion(X, 1), 'fecha': A.iso(F1), 'id_alumno': D.alumno('Grado1P1 Entrada QA')}}])[0]
    A.finalizar_actividad(RV, act)
    return out


def grilla(p):
    return [r.replace('\n', ' | ').replace('\t', ' | ')[:170] for r in p.locator('main tbody tr').all_inner_texts()]


def abrir_seg(p):
    login(p, sup_ui()); ir(p, 'Seguimiento'); p.wait_for_timeout(2500)


def aplicar(p):
    b = p.locator('main').get_by_role('button', name=re.compile('^(Filtrar|Buscar|Aplicar)'))
    if b.count():
        b.first.click()
    p.wait_for_timeout(2500)


def abrir_docente(p, nombre='Docente A', colegio=True):
    if colegio:
        poner(p, 'Colegio', D.nombre_colegio('norte')); aplicar(p)
    p.locator('main tbody tr').filter(has_text=nombre).first.get_by_role('button', name=re.compile('Ver detalle')).first.click()
    p.wait_for_timeout(2500)


def _api_seg(tk, **f):
    r = A.api('GET', '/seguimiento/docentes?' + A.q(**f), tk)[1] or {}
    return r.get('total'), [(i['nombres'] + ' ' + i['apellidos'])[:30] for i in r.get('items', [])][:5]


@caso('CP-SEG-01')
def cp_seg01():
    R = Run('CP-SEG-01'); chk = {}; n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    pre = asegurar_docentes(); chk['sinc'] = estados_sincronizacion()
    R.consola(ctx, 'Precondición (por la API)', pre + [f'Docente A con un rechazo (asistencia de una fecha futura): {chk["sinc"]["error"]}',
                                                     f'Docente RV con pendientes informados: HTTP {chk["sinc"]["pendiente"]}'])
    abrir_seg(p); m = p.locator('main')
    chk['columnas'] = [x.strip() for x in m.locator('thead th').all_inner_texts()]
    chk['ayuda'] = textos(p, 'corresponde a los datos', 'dispositivos')
    R.shot(p, f'Pasos 1-2: columnas {chk["columnas"]}; texto de ayuda {chk["ayuda"]}', full=True)
    g = grilla(p); chk['n'] = len(g); chk['pie'] = pie_txt(p)
    chk['sin_login'] = len([r for r in g if 'Sin inicio de sesión' in r]); chk['no_disponible'] = [r for r in g if 'No disponible' in r][:2]
    R.shot(p, f'Paso 3: "Sin inicio de sesión registrado": {chk["sin_login"]} filas; "No disponible": {chk["no_disponible"]}')
    tks = token_navegador(p)
    items = A.todas_las_paginas('/seguimiento/docentes', tks)
    r1 = A.api('GET', '/seguimiento/docentes', tks)[1] or {}
    activos = (A.api('GET', '/usuarios?' + A.q(rol='Docente', activo='true'), tks)[1] or {}).get('total')
    chk['api'] = {'total': r1.get('total'), 'paginas': r1.get('total_pages'), 'docentes_activos_usuarios': activos,
                  'orden': [((i['nombres'] + ' ' + i['apellidos'])[:24], i.get('sincronizacion')) for i in items][:10]}
    grupos = [i.get('sincronizacion') for i in items]
    chk['orden_grupos'] = [x for k, x in enumerate(grupos) if k == 0 or grupos[k - 1] != x]
    idd = D.id_docente('docente-a'); da = next((i for i in items if i['id_docente'] == idd), None)
    hist = (A.api('GET', f'/seguimiento/docentes/{idd}/actividades', tks)[1] or {}).get('items', [])
    chk['ultima_conexion'] = (da.get('ultima_conexion') if da else None, hist[0]['inicio'] if hist else None)
    R.consola(ctx, 'Pasos 4-6: API (en local se comparaba con la base de datos)',
              [f'GET /api/seguimiento/docentes → total {chk["api"]["total"]}, páginas {chk["api"]["paginas"]}; Docentes activos en Usuarios: {activos}',
               f'Secuencia de grupos de sincronización en el orden de la API: {chk["orden_grupos"]}',
               f'Primeros: {chk["api"]["orden"]}',
               f'Docente A: última conexión {chk["ultima_conexion"][0]}; inicio de su actividad más reciente {chk["ultima_conexion"][1]} '
               '(la suite entra como Docente A al empezar cada caso; si la actividad es posterior, la columna debe seguir mostrando el inicio de sesión)',
               f'Filas en la página de la interfaz: {chk["n"]}; pie "{chk["pie"]}"'])
    R.shot(p, f'Pasos 5-6: primeras filas {g[:4]}; filas {chk["n"]}; pie "{chk["pie"]}"', full=True)
    b = m.get_by_role('button', name='Siguiente')
    if b.count() and b.first.is_enabled():
        b.first.click(); p.wait_for_timeout(1500); chk['pagina2'] = (len(grilla(p)), pie_txt(p))
        R.shot(p, f'Paso 6: página 2: {chk["pagina2"]}', full=True)
    filtros = {}; X = D.X(); H = A.hoy()
    poner(p, 'Colegio', D.nombre_colegio('norte')); aplicar(p)
    filtros['colegio'] = (grilla(p)[:5], pie_txt(p), _api_seg(tks, id_colegio=X))
    R.shot(p, f'Paso 7: colegio Norte del caso → {filtros["colegio"][:2]}; API {filtros["colegio"][2]}')
    poner(p, 'Colegio', 'Todos')
    try:
        p.get_by_label('Conectado desde', exact=True).fill(A.iso(H)); p.get_by_label('Hasta', exact=True).fill(A.iso(H)); aplicar(p)
        filtros['rango'] = (len(grilla(p)), pie_txt(p), _api_seg(tks, desde=A.iso(H), hasta=A.iso(H))[0])
        R.shot(p, f'Paso 7: conectados hoy → {filtros["rango"]} (filas | pie | API)')
        p.get_by_label('Conectado desde', exact=True).fill(''); p.get_by_label('Hasta', exact=True).fill('')
    except Exception as e:
        filtros['rango'] = 'sin campos de fecha: ' + str(e)[:80]
    poner(p, 'Sincronización', 'Error'); aplicar(p)
    filtros['error'] = (grilla(p)[:3], _api_seg(tks, sincronizacion='error'), opciones(p, 'Sincronización'))
    R.shot(p, f'Paso 7: sincronización Error → {filtros["error"][0]}; API {filtros["error"][1]}; opciones {filtros["error"][2]}')
    filtros['criterios_ui'] = [l for l, _ in filtros_ui(p)]
    filtros['inactivos_api'] = _api_seg(tks, activo='false')
    est = next((l for l in filtros['criterios_ui'] if 'docente' in l.lower() or l.lower().startswith('estado')), None)
    if est:
        poner(p, 'Sincronización', 'Todos'); poner(p, est, 'Inactivo'); aplicar(p); filtros['inactivo_ui'] = grilla(p)[:3]
        R.shot(p, f'Paso 7: estado del Docente Inactivo → {filtros["inactivo_ui"]}')
        poner(p, est, 'Activo'); poner(p, 'Sincronización', 'Error')
    chk['filtros'] = filtros
    poner(p, 'Colegio', D.nombre_colegio('sur')); aplicar(p)
    chk['sin_coincidencias'] = (textos(p, 'Sin docentes', 'No se encontraron', 'Pruebe'), filtros_ui(p))
    R.shot(p, f'Paso 8: colegio Sur + Error: {chk["sin_coincidencias"]}; criterios de la interfaz {filtros["criterios_ui"]}; API activo=false → {filtros["inactivos_api"]}')
    ls = p.evaluate('JSON.stringify(localStorage)'); ir(p, 'Inicio'); p.wait_for_timeout(1000); ir(p, 'Seguimiento'); p.wait_for_timeout(2000)
    chk['restaura'] = (filtros_ui(p), ls[:300])
    R.shot(p, f'Paso 9: al volver de otro módulo: {chk["restaura"][0]}')
    R.consola(ctx, 'Paso 9: Local Storage', [ls[:800]])
    fin(R, chk, n)


@caso('CP-SEG-02')
def cp_seg02():
    R = Run('CP-SEG-02'); chk = {}; n = Nav(); ctx = n.ctx(); p = ctx.new_page(); C = D.cuenta('docente-a')
    chk['prep'] = {k: v for k, v in preparar_ses(R, ctx).items() if k in ('total', 'cierres')}
    asegurar_docentes(0)
    act = ciclo(C)  # actividad en curso
    abrir_seg(p); m = p.locator('main'); abrir_docente(p, 'Docente A')
    chk['cabecera'] = m.inner_text()[:400]; chk['grilla_visible'] = 'Colegios asignados' in [x.strip() for x in m.locator('thead th').all_inner_texts()]
    chk['pestanas'] = m.get_by_role('tab').count()
    R.shot(p, f'Pasos 1-3: historial de Docente A (pestañas: {chk["pestanas"]}; grilla general visible: {chk["grilla_visible"]})', full=True)
    chk['columnas'] = [x.strip() for x in m.locator('thead th').all_inner_texts()]; g = grilla(p); chk['filas'] = len(g); chk['pie'] = pie_txt(p)
    chk['primeras'] = g[:3]
    tks = token_navegador(p); idd = D.id_docente('docente-a'); r = A.api('GET', f'/seguimiento/docentes/{idd}/actividades', tks)[1] or {}
    it = r.get('items') or [{}]
    chk['api'] = {'total': r.get('total'), 'paginas': r.get('total_pages'), 'en_curso_es_la_primera': it[0].get('id') == act,
                  'primera': {k: it[0].get(k) for k in ['fecha', 'inicio', 'fin', 'estado', 'tipo_cierre', 'sincronizacion', 'productividad_texto']}}
    chk['prod'] = list(dict.fromkeys(x['productividad_texto'] for x in A.todas_las_paginas(f'/seguimiento/docentes/{idd}/actividades', tks) if x.get('productividad_texto')))[:6]
    R.shot(p, f'Pasos 4-6: columnas {chk["columnas"]}; filas {chk["filas"]}; pie "{chk["pie"]}"; primera {g[:1]}', full=True)
    b = m.get_by_role('button', name='Siguiente')
    if b.count() and b.first.is_enabled():
        b.first.click(); p.wait_for_timeout(1500); chk['pagina2'] = (len(grilla(p)), pie_txt(p))
        R.shot(p, f'Paso 6: página 2 del historial: {chk["pagina2"]}', full=True)
    R.consola(ctx, 'Pasos 4-6: API (en local se comparaba con la base de datos)', [json.dumps(chk['api'], ensure_ascii=False), f'Textos de Productividad distintos: {chk["prod"]}'])
    m.get_by_role('button', name=re.compile('Volver')).first.click(); p.wait_for_timeout(2000)
    poner(p, 'Colegio', 'Todos'); aplicar(p)
    try:
        # el Docente sin actividades: la cuenta de la suite que nunca inició sesión
        idx = None
        for pg in range(1, 6):
            if p.locator('main tbody tr').filter(has_text='Seguimiento Sin Login').count():
                idx = pg; break
            b = m.get_by_role('button', name='Siguiente')
            if not (b.count() and b.first.is_enabled()):
                break
            b.first.click(); p.wait_for_timeout(1500)
        abrir_docente(p, 'Seguimiento Sin Login', colegio=False)
        chk['sin_actividades'] = textos(p, 'Sin sesiones', 'No hay actividades', 'todavía no')
    except Exception as e:
        chk['sin_actividades'] = 'no se encontró la fila: ' + str(e)[:80]
    R.shot(p, f'Paso 7: Docente sin actividades (Seguimiento Sin Login): {chk["sin_actividades"]}')
    fin(R, chk, n, C)


@caso('CP-SEG-03')
def cp_seg03():
    import datetime as dt
    R = Run('CP-SEG-03'); chk = {}; n = Nav(); ctx = n.ctx(); C = D.cuenta('docente-a'); X = D.X()
    a, b = D.alumno('Ana Norte QA'), D.alumno('Beto Norte QA')
    hoy_c = FE.ultima_clase(3, X, incluir_hoy=True)
    pa = FE.pa_actual(X)
    previas = [f for f in FE.clases_habituales(3, pa['fecha_inicio'], hoy_c - dt.timedelta(days=1), X)] if pa else []
    if previas:
        prev, perm = previas[-1], None
    else:
        pa_ant = FE.pa_anterior(X); cl = FE.clases_del_pa(3, pa_ant['numero'], X)
        prev = cl[-1]
        perm = A.permiso(D.id_usuario('docente-a'), X, 3, pa_ant['id_periodo_academico'], 'asistencias', A.ahora() + dt.timedelta(days=2))[0]
    act = ciclo(C)
    chk['prep'] = {'hoy': (A.iso(hoy_c), put_asis(C, hoy_c, [(a, 'presente', None)], act)),
                   'correccion': (A.iso(prev), perm, put_asis(C, prev, [(a, 'tardanza', None)], act)),
                   'rubrica': rub_put(C, rub_items([(a, 3, 2), (b, 2, 2)], act)),
                   'rv': rv_put(C, rv_items([(a, PA_ACT(X), {'id_nivel_colocado': A.niveles_rk()['L']})], act))}
    A.finalizar_actividad(C, act)
    R.consola(ctx, 'Precondición (por la API): actividad de Docente A', [f'{k}: {v}' for k, v in chk['prep'].items()] +
              ([f'La clase anterior es del PA anterior: se otorgó un permiso de Asistencias → HTTP {perm}'] if perm else []))
    p = ctx.new_page(); abrir_seg(p); m = p.locator('main'); abrir_docente(p, 'Docente A')
    fila0 = m.locator('tbody tr').first; chk['atajos'] = fila0.get_by_role('button').all_inner_texts()
    chk['fila'] = fila0.inner_text().replace('\n', ' | ')[:200]
    R.shot(p, f'Paso 1: atajos de la actividad: {chk["atajos"]}; fila {chk["fila"]}', full=True)
    res = {}
    for mod in ['Asistencias', 'Rúbrica', 'Registro de Vuelo', 'Seguimiento de Lectura', 'Alumnos']:
        fila0 = m.locator('tbody tr').first
        bt = fila0.get_by_role('button', name=re.compile(f'Ver {mod}'))
        if not bt.count():
            res[mod] = 'sin atajo'
            continue
        bt.first.click(); p.wait_for_timeout(2000); d = p.locator('[role=dialog]:visible').last
        res[mod] = (p.url.split('/', 3)[-1], d.inner_text()[:400] if d.count() else m.inner_text()[:300])
        txt = p.locator('body').inner_text()
        res[mod] += ([x for x in ['Registrar evaluaciones', 'Registrar niveles', 'Marcar todos como presentes'] if x in txt],)
        R.shot(p, f'Pasos 2-4: "Ver {mod}": {str(res[mod])[:300]}', full=True)
        cerrar_dialogos(p)
        vb = m.get_by_role('button', name=re.compile('Volver al historial'))
        if vb.count():
            vb.first.click(); p.wait_for_timeout(1800)
    chk['modulos'] = res
    tks = token_navegador(p); chk['api_sup'] = rub_put(tks, rub_items([(a, 4, 4)], act))
    R.consola(ctx, 'Paso 5: PUT /api/rubricas con el token de la Supervisora', [str(chk['api_sup'])])
    bt = m.get_by_role('button', name=re.compile('Volver')); chk['volver'] = bt.all_inner_texts()
    if bt.count():
        bt.first.click(); p.wait_for_timeout(2000)
    chk['tras_volver'] = (p.url.split('/', 3)[-1], pie_txt(p), grilla(p)[:1])
    R.shot(p, f'Paso 6: {chk["volver"]} → {chk["tras_volver"]}')
    fin(R, chk, n, C)


@caso('CP-SEG-04')
def cp_seg04():
    R = Run('CP-SEG-04'); chk = {}; n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    abrir_seg(p); m = p.locator('main')
    poner(p, 'Colegio', D.nombre_colegio('norte')); aplicar(p)
    ctx.set_offline(True); p.wait_for_timeout(1500)
    chk['offline'] = {'texto': m.inner_text()[:300], 'tabla': m.locator('table').count(), 'filtros': m.locator('select, input').count(),
                      'reintentar': m.get_by_role('button', name='Reintentar').count()}
    R.shot(p, f'Paso 1: sin conexión: {chk["offline"]}')
    ir(p, 'Colegios'); p.wait_for_timeout(1500); chk['navegar'] = p.url.split('/', 3)[-1]
    R.shot(p, f'Paso 2: navegación a otro módulo sin conexión: /{chk["navegar"]}')
    ir(p, 'Seguimiento'); p.wait_for_timeout(800); ctx.set_offline(False); p.wait_for_timeout(3000)
    chk['reconectado'] = (filtros_ui(p), len(grilla(p)))
    R.shot(p, f'Paso 3: reconectado: {chk["reconectado"]}')
    abrir_docente(p, 'Docente A', colegio=False); ctx.set_offline(True); p.wait_for_timeout(1500)
    chk['historial_offline'] = {'texto': m.inner_text()[:400], 'tabla': m.locator('table').count(), 'reintentar': m.get_by_role('button', name='Reintentar').count()}
    R.shot(p, f'Paso 4: historial de Docente A sin conexión: {chk["historial_offline"]}', full=True)
    ctx.set_offline(False); p.wait_for_timeout(3000); chk['historial_online'] = (m.locator('table').count(), len(grilla(p)))
    R.shot(p, f'Paso 5: reconectado: {chk["historial_online"]}')
    backend_caido(ctx, True); p.reload(); p.wait_for_timeout(4000)
    chk['caido'] = p.locator('body').inner_text()[:400]
    R.shot(p, f'Paso 6: backend sin responder y recarga: {chk["caido"][:250]}', full=True)
    backend_caido(ctx, False); p.wait_for_timeout(1000)
    raw = idb_todo(p)
    chk['idb'] = {'almacenes': list(json.loads(raw).keys()), 'seguimiento': raw.count('ultima_conexion'), 'historial': raw.count('productividad_texto')}
    R.consola(ctx, 'Paso 7: IndexedDB', [f'Almacenes: {chk["idb"]["almacenes"]}',
                                         f'Apariciones de "ultima_conexion": {chk["idb"]["seguimiento"]}; de "productividad_texto": {chk["idb"]["historial"]}'])
    fin(R, chk, n)
