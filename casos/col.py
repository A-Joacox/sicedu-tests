"""Colegios (CU013): CP-COL-01, 02, 03, 04, 06, 07 y 08, adaptados a QA.

- Supervisora en la interfaz: supervisor-2. Los colegios que crea un caso llevan la hora del caso en
  el nombre y se inactivan al terminar (como los de la corrida).
- CP-COL-01 necesita más de 40 colegios activos: si QA tiene menos, el caso crea los que faltan (en
  varios departamentos y distritos) y los inactiva al terminar.
- CP-COL-07 y 08 usan un colegio propio con el 2.º los lunes y el 3.º los martes y un calendario
  particular con un día no lectivo un lunes del mes. Las fechas salen de su calendario.
- Lo que en local se veía en la base de datos se ve por la API (GET /colegios/{id}, clases y
  GET /clases/{id}/reprogramaciones).
"""
import datetime as dt
import re

from lib import api as A
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import caso
from lib.ui import BASE, Nav, Run, cerrar_dialogos, con_actividad, dlg, filtros_ui, ir, login, main_txt, opciones, poner, toasts_txt

from casos._comun import crear_colegio, fin, hhmmss, hay_dialogo, registrar_colegio, sup_ui
from casos.asi import put_asis

UBIC_VOL = [('Áncash', 'Huaraz', 'Independencia'), ('Áncash', 'Carhuaz', 'Shilla'), ('Áncash', 'Yungay', 'Yungay'),
            ('Lima', 'Lima', 'Comas'), ('Junín', 'Tarma', 'Tarma'), ('Cusco', 'Cusco', 'Wanchaq')]
DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes']


def filas(p):
    return p.locator('main tbody tr')


def pie(p):
    t = main_txt(p); m = re.search(r'Mostrando (\d+) a (\d+) de (\d+)', t); pg = re.search(r'(\d+) / (\d+)', t)
    return (m.groups() if m else None, pg.groups() if pg else None)


def abrir_colegios(p):
    p.goto(BASE + '/colegios'); p.wait_for_load_state('networkidle'); p.wait_for_timeout(1500)
    try:
        filas(p).first.wait_for(timeout=6000)
    except Exception:
        pass


def buscar(p, texto):
    p.get_by_label('Buscar').fill(texto); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1500)


def fila_col(p, nombre):
    return filas(p).filter(has_text=nombre).first


def nombres_tabla(p):
    return [r.split('\t')[0].strip() for r in filas(p).all_inner_texts()]


def S(p, i):
    return p.locator('main select').nth(i)


def marcar(d, texto):
    d.get_by_text(texto, exact=True).first.click(); d.page.wait_for_timeout(300)


def errores(p):
    if not hay_dialogo(p):
        return ['(el modal se cerró)']
    return re.findall(r'\n([^\n]*(?:obligatorio|Obligatorio|Falta|Ya existe|inválid|debe|Selecciona|Ingresa)[^\n]*)', '\n' + dlg(p).inner_text())


def cerrar_todos(p):
    for _ in range(4):
        if not hay_dialogo(p):
            return
        b = dlg(p).get_by_role('button', name=re.compile('Cancelar|Descartar|Cerrar'))
        (b.last if b.count() else dlg(p).get_by_role('button').last).click(); p.wait_for_timeout(400)


def dia_del_grado(d, grado):
    """Select "Día de clase" del grado (el bloque del grado marcado)."""
    bloque = d.locator('div.rounded-lg').filter(has=d.page.get_by_text(grado, exact=True)).filter(has=d.page.locator('select')).first
    return bloque.locator('select').first


def form_colegio(d, nombre=None, dep=None, prov=None, dist=None, subs=(), grados=None):
    if nombre is not None:
        d.get_by_label('Nombre del colegio').fill(nombre)
    if dep is not None:
        d.get_by_label('Departamento').fill(dep)
    if prov is not None:
        d.get_by_label('Provincia').fill(prov)
    if dist is not None:
        d.get_by_label('Distrito').fill(dist)
    for s in subs:
        marcar(d, s)
    for g, dia in (grados or {}).items():
        marcar(d, g)
        if dia:
            dia_del_grado(d, g).select_option(label=dia)


def detalle_api(cid):
    c = A.colegio(cid)
    return {'id': c['id'], 'activo': c.get('activo'), 'distrito': c.get('distrito'), 'provincia': c.get('provincia'),
            'grados': [(g.get('nombre') or g['id'], g.get('dia_clase'), [s['nombre'] for s in g.get('secciones', [])]) for g in c.get('grados', [])]}


# ── CP-COL-01 ───────────────────────────────────────────────────────────────────────

@caso('CP-COL-01')
def cp_col01():
    R = Run('CP-COL-01'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    activos = (A.api('GET', '/colegios?activo=true', A.sup())[1] or {}).get('total', 0)
    faltan = max(0, 41 - activos); creados = []
    for k in range(faltan):
        dep, prov, dist = UBIC_VOL[k % len(UBIC_VOL)]
        creados.append(crear_colegio(f'QA AUTO {hhmmss()} Volumen {k + 1:02d}', {3: 1}, departamento=dep, provincia=prov, distrito=dist))
    R.consola(ctx, 'Precondición (por la API)', [f'Colegios activos en QA: {activos}; se crearon {faltan} para pasar de 40 (se inactivan al terminar el caso).',
                                                f'Inactivos: {(A.api("GET", "/colegios?activo=false", A.sup())[1] or {}).get("total")}'])
    login(p, sup_ui()); abrir_colegios(p); m = p.locator('main')
    chk['botones_sup'] = m.get_by_role('button').all_inner_texts()[:3]
    chk['cabeceras'] = [t.strip() for t in p.locator('main thead th').all_inner_texts()]
    f0 = filas(p).first
    chk['controles'] = [(x.get_attribute('aria-label') or x.inner_text()) for x in f0.locator('button,[role=switch]').all()]
    chk['tooltip_ver'] = [x.get_attribute('title') for x in f0.locator('button').all()][:3]
    chk['filtros'] = [s.evaluate("s=>[...s.options].map(o=>o.text)")[:8] for s in p.locator('main select').all()]
    chk['pie'] = pie(p); chk['n_filas'] = filas(p).count()
    R.shot(p, f'Pasos 1-4: botones {chk["botones_sup"]}; columnas {chk["cabeceras"]}; controles {chk["controles"]}; filas {chk["n_filas"]}, pie {chk["pie"]}', full=True)
    sig = p.get_by_role('button', name='Siguiente')
    if sig.count() and sig.first.is_enabled():
        sig.first.click(); p.wait_for_timeout(1200)
    chk['pag2'] = pie(p); R.shot(p, f'Paso 5: página 2: {chk["pag2"]}')
    dep = 'Junín'
    S(p, 0).select_option(label=dep); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1500)
    chk['f_dep'] = (pie(p), nombres_tabla(p)[:10]); chk['dist_tras_dep'] = S(p, 1).evaluate("s=>[...s.options].map(o=>o.text)")
    api_dep = (A.api('GET', '/colegios?' + A.q(departamento=dep, activo='true'), A.sup())[1] or {}).get('total')
    R.shot(p, f'Paso 5: Departamento = {dep} desde la página 2: {chk["f_dep"]}; API {api_dep}; opciones de Distrito: {chk["dist_tras_dep"][:10]}')
    p.get_by_role('button', name='Limpiar').click(); p.wait_for_timeout(800)
    dis = 'Shilla'
    S(p, 1).select_option(label=dis); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1500)
    chk['f_dis'] = (pie(p), nombres_tabla(p)[:8])
    api_dis = (A.api('GET', '/colegios?' + A.q(distrito=dis, activo='true'), A.sup())[1] or {}).get('total')
    R.shot(p, f'Paso 6: Distrito = {dis}: {chk["f_dis"]}; API {api_dis}')
    p.get_by_role('button', name='Limpiar').click(); p.wait_for_timeout(800)
    S(p, 2).select_option(label='Inactivos'); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1500)
    chk['f_inac'] = (pie(p), nombres_tabla(p)[:6])
    api_in = (A.api('GET', '/colegios?activo=false', A.sup())[1] or {}).get('total')
    R.shot(p, f'Paso 6: estado Inactivos: {chk["f_inac"]}; API {api_in}')
    R.consola(ctx, 'Pasos 4-6: comparación con la API (en local, con la base de datos)',
              [f'Colegios activos (API): {(A.api("GET", "/colegios?activo=true", A.sup())[1] or {}).get("total")}; filas en la página 1: {chk["n_filas"]}; pie {chk["pie"]}; página 2 {chk["pag2"]}',
               f'Departamento {dep}: API {api_dep} · tabla {chk["f_dep"][0]}', f'Distrito {dis}: API {api_dis} · tabla {chk["f_dis"][0]}',
               f'Inactivos: API {api_in} · tabla {chk["f_inac"][0]}'])
    fin(R, chk, n)


# ── CP-COL-02 ───────────────────────────────────────────────────────────────────────

@caso('CP-COL-02')
def cp_col02():
    R = Run('CP-COL-02'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    NOM = f'I.E. Educación QA {hhmmss()}'
    login(p, sup_ui()); abrir_colegios(p)
    p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(800); d = dlg(p)
    ne = d.get_by_label('Nivel educativo')
    chk['nivel'] = (ne.input_value() if ne.count() else None, (ne.is_disabled() or ne.get_attribute('readonly') is not None) if ne.count() else None)
    chk['grados_ofrecidos'] = re.findall(r'\n([1-9]\.º)', '\n' + d.inner_text())
    chk['secundaria'] = 'Secundaria' in d.inner_text()
    R.shot(p, f'Paso 1: formulario; Nivel educativo = {chk["nivel"]}; grados {chk["grados_ofrecidos"]}; ofrece Secundaria = {chk["secundaria"]}')
    marcar(d, '3.º'); marcar(d, '4.º'); t = d.inner_text()
    chk['dia_y_secciones'] = (t.upper().count('DÍA DE CLASE'), t.upper().count('SECCIONES'), 'Ninguna todavía' in t, 'Única' in t)
    marcar(d, '4.º'); chk['tras_quitar'] = d.inner_text().upper().count('DÍA DE CLASE')
    R.shot(p, f'Paso 2: con 3.º y 4.º: "Día de clase" ×{chk["dia_y_secciones"][0]}, secciones ×{chk["dia_y_secciones"][1]} (Ninguna todavía {chk["dia_y_secciones"][2]}, Única {chk["dia_y_secciones"][3]}); al quitar 4.º quedan {chk["tras_quitar"]}')
    marcar(d, '3.º')
    base = dict(nombre=NOM, dep='Áncash', prov='Huaraz')
    res3 = {}
    for falta in ['nombre', 'dep', 'prov', 'subs', 'grados', 'dia']:
        cerrar_todos(p)
        p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(600); d = dlg(p)
        kw = dict(base); kw['subs'] = ['Comprensión Lectora']; kw['grados'] = {'2.º': 'Lunes'}
        if falta in ('nombre', 'dep', 'prov'):
            kw.pop(falta)
        if falta == 'subs':
            kw['subs'] = []
        if falta == 'grados':
            kw['grados'] = {}
        if falta == 'dia':
            kw['grados'] = {'2.º': None}
        form_colegio(d, **kw); d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1200)
        res3[falta] = (hay_dialogo(p), errores(p)[:3])
    chk['obligatorios'] = res3
    chk['no_creado'] = A.colegio_por_nombre(NOM) is None
    R.shot(p, f'Paso 3: guardar sin cada campo obligatorio (modal abierto, errores): {res3}; no se creó = {chk["no_creado"]}')
    cerrar_todos(p)
    p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(600); d = dlg(p)
    form_colegio(d, nombre=NOM, dep='Áncash', prov='Huaraz', subs=['Comprensión Lectora'],
                 grados={'2.º': 'Lunes', '3.º': 'Martes', '4.º': 'Miércoles', '5.º': 'Jueves', '6.º': 'Viernes'})
    d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(2000)
    chk['creado'] = toasts_txt(p)
    col = A.colegio_por_nombre(NOM); cid = col['id'] if col else None
    if cid:
        registrar_colegio(cid, NOM)
    chk['api'] = detalle_api(cid) if cid else None
    buscar(p, NOM); chk['en_tabla'] = nombres_tabla(p)
    R.shot(p, f'Paso 4: colegio creado sin distrito: {chk["creado"]}; tabla {chk["en_tabla"]}')
    R.consola(ctx, 'Paso 4: GET /api/colegios/{id} (en local, la base de datos): id | activo | distrito | grado, día, secciones',
              [str(chk['api']) if chk['api'] else '(no se creó)'])
    p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(600); d = dlg(p)
    dup = NOM.lower().replace('educación', 'educacion').replace(' ', '   ', 2)
    form_colegio(d, nombre=dup, dep='Áncash', prov='Huaraz', subs=['Comprensión Lectora'], grados={'2.º': 'Lunes'})
    d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1500)
    chk['duplicado'] = (dup, hay_dialogo(p), errores(p) + toasts_txt(p))
    R.shot(p, f'Paso 5: "{dup}": modal abierto {chk["duplicado"][1]}; {chk["duplicado"][2]}')
    cerrar_todos(p)
    buscar(p, NOM)
    fila_col(p, NOM).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(800); d = dlg(p)
    d.get_by_label('Distrito').fill('Independencia'); dia_del_grado(d, '2.º').select_option(label='Viernes')
    d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1800)
    if hay_dialogo(p) and dlg(p).get_by_role('button', name=re.compile('Confirmar|Guardar')).count():
        dlg(p).get_by_role('button', name=re.compile('Confirmar|Guardar')).last.click(); p.wait_for_timeout(1500)
    chk['edicion'] = (toasts_txt(p), filas(p).first.inner_text().replace('\t', ' | ')[:200])
    chk['api_edit'] = detalle_api(cid) if cid else None
    R.shot(p, f'Paso 6: distrito y día de clase del 2.º: {chk["edicion"]}; API {chk["api_edit"]}')
    s1, r1 = A.api('POST', '/colegios', A.sup(), {'nombre': f'QA Secundaria {hhmmss()}', 'departamento': 'Áncash', 'provincia': 'Huaraz', 'nivel_educativo': 'Secundaria',
                                                   'grados': [{'id_grado': A.id_grado(1), 'dia_clase': 1}], 'programas': [A.ALFA()]})
    s2, r2 = A.api('POST', '/colegios', A.sup(), {'nombre': f'QA Grado 7 {hhmmss()}', 'departamento': 'Áncash', 'provincia': 'Huaraz', 'nivel_educativo': 'Primaria',
                                                   'grados': [{'id_grado': 7, 'dia_clase': 1}], 'programas': [A.ALFA()]})
    for s_, r_ in ((s1, r1), (s2, r2)):
        if s_ == 201:
            registrar_colegio(r_['id'], r_['nombre'])
    chk['api_fuera'] = (s1, s2)
    R.consola(ctx, 'Paso 7: valores fuera de Primaria por la API', [f'Nivel "Secundaria" → HTTP {s1} {str(r1)[:200]}', f'Grado 7 → HTTP {s2} {str(r2)[:200]}'])
    # Paso 8: validaciones de la edición
    ed = {}
    for clave in ['provincia', 'subprogramas', 'grados', 'grado sin día']:
        cerrar_todos(p); buscar(p, NOM)
        fila_col(p, NOM).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(800); d = dlg(p)
        if clave == 'provincia':
            d.get_by_label('Provincia').fill('')
        elif clave == 'subprogramas':
            marcar(d, 'Comprensión Lectora')
        elif clave == 'grados':
            for g in ['2.º', '3.º', '4.º', '5.º', '6.º']:
                marcar(d, g)
        else:
            marcar(d, '1.º')
        d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1200)
        ed[clave] = (hay_dialogo(p), errores(p)[:3])
    cerrar_todos(p); buscar(p, NOM)
    fila_col(p, NOM).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(800); d = dlg(p)
    marcar(d, 'Alfabetización'); marcar(d, '1.º'); dia_del_grado(d, '1.º').select_option(label='Lunes')
    d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1800)
    ed['grado con día'] = (hay_dialogo(p), toasts_txt(p), detalle_api(cid)['grados'][:1] if cid else None)
    chk['edicion_invalida'] = ed
    R.shot(p, f'Paso 8: edición sin provincia / sin subprogramas / sin grados / grado sin día → {ed}')
    cerrar_todos(p); buscar(p, NOM)
    fila_col(p, NOM).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(800); d = dlg(p)
    d.get_by_label('Nombre del colegio').fill(D.nombre_colegio('sur')); d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1500)
    chk['nombre_de_otro'] = (hay_dialogo(p), errores(p) + toasts_txt(p))
    cerrar_todos(p); buscar(p, NOM)
    fila_col(p, NOM).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(800); d = dlg(p)
    d.get_by_label('Distrito').fill(''); d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1500)
    chk['mismo_nombre_sin_distrito'] = (hay_dialogo(p), toasts_txt(p), detalle_api(cid)['distrito'] if cid else None)
    R.shot(p, f'Paso 9: nombre de otro colegio → {chk["nombre_de_otro"]}; mismo nombre y distrito vacío → {chk["mismo_nombre_sin_distrito"]}')
    fin(R, chk, n)


# ── CP-COL-03 ───────────────────────────────────────────────────────────────────────

@caso('CP-COL-03')
def cp_col03():
    R = Run('CP-COL-03'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    NOM = f'I.E. Educación QA {hhmmss()} Estado'; cid = crear_colegio(NOM, {2: 1, 3: 2})
    Dir = D.cuenta('directivo')

    def operando():
        s, r = A.api('GET', '/inicio/directivo', Dir)
        return s, {k: v for k, v in (r or {}).items() if 'colegio' in k.lower()} if isinstance(r, dict) else str(r)[:200]
    chk['op_antes'] = operando()
    login(p, sup_ui()); abrir_colegios(p); buscar(p, NOM)
    fila_col(p, NOM).get_by_role('button', name=re.compile('Inactivar')).first.click(); p.wait_for_timeout(800)
    chk['confirmacion'] = dlg(p).inner_text()[:300] if hay_dialogo(p) else None
    R.shot(p, f'Paso 1: el switch pide confirmación: {chk["confirmacion"]}')
    if chk['confirmacion']:
        dlg(p).get_by_role('button', name='Cancelar').click(); p.wait_for_timeout(800)
    chk['tras_cancelar'] = A.colegio(cid).get('activo')
    R.shot(p, f'Paso 2: tras "Cancelar", activo según la API = {chk["tras_cancelar"]}')
    fila_col(p, NOM).get_by_role('button', name=re.compile('Inactivar')).first.click(); p.wait_for_timeout(800)
    dlg(p).get_by_role('button').filter(has_text=re.compile('Inactivar|Confirmar')).last.click(); p.wait_for_timeout(1500)
    chk['aviso'] = toasts_txt(p); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1200)
    chk['vista_defecto'] = nombres_tabla(p)
    S(p, 2).select_option(label='Inactivos'); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1500)
    chk['inactivos'] = nombres_tabla(p)
    R.shot(p, f'Paso 3: confirmado: {chk["aviso"]}; vista por defecto {chk["vista_defecto"]}; filtro Inactivos {chk["inactivos"]}')
    chk['api'] = {k: A.colegio(cid).get(k) for k in ('id', 'nombre', 'activo')}
    chk['op_despues'] = operando()
    R.consola(ctx, 'Pasos 4-5: el registro sigue existiendo (API) y Colegios Operando del Directivo',
              [f'GET /api/colegios/{cid}: {chk["api"]}', f'Directivo antes: {chk["op_antes"]}', f'Directivo después: {chk["op_despues"]}'])
    b = fila_col(p, NOM).get_by_role('button', name=re.compile('Activar|Reactivar'))
    chk['boton_reactivar'] = b.count()
    if b.count():
        b.first.click(); p.wait_for_timeout(800)
        if hay_dialogo(p):
            dlg(p).get_by_role('button').filter(has_text=re.compile('Activar|Confirmar')).last.click(); p.wait_for_timeout(1500)
    S(p, 2).select_option(label='Activos'); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1500)
    chk['reactivado'] = (A.colegio(cid).get('activo'), nombres_tabla(p), operando())
    R.shot(p, f'Paso 6: reactivado: {chk["reactivado"]}')
    fin(R, chk, n)


# ── CP-COL-04 ───────────────────────────────────────────────────────────────────────

@caso('CP-COL-04')
def cp_col04():
    R = Run('CP-COL-04'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    NX = D.nombre_colegio('norte')
    login(p, sup_ui()); abrir_colegios(p); buscar(p, NX)
    fila_col(p, NX).get_by_role('button', name=re.compile('Ver detalle')).first.click(); p.wait_for_timeout(2500)
    pc = p.get_by_role('tab', name=re.compile('Programación')).or_(p.get_by_role('button', name=re.compile('Programación')))
    if pc.count():
        pc.first.click(); p.wait_for_timeout(2000)
    chk['detalle'] = {'url': p.url.replace(BASE, ''), 'pestanas': p.get_by_role('tab').all_inner_texts(), 'filas': filas(p).count()}
    R.shot(p, f'Paso 1: detalle y "Programación de clases": {chk["detalle"]}', full=True)
    vb = p.locator('main').get_by_role('button', name='Volver a Colegios')
    if vb.count():
        vb.first.click(); p.wait_for_timeout(1500)
    p.get_by_role('button', name='Limpiar').click(); p.wait_for_timeout(1200)
    ctx.set_offline(True); p.wait_for_timeout(1500)
    m = p.locator('main')
    ag = m.get_by_role('button', name='Agregar')
    chk['offline'] = {'filas': filas(p).count(), 'agregar_deshabilitado': ag.first.is_disabled() if ag.count() else None,
                      'editar_deshabilitado': [b.is_disabled() for b in m.locator('tbody button').filter(has_text='Editar').all()[:3]],
                      'texto': [l for l in main_txt(p).split('\n') if 'conexi' in l.lower()][:3]}
    if ag.count():
        try:
            ag.first.hover(); p.wait_for_timeout(600)
        except Exception:
            pass
    chk['offline']['al_pasar'] = [l for l in p.locator('body').inner_text().split('\n') if 'sin conexión' in l.lower()][:3]
    R.shot(p, f'Pasos 2-3: sin conexión: {chk["offline"]}', full=True)
    try:
        p.get_by_label('Buscar').fill(NX); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1500)
        chk['filtro_offline'] = (nombres_tabla(p)[:5], [l for l in main_txt(p).split('\n') if 'conexi' in l.lower()][:2])
    except Exception as e:
        chk['filtro_offline'] = str(e)[:80]
    R.shot(p, f'Paso 4: filtrar sin conexión: {chk["filtro_offline"]}')
    try:
        fila_col(p, NX).get_by_role('button', name=re.compile('Ver detalle')).first.click(timeout=5000); p.wait_for_timeout(2000)
        pc = p.get_by_role('tab', name=re.compile('Programación')).or_(p.get_by_role('button', name=re.compile('Programación')))
        if pc.count():
            pc.first.click(); p.wait_for_timeout(1500)
        rb = p.locator('main tbody').get_by_role('button', name='Reprogramar')
        chk['reprogramar_offline'] = {'botones': rb.count(), 'deshabilitado': rb.first.is_disabled() if rb.count() else None}
        if rb.count() and rb.first.is_enabled():
            rb.first.click(); p.wait_for_timeout(1000)
            g = dlg(p).get_by_role('button', name=re.compile('Guardar')) if hay_dialogo(p) else None
            chk['reprogramar_offline']['modal'] = hay_dialogo(p); chk['reprogramar_offline']['guardar_deshabilitado'] = g.first.is_disabled() if g and g.count() else None
    except Exception as e:
        chk['reprogramar_offline'] = 'no se pudo abrir el detalle sin conexión: ' + str(e)[:80]
    R.shot(p, f'Paso 5: "Reprogramar" sin conexión: {chk["reprogramar_offline"]}', full=True)
    cerrar_todos(p)
    ctx.set_offline(False); p.wait_for_timeout(2500)
    abrir_colegios(p)
    ag = p.get_by_role('button', name='Agregar')
    chk['online'] = {'agregar': ag.first.is_enabled() if ag.count() else None, 'filas': filas(p).count()}
    R.shot(p, f'Paso 6: con conexión: {chk["online"]}')
    fin(R, chk, n)


# ── CP-COL-06 ───────────────────────────────────────────────────────────────────────

@caso('CP-COL-06')
def cp_col06():
    R = Run('CP-COL-06'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    NX = D.nombre_colegio('norte'); X = D.X(); C = D.cuenta('docente-b')   # Docente B: 4.º del Norte; se le suma el 3.º
    s_asg = A.asignar(D.id_usuario('docente-b'), [(X, [3, 4])])[0]
    login(p, sup_ui()); abrir_colegios(p); buscar(p, NX)
    fila_col(p, NX).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(800); d = dlg(p)
    bloque = d.locator('div.rounded-lg').filter(has=p.get_by_text('3.º', exact=True)).filter(has=p.get_by_placeholder('Añadir sección')).first
    inp = bloque.get_by_placeholder('Añadir sección')
    for s in ['A', 'B']:
        inp.fill(s); inp.press('Enter'); p.wait_for_timeout(300)
    R.shot(p, 'Paso 1: secciones "A" y "B" en el 3.º del colegio Norte del caso')
    d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1500)
    if hay_dialogo(p) and dlg(p).get_by_role('button', name=re.compile('Confirmar|Guardar')).count():
        dlg(p).get_by_role('button', name=re.compile('Confirmar|Guardar')).last.click(); p.wait_for_timeout(1500)
    chk['guardar'] = toasts_txt(p)
    chk['api'] = detalle_api(X)['grados']
    R.consola(ctx, 'Paso 2: GET /api/colegios/{id} (grado | día | secciones)', [str(x) for x in chk['api']] + [f'Mensaje: {chk["guardar"]}',
              f'Docente B asignado al 3.º y 4.º del colegio Norte → HTTP {s_asg}'])
    n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    con_actividad(p, C); ir(p, 'Asistencias'); p.wait_for_timeout(1500)
    poner(p, 'Colegio', NX); poner(p, 'Grado', '3.º')
    chk['seccion_3'] = (next((v for k, v in filtros_ui(p) if k.upper().startswith('SECCI')), None), opciones(p, 'Sección'))
    R.shot(p, f'Paso 3: Asistencias, 3.º: sección = "{chk["seccion_3"][0]}" (opciones {chk["seccion_3"][1]})')
    poner(p, 'Grado', '4.º')
    chk['seccion_4'] = (next((v for k, v in filtros_ui(p) if k.upper().startswith('SECCI')), None), opciones(p, 'Sección'))
    R.shot(p, f'Paso 4: 4.º: sección = "{chk["seccion_4"][0]}" (opciones {chk["seccion_4"][1]})')
    ir(p, 'Alumnos'); p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(800); d = dlg(p)
    lab = lambda t: d.get_by_label(re.compile('^' + t))  # noqa: E731
    try:
        lab('Colegio').select_option(label=NX)
    except Exception:
        lab('Colegio').select_option(index=1)
    p.wait_for_timeout(1000)
    try:
        lab('Grado').select_option(label='3.º', timeout=8000); p.wait_for_timeout(1500)
    except Exception as e:
        chk['grado_err'] = (str(e)[:80], lab('Grado').inner_text().replace('\n', '/'))
    chk['alumno_seccion'] = lab('Secci').inner_text().replace('\n', '/') if lab('Secci').count() else None
    sels = d.locator('select')
    d.get_by_label('Nombres').fill('Seccion'); d.get_by_label('Apellidos').fill('Pendiente QA')
    try:
        sels.nth(3).select_option(label='Comprensión Lectora')
    except Exception:
        pass
    d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1200)
    chk['sin_seccion'] = (hay_dialogo(p), errores(p) + toasts_txt(p))
    R.shot(p, f'Paso 5: nuevo alumno del 3.º: secciones {chk["alumno_seccion"]}; sin elegir sección: {chk["sin_seccion"]}')
    cerrar_dialogos(p)
    fin(R, chk, n, C)


# ── CP-COL-07 y 08: colegio con programación propia ────────────────────────────────

def colegio_programacion(R, ctx):
    """2.º los lunes y 3.º los martes, con alumnos (las clases solo se generan para grados con alumnos) y un
    calendario particular con un día no lectivo un lunes del mes actual."""
    nombre = f'QA AUTO {hhmmss()} Programación'
    cid = crear_colegio(nombre, {2: 1, 3: 2, 4: 3})
    desde = FE.pa(1, cid)['fecha_inicio']
    A.crear_alumno('Lucía', 'Programación QA', cid, 2, A.ALFA(), desde)
    A.crear_alumno('Mateo', 'Programación QA', cid, 3, A.CL(), desde)
    A.crear_alumno('Nayeli', 'Programación QA', cid, 3, A.ALFA(), desde)
    cal = A.calendario(cid); hoy = A.hoy()
    pa = FE.pa_actual(cid)
    lunes = [hoy.replace(day=1) + dt.timedelta(days=i) for i in range(31)]
    lunes = [d for d in lunes if d.month == hoy.month and d.isoweekday() == 1 and pa and A.fecha(pa['fecha_inicio']) <= d <= A.fecha(pa['fecha_fin'])]
    nl = lunes[-1] if lunes else None
    periodos = [{k: p_[k] for k in ('tipo', 'numero', 'fecha_inicio', 'fecha_fin')} for p_ in cal['periodos']]
    dnl = [{'motivo': x['motivo'], 'fecha_inicio': x['fecha_inicio'], 'fecha_fin': x['fecha_fin']} for x in cal.get('dias_no_lectivos', [])]
    if nl:
        dnl.append({'motivo': 'Día no lectivo QA (lunes)', 'fecha_inicio': nl.isoformat(), 'fecha_fin': nl.isoformat()})
    s, r = A.api('POST', '/calendarios/particulares', A.sup(), {'id_colegio': cid, 'id_anio_escolar': A.anio(), 'periodos': periodos, 'dias_no_lectivos': dnl})
    prs = [x for x in cal['periodos'] if x['tipo'] == 'PR' and (A.fecha(x['fecha_inicio']).month == hoy.month or A.fecha(x['fecha_fin']).month == hoy.month)]
    lineas = [f'Colegio {nombre} (id {cid}): 2.º los lunes (Lucía, Alfabetización), 3.º los martes (Mateo CL y Nayeli Alfabetización), 4.º los miércoles sin alumnos',
              f'Calendario particular con el lunes {FE.legible(nl)} no lectivo → HTTP {s} {"" if s < 300 else str(r)[:200]}',
              f'PR dentro del mes: {[(x["numero"], x["fecha_inicio"], x["fecha_fin"]) for x in prs] or "ninguno (el calendario no tiene un receso este mes)"}']
    if not prs:
        R.nota('Precondición: el calendario no tiene un PR dentro del mes actual; la exclusión de las fechas del PR no se ve este mes.')
    R.consola(ctx, 'Precondición (por la API)', lineas)
    return cid, nombre, nl, prs


def abrir_programacion(p, nombre):
    abrir_colegios(p); buscar(p, nombre)
    fila_col(p, nombre).get_by_role('button', name=re.compile('Ver detalle')).first.click(); p.wait_for_timeout(2500)
    pc = p.get_by_role('tab', name=re.compile('Programación')).or_(p.get_by_role('button', name=re.compile('Programación')))
    if pc.count():
        pc.first.click(); p.wait_for_timeout(2000)


def filas_prog(p):
    return [r.split('\t') for r in p.locator('main tbody tr').all_inner_texts()]


def sel_prog(p, i, label):
    S(p, i).select_option(label=label); p.wait_for_timeout(1200)


def clases_mes(cid, mes_ini, mes_fin):
    r = A.ok(A.api('GET', f'/colegios/{cid}/clases?' + A.q(desde=A.iso(mes_ini), hasta=A.iso(mes_fin)), A.sup()), 'clases')
    items = r.get('items', r) if isinstance(r, dict) else r
    return [(c['fecha'], c['id_grado'], c['tipo'], [s['nombre'] for s in c.get('subprogramas', [])]) for c in items]


@caso('CP-COL-07')
def cp_col07():
    R = Run('CP-COL-07'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    cid, NOM, nl, prs = colegio_programacion(R, ctx)
    hoy = A.hoy(); ini = hoy.replace(day=1); fin_m = (ini + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    login(p, sup_ui()); abrir_colegios(p)
    sig = p.get_by_role('button', name='Siguiente')
    if sig.count() and sig.first.is_enabled():
        sig.first.click(); p.wait_for_timeout(1200)
    chk['pie_listado'] = pie(p)
    buscar(p, NOM)
    fila_col(p, NOM).get_by_role('button', name=re.compile('Ver detalle')).first.click(); p.wait_for_timeout(2500)
    m = p.locator('main'); chk['cabecera'] = main_txt(p)[:120]; chk['volver'] = m.get_by_role('button', name='Volver a Colegios').count()
    R.shot(p, f'Paso 1: cabecera "{chk["cabecera"][:60]}"; "Volver a Colegios" = {chk["volver"]}')
    pc = p.get_by_role('tab', name=re.compile('Programación')).or_(p.get_by_role('button', name=re.compile('Programación')))
    if pc.count():
        pc.first.click(); p.wait_for_timeout(2000)
    chk['filtros'] = [(s.evaluate("s=>s.selectedIndex>=0?s.options[s.selectedIndex].text:''"), s.evaluate("s=>[...s.options].map(o=>o.text)")[:8]) for s in m.locator('select').all()]
    chk['columnas'] = [x.strip() for x in m.locator('thead th').all_inner_texts()]
    chk['mes'] = filas_prog(p)
    R.shot(p, f'Pasos 2-3: filtros {[f[0] for f in chk["filtros"]]}; columnas {chk["columnas"]}', full=True)
    api_mes = clases_mes(cid, ini, fin_m)
    lunes = [ini + dt.timedelta(days=i) for i in range((fin_m - ini).days + 1) if (ini + dt.timedelta(days=i)).isoweekday() == 1]
    martes = [ini + dt.timedelta(days=i) for i in range((fin_m - ini).days + 1) if (ini + dt.timedelta(days=i)).isoweekday() == 2]
    R.consola(ctx, f'Paso 4: clases de {FE.mes_nombre(hoy)} ({NOM})',
              [f'Tabla (fecha original | fecha vigente | grado | programación): {[(r[3] if len(r) > 3 else r, r[4] if len(r) > 4 else "", r[0], r[5] if len(r) > 5 else "") for r in chk["mes"]]}',
               f'API GET /colegios/{{id}}/clases del mes (fecha | grado | tipo | subprogramas): {api_mes}',
               f'Lunes del mes: {[FE.legible(d) for d in lunes]}; martes: {[FE.legible(d) for d in martes]}',
               f'Lunes no lectivo: {FE.legible(nl)}; PR del mes: {[(x["fecha_inicio"], x["fecha_fin"]) for x in prs]}'])
    R.shot(p, f'Pasos 4-5: {len(chk["mes"])} filas; pie {pie(p)}', full=True)
    etiquetas = [x.lower() for x in re.findall(r'\n(AÑO ESCOLAR|MES|GRADO|SECCIÓN|SUBPROGRAMA)\n', '\n' + main_txt(p).upper())]
    i_sub = next((k for k, f in enumerate(chk['filtros']) if 'Alfabetización' in f[1]), 4)
    i_gra = next((k for k, f in enumerate(chk['filtros']) if '2.º' in f[1]), 2)
    sel_prog(p, i_sub, 'Alfabetización'); chk['sub'] = filas_prog(p)
    R.shot(p, f'Paso 6: subprograma Alfabetización: {[(r[0], r[2] if len(r) > 2 else "", r[4] if len(r) > 4 else "") for r in chk["sub"]]}', full=True)
    sel_prog(p, i_sub, 'Todos'); sel_prog(p, i_gra, '4.º'); chk['vacio'] = main_txt(p)[-200:]
    R.shot(p, f'Paso 7: 4.º (sin alumnos, sin clases): {chk["vacio"][-100:]}')
    m.get_by_role('button', name='Volver a Colegios').click(); p.wait_for_timeout(2000)
    chk['volver_listado'] = (pie(p), p.get_by_label('Buscar').input_value())
    R.shot(p, f'Paso 8: al volver a Colegios: {chk["volver_listado"]} (antes de abrir el detalle: búsqueda "{NOM}")')
    chk['etiquetas'] = etiquetas
    fin(R, chk, n)


def reprog_ui(p, fecha_vig, nueva, motivo, boton='^Reprogramar$|Modificar'):
    fila = p.locator('main tbody tr').filter(has_text=fecha_vig).first
    fila.get_by_role('button', name=re.compile(boton)).first.click(); p.wait_for_timeout(1000)
    d = dlg(p)
    if nueva is not None:
        d.get_by_label('Nueva fecha').fill(nueva)
    if motivo is not None:
        d.locator('textarea').fill(motivo)
    try:
        with p.expect_response(lambda r: 'reprogramaciones' in r.url and r.request.method in ('POST', 'PUT', 'PATCH'), timeout=8000) as ri:
            d.get_by_role('button', name=re.compile('Guardar')).click()
        r = ri.value; p.wait_for_timeout(1500)
        try:
            body = r.json()
        except Exception:
            body = r.text()[:200]
        return r.status, body
    except Exception as e:
        return 'sin petición', str(e)[:80]


@caso('CP-COL-08')
def cp_col08():
    R = Run('CP-COL-08'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    cid, NOM, nl, prs = colegio_programacion(R, ctx)
    hoy = A.hoy(); pa = FE.pa_actual(cid)
    pa_ini, pa_fin = A.fecha(pa['fecha_inicio']), A.fecha(pa['fecha_fin'])
    lunes = FE.clases_habituales(2, max(hoy + dt.timedelta(days=1), pa_ini), pa_fin, cid)
    lect = lambda d: A.es_lectivo(cid, d) and pa_ini <= d <= pa_fin  # noqa: E731
    obj = next((d for d in lunes if d.month == hoy.month and lect(d + dt.timedelta(days=3))), lunes[0] if lunes else None)
    if not obj:
        R.nota('No hay clases futuras del 2.º en el PA vigente: no se puede reprogramar en este momento del año.')
        R.save(checks=chk); n.close(); return
    jueves = obj + dt.timedelta(days=3)
    chk['fechas'] = {'clase del 2.º': A.iso(obj), 'jueves destino': A.iso(jueves)}
    login(p, sup_ui()); abrir_programacion(p, NOM)
    p.locator('main tbody tr').filter(has_text=FE.legible(obj)).filter(has_text='2').first.get_by_role('button', name='Reprogramar').click(); p.wait_for_timeout(1000)
    d = dlg(p); chk['modal'] = d.inner_text(); chk['botones'] = d.get_by_role('button').all_inner_texts()
    R.shot(p, f'Pasos 1-2: modal "Reprogramar clase": {chk["modal"][:400]}')
    d.get_by_label('Nueva fecha').fill(A.iso(jueves)); d.locator('textarea').fill('Actividad del colegio QA')
    try:
        with p.expect_response(lambda r: 'reprogramaciones' in r.url, timeout=8000) as ri:
            d.get_by_role('button', name='Guardar reprogramación').click()
        p.wait_for_timeout(1500); r = ri.value
        chk['guardar'] = (r.status, r.json() if r.status < 500 else None, toasts_txt(p))
    except Exception as e:
        chk['guardar'] = ('sin petición', str(e)[:80], toasts_txt(p))
    chk['filas'] = filas_prog(p)
    R.shot(p, f'Paso 3: {chk["guardar"][2]}; filas {[(r_[3] if len(r_) > 3 else r_, r_[4] if len(r_) > 4 else "", r_[5] if len(r_) > 5 else "") for r_ in chk["filas"]]}', full=True)
    idc = chk['guardar'][1].get('id_clase') if isinstance(chk['guardar'][1], dict) else None
    chk['historial_api'] = A.api('GET', f'/clases/{idc}/reprogramaciones', A.sup())[1] if idc else None
    chk['otras'] = [(c['fecha'], c['tipo']) for c in A.clases(cid, 2, pa_ini, pa_fin)][:20]
    R.consola(ctx, 'Pasos 3-5: respuesta, historial de la clase y demás clases del 2.º (en local, la base de datos)',
              [f'POST reprogramaciones → HTTP {chk["guardar"][0]}: {str(chk["guardar"][1])[:300]}',
               f'GET /api/clases/{idc}/reprogramaciones: {str(chk["historial_api"])[:600]}',
               f'Clases del 2.º en el PA (fecha | tipo): {chk["otras"]}'])
    # Paso 6: a una fecha del mes siguiente
    primero_sig = (hoy.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    ocupadas = set(lunes)
    destino = next((primero_sig + dt.timedelta(days=k) for k in range(0, 28)
                    if primero_sig + dt.timedelta(days=k) <= pa_fin and (primero_sig + dt.timedelta(days=k)).isoweekday() <= 5
                    and primero_sig + dt.timedelta(days=k) not in ocupadas and lect(primero_sig + dt.timedelta(days=k))), None)
    orig2 = next((d for d in lunes if d != obj and d.month == hoy.month), None)
    if destino and orig2:
        chk['traslado'] = (A.iso(orig2), A.iso(destino), reprog_ui(p, FE.legible(orig2), A.iso(destino), 'Traslado QA al mes siguiente'), toasts_txt(p))
        R.shot(p, f'Paso 6: {FE.legible(orig2)} → {FE.legible(destino)}: {chk["traslado"][2:]}', full=True)
        cerrar_dialogos(p)
    else:
        R.nota('Paso 6: el PA vigente termina este mes; no hay una fecha lectiva del mes siguiente en el mismo PA.')
    # Pasos 7-8
    fila = p.locator('main tbody tr').filter(has_text=FE.legible(jueves)).first
    chk['acciones_fila'] = fila.get_by_role('button').all_inner_texts()
    b = fila.get_by_role('button', name=re.compile('Ver reprogramaci'))
    if b.count():
        b.first.click(); p.wait_for_timeout(1000); d = dlg(p); chk['ver'] = (d.inner_text()[:500], d.get_by_role('button').all_inner_texts())
        R.shot(p, f'Paso 7: "Ver reprogramación": {chk["ver"][1]}')
        mb = d.get_by_role('button', name=re.compile('Modificar'))
        viernes = jueves + dt.timedelta(days=1)
        if mb.count() and lect(viernes):
            mb.first.click(); p.wait_for_timeout(1000); d = dlg(p)
            d.get_by_label('Nueva fecha').fill(A.iso(viernes)); d.locator('textarea').fill('Cambio QA de la reprogramación')
            try:
                with p.expect_response(lambda r: 'reprogramaciones' in r.url, timeout=8000) as ri:
                    d.get_by_role('button', name=re.compile('Guardar')).click()
                p.wait_for_timeout(1500); chk['modificar'] = (ri.value.status, toasts_txt(p))
            except Exception as e:
                chk['modificar'] = ('sin petición', str(e)[:80])
            cerrar_dialogos(p)
            f2 = p.locator('main tbody tr').filter(has_text=FE.legible(viernes)).first.get_by_role('button', name=re.compile('Ver reprogramaci'))
            if f2.count():
                f2.first.click(); p.wait_for_timeout(1000); chk['historial'] = dlg(p).inner_text()[:600]
            chk['historial_api_2'] = A.api('GET', f'/clases/{idc}/reprogramaciones', A.sup())[1] if idc else None
            R.shot(p, f'Paso 8: modificada a {FE.legible(viernes)}: {chk["modificar"]}; historial: {str(chk.get("historial"))[:250]}; API: {str(chk["historial_api_2"])[:250]}')
            cerrar_dialogos(p)
    else:
        R.shot(p, f'Paso 7: acciones de la fila reprogramada: {chk["acciones_fila"]}')
    # Paso 9: intentos inválidos
    inval = {}
    usadas = (obj, A.fecha(chk['traslado'][0]) if chk.get('traslado') else None)
    lun = [d for d in lunes if d not in usadas]
    base = next((d for d in lun if d.month == hoy.month), lun[0] if lun else None)

    def intento(clave, fecha_vig, nueva, motivo):
        antes = clases_mes(cid, pa_ini, pa_fin)
        fila = p.locator('main tbody tr').filter(has_text=fecha_vig).first
        bt = fila.get_by_role('button', name='Reprogramar')
        if not bt.count() or bt.first.is_disabled():
            inval[clave] = {'boton': 'deshabilitado' if bt.count() else 'no está', 'title': bt.first.get_attribute('title') if bt.count() else None}
            R.shot(p, f'Paso 9 · {clave}: {inval[clave]}'); return
        bt.first.click(); p.wait_for_timeout(800); d = dlg(p)
        if nueva:
            d.get_by_label('Nueva fecha').fill(nueva)
        if motivo:
            d.locator('textarea').fill(motivo)
        g = d.get_by_role('button', name='Guardar reprogramación'); res = None
        if g.is_enabled():
            try:
                with p.expect_response(lambda r: 'reprogramaciones' in r.url, timeout=5000) as ri:
                    g.click()
                res = ri.value.status
            except Exception:
                res = 'sin petición'
            p.wait_for_timeout(1200)
        dd = p.locator('[role=dialog]:visible')
        inval[clave] = {'guardar_habilitado': g.is_enabled() if dd.count() else None, 'http': res,
                        'mensajes': ([l for l in dd.inner_text().split('\n') if re.search(r'no |No |debe|Debe|Ingresa|ya |Ya |fuera|Selecciona|obligatori', l)] if dd.count() else []) + toasts_txt(p),
                        'sin_cambios': clases_mes(cid, pa_ini, pa_fin) == antes}
        R.shot(p, f'Paso 9 · {clave}: {inval[clave]}')
        cerrar_dialogos(p)
    if base:
        fb = FE.legible(base)
        pr_fecha = next((x['fecha_inicio'] for x in A.periodos(cid, 'PR') if A.fecha(x['fecha_inicio']) > hoy), None)
        otro_pa = next((A.fecha(x['fecha_inicio']) for x in A.periodos(cid) if A.fecha(x['fecha_inicio']) > pa_fin), None)
        if otro_pa:
            while otro_pa.isoweekday() > 5:
                otro_pa += dt.timedelta(days=1)
        if pr_fecha:
            intento('fecha del PR', fb, pr_fecha, 'PR QA')
        if nl and nl > hoy:
            intento('día no lectivo', fb, A.iso(nl + dt.timedelta(days=0)), 'No lectivo QA')
        if otro_pa:
            intento('otro PA', fb, A.iso(otro_pa), 'Otro PA QA')
        intento('misma fecha', fb, A.iso(base), 'Misma QA')
        otra = next((d for d in lun if d != base), None)
        if otra:
            intento('fecha con otra clase', fb, A.iso(otra), 'Choque QA')
        intento('sin motivo', fb, A.iso(base + dt.timedelta(days=1)), None)
    # clase con asistencias: el 3.º del colegio Norte del caso con la asistencia de hoy de Docente A
    X = D.X(); Fx = FE.ultima_clase(3, X, incluir_hoy=True); C = D.cuenta('docente-a')
    act = A.iniciar_actividad(C); s_as = put_asis(C, Fx, [(D.alumno('Ana Norte QA'), 'presente', None)], act); A.cerrar_abiertas(C)
    s_rep = A.api('POST', f'/colegios/{X}/clases/reprogramaciones', A.sup(), {'id_grado': A.id_grado(3), 'id_seccion': A.seccion(X, 3), 'fecha_original': A.iso(Fx),
                                                                             'fecha_nueva': A.iso(Fx + dt.timedelta(days=1)), 'motivo': 'Con asistencias QA'})
    inval['clase con asistencias (API)'] = {'asistencia': s_as, 'reprogramar': (s_rep[0], str(s_rep[1])[:200])}
    abrir_programacion(p, D.nombre_colegio('norte'))
    fx = p.locator('main tbody tr').filter(has_text=FE.legible(Fx)).first.get_by_role('button', name='Reprogramar')
    inval['clase con asistencias (UI)'] = {'boton': fx.count(), 'deshabilitado': fx.first.is_disabled() if fx.count() else None,
                                           'title': fx.first.get_attribute('title') if fx.count() else None}
    R.shot(p, f'Paso 9 · clase con asistencias ({FE.legible(Fx)}, colegio Norte): {inval["clase con asistencias (UI)"]}; API {inval["clase con asistencias (API)"]}')
    chk['invalidos'] = inval
    fin(R, chk, n, C)
