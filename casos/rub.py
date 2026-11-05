"""Rúbrica (CU029, CU030): CP-RUB-01 a CP-RUB-09, adaptados a QA.

El mes de trabajo es el mes actual (en local era octubre). Su PA sale de GET /rubricas (regla R1);
Docente A tiene permisos de Rúbrica y Registro de Vuelo para los PA ya culminados, como en local.
"""
import datetime as dt
import json
import re

from lib import api as A
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import caso
from lib.ui import (BASE, Nav, Run, cerrar_dialogos, cola_idb, con_actividad, filtros_ui, fila, idb_todo, ir, login, opciones, pie,
                    poner, sel_txt, textos, toasts_txt, token_navegador)
from casos.asi import _c, act_de, nueva_act, sup_ui, NX


# ── Mes y periodos ──────────────────────────────────────────────────────────────────

def mes_actual():
    return A.hoy().month


def mes_futuro():
    return mes_actual() % 12 + 1


def pa_de_mes(mes, cid=None, grado=3, prog=None):
    x = cid or D.X()
    s, r = A.api('GET', '/rubricas?' + A.q(id_colegio=x, id_grado=A.id_grado(grado), id_seccion=A.seccion(x, grado), id_programa=prog or A.CL(),
                                          id_anio_escolar=A.anio(), mes=mes), A.sup())
    if s != 200:
        return None
    ids = {p['id_periodo_academico']: p['numero'] for p in A.periodos(x)}
    return ids.get(r.get('id_periodo_academico'))


def meses_de_pa(numero, cid=None):
    """Meses cuya rúbrica pertenece al PA indicado (regla R1), hasta el mes actual."""
    return [m for m in range(3, mes_actual() + 1) if pa_de_mes(m, cid) == numero]


def niv(letra):
    return A.niveles_rk()[letra]


# ── Ayudas de Rúbrica ───────────────────────────────────────────────────────────────

def rub_items(lst, act, grado=3, prog=None, mes=None, cid=None):
    x = cid or D.X(); sec = A.seccion(x, grado); out = []
    for aid, f, c in lst:
        it = {'id_operacion': A.uid(), 'id_actividad': act, 'id_alumno': aid, 'id_colegio': x, 'id_grado': A.id_grado(grado), 'id_seccion': sec,
              'id_programa': prog or A.CL(), 'id_anio_escolar': A.anio(), 'mes': mes or mes_actual()}
        if f != '-':
            it['fluidez'] = f
        if c != '-':
            it['comprension'] = c
        out.append(it)
    return out


def rub_put(quien, items):
    s, r = A.api('PUT', '/rubricas', quien, items)
    return s, ([(x.get('estado'), x.get('motivo'), (x.get('registro') or {}).get('resultado_decimas')) for x in r] if isinstance(r, list) else r)


def rub_get(quien, grado=3, prog=None, mes=None, cid=None, page=None):
    x = cid or D.X()
    return A.api('GET', '/rubricas?' + A.q(id_colegio=x, id_programa=prog or A.CL(), id_grado=A.id_grado(grado), id_seccion=A.seccion(x, grado),
                                          id_anio_escolar=A.anio(), mes=mes or mes_actual(), page=page), quien)


def rub_de(nombre, mes=None, prog=None, cid=None, grado=3):
    """Evaluación de un alumno según la API: (fluidez, comprensión, estado, resultado, versión)."""
    pagina = 1
    while True:
        s, r = rub_get(A.sup(), grado, prog, mes, cid, page=pagina)
        if s != 200:
            return s
        for it in r.get('items', []):
            if it['nombre'].startswith(nombre):
                return (it.get('fluidez'), it.get('comprension'), it.get('estado'), it.get('resultado_decimas'), it.get('version'))
        if pagina >= (r.get('total_pages') or 1):
            return None
        pagina += 1


def abrir_rubrica(p, grado='3.º', sub='Comprensión Lectora', mes=None, colegio=None):
    ir(p, 'Rúbrica'); p.wait_for_timeout(2000)
    if colegio:
        poner(p, 'Colegio', colegio)
    poner(p, 'Grado', grado); poner(p, 'Sección', 'Única'); poner(p, 'Subprograma', sub); poner(p, 'Mes', FE.mes_nombre(mes or mes_actual())); p.wait_for_timeout(1500)


def elegir(p, nombre, dim, valor):
    """Cambia un desplegable de la fila y devuelve (estado HTTP, cuerpo, enviado) del PUT que dispara."""
    s = p.get_by_label(f'{dim} de {nombre}', exact=True)
    try:
        with p.expect_response(lambda r: '/api/rubricas' in r.url and r.request.method == 'PUT', timeout=8000) as ri:
            s.select_option(label=valor)
        r = ri.value; p.wait_for_timeout(1200)
        try:
            b = r.json()
        except Exception:
            b = r.text()[:200]
        return r.status, [(x.get('estado'), x.get('motivo')) for x in b] if isinstance(b, list) else b, json.loads(r.request.post_data)
    except Exception as e:
        return 'sin petición', str(e)[:80], None


def estado_fila(p, nombre):
    f = fila(p, nombre)
    if not f.count():
        return None
    return [sel_txt(s) for s in f.locator('select').all()] + f.inner_text().split('\t')[-2:]


def criterios_modal(p):
    p.locator('main').get_by_role('button', name=re.compile('Ver criterios')).first.click(); p.wait_for_timeout(1500)
    d = p.locator('[role=dialog]:visible').last
    return d, (d.inner_text() if d.count() else '')


def _fin(R, chk, n, *cuentas):
    for c in (cuentas or (_c(),)):
        try:
            A.cerrar_abiertas(c)
        except Exception:
            pass
    R.save(checks=chk)
    if n:
        n.close()


# ───────────────────────────────────────────────────────────────────────────────────

@caso('CP-RUB-01')
def cp_rub01():
    R = Run('CP-RUB-01'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); M = mes_actual()
    _, act = nueva_act(C)
    a, b = D.alumno('Ana Norte QA'), D.alumno('Beto Norte QA')
    chk['pre'] = rub_put(C, rub_items([(a, 3, 3), (b, 2, '-')], act)); A.cerrar_abiertas(C)
    R.consola(ctx, f'Precondición: evaluaciones de {FE.mes_nombre(M).lower()} por la API (PA{pa_de_mes(M)} del mes; Docente A con permisos de los PA culminados)',
              [f'Ana Norte QA: F3 C3; Beto Norte QA: solo F2 → {chk["pre"]}', 'Extra12 Rubrica QA: inactivo desde hoy (perteneció al grupo este mes).'])
    con_actividad(p, C); ir(p, 'Rúbrica'); p.wait_for_timeout(2500)
    chk['filtros_iniciales'] = filtros_ui(p)
    R.shot(p, f'Paso 1: filtros en pantalla (orden, valor): {chk["filtros_iniciales"]}', full=True)
    abrir_rubrica(p)
    m = p.locator('main'); t = m.inner_text()
    chk['ciclo'] = re.findall(r'Ciclo [IV]+', t); chk['ciclo_es_filtro'] = any('CICLO' in f[0].upper() for f in filtros_ui(p))
    chk['columnas'] = [x.strip() for x in m.locator('thead th').all_inner_texts()]
    R.shot(p, f'Pasos 2-3: {chk["ciclo"]} (filtro: {chk["ciclo_es_filtro"]}); columnas {chk["columnas"]}', full=True)
    filas_ = m.locator('tbody tr')
    chk['n_filas'] = filas_.count(); chk['pie'] = pie(p)
    fa, fb = fila(p, 'Ana Norte QA'), fila(p, 'Beto Norte QA')
    chk['ana'] = [sel_txt(s) for s in fa.locator('select').all()] + [fa.inner_text().replace('\n', ' | ')[-80:]]
    chk['beto'] = [sel_txt(s) for s in fb.locator('select').all()] + [fb.inner_text().replace('\n', ' | ')[-80:]]
    otra = filas_.filter(has_not_text='Ana Norte').filter(has_not_text='Beto Norte').first
    chk['sin_eval'] = [sel_txt(s) for s in otra.locator('select').all()] + [otra.inner_text().replace('\n', ' | ')[-60:]]
    chk['opciones_fluidez'] = fa.locator('select').first.evaluate("s=>[...s.options].map(o=>o.text+'='+o.value)")
    R.shot(p, f'Pasos 4-5: Ana {chk["ana"]}; Beto {chk["beto"]}; sin evaluación {chk["sin_eval"]}; opciones {chk["opciones_fluidez"]}')
    f12 = fila(p, 'Extra12')
    chk['inactivo'] = f12.inner_text().replace('\n', ' | ')[:160] if f12.count() else None
    chk['inactivo_marca'] = f12.locator('[title]').evaluate_all("els=>els.map(e=>e.title+' / '+e.innerText)") if f12.count() else None
    sig = p.get_by_role('button', name='Siguiente')
    if sig.count() and sig.first.is_enabled():
        sig.first.click(); p.wait_for_timeout(1500)
    chk['pag2'] = (pie(p), [r.split('\t')[0] for r in m.locator('tbody tr').all_inner_texts()])
    R.shot(p, f'Pasos 5 y 7: página 1 con {chk["n_filas"]} filas ({chk["pie"]}); página 2 {chk["pag2"]}; alumno inactivo (página 1): {chk["inactivo"]} {chk["inactivo_marca"]}', full=True)
    ant = (M - 2) % 12 + 1
    poner(p, 'Mes', FE.mes_nombre(ant)); p.wait_for_timeout(1500); chk['tras_filtro'] = pie(p)
    poner(p, 'Mes', FE.mes_nombre(M)); p.wait_for_timeout(1500)
    R.shot(p, f'Paso 7: al cambiar el mes vuelve a {chk["tras_filtro"]}')
    s0 = fa.locator('select').first; s0.hover(); p.wait_for_timeout(700)
    chk['descriptor'] = (p.locator('[role=tooltip]').all_inner_texts(), s0.get_attribute('title'), fa.locator('[title]').evaluate_all("els=>els.map(e=>e.title)"))
    R.shot(p, f'Paso 6: descriptor del código elegido: {chk["descriptor"]}')
    ls = p.evaluate('JSON.stringify(localStorage)'); raw = idb_todo(p)
    chk['ls'] = ls; chk['idb_rubricas'] = 'rubricas' in raw
    R.consola(ctx, 'Paso 8: Local Storage e IndexedDB', [f'localStorage = {ls[:600]}', f'IndexedDB contiene la consulta de rúbricas: {chk["idb_rubricas"]}', raw[:600]])
    s, r = rub_get(C); chk['api'] = (s, r.get('total'), r.get('ciclo'), r.get('id_periodo_academico'))
    R.consola(ctx, f'Referencia: GET /api/rubricas ({FE.mes_nombre(M).lower()})', [f'HTTP {s}; total {r.get("total")}; ciclo {r.get("ciclo")}; PA del mes {r.get("id_periodo_academico")}',
                                                                              json.dumps(r.get('items', [])[:3], ensure_ascii=False)[:600]])
    _fin(R, chk, n)


@caso('CP-RUB-02')
def cp_rub02():
    R = Run('CP-RUB-02'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    login(p, sup_ui()); abrir_rubrica(p, grado='4.º', sub='Alfabetización', colegio=NX())
    chk['alfa4_ciclo'] = re.findall(r'Ciclo [IV]+', p.locator('main').inner_text())
    d, t = criterios_modal(p); chk['alfa4'] = t
    R.shot(p, f'Pasos 1-2: Alfabetización 4.º: {chk["alfa4_ciclo"]}; criterios: {t[:200]}')
    chk['alfa_fluidez0'] = 'No puede leer porque le cuesta reconocer consonantes y vocales.' in t
    secc = re.split(r'\nComprensión\n', '\n' + t)
    chk['alfa_comprension_codigos'] = re.findall(r'\n(\d) · ', '\n' + (secc[1] if len(secc) > 1 else ''))
    chk['alfa_fluidez_codigos'] = re.findall(r'\n(\d) · ', secc[0])
    chk['solo_lectura'] = d.locator('input, select, textarea').count()
    d.get_by_role('button', name='Cerrar').last.click(); p.wait_for_timeout(600)
    chk['cierra'] = p.locator('[role=dialog]:visible').count() == 0
    res = {}
    for g, cic in [('2.º', 'III'), ('4.º', 'IV'), ('6.º', 'V')]:
        poner(p, 'Grado', g); poner(p, 'Sección', 'Única'); poner(p, 'Subprograma', 'Comprensión Lectora'); p.wait_for_timeout(1500)
        ciclo = re.findall(r'Ciclo [IV]+', p.locator('main').inner_text())
        d, t = criterios_modal(p)
        id_ciclo = {'III': 1, 'IV': 2, 'V': 3}[cic]
        api_c = A.api('GET', f'/rubricas/criterios?id_programa={A.CL()}&id_ciclo={id_ciclo}', A.sup())[1]
        coinc = all(c['descriptor'] in t for c in api_c) if isinstance(api_c, list) else None
        res[g] = {'ciclo': ciclo, 'esperado': cic, 'codigos': re.findall(r'\n(\d) · ', '\n' + t), 'coincide_catalogo': coinc,
                  'n_catalogo': len(api_c) if isinstance(api_c, list) else api_c}
        R.shot(p, f'Paso 3: Comprensión Lectora {g}: {res[g]}')
        d.get_by_role('button', name='Cerrar').last.click(); p.wait_for_timeout(500)
    chk['cl'] = res
    R.consola(ctx, 'Pasos 1-4: resumen', [f'Alfabetización 4.º: {chk["alfa4_ciclo"]}; Fluidez {chk["alfa_fluidez_codigos"]} (Pre-inicio con el descriptor de CU029 = {chk["alfa_fluidez0"]}); Comprensión {chk["alfa_comprension_codigos"]}',
                                       f'Controles editables en el panel: {chk["solo_lectura"]}; se cierra con "Cerrar": {chk["cierra"]}'] + [f'Comprensión Lectora {g}: {v}' for g, v in res.items()])
    R.save(checks=chk); n.close()


@caso('CP-RUB-03')
def cp_rub03():
    R = Run('CP-RUB-03'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    _, act = nueva_act(C); a = D.alumno('Ana Norte QA'); rub_put(C, rub_items([(a, 3, 3)], act)); A.cerrar_abiertas(C)
    login(p, sup_ui()); ir(p, 'Rúbrica'); p.wait_for_timeout(2000)
    col = p.locator('main select').first
    chk['colegios'] = (len(col.evaluate("s=>[...s.options].map(o=>o.text)")), len(A.colegios(True)))
    R.shot(p, f'Paso 1: la Supervisora ve {chk["colegios"][0]} opciones de colegio (activos según la API: {chk["colegios"][1]})')
    abrir_rubrica(p, colegio=NX())
    m = p.locator('main')
    chk['botones'] = m.get_by_role('button').all_inner_texts()[:10]
    chk['selects_tabla'] = [s.is_disabled() for s in m.locator('tbody select').all()][:6]
    chk['aviso'] = [l for l in m.inner_text().split('\n') if 'lectura' in l.lower() or 'consulta' in l.lower()][:3]
    R.shot(p, f'Paso 2: tabla de la Supervisora: botones {chk["botones"]}; desplegables deshabilitados {chk["selects_tabla"]}; avisos {chk["aviso"]}', full=True)
    antes = rub_de('Ana Norte QA')
    s, r = rub_put(token_navegador(p), rub_items([(a, 1, 1)], None)); chk['api_sup'] = (s, r, antes == rub_de('Ana Norte QA'))
    R.consola(ctx, 'Paso 3: guardado con el token de la Supervisora', [f'PUT /api/rubricas → HTTP {s} {r}', f'La evaluación de Ana no cambió: {chk["api_sup"][2]} ({antes})'])
    n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); login(p, D.cuenta('directivo')); p.wait_for_timeout(1500)
    chk['menu_dir'] = [t.strip() for t in p.locator('aside nav a').all_inner_texts()]
    p.goto(BASE + '/rubrica'); p.wait_for_timeout(2000); chk['ruta_dir'] = (p.url.replace(BASE, ''), p.locator('body').inner_text()[:120])
    R.shot(p, f'Paso 4: Directivo: menú {chk["menu_dir"]}; /rubrica → {chk["ruta_dir"]}')
    chk['api_dir'] = rub_get(token_navegador(p))[0]
    R.consola(ctx, 'Paso 4: API con el token del Directivo', [f'GET /api/rubricas → HTTP {chk["api_dir"]}'])
    R.save(checks=chk); n.close()


@caso('CP-RUB-04')
def cp_rub04():
    R = Run('CP-RUB-04'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    con_actividad(p, C); abrir_rubrica(p); m = p.locator('main')
    chk['boton_registrar'] = m.get_by_role('button', name=re.compile('Registrar evaluaciones')).count()
    chk['editables'] = sum(1 for s in m.locator('tbody select').all() if s.is_enabled())
    chk['botones'] = m.get_by_role('button').all_inner_texts()[:8]
    R.shot(p, f'Paso 1: "Registrar evaluaciones" = {chk["boton_registrar"]}; desplegables editables en la consulta = {chk["editables"]}; botones {chk["botones"]}', full=True)
    chk['opciones'] = p.get_by_label('Fluidez de Extra01 Rubrica QA', exact=True).evaluate("s=>[...s.options].map(o=>o.text)")
    R.shot(p, f'Paso 2: opciones de Fluidez (Comprensión Lectora): {chk["opciones"]}')
    ops = {}
    ops['E1_F'] = elegir(p, 'Extra01 Rubrica QA', 'Fluidez', 'En proceso'); chk['tras_un_cambio'] = estado_fila(p, 'Extra01 Rubrica QA')
    R.shot(p, f'Paso 3: al elegir solo Fluidez de Extra01 la fila queda {chk["tras_un_cambio"]} y se envía {ops["E1_F"][:2]}; avisos {toasts_txt(p)}')
    ops['E1_C'] = elegir(p, 'Extra01 Rubrica QA', 'Comprensión', 'Logrado')
    ops['E2_F'] = elegir(p, 'Extra02 Rubrica QA', 'Fluidez', 'Logrado')
    chk['estados'] = {k: estado_fila(p, k) for k in ['Extra01 Rubrica QA', 'Extra02 Rubrica QA', 'Extra03 Rubrica QA']}
    chk['ops'] = {k: v[:2] for k, v in ops.items()}; chk['cuerpo_ejemplo'] = ops['E1_C'][2]
    R.shot(p, f'Pasos 3-4: estados {chk["estados"]}; envíos {chk["ops"]}; avisos {toasts_txt(p)}', full=True)
    chk['api'] = {k: rub_de(k) for k in ['Extra01', 'Extra02', 'Extra03']}
    hist = A.api('GET', f'/alumnos/{D.alumno("Extra01")}/historial', A.sup())[1]
    chk['historial'] = json.dumps((hist or {}).get('items', [])[:3], ensure_ascii=False)[:800] if isinstance(hist, dict) else hist
    R.consola(ctx, 'Paso 5: lo guardado (API)', ['Evaluaciones (fluidez | comprensión | estado | resultado | versión):'] + [f'{k}: {v}' for k, v in chk['api'].items()] + ['', f'Historial de Extra01: {chk["historial"]}'])
    R.nota('Paso 5: Docente, actividad y auditoría por campo de rubrica_mensual solo se ven en la base de datos; en QA se muestra el historial del alumno.')
    ops['E1_F2'] = elegir(p, 'Extra01 Rubrica QA', 'Fluidez', 'Avanzado')
    chk['modif'] = (ops['E1_F2'][:2], rub_de('Extra01'))
    R.consola(ctx, 'Paso 6: modificación de Fluidez de Extra01 (En proceso → Avanzado)', [f'Envío: {chk["modif"][0]}', f'Evaluación tras el cambio (F | C | estado | resultado | versión): {chk["modif"][1]}'])
    e1 = D.alumno('Extra01')
    mv = A.api('PATCH', f'/alumnos/{e1}', A.sup(), {'id_programa': A.ALFA(), 'cambio_grupo_desde': A.iso(A.hoy())}); chk['mover'] = mv[0]
    p.reload(); p.wait_for_timeout(2500); abrir_rubrica(p, sub='Alfabetización')
    chk['en_alfa'] = fila(p, 'Extra01').count()
    chk['api_otro_grupo'] = rub_put(C, rub_items([(e1, 1, 1)], act_de(C), prog=A.ALFA()))
    R.shot(p, f'Paso 7: Extra01 pasa a Alfabetización (PATCH → {mv[0]}); aparece en la rúbrica del mes de Alfabetización: {chk["en_alfa"]}; evaluarlo allí por la API → {chk["api_otro_grupo"]}', full=True)
    if chk['en_alfa']:
        chk['ui_otro_grupo'] = elegir(p, 'Extra01 Rubrica QA', 'Fluidez', 'Inicio')[:2]; p.wait_for_timeout(1500)
        chk['msg_fila'] = fila(p, 'Extra01').inner_text().replace('\n', ' | ')
        R.shot(p, f'Paso 7: en la interfaz: {chk["ui_otro_grupo"]}; fila: {chk["msg_fila"][:250]}; avisos {toasts_txt(p)}', full=True)
    abrir_rubrica(p); chk['en_cl'] = estado_fila(p, 'Extra01 Rubrica QA')
    R.shot(p, f'Paso 7: en Comprensión Lectora (donde se guardó) sigue la evaluación: {chk["en_cl"]}')
    _fin(R, chk, n)


@caso('CP-RUB-05')
def cp_rub05():
    from casos.rv import abrir_rv, rv_get, rv_items, rv_put
    R = Run('CP-RUB-05'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); M = mes_actual(); PAM = pa_de_mes(M)
    _, act = nueva_act(C)
    CLs = [(1, 2, 2, 20), (2, 3, 3, 30), (3, 4, 2, 28), (4, 1, 4, 28), (5, 3, 1, 18), (6, 3, 2, 24), (7, 4, 4, 40)]
    chk['cl'] = rub_put(C, rub_items([(D.alumno(f'Extra{i:02d}'), f, c) for i, f, c, _ in CLs], act))
    alfa = [a for a in A.alumnos(D.X(), 3, A.ALFA())][:3]
    ALs = [(alfa[0]['id'], 0, 3, 18), (alfa[1]['id'], 0, 4, 24), (alfa[2]['id'], 0, '-', None)]
    chk['alfa'] = rub_put(C, rub_items([(a, f, c) for a, f, c, _ in ALs], act, prog=A.ALFA()))
    esperado = [e for *_, e in CLs] + [e for *_, e in ALs]
    obtenido = [x[2] for x in chk['cl'][1]] + [x[2] for x in chk['alfa'][1]] if isinstance(chk['cl'][1], list) and isinstance(chk['alfa'][1], list) else None
    chk['decimas'] = list(zip(esperado, obtenido or [])); chk['coinciden'] = esperado == obtenido
    R.consola(ctx, 'Pasos 1-3: evaluaciones por la API y resultado ponderado (en décimas)', [f'Comprensión Lectora F/C: {[(f, c) for _, f, c, _ in CLs]}', f'Alfabetización F/C: {[(f, c) for _, f, c, _ in ALs]}',
                                                                                          f'Esperado: {esperado}', f'Obtenido: {obtenido}', f'Coinciden: {chk["coinciden"]}'])
    if PAM and PAM > 1:
        chk['entrada'] = rv_put(C, rv_items([(D.alumno(f'Extra{i:02d}'), PAM - 1, {'id_nivel_colocado': niv('J')}) for i, *_ in CLs], act))
        R.consola(ctx, f'Precondición del paso 4: nivel colocado J en PA{PAM - 1} (entrada del PA{PAM}) para Extra01 a Extra07', [f'PUT /api/registro-vuelo → {chk["entrada"]}'])
    A.cerrar_abiertas(C); con_actividad(p, C); abrir_rubrica(p)
    chk['ui_cl'] = [(f'Extra{i:02d}', fila(p, f'Extra{i:02d}').inner_text().split('\t')[-2:]) for i, *_ in CLs]
    R.shot(p, f'Paso 3: columna Resultado en Comprensión Lectora: {chk["ui_cl"]}', full=True)
    abrir_rubrica(p, sub='Alfabetización')
    nombres = [f'{a["nombres"]} {a["apellidos"]}' for a in alfa]
    chk['ui_alfa'] = [(nm, fila(p, nm).inner_text().split('\t')[-2:]) for nm in nombres]
    R.shot(p, f'Paso 3: Alfabetización: {chk["ui_alfa"]}', full=True)
    s, r = rv_get(C); sug = {}
    for it in (r.get('items', []) if s == 200 else []):
        if it['nombre'].startswith('Extra0') and int(it['nombre'][5:7]) <= 7:
            pa = [x for x in it['periodos'] if x['numero'] == PAM]
            if pa:
                pa = pa[0]; sg = pa.get('sugerencia') or {}
                sug[it['nombre']] = (sg.get('accion'), sg.get('texto'), sg.get('resultado_decimas'), pa.get('nivel_colocado'))
    chk['sugerencias'] = sug
    abrir_rv(p, pa=f'PA{PAM}')
    chk['ui_rv'] = [(f'Extra{i:02d}', fila(p, f'Extra{i:02d}').inner_text().split('\t')[1:4]) for i, *_ in CLs if fila(p, f'Extra{i:02d}').count()]
    R.shot(p, f'Pasos 4-6: Registro de Vuelo, PA{PAM}: {chk["ui_rv"]}', full=True)
    R.consola(ctx, f'Pasos 4-6: sugerencia del PA{PAM} (acción | texto | resultado | nivel colocado), por la API', [f'{k}: {v}' for k, v in sorted(sug.items())])
    _fin(R, chk, n)


@caso('CP-RUB-06')
def cp_rub06():
    R = Run('CP-RUB-06'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    con_actividad(p, C); abrir_rubrica(p)
    chk['opciones_cl'] = p.get_by_label('Fluidez de Extra01 Rubrica QA', exact=True).evaluate("s=>[...s.options].map(o=>o.text)")
    R.shot(p, f'Paso 1: Fluidez en Comprensión Lectora: {chk["opciones_cl"]}')
    act = act_de(C); a = D.alumno('Ana Norte QA')
    rub_put(C, rub_items([(a, 3, 3)], act)); antes = rub_de('Ana Norte QA')
    alfa = A.alumnos(D.X(), 3, A.ALFA())[0]['id']
    casos = {'Fluidez 0 en Comprensión Lectora': rub_items([(a, 0, '-')], act), 'Comprensión 0 en Alfabetización': rub_items([(alfa, '-', 0)], act, prog=A.ALFA()),
             'Fluidez 5': rub_items([(a, 5, '-')], act), 'Fluidez -1': rub_items([(a, -1, '-')], act), 'Fluidez 2,5': rub_items([(a, 2.5, '-')], act), 'Fluidez "A"': rub_items([(a, 'A', '-')], act)}
    res = {}
    for k, it in casos.items():
        s, r = A.api('PUT', '/rubricas', C, it)
        res[k] = (s, [(x.get('estado'), x.get('motivo'), x.get('detail')) for x in r] if isinstance(r, list) else ((r or {}).get('motivo'), ((r or {}).get('errores') or [{}])[0].get('mensaje')) if isinstance(r, dict) else r)
    chk['api'] = res; chk['sin_cambios'] = antes == rub_de('Ana Norte QA')
    R.consola(ctx, 'Paso 2: valores no permitidos por la API (token del Docente)', [f'{k}: HTTP {v[0]} {v[1]}' for k, v in res.items()] + [f'La evaluación confirmada de Ana (F3 C3) no cambió: {chk["sin_cambios"]}'])
    p.reload(); p.wait_for_timeout(2500); abrir_rubrica(p)
    s = p.get_by_label('Fluidez de Extra03 Rubrica QA', exact=True)
    s.evaluate("s=>{const o=document.createElement('option'); o.value='0'; o.text='Pre-inicio (alterado)'; s.appendChild(o)}")
    try:
        with p.expect_response(lambda r: '/api/rubricas' in r.url and r.request.method == 'PUT', timeout=8000) as ri:
            s.select_option(value='0')
        rr = ri.value; envio = (rr.status, rr.json())
    except Exception as e:
        envio = ('sin petición', str(e)[:60])
    p.wait_for_timeout(1500)
    chk['dom'] = {'envio': envio, 'fila': fila(p, 'Extra03').inner_text().replace('\n', ' | ')[-250:], 'avisos': toasts_txt(p), 'api': rub_de('Extra03')}
    R.shot(p, f'Paso 3: opción alterada en el DOM: {chk["dom"]}', full=True)
    lote = rub_items([(D.alumno('Extra04'), 2, 2)], act) + rub_items([(D.alumno('Extra05'), 9, '-')], act)
    s2, r2 = A.api('PUT', '/rubricas', C, lote)
    chk['lote'] = (s2, [(x.get('estado'), x.get('motivo')) for x in r2] if isinstance(r2, list) else r2, {k: rub_de(k) for k in ['Extra04', 'Extra05']})
    R.consola(ctx, 'Paso 4: lote con una evaluación válida (Extra04 F2 C2) y una inválida (Extra05 F9)', [f'PUT /api/rubricas → HTTP {s2} {chk["lote"][1]}', f'Guardadas: {chk["lote"][2]}'])
    _fin(R, chk, n)


@caso('CP-RUB-07')
def cp_rub07():
    R = Run('CP-RUB-07'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); M = mes_actual()
    A.cerrar_abiertas(C); login(p, C); p.wait_for_timeout(1500); abrir_rubrica(p); m = p.locator('main')
    chk['sin_actividad'] = {'boton': m.get_by_role('button', name=re.compile('Registrar evaluaciones')).count(),
                            'deshabilitados': all(s.is_disabled() for s in m.locator('tbody select').all()[:6]),
                            'avisos': [l for l in m.inner_text().split('\n') if 'actividad' in l.lower()][:3]}
    R.shot(p, f'Paso 1: sin actividad: {chk["sin_actividad"]}', full=True)
    n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); D1 = D.cuenta('rv-uno')
    con_actividad(p, D1); abrir_rubrica(p, grado='1.º', sub='Alfabetización'); m = p.locator('main')
    chk['solo_consulta'] = {'avisos': [l for l in m.inner_text().split('\n') if 'habilitaci' in l.lower()][:3], 'filas': m.locator('tbody tr').count(),
                            'deshabilitados': all(s.is_disabled() for s in m.locator('tbody select').all()[:6])}
    R.shot(p, f'Paso 2: Docente de 1.º (asignación del PA vigente) en la rúbrica de {FE.mes_nombre(M).lower()} (PA{pa_de_mes(M)} por R1): {chk["solo_consulta"]}', full=True)
    A.cerrar_abiertas(D1); n.close()
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C); abrir_rubrica(p)
    elegir(p, 'Extra08 Rubrica QA', 'Fluidez', 'Inicio')
    act = act_de(C)
    p2 = ctx.new_page(); p2.goto(BASE + '/inicio'); p2.wait_for_timeout(2500)
    chk['boton_otra_pestana'] = p2.get_by_role('button', name=re.compile('Finalizar actividad')).count()
    if chk['boton_otra_pestana']:
        p2.get_by_role('button', name=re.compile('Finalizar actividad')).first.click(); p2.wait_for_timeout(1200)
        dd = p2.locator('[role=dialog]:visible')
        if dd.count():
            dd.get_by_role('button', name=re.compile('Finalizar')).last.click(); p2.wait_for_timeout(2000)
    det = A.api('GET', f'/actividades/{act}', C)[1]
    chk['finalizada'] = (det.get('estado'), det.get('tipo_cierre')) if isinstance(det, dict) else det
    if isinstance(det, dict) and det.get('estado') != 'finalizada':
        chk['finalizada_api'] = A.finalizar_actividad(C, act)[0]
        det = A.api('GET', f'/actividades/{act}', C)[1]; chk['finalizada'] = (det.get('estado'), det.get('tipo_cierre'))
    R.shot(p2, f'Paso 3: la actividad se finaliza desde otra pestaña (botón en la otra pestaña: {chk["boton_otra_pestana"]}; por la API: {chk.get("finalizada_api")}): {chk["finalizada"]}')
    p.bring_to_front(); p.wait_for_timeout(1500)
    r = elegir(p, 'Extra08 Rubrica QA', 'Comprensión', 'Logrado')
    chk['tras_fin'] = {'envio': r[:2], 'fila': estado_fila(p, 'Extra08 Rubrica QA'), 'avisos': toasts_txt(p) + [l for l in p.locator('main').inner_text().split('\n') if 'actividad' in l.lower()][:3]}
    R.shot(p, f'Paso 3: cambio con la actividad finalizada: {chk["tras_fin"]}', full=True)
    raw = idb_todo(p)
    chk['api'] = rub_de('Extra08')
    chk['idb_cola'] = [raw[max(0, mm.start() - 80): mm.start() + 120] for mm in re.finditer('"comprension"', raw)][:2]
    R.consola(ctx, 'Paso 4: servidor e IndexedDB', [f'Evaluación de Extra08 según la API (F | C | estado | resultado | versión): {chk["api"]}', f'Operaciones con "comprension" en IndexedDB: {chk["idb_cola"]}'])
    p.reload(); p.wait_for_timeout(3000); ir(p, 'Inicio'); p.wait_for_timeout(1500)
    chk['inicio_tras_fin'] = [b.inner_text() for b in p.locator('header button').all()][:4]
    R.shot(p, f'Paso 5: tras recargar, la barra superior muestra {chk["inicio_tras_fin"]}')
    f = p.get_by_role('button', name='Finalizar actividad')
    if f.count():
        f.first.click(); p.wait_for_timeout(1200); dd = p.locator('[role=dialog]:visible')
        if dd.count():
            dd.get_by_role('button', name=re.compile('Finalizar')).last.click(); p.wait_for_timeout(2000)
        chk['finalizar_ui'] = toasts_txt(p)
    b = p.get_by_role('button', name='Iniciar actividad')
    if b.count():
        b.first.click(); p.wait_for_timeout(2500)
    abrir_rubrica(p); r2 = elegir(p, 'Extra08 Rubrica QA', 'Comprensión', 'Logrado')
    chk['nueva_actividad'] = (r2[:2], estado_fila(p, 'Extra08 Rubrica QA'))
    R.shot(p, f'Paso 5: con una actividad nueva: {chk["nueva_actividad"]}')
    _fin(R, chk, n)


@caso('CP-RUB-08', notas='Usa un calendario particular del colegio Sur con hoy dentro del PR2 (como en local).')
def cp_rub08():
    R = Run('CP-RUB-08'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); MF = mes_futuro()
    con_actividad(p, C); abrir_rubrica(p, mes=MF); m = p.locator('main')
    chk['ui_futuro'] = {'texto': [l for l in m.inner_text().split('\n') if 'futur' in l.lower() or 'evaluar' in l.lower()][:4], 'selects': m.locator('tbody select').count(),
                        'meses': opciones(p, 'Mes')}
    chk['api_futuro'] = rub_put(C, rub_items([(D.alumno('Extra09'), 2, 2)], act_de(C), mes=MF)); chk['get_futuro'] = rub_get(C, mes=MF)[1]
    R.shot(p, f'Paso 1: {FE.mes_nombre(MF).lower()} (mes futuro): {chk["ui_futuro"]}; guardar por la API → {chk["api_futuro"]}', full=True)
    A.cerrar_abiertas(C); n.close()
    Y = D.Y(); CR = D.cuenta('retro'); NY = D.nombre_colegio('sur')
    s, r = FE.poner_calendario_en_pr(Y, True)
    pa2 = FE.pa(2, Y); aid = A.crear_alumno('Rita', 'Retro Rubrica QA', Y, 3, A.CL(), pa2['fecha_inicio'])
    asg = A.asignar(D.id_usuario('retro'), [(Y, [3])], 'retroactivo')
    meses2 = meses_de_pa(2, Y); MR = meses2[-1] if meses2 else None
    chk['prep'] = {'calendario': s, 'asignacion': asg[0], 'mes_de_pa2': MR}
    n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    R.consola(ctx, 'Precondición: colegio Sur con calendario particular (hoy en el PR2); Docente Retro con asignación Retroactiva',
              [f'Calendario particular → HTTP {s}', f'PATCH asignación retroactiva → HTTP {asg[0]} {str(asg[1])[:200] if asg[0] >= 300 else ""}', f'Mes cuya rúbrica es del PA2 en ese calendario: {MR}'])
    if not MR:
        R.nota('No hay un mes cuya rúbrica pertenezca al PA2 del calendario particular; no se pueden hacer los pasos 2-4.'); _fin(R, chk, n, CR); return
    con_actividad(p, CR); abrir_rubrica(p, mes=MR, colegio=NY); actr = act_de(CR)
    chk['pr_api'] = rub_put(CR, rub_items([(aid, 3, 3)], actr, mes=MR, cid=Y))
    c2 = n.ctx(); p2 = c2.new_page(); login(p2, CR); p2.wait_for_timeout(1500); abrir_rubrica(p2, mes=MR, colegio=NY)
    chk['pr_ui_otro_navegador'] = estado_fila(p2, 'Rita Retro Rubrica QA')
    R.shot(p2, f'Paso 2: la misma rúbrica en otro navegador (sin copia local): {chk["pr_ui_otro_navegador"]}', full=True); c2.close()
    p.reload(); p.wait_for_timeout(2500)
    if '/login' in p.url:
        login(p, CR)
    abrir_rubrica(p, mes=MR, colegio=NY); chk['pr_ui'] = estado_fila(p, 'Rita Retro Rubrica QA')
    R.shot(p, f'Paso 2: durante el PR2, Retro registra la rúbrica de {FE.mes_nombre(MR).lower()} (PA2) por la API → {chk["pr_api"]}; en su navegador, tras recargar, la fila queda {chk["pr_ui"]}', full=True)
    s3, _ = FE.poner_calendario_en_pr(Y, False, A.calendario(Y)); chk['mover'] = s3
    A.cerrar_abiertas(CR)
    n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); login(p, CR); p.wait_for_timeout(1500)
    b = p.get_by_role('button', name='Iniciar actividad'); chk['iniciar_tras_pr'] = b.first.is_enabled() if b.count() else 'no está'
    s_, r_ = A.api('POST', '/actividades', CR, {'id_actividad': A.uid()}); actr = (r_ or {}).get('actividad', {}).get('id') if isinstance(r_, dict) else None
    chk['iniciar_api'] = (s_, (r_ or {}).get('motivo') if isinstance(r_, dict) else r_)
    p.reload(); p.wait_for_timeout(2000); abrir_rubrica(p, mes=MR, colegio=NY)
    chk['fin_pr_ui'] = [l for l in p.locator('main').inner_text().split('\n') if 'habilitaci' in l.lower() or 'actividad' in l.lower()][:3]
    chk['fin_pr_api'] = rub_put(CR, rub_items([(aid, 4, 4)], actr, mes=MR, cid=Y))
    R.shot(p, f'Paso 3: PR2 terminado (PUT calendario → {s3}): {chk["fin_pr_ui"]}; iniciar actividad por la API {chk["iniciar_api"]}; guardar por la API → {chk["fin_pr_api"]}', full=True)
    pm = A.permiso(D.id_usuario('retro'), Y, 3, pa2['id_periodo_academico'], 'rubrica', A.ahora() + dt.timedelta(days=30)); chk['permiso'] = pm[0]
    n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, CR); abrir_rubrica(p, mes=MR, colegio=NY); actr = act_de(CR)
    chk['con_permiso_ui'] = [l for l in p.locator('main').inner_text().split('\n') if 'Corrección excepcional' in l]
    v = rub_de('Rita', mes=MR, cid=Y)
    it = rub_items([(aid, 4, 4)], actr, mes=MR, cid=Y); it[0]['version'] = v[4] if isinstance(v, tuple) else None
    chk['con_permiso_api'] = rub_put(CR, it); chk['api'] = rub_de('Rita', mes=MR, cid=Y)
    R.shot(p, f'Paso 4: con permiso de Rúbrica para PA2 (HTTP {pm[0]}): {chk["con_permiso_ui"]}; guardar → {chk["con_permiso_api"]}', full=True)
    R.consola(ctx, 'Paso 4: lo guardado (API)', [f'Rúbrica de Rita (F | C | estado | resultado | versión): {chk["api"]}'])
    R.nota('Paso 4: el id_permiso de la evaluación solo se ve en la base de datos.')
    _fin(R, chk, n, CR)


@caso('CP-RUB-09', modo='parcial', notas='El paso 7 (backend detenido) se simula bloqueando /api desde el navegador.')
def cp_rub09():
    from lib.ui import backend_caido
    R = Run('CP-RUB-09'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    con_actividad(p, C); abrir_rubrica(p)
    ctx.set_offline(True); p.wait_for_timeout(800)
    for nm, d, v in [('Extra11 Rubrica QA', 'Fluidez', 'Logrado'), ('Extra11 Rubrica QA', 'Comprensión', 'En proceso'), ('Extra10 Rubrica QA', 'Fluidez', 'Inicio')]:
        p.get_by_label(f'{d} de {nm}', exact=True).select_option(label=v); p.wait_for_timeout(700)
    chk['offline'] = {'filas': {k: estado_fila(p, k) for k in ['Extra11 Rubrica QA', 'Extra10 Rubrica QA']}, 'avisos': toasts_txt(p), 'barra': p.locator('header').first.inner_text()[-80:]}
    R.shot(p, f'Paso 1: sin conexión: {chk["offline"]}', full=True)
    chk['idb'] = cola_idb(p)
    R.consola(ctx, 'Paso 2: operaciones en IndexedDB', chk['idb'] or ['(ninguna)'])
    p.get_by_label('Fluidez de Extra11 Rubrica QA', exact=True).select_option(label='Avanzado'); p.wait_for_timeout(700)
    chk['idb2'] = len(cola_idb(p))
    ctx.set_offline(False); p.wait_for_timeout(9000)
    chk['api'] = {k: rub_de(k) for k in ['Extra10', 'Extra11']}
    R.shot(p, f'Paso 3: tras reconectar: {estado_fila(p, "Extra11 Rubrica QA")}; avisos {toasts_txt(p)}')
    R.consola(ctx, 'Paso 3: lo guardado tras sincronizar (API)', [f'Operaciones en la cola antes de reconectar: {chk["idb2"]}', 'Evaluaciones (F | C | estado | resultado | versión):'] + [f'{k}: {v}' for k, v in chk['api'].items()])
    cortes = []

    def cortar(route):
        resp = route.fetch(); cortes.append((resp.status, route.request.post_data[:300])); route.abort()
    p.route('**/api/rubricas', lambda route: cortar(route) if route.request.method == 'PUT' and not cortes else route.continue_())
    p.get_by_label('Comprensión de Extra10 Rubrica QA', exact=True).select_option(label='Logrado'); p.wait_for_timeout(3000)
    chk['corte'] = {'avisos': toasts_txt(p), 'fila': estado_fila(p, 'Extra10 Rubrica QA'), 'barra': p.locator('header').first.inner_text()[-80:], 'servidor': [c[0] for c in cortes]}
    R.shot(p, f'Paso 4: se corta la red después de que el servidor guardó: {chk["corte"]}', full=True)
    p.unroute('**/api/rubricas'); p.wait_for_timeout(9000)
    ido = json.loads(cortes[0][1])[0]['id_operacion'] if cortes else None
    op = A.api('GET', f'/sincronizacion/operaciones/{ido}', C) if ido else None
    chk['verif'] = {'api': rub_de('Extra10'), 'operacion': op, 'barra': p.locator('header').first.inner_text()[-80:]}
    R.consola(ctx, 'Paso 4: verificación al reconectar', [f'id_operacion cortada: {ido}', f'Evaluación: {chk["verif"]["api"]}; la operación según el servidor: {chk["verif"]["operacion"]}; barra: {chk["verif"]["barra"]}'])
    ctx.set_offline(True); abrir_rubrica(p, sub='Alfabetización', mes=(mes_actual() - 2) % 12 + 1); p.wait_for_timeout(1500)
    chk['sin_copia'] = p.locator('main').inner_text()[-300:]
    R.shot(p, f'Paso 7: sin conexión, grupo y mes sin copia local: {chk["sin_copia"][-160:]}', full=True)
    ctx.set_offline(False); backend_caido(ctx, True); p.reload(); p.wait_for_timeout(3000)
    chk['backend_caido'] = p.locator('body').inner_text()[:300]
    R.shot(p, f'Paso 7: backend sin responder (llamadas a /api bloqueadas) y recarga: {chk["backend_caido"][:160]}', full=True)
    backend_caido(ctx, False); p.reload(); p.wait_for_timeout(3000)
    ctx.set_offline(True); p.reload(); p.wait_for_timeout(3000)
    chk['reabrir_offline'] = p.locator('body').inner_text()[:250]
    R.shot(p, f'Pasos 5-6: recargar la aplicación sin conexión: {chk["reabrir_offline"][:150]}')
    ctx.set_offline(False)
    _fin(R, chk, n)
