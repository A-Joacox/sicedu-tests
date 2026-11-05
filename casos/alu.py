"""Alumnos (CU014, CU015): CP-ALU-01 a CP-ALU-08, adaptados a QA.

- Docente: Docente A (3.º del colegio Norte del caso, con 55 alumnos activos y Extra12 inactivo).
  Supervisora en la interfaz: supervisor-2. El "colegio B" es el Sur del caso (5.º de Docente Retro).
- El intervalo de pertenencia que en local se leía en la base de datos se lee por la API
  (GET /alumnos/{id}: pertenece_desde y fecha_registro) y en el historial (GET /alumnos/{id}/historial).
- Las fechas (clase anterior, clase de hoy) salen del calendario del colegio del caso.
"""
import datetime as dt
import json
import re

from lib import api as A
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import caso
from lib.ui import BASE, Nav, Run, cerrar_dialogos, con_actividad, dlg, ir, login, logout, main_txt, toasts_txt, token_navegador

from casos._comun import crear_colegio, fin, hay_dialogo, hhmmss, sup_ui
from casos.asi import abrir_asis, put_asis
from casos.lec import Semanas, filas_put, tabla_post, version_fila
from casos.rub import rub_items, rub_put
from casos.rv import PA_ACT, rv_items, rv_put


def _c():
    return D.cuenta('docente-a')


def filas(p):
    return p.locator('main tbody tr')


def pie(p):
    m = re.search(r'Mostrando (\d+) a (\d+) de (\d+)', main_txt(p))
    return m.groups() if m else None


def abrir_alumnos(p):
    ir(p, 'Alumnos'); p.wait_for_timeout(1500)
    try:
        filas(p).first.wait_for(timeout=6000)
    except Exception:
        pass


def sel(p, i):
    """Filtros de Alumnos: 0 colegio, 1 grado, 2 ciclo, 3 subprograma, 4 estado."""
    return p.locator('main select').nth(i)


def filtrar(p):
    p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1500)


def buscar(p, texto):
    p.get_by_label('Buscar').fill(texto); filtrar(p)


def errores(p):
    if not hay_dialogo(p):
        return ['(el modal se cerró)']
    return re.findall(r'\n([^\n]*(?:obligatori|Selecciona|Ingresa|debe|posterior|anterior|No se pudo|fecha)[^\n]*)', '\n' + dlg(p).inner_text())


def form_alumno(d, nom, ape, colegio=None, grado=None, sec=None, prog=None, desde=None):
    d.get_by_label('Nombres').fill(nom); d.get_by_label('Apellidos').fill(ape)
    sl = d.locator('select')
    if colegio is None:
        sl.nth(0).select_option(index=1)
    else:
        sl.nth(0).select_option(label=colegio)
    d.page.wait_for_timeout(600)
    if grado:
        sl.nth(1).select_option(label=grado); d.page.wait_for_timeout(800)
    if sec:
        try:
            sl.nth(2).select_option(label=sec)
        except Exception:
            pass
    if prog:
        sl.nth(3).select_option(label=prog)
    if desde:
        d.get_by_label('Pertenece al grupo desde').fill(desde)


def pertenencia(aid):
    """Lo que en local salía de alumno_pertenencia, por la API."""
    s, r = A.api('GET', f'/alumnos/{aid}', A.sup())
    if s != 200:
        return {'http': s}
    return {'colegio': r['colegio']['nombre'], 'grado': r['grado']['nombre'], 'seccion': r['seccion']['nombre'], 'programa': r['programa']['nombre'],
            'ciclo': r['ciclo'], 'activo': r['activo'], 'pertenece_desde': r.get('pertenece_desde'), 'fecha_registro': r.get('fecha_registro')}


def historial(aid):
    s, r = A.api('GET', f'/alumnos/{aid}/historial', A.sup())
    return r if s == 200 else {'http': s}


def clase_anterior(grado=3, cid=None):
    """La clase habitual más reciente anterior a hoy (en el PA vigente o en el anterior)."""
    cid = cid or D.X(); hoy = A.hoy()
    fs = FE.clases_habituales(grado, hoy - dt.timedelta(days=60), hoy - dt.timedelta(days=1), cid)
    return fs[-1] if fs else None


def permiso_si_hace_falta(fecha, modulo='asistencias', etiqueta='docente-a', cid=None, grado=3):
    """Si la fecha cae en un PA ya culminado, otorga a la cuenta un permiso de corrección de ese PA."""
    cid = cid or D.X()
    per = A.periodo_de(cid, fecha)
    act = FE.pa_actual(cid)
    if act and per.get('id_periodo_academico') == act['id_periodo_academico']:
        return None
    return A.permiso(D.id_usuario(etiqueta), cid, grado, per['id_periodo_academico'], modulo, A.ahora() + dt.timedelta(days=2))[0]


def asis_de(fecha, nombre_parte, grado=3, cid=None, quien=None):
    cid = cid or D.X()
    s, r = A.api('GET', '/asistencias?' + A.q(id_colegio=cid, id_grado=A.id_grado(grado), id_seccion=A.seccion(cid, grado), fecha=A.iso(fecha)), quien or A.sup())
    if s != 200:
        return s, (r or {}).get('motivo') if isinstance(r, dict) else r
    return s, [(a['nombre'], a.get('estado'), a.get('inactivo')) for a in r.get('alumnos', []) if nombre_parte in a['nombre']]


# ── CP-ALU-01 ───────────────────────────────────────────────────────────────────────

@caso('CP-ALU-01')
def cp_alu01():
    R = Run('CP-ALU-01'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); X = D.X(); NX = D.nombre_colegio('norte')
    ina_nom = f'QA AUTO {hhmmss()} Inactivo'; ina = crear_colegio(ina_nom, {1: 1})
    A.crear_alumno('Ines', 'Colegio Inactivo QA', ina, 1, A.ALFA(), FE.pa(1, ina)['fecha_inicio'])
    A.api('PATCH', f'/colegios/{ina}/desactivar', A.sup())
    R.consola(ctx, 'Precondición (por la API)', [f'Docente A: 3.º de {NX} con 55 alumnos activos y Extra12 Rubrica QA inactivo desde hoy',
                                                f'Colegio inactivo {ina_nom} con la alumna Ines Colegio Inactivo QA'])
    A.cerrar_abiertas(C); login(p, C); abrir_alumnos(p); tk = token_navegador(p)
    api_doc = (A.api('GET', '/alumnos', tk)[1] or {}).get('total')
    chk['doc'] = (pie(p), filas(p).count(), sorted(set(r.split('\t')[1] for r in filas(p).all_inner_texts() if '\t' in r)))
    R.shot(p, f'Pasos 1-2: Docente: pie {chk["doc"][0]}, filas {chk["doc"][1]}, colegios en la tabla {chk["doc"][2]}; total por la API con su token: {api_doc}', full=True)
    sig = p.get_by_role('button', name='Siguiente')
    if sig.count() and sig.first.is_enabled():
        sig.first.click(); p.wait_for_timeout(1200); chk['pag2'] = (pie(p), filas(p).count())
        R.shot(p, f'Paso 2: página 2: {chk["pag2"]}', full=True)
    try:
        sel(p, 0).select_option(label=NX); sel(p, 3).select_option(label='Comprensión Lectora'); sel(p, 2).select_option(label='IV'); sel(p, 1).select_option(label='3.º')
    except Exception as e:
        chk['err_filtros'] = str(e)[:100]
    filtrar(p)
    api_comb = (A.api('GET', '/alumnos?' + A.q(id_colegio=X, id_programa=A.CL(), ciclo='IV', id_grado=A.id_grado(3)), tk)[1] or {}).get('total')
    chk['combinado'] = (pie(p), api_comb)
    R.shot(p, f'Paso 3: filtro combinado (Norte, Comprensión Lectora, IV, 3.º): {chk["combinado"][0]}; API {api_comb}')
    sel(p, 4).select_option(label='Inactivos'); filtrar(p)
    chk['inactivos'] = [r.split('\t')[0] for r in filas(p).all_inner_texts()]
    chk['ls'] = p.evaluate("JSON.stringify(Object.fromEntries(Object.entries(localStorage).filter(([k])=>k.includes('alumno'))))")
    R.shot(p, f'Pasos 3-4: estado Inactivo: {chk["inactivos"]}; Local Storage: {chk["ls"]}')
    sel(p, 4).select_option(label='Activos'); filtrar(p)
    lk = filas(p).first.locator('a'); chk['enlace'] = (lk.count(), lk.first.inner_text() if lk.count() else None)
    if lk.count():
        lk.first.click(); p.wait_for_timeout(1800)
    chk['enlace_url'] = p.url.replace(BASE, '')
    R.shot(p, f'Paso 5: el nombre ({chk["enlace"]}) abre {chk["enlace_url"]}')
    logout(p); p.wait_for_timeout(800); chk['ls_logout'] = p.evaluate('JSON.stringify(localStorage)')
    R.consola(ctx, 'Paso 6: Local Storage después de cerrar sesión', [chk['ls_logout']])
    S = sup_ui(); login(p, S); abrir_alumnos(p); tks = token_navegador(p)
    buscar(p, 'Colegio Inactivo QA')
    chk['sup'] = (filas(p).count(), main_txt(p)[-160:].replace('\n', ' '), (A.api('GET', '/alumnos?' + A.q(q='Colegio Inactivo QA'), tks)[1] or {}).get('total'))
    p.get_by_role('button', name='Limpiar').click(); p.wait_for_timeout(1500)
    chk['sup_total'] = (pie(p), (A.api('GET', '/alumnos', tks)[1] or {}).get('total'), sorted(set(r.split('\t')[1] for r in filas(p).all_inner_texts() if '\t' in r))[:8])
    R.shot(p, f'Paso 7: Supervisora: {chk["sup_total"][0]} (API {chk["sup_total"][1]}); colegios en la página {chk["sup_total"][2]}; '
              f'alumna del colegio inactivo: filas {chk["sup"][0]}, API {chk["sup"][2]}')
    fin(R, chk, n, C)


# ── CP-ALU-02 ───────────────────────────────────────────────────────────────────────

@caso('CP-ALU-02')
def cp_alu02():
    R = Run('CP-ALU-02'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); X = D.X(); NX = D.nombre_colegio('norte')
    hoy = A.hoy(); manana = A.iso(hoy + dt.timedelta(days=1)); hace2 = A.iso(hoy - dt.timedelta(days=14))
    con_actividad(p, C); abrir_alumnos(p)
    p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(800); d = dlg(p)
    f = d.get_by_label('Pertenece al grupo desde'); t = d.inner_text()
    chk['campo'] = (f.input_value() if f.count() else None, t[t.upper().find('PERTENECE'):][:200])
    R.shot(p, f'Pasos 1-2: "Pertenece al grupo desde": {chk["campo"]}')
    form_alumno(d, 'Futuro', f'Fecha QA {hhmmss()}', NX, '3.º', 'Única', 'Comprensión Lectora', manana)
    d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1300)
    chk['futura'] = (hay_dialogo(p), errores(p) + toasts_txt(p), d.get_by_label('Nombres').input_value() if hay_dialogo(p) else None)
    R.shot(p, f'Paso 3: fecha futura ({manana}): {chk["futura"]}')
    ape = f'Comprension QA {hhmmss()}'
    d.get_by_label('Nombres').fill('Nuevo'); d.get_by_label('Apellidos').fill(ape); d.get_by_label('Pertenece al grupo desde').fill(hace2)
    d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1800); chk['crear'] = toasts_txt(p)
    buscar(p, ape); chk['fila'] = filas(p).first.inner_text().replace('\t', ' | ') if filas(p).count() else None
    lst = (A.api('GET', '/alumnos?' + A.q(q=ape), A.sup())[1] or {}).get('items', [])
    aid = lst[0]['id'] if lst else None
    chk['api'] = pertenencia(aid) if aid else None
    R.shot(p, f'Paso 4: Comprensión Lectora, 3.º, desde {hace2}: {chk["crear"]}; fila {str(chk["fila"])[:140]}; ciclo {chk["api"] and chk["api"]["ciclo"]}')
    s, r = A.api('POST', '/alumnos', A.sup(), {'nombres': 'Nuevo', 'apellidos': f'Alfabetizacion QA {hhmmss()}', 'id_colegio': X, 'id_grado': A.id_grado(4),
                                                'id_programa': A.ALFA(), 'pertenece_desde': A.iso(hoy)})
    chk['alfa4'] = (s, (r or {}).get('ciclo'))
    R.consola(ctx, 'Paso 5: alumno de Alfabetización de 4.º (lo crea la Supervisora por la API: Docente A solo tiene el 3.º)', [f'POST /api/alumnos → HTTP {s}; ciclo = {chk["alfa4"][1]}'])
    hist = historial(aid) if aid else None
    R.consola(ctx, 'Paso 6: pertenencia por la API (en local, la tabla alumno_pertenencia) e historial', [str(chk['api']), json.dumps(hist, ensure_ascii=False)[:600]])
    F = clase_anterior()
    if F and A.iso(F) >= hace2:
        abrir_asis(p, F, sub='Todos')
        chk['en_lista'] = ('Nuevo' in main_txt(p) and ape.split(' ')[0] in main_txt(p), asis_de(F, ape.split(' ')[0]))
        R.shot(p, f'Paso 7: Asistencias, clase del {FE.legible(F)} del 3.º: el alumno nuevo aparece = {chk["en_lista"]}', full=True)
    else:
        R.nota(f'Paso 7: no hay una clase del 3.º entre {FE.legible(A.fecha(hace2))} y ayer ({FE.legible(F)}); no se puede ver al alumno en una clase anterior.')
    fin(R, chk, n, C)


# ── CP-ALU-03 ───────────────────────────────────────────────────────────────────────

@caso('CP-ALU-03')
def cp_alu03():
    R = Run('CP-ALU-03'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); X = D.X()
    ape = f'Grupo QA {hhmmss()}'
    aid = A.crear_alumno('Edita', ape, X, 3, A.CL(), FE.pa(1, X)['fecha_inicio'])
    F = clase_anterior(); perm = permiso_si_hace_falta(F)
    con_actividad(p, C); tk = token_navegador(p); act = A.actividad_en_curso(tk)
    chk['asis_previa'] = (A.iso(F), perm, put_asis(tk, F, [(aid, 'presente', None)], act))
    R.consola(ctx, 'Precondición', [f'Alumno Edita {ape} (3.º, Comprensión Lectora) con asistencia guardada en la clase del {FE.legible(F)} → {chk["asis_previa"][2]}'
                                   + (f' (permiso de corrección del PA de esa fecha → HTTP {perm})' if perm else '')])
    abrir_alumnos(p); buscar(p, ape)
    filas(p).first.get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(800); d = dlg(p)
    ape2 = ape.replace('Grupo', 'Grupo Cambiado')
    d.get_by_label('Apellidos').fill(ape2); chk['campo_solo_apellidos'] = 'Cambio de grupo desde' in d.inner_text()
    d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1500)
    chk['apellidos'] = (toasts_txt(p), pertenencia(aid))
    R.shot(p, f'Paso 1: solo apellidos: "Cambio de grupo desde" visible = {chk["campo_solo_apellidos"]}; {chk["apellidos"]}')
    buscar(p, ape2)
    filas(p).first.get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(800); d = dlg(p)
    sl = d.locator('select'); chk['grados_editables'] = sl.nth(1).inner_text().replace('\n', '/')
    opc = [o for o in chk['grados_editables'].split('/') if o not in ('Seleccione', '3.º')]
    if opc:
        sl.nth(1).select_option(label=opc[0])
    else:
        sl.nth(3).select_option(label='Alfabetización')
    p.wait_for_timeout(800); chk['campo_cambio'] = [l for l in d.inner_text().split('\n') if 'grupo' in l.lower()][:4]
    R.shot(p, f'Paso 2: al cambiar el grupo (grados del Docente: {chk["grados_editables"]}): {chk["campo_cambio"]}')
    cerrar_dialogos(p)
    s1, r1 = A.api('PATCH', f'/alumnos/{aid}', A.sup(), {'id_grado': A.id_grado(4), 'id_seccion': A.seccion(X, 4), 'cambio_grupo_desde': A.iso(F - dt.timedelta(days=1))})
    s2, r2 = A.api('PATCH', f'/alumnos/{aid}', A.sup(), {'id_grado': A.id_grado(4), 'id_seccion': A.seccion(X, 4), 'cambio_grupo_desde': A.iso(F + dt.timedelta(days=1))})
    chk['api'] = ((s1, r1), (s2, r2)); chk['pertenencia'] = pertenencia(aid)
    chk['asis_original'] = asis_de(F, 'Edita')
    hist = historial(aid)
    R.consola(ctx, 'Pasos 3-6: cambio de 3.º a 4.º con fecha efectiva (por la API, como lo envía el formulario de la Supervisora: el Docente solo tiene el 3.º)',
              [f'Desde {FE.legible(F - dt.timedelta(days=1))} (antes de la lista del {FE.legible(F)}) → HTTP {s1} {json.dumps(r1, ensure_ascii=False)[:250]}',
               f'Desde {FE.legible(F + dt.timedelta(days=1))} (después) → HTTP {s2} {json.dumps(r2, ensure_ascii=False)[:250]}',
               f'Alumno ahora (API): {chk["pertenencia"]}', f'Asistencia del {FE.legible(F)} en el 3.º (nombre | estado | inactivo): {chk["asis_original"]}',
               f'Historial: {json.dumps(hist, ensure_ascii=False)[:700]}'])
    fin(R, chk, n, C)


# ── CP-ALU-04 ───────────────────────────────────────────────────────────────────────

@caso('CP-ALU-04')
def cp_alu04():
    R = Run('CP-ALU-04'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); X = D.X()
    ape = f'Switch QA {hhmmss()}'
    aid = A.crear_alumno('Baja', ape, X, 3, A.CL(), FE.pa(1, X)['fecha_inicio'])
    F = clase_anterior(); perm = permiso_si_hace_falta(F); H = FE.ultima_clase(3, X, incluir_hoy=True)
    con_actividad(p, C); tk = token_navegador(p); act = A.actividad_en_curso(tk)
    chk['asis_previa'] = put_asis(tk, F, [(aid, 'presente', None)], act)
    R.consola(ctx, 'Precondición', [f'Alumno Baja {ape} con asistencia en la clase del {FE.legible(F)} → {chk["asis_previa"]}' + (f'; permiso de corrección → HTTP {perm}' if perm else ''),
                                   f'Clase de hoy del 3.º: {FE.legible(H)} (sin lista guardada todavía)'])
    abrir_alumnos(p); buscar(p, ape)
    filas(p).first.get_by_role('button', name=re.compile('^Inactivar')).first.click(); p.wait_for_timeout(800); d = dlg(p)
    chk['modal'] = (d.inner_text()[:300], d.locator('input[type=date]').first.input_value())
    R.shot(p, f'Paso 1: modal de inactivación: {chk["modal"]}')
    d.locator('input[type=date]').first.fill(A.iso(A.hoy() + dt.timedelta(days=2))); d.get_by_role('button', name='Inactivar').click(); p.wait_for_timeout(1200)
    chk['futura'] = (hay_dialogo(p), errores(p) + toasts_txt(p), pertenencia(aid))
    R.shot(p, f'Paso 2: fecha futura: {chk["futura"]}')
    if not hay_dialogo(p):
        if chk['futura'][2].get('activo') is False:
            A.api('PATCH', f'/alumnos/{aid}/activar', A.sup(), {'aplicar_desde': A.iso(A.hoy())})
        filtrar(p)
        filas(p).first.get_by_role('button', name=re.compile('Inactivar')).first.click(); p.wait_for_timeout(800); d = dlg(p)
    d.locator('input[type=date]').first.fill(A.iso(A.hoy())); d.get_by_role('button', name='Inactivar').click(); p.wait_for_timeout(1500)
    chk['hoy'] = toasts_txt(p); chk['api'] = pertenencia(aid); hist = historial(aid)
    R.shot(p, f'Paso 3: inactivado desde hoy: {chk["hoy"]}')
    R.consola(ctx, 'Paso 3: el alumno por la API (en local, la base de datos) e historial', [str(chk['api']), json.dumps(hist, ensure_ascii=False)[:600]])
    chk['lista_anterior'] = asis_de(F, 'Baja'); chk['lista_hoy'] = asis_de(H, 'Baja') if H else None
    s5, r5 = A.api('GET', f'/alumnos/{aid}/resumen', A.sup())
    abrir_asis(p, H, sub='Todos'); chk['ui_hoy'] = 'Baja' in main_txt(p) and ape.split(' ')[0] in main_txt(p)
    R.shot(p, f'Paso 4: Asistencias, clase de hoy ({FE.legible(H)}): el alumno aparece = {chk["ui_hoy"]}', full=True)
    abrir_asis(p, F, sub='Todos'); chk['ui_anterior'] = [l for l in main_txt(p).split('\n') if 'Baja' in l or 'Inactivo' in l][:4]
    R.shot(p, f'Paso 4: clase anterior ({FE.legible(F)}): {chk["ui_anterior"]}', full=True)
    R.consola(ctx, 'Pasos 4-5: listas y registros anteriores (por la API)',
              [f'Lista del {FE.legible(F)} (nombre | estado | inactivo): {chk["lista_anterior"]}', f'Lista de hoy {FE.legible(H)}: {chk["lista_hoy"]}',
               f'Resumen del alumno → HTTP {s5} {json.dumps(r5, ensure_ascii=False)[:400]}'])
    abrir_alumnos(p); buscar(p, ape); sel(p, 4).select_option(label='Inactivos'); filtrar(p)
    b = filas(p).first.get_by_role('button', name=re.compile('Activar|Reactivar')); chk['boton_activar'] = b.count()
    if b.count():
        b.first.click(); p.wait_for_timeout(800); d = dlg(p); chk['modal_activar'] = d.inner_text()[:300]
        d.get_by_role('button', name=re.compile('Activar|Reactivar')).last.click(); p.wait_for_timeout(1500); chk['activar'] = toasts_txt(p)
    chk['api2'] = pertenencia(aid); chk['lista_hoy_tras'] = asis_de(H, 'Baja') if H else None
    R.shot(p, f'Paso 6: reactivación: {chk.get("modal_activar", "")[:150]} → {chk.get("activar")}')
    R.consola(ctx, 'Paso 6: tras reactivar (API)', [str(chk['api2']), f'Lista de hoy: {chk["lista_hoy_tras"]}', json.dumps(historial(aid), ensure_ascii=False)[:500]])
    fin(R, chk, n, C)


# ── CP-ALU-05 ───────────────────────────────────────────────────────────────────────

@caso('CP-ALU-05')
def cp_alu05():
    R = Run('CP-ALU-05'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    NX, NY = D.nombre_colegio('norte'), D.nombre_colegio('sur')
    ina_nom = f'QA AUTO {hhmmss()} Inactivo'; ina = crear_colegio(ina_nom, {1: 1}); A.api('PATCH', f'/colegios/{ina}/desactivar', A.sup())
    login(p, sup_ui()); abrir_alumnos(p); p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(800); d = dlg(p)
    ops = d.locator('select').first.inner_text().split('\n'); chk['colegios'] = (len(ops) - 1, ina_nom in ops, NX in ops, NY in ops)
    R.shot(p, f'Paso 1: selector Colegio con {chk["colegios"][0]} colegios; incluye el inactivo = {chk["colegios"][1]}; Norte {chk["colegios"][2]}; Sur {chk["colegios"][3]}')
    ape = f'Colegios QA {hhmmss()}'
    form_alumno(d, 'Rota', ape, NX, '3.º', 'Única', 'Comprensión Lectora', A.iso(A.hoy()))
    d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1800); chk['crear'] = toasts_txt(p)
    lst = (A.api('GET', '/alumnos?' + A.q(q=ape), A.sup())[1] or {}).get('items', []); aid = lst[0]['id'] if lst else None
    R.shot(p, f'Paso 2: alumno creado en el colegio Norte sin actividad: {chk["crear"]}')
    buscar(p, ape)
    filas(p).first.get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(800); d = dlg(p)
    sl = d.locator('select'); sl.nth(0).select_option(label=NY); p.wait_for_timeout(800); sl.nth(1).select_option(label='5.º'); p.wait_for_timeout(800)
    try:
        sl.nth(2).select_option(label='Única')
    except Exception:
        pass
    try:
        sl.nth(3).select_option(label='Comprensión Lectora')
    except Exception:
        pass
    f = d.get_by_label(re.compile('Cambi[oa] de grupo|Fecha efectiva', re.I))
    if f.count():
        f.first.fill(A.iso(A.hoy()))
    d.get_by_role('button', name='Guardar').click(); p.wait_for_timeout(1800)
    chk['mover'] = (toasts_txt(p), hay_dialogo(p), errores(p) if hay_dialogo(p) else [], pertenencia(aid) if aid else None)
    R.shot(p, f'Paso 3: cambio al colegio Sur (5.º): {chk["mover"][:3]}')
    cerrar_dialogos(p)
    chk['hist'] = historial(aid) if aid else None
    R.consola(ctx, 'Paso 4: historial del alumno', [json.dumps(chk['hist'], ensure_ascii=False)[:900]])
    vistos = {}
    for et in ['docente-a', 'retro']:
        r = A.api('GET', '/alumnos?' + A.q(q=ape), D.cuenta(et))[1] or {}
        vistos[et] = [x['nombres'] + ' ' + x['apellidos'] for x in r.get('items', [])]
    chk['docentes'] = vistos
    R.consola(ctx, 'Paso 5: qué ve cada Docente (GET /api/alumnos con su token)', [f'Docente A (colegio Norte): {vistos["docente-a"]}', f'Docente Retro (colegio Sur, 5.º): {vistos["retro"]}'])
    abrir_alumnos(p)
    chk['masiva'] = [b for b in p.locator('main').get_by_role('button').all_inner_texts() if re.search('Import|Carga|Excel|CSV', b, re.I)]
    R.shot(p, f'Paso 6: botones de importación o carga masiva: {chk["masiva"]}')
    fin(R, chk, n)


# ── CP-ALU-06 ───────────────────────────────────────────────────────────────────────

@caso('CP-ALU-06')
def cp_alu06():
    R = Run('CP-ALU-06'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    con_actividad(p, C); abrir_alumnos(p); ctx.set_offline(True); p.wait_for_timeout(1200)
    chk['texto'] = main_txt(p)[:300]
    ag = p.get_by_role('button', name='Agregar')
    chk['controles'] = {'agregar': ag.first.is_disabled() if ag.count() else 'no está',
                        'editar': filas(p).first.get_by_role('button', name=re.compile('^Editar')).first.is_disabled() if filas(p).count() else 'no está',
                        'switch': filas(p).first.get_by_role('button', name=re.compile('Inactivar')).first.is_disabled() if filas(p).count() else 'no está'}
    if ag.count():
        try:
            ag.first.hover(); p.wait_for_timeout(600)
        except Exception:
            pass
    aviso = 'Acción no disponible sin conexión. Conéctate a internet para gestionar estudiantes.'
    chk['aviso'] = aviso in p.locator('body').inner_text() or any('Acción no disponible' in x for x in p.locator('[role=tooltip]').all_inner_texts())
    R.shot(p, f'Pasos 1-3: sin conexión: controles deshabilitados {chk["controles"]}; aviso de CU014 = {chk["aviso"]}')
    try:
        sel(p, 4).select_option(label='Todos'); filtrar(p); chk['filtro'] = pie(p)
        sig = p.get_by_role('button', name='Siguiente')
        if sig.count() and sig.first.is_enabled():
            sig.first.click(); p.wait_for_timeout(1000)
        chk['pagina'] = pie(p)
    except Exception as e:
        chk['filtro_err'] = str(e)[:100]
    R.shot(p, f'Paso 4: filtro y paginación sin conexión: {chk.get("filtro")} → {chk.get("pagina")}')
    lk = filas(p).first.locator('a')
    if lk.count():
        lk.first.click(); p.wait_for_timeout(2000)
    chk['detalle'] = (p.url.replace(BASE, ''), main_txt(p)[:250])
    tabs = p.get_by_role('tab').all_inner_texts(); chk['pestanas'] = tabs
    h = p.get_by_role('tab', name='Historial')
    if h.count():
        h.first.click(); p.wait_for_timeout(1200)
    chk['historial_offline'] = [l for l in main_txt(p).split('\n') if 'conexión' in l.lower() or 'historial' in l.lower()][:3]
    R.shot(p, f'Pasos 4 y 6: detalle sin conexión {chk["detalle"][0]}; pestañas {tabs}; Historial: {chk["historial_offline"]}', full=True)
    ctx.set_offline(False); abrir_alumnos(p); chk['online'] = p.get_by_role('button', name='Agregar').first.is_enabled()
    R.shot(p, f'Paso 5: con conexión, "Agregar" habilitado = {chk["online"]}')
    fin(R, chk, n, C)


# ── CP-ALU-07 ───────────────────────────────────────────────────────────────────────

@caso('CP-ALU-07')
def cp_alu07():
    R = Run('CP-ALU-07'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    otro = D.alumno('Kira Sur QA')
    con_actividad(p, C); abrir_alumnos(p)
    chk['filtro_colegios'] = sel(p, 0).evaluate("s=>[...s.options].map(o=>o.text)")
    p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(1000)
    chk['form_colegios'] = dlg(p).locator('select').first.evaluate("s=>[...s.options].map(o=>o.text)") if hay_dialogo(p) else None
    R.shot(p, f'Paso 1: filtro {chk["filtro_colegios"]}; formulario {chk["form_colegios"]}'); cerrar_dialogos(p)
    p.goto(BASE + f'/estudiantes/{otro}'); p.wait_for_timeout(2500)
    chk['detalle'] = (p.url.replace(BASE, ''), p.locator('body').inner_text()[:250])
    R.shot(p, f'Paso 2: /estudiantes/{otro} (Kira, colegio Sur): {chk["detalle"]}')
    tk = token_navegador(p); antes = pertenencia(otro)
    chk['api'] = {'GET': A.api('GET', f'/alumnos/{otro}', tk), 'PATCH': A.api('PATCH', f'/alumnos/{otro}', tk, {'nombres': 'Cambiado QA'}),
                  'desactivar': A.api('PATCH', f'/alumnos/{otro}/desactivar', tk, {'aplicar_desde': A.iso(A.hoy())})}
    chk['sin_cambios'] = pertenencia(otro) == antes
    R.consola(ctx, 'Pasos 3-4: peticiones con el token de Docente A y el alumno según la API',
              [f'Alumna {otro} (Kira Sur QA, colegio Sur)'] + [f'{k}: HTTP {v[0]} {json.dumps(v[1], ensure_ascii=False)[:200]}' for k, v in chk['api'].items()]
              + [f'Sin cambios (GET /api/alumnos/{otro} como Supervisora): {chk["sin_cambios"]}'])
    fin(R, chk, n, C)


# ── CP-ALU-08 ───────────────────────────────────────────────────────────────────────

def _registros(cuenta, aid, grado, cid, letra, prog, otros):
    """Asistencias (listas completas de las clases del PA vigente y del anterior, una incompleta), rúbrica del mes,
    una fila de lectura y el Nivel colocado del PA vigente."""
    out = {}
    A.cerrar_abiertas(cuenta); act = A.iniciar_actividad(cuenta)
    pa_ant = FE.pa_anterior(cid); clases = []
    if pa_ant:
        et = {'docente-a': 'docente-a', 'rv-uno': 'rv-uno', 'retro': 'retro'}[cuenta_etiqueta(cuenta)]
        out['permiso'] = A.permiso(D.id_usuario(et), cid, grado, pa_ant['id_periodo_academico'], 'asistencias', A.ahora() + dt.timedelta(days=2))[0]
        clases += FE.clases_del_pa(grado, pa_ant['numero'], cid)[-8:]
    clases += FE.clases_habituales(grado, FE.pa_actual(cid)['fecha_inicio'], A.hoy() - dt.timedelta(days=1), cid)
    estados = (['presente'] * 5 + ['tardanza'] * 2 + ['ausente'] * 3) * 3
    res = []
    for f, e in zip(clases, estados):
        res.append(put_asis(cuenta, f, [(aid, e, None)] + [(o, 'presente', None) for o in otros], act, grado=grado, colegio=cid)[0])
    H = FE.ultima_clase(grado, cid, incluir_hoy=True)
    out['incompleta'] = (A.iso(H), put_asis(cuenta, H, [(aid, 'presente', None)], act, grado=grado, colegio=cid)[0]) if H and H not in clases else None
    out['asistencias'] = (len(clases), res)
    out['rv'] = rv_put(cuenta, rv_items([(aid, PA_ACT(cid), {'id_nivel_colocado': A.niveles_rk()[letra]})], act, grado=grado, prog=prog, cid=cid))
    out['rubrica'] = rub_put(cuenta, rub_items([(aid, 3, 2)], act, grado=grado, prog=prog, cid=cid))
    S = Semanas(grado, cid)
    if S.ACT:
        s, t = tabla_post(cuenta, act, S.ACT, S.mes_act, grado=grado, prog=prog, colegio=cid)
        out['lectura'] = (s, filas_put(cuenta, t['id'], act, [(aid, version_fila(cuenta, aid, S.ACT, S.mes_act, prog=prog, colegio=cid), {'cantidad_lsl': 3})]) if s == 201 else t)
    A.cerrar_abiertas(cuenta)
    return out


def cuenta_etiqueta(cuenta):
    for et in ('docente-a', 'rv-uno', 'retro'):
        if cuenta.correo == D.cuenta(et).correo:
            return et
    return 'docente-a'


def _tabs(p):
    return [t.strip() for t in p.get_by_role('tab').all_inner_texts()]


@caso('CP-ALU-08')
def cp_alu08():
    R = Run('CP-ALU-08'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); X, Y = D.X(), D.Y()
    desde = FE.pa(1, X)['fecha_inicio']; suf = hhmmss()
    a3 = A.crear_alumno('Detalle', f'Tercero QA {suf}', X, 3, A.CL(), desde)
    a2 = A.crear_alumno('Detalle', f'Segundo QA {suf}', X, 2, A.CL(), desde)
    a5 = A.crear_alumno('Detalle', f'Quinto QA {suf}', Y, 5, A.CL(), desde)
    vacio = A.crear_alumno('Sin', f'Registros QA {suf}', X, 3, A.CL(), A.iso(A.hoy()))
    # Las listas completas incluyen a Extra12, que perteneció al grupo hasta ayer (hoy está inactivo).
    otros3 = [a['id'] for a in A.alumnos(X, 3) + A.alumnos(X, 3, activo=False) if a['id'] not in (a3, vacio)]
    otros2 = [a['id'] for a in A.alumnos(X, 2) if a['id'] != a2]
    otros5 = [a['id'] for a in A.alumnos(Y, 5) if a['id'] != a5]
    chk['prep'] = {'3.º H': _registros(C, a3, 3, X, 'H', A.CL(), otros3),
                   '2.º A': _registros(D.cuenta('rv-uno'), a2, 2, X, 'A', A.CL(), otros2),
                   '5.º R': _registros(D.cuenta('retro'), a5, 5, Y, 'R', A.CL(), otros5)}
    A.api('PATCH', f'/alumnos/{a3}', A.sup(), {'nombres': 'Detalle José'})
    R.consola(ctx, 'Precondición (por la API): tres alumnos con registros y uno sin registros',
              [f'{k}: {json.dumps(v, ensure_ascii=False, default=str)[:420]}' for k, v in chk['prep'].items()] +
              ['Detalle Tercero: se le cambió el nombre (queda un evento en su historial).', f'Sin Registros QA {suf}: alumno nuevo de hoy, sin registros.'])
    login(p, C); p.goto(BASE + f'/estudiantes/{a3}'); p.wait_for_timeout(2500)
    t = main_txt(p); chk['cabecera'] = t[:250]; chk['pestanas'] = _tabs(p)
    R.shot(p, f'Pasos 1-2: detalle de Detalle José Tercero (3.º, nivel H): pestañas {chk["pestanas"]}', full=True)
    chk['api_resumen'] = A.api('GET', f'/alumnos/{a3}/resumen', A.sup())[1]
    info = p.get_by_role('button', name=re.compile('Qué clases incluye|información', re.I))
    if info.count():
        try:
            info.first.hover(); p.wait_for_timeout(700)
        except Exception:
            pass
    chk['tooltip'] = p.locator('[role=tooltip]').all_inner_texts() + [x for x in p.locator('body').inner_text().split('\n') if 'listas de asistencia completas' in x]
    chk['texto_asistencia'] = [x for x in t.split('\n') if 'clases contabilizadas' in x or '%' in x][:3]
    R.shot(p, f'Pasos 3-6: resumen {json.dumps(chk["api_resumen"], ensure_ascii=False)[:300]}; asistencia {chk["texto_asistencia"]}; ayuda {chk["tooltip"]}')
    for nombre in ['Registro de Vuelo', 'Rúbrica', 'Seguimiento de Lectura', 'Historial']:
        b = p.get_by_role('tab', name=nombre)
        if b.count():
            b.first.click(); p.wait_for_timeout(1500)
        chk['tab_' + nombre] = main_txt(p)[:400]
        chk['filas_' + nombre] = filas(p).count()
        R.shot(p, f'Pasos 7-8: pestaña {nombre}: {chk["filas_" + nombre]} filas', full=True)
        if nombre == 'Registro de Vuelo':
            chk['svg_grafica'] = p.locator('main svg').count()
            chk['editable'] = p.locator('main select, main input:not([type=hidden])').count()
            fila = filas(p).first
            if fila.count():
                fila.click(); p.wait_for_timeout(2500)
                chk['rv_fila'] = (p.url.replace(BASE, ''), [s.evaluate("s=>s.selectedIndex>=0?s.options[s.selectedIndex].text:''") for s in p.locator('main select').all()][:6])
                R.shot(p, f'Paso 7: la fila abre {chk["rv_fila"]}')
                if '/estudiantes/' not in p.url:
                    p.go_back(); p.wait_for_timeout(2000)
    for et, aid, nom in [('rv-uno', a2, '2.º, nivel A'), ('retro', a5, '5.º, nivel R')]:
        p2 = n.ctx().new_page(); login(p2, D.cuenta(et)); p2.goto(BASE + f'/estudiantes/{aid}'); p2.wait_for_timeout(2500)
        chk[f'resumen_{et}'] = (A.api('GET', f'/alumnos/{aid}/resumen', A.sup())[1], main_txt(p2)[:200])
        R.shot(p2, f'Paso 3: {nom}: resumen {json.dumps(chk[f"resumen_{et}"][0], ensure_ascii=False)[:300]}', full=True)
    p.goto(BASE + f'/estudiantes/{vacio}'); p.wait_for_timeout(2500); t = main_txt(p)
    chk['vacio'] = {'sin_evaluar': 'Sin evaluar' in t, 'sin_asistencia': 'Sin datos de asistencia' in t, 'api': A.api('GET', f'/alumnos/{vacio}/resumen', A.sup())[1]}
    R.shot(p, f'Paso 9: alumno sin registros: {chk["vacio"]}', full=True)
    for nombre in ['Registro de Vuelo', 'Rúbrica', 'Seguimiento de Lectura']:
        b = p.get_by_role('tab', name=nombre)
        if b.count():
            b.first.click(); p.wait_for_timeout(1200)
        chk['vacio_' + nombre] = 'No hay registros recientes' in main_txt(p)
    R.shot(p, f'Paso 9: mini-grillas vacías ("No hay registros recientes"): {[chk["vacio_" + x] for x in ["Registro de Vuelo", "Rúbrica", "Seguimiento de Lectura"]]}', full=True)
    fin(R, chk, n, C, D.cuenta('rv-uno'), D.cuenta('retro'))
