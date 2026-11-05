"""Registro de Vuelo (CU031, CU032): CP-RV-01 a CP-RV-09, adaptados a QA.

Los PA se toman del calendario: PA_ACT es el PA en curso y PA_M el PA de la rúbrica del mes actual
(en local eran el PA4 y el PA3). PA1 y PA2 son periodos culminados con permiso de Docente A.
"""
import datetime as dt
import json
import re

from lib import api as A
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import caso
from lib.ui import (BASE, Nav, Run, cerrar_dialogos, cola_idb, con_actividad, filtros_ui, fila, ir, login, pie, poner,
                    sel_txt, textos, toasts_txt, token_navegador)
from casos.asi import _c, act_de, nueva_act, sup_ui, NX
from casos.rub import mes_actual, niv, pa_de_mes, rub_items, rub_put


def PA_ACT(cid=None):
    p = FE.pa_actual(cid)
    return p['numero'] if p else None


def id_pa(numero, cid=None):
    return FE.pa(numero, cid)['id_periodo_academico']


def rv_items(lst, act, grado=3, prog=None, cid=None):
    """lst: [(id_alumno, número de PA, {campos})]"""
    x = cid or D.X(); sec = A.seccion(x, grado); out = []
    for aid, pa, extra in lst:
        it = {'id_operacion': A.uid(), 'id_actividad': act, 'id_alumno': aid, 'id_periodo_academico': id_pa(pa, x), 'id_colegio': x,
              'id_grado': A.id_grado(grado), 'id_seccion': sec, 'id_programa': prog or A.CL()}
        it.update(extra); out.append(it)
    return out


def rv_put(quien, items):
    s, r = A.api('PUT', '/registro-vuelo', quien, items)
    return s, ([(x.get('estado'), x.get('motivo')) for x in r] if isinstance(r, list) else r)


def rv_get(quien, grado=3, prog=None, cid=None, page=None):
    x = cid or D.X()
    return A.api('GET', '/registro-vuelo?' + A.q(id_colegio=x, id_programa=prog or A.CL(), id_grado=A.id_grado(grado), id_seccion=A.seccion(x, grado),
                                                id_anio_escolar=A.anio(), page=page), quien)


def pa_por_api(quien, nombre, num, grado=3, prog=None, cid=None):
    pagina = 1
    while True:
        s, r = rv_get(quien, grado, prog, cid, page=pagina)
        if s != 200:
            return s
        for it in r.get('items', []):
            if it['nombre'] == nombre:
                pa = [x for x in it['periodos'] if x['numero'] == num]
                if not pa:
                    return None
                pa = pa[0]; en = pa.get('entrada') or {}; sg = pa.get('sugerencia') or {}
                return {'entrada': ((en.get('nivel') or {}).get('letra'), en.get('texto')),
                        'sug': (sg.get('accion'), sg.get('texto'), (sg.get('nivel') or {}).get('letra'), sg.get('excepcion'), sg.get('resultado_decimas')),
                        'colocado': (pa.get('nivel_colocado') or {}).get('letra'), 'programa': pa.get('nivel_programa'),
                        'proy': (pa.get('proyeccion') or pa.get('nivel_proyeccion') or {}).get('letra') if (pa.get('proyeccion') or pa.get('nivel_proyeccion')) else None,
                        'obs': pa.get('observacion'), 'aviso': pa.get('aviso'), 'aviso_entrada_cambio': pa.get('aviso_entrada_cambio'),
                        'version': pa.get('version'), 'avance': it.get('avance_anual')}
        if pagina >= (r.get('total_pages') or 1):
            return None
        pagina += 1


def celdas(p, nombre):
    f = fila(p, nombre)
    if not f.count():
        return None
    out = []
    for td in f.locator('td').all():
        s = td.locator('select')
        out.append(sel_txt(s.first) if s.count() else td.inner_text().strip().replace('\n', ' '))
    return out


def abrir_rv(p, grado='3.º', sub='Comprensión Lectora', colegio=None, pa=None):
    ir(p, 'Registro de Vuelo'); p.wait_for_timeout(2000)
    if colegio:
        poner(p, 'Colegio', colegio)
    poner(p, 'Grado', grado); poner(p, 'Sección', 'Única'); poner(p, 'Subprograma', sub); p.wait_for_timeout(1500)
    if pa:
        tab(p, pa)


def tab(p, pa):
    t = p.locator('main').get_by_role('tab', name=re.compile(f'^{pa}'))
    if t.count():
        t.first.click(); p.wait_for_timeout(1200)
        return True
    return False


def elegir_rv(p, nombre, campo, valor):
    s = p.get_by_label(f'{campo} de {nombre}', exact=True)
    try:
        with p.expect_response(lambda r: '/api/registro-vuelo' in r.url and r.request.method == 'PUT', timeout=8000) as ri:
            s.select_option(label=valor)
        r = ri.value; p.wait_for_timeout(1200)
        b = r.json()
        return r.status, [(x.get('estado'), x.get('motivo')) for x in b] if isinstance(b, list) else b
    except Exception as e:
        return 'sin petición', str(e)[:80]


def resumen_rv():
    r = A.api('GET', '/inicio/supervisor', A.sup())[1]
    return {k: v for k, v in (r or {}).items() if 'incomplet' in k or 'vencid' in k} if isinstance(r, dict) else r


def preparar_pa1(quien, act):
    """Ana: K en PA1 con proyección N y observación; Beto sin decisión en PA1."""
    return rv_put(quien, rv_items([(D.alumno('Ana Norte QA'), 1, {'id_nivel_colocado': niv('K'), 'id_nivel_proyeccion': niv('N'),
                                                                  'observacion': 'Lee con fluidez; se coloca un nivel arriba.'})], act))


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

@caso('CP-RV-01')
def cp_rv01():
    R = Run('CP-RV-01'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); PA = PA_ACT()
    _, act = nueva_act(C); chk['pre'] = preparar_pa1(C, act); A.cerrar_abiertas(C)
    R.consola(ctx, 'Precondición: decisión de PA1 de Ana Norte QA (K, proyección N, observación) por la API', [str(chk['pre']), 'Extra12 Rubrica QA inactivo desde hoy.'])
    con_actividad(p, C); ir(p, 'Registro de Vuelo'); p.wait_for_timeout(2500)
    chk['filtros_iniciales'] = filtros_ui(p)
    abrir_rv(p); m = p.locator('main')
    chk['filtros'] = filtros_ui(p); chk['ciclo'] = re.findall(r'Ciclo [IV]+', m.inner_text())
    chk['pestanas'] = [t.replace('\n', ' ') for t in m.get_by_role('tab').all_inner_texts()]
    chk['columnas'] = [x.strip() for x in m.locator('thead th').all_inner_texts()]
    chk['fechas'] = re.findall(r'PA\d · del [^\n]+', m.inner_text())
    R.shot(p, f'Pasos 1-3: filtros {chk["filtros"]} (al entrar: {chk["filtros_iniciales"]}); ciclo {chk["ciclo"]}; pestañas {chk["pestanas"]}; columnas {chk["columnas"]}; fechas {chk["fechas"]}', full=True)
    cal = [(x['numero'], x['fecha_inicio'], x['fecha_fin']) for x in A.periodos(D.X())]
    fechas = {}
    for k in ['PA1', 'PA2', 'PA3', 'PA4']:
        tab(p, k); fechas[k] = re.findall(r'PA\d · del [^\n]+', m.inner_text())
    chk['fechas_por_pa'] = fechas
    R.consola(ctx, 'Paso 3: fechas de cada PA frente al calendario del colegio', [f'Pantalla: {fechas}', f'Calendario (API): {cal}'])
    tab(p, 'PA1')
    chk['ana_pa1'] = celdas(p, 'Ana Norte QA'); chk['beto_pa1'] = celdas(p, 'Beto Norte QA')
    chk['inactivo'] = celdas(p, 'Extra12'); chk['n_filas'] = m.locator('tbody tr').count(); chk['pie'] = pie(p)
    R.shot(p, f'Paso 5: PA1: Ana {chk["ana_pa1"]}; Beto {chk["beto_pa1"]}; inactivo {chk["inactivo"]}; {chk["n_filas"]} filas, página {chk["pie"]}', full=True)
    b = fila(p, 'Ana Norte QA').get_by_role('button', name=re.compile('observación'))
    chk['obs_boton'] = b.first.get_attribute('aria-label') if b.count() else None
    if b.count():
        b.first.click(); p.wait_for_timeout(1000); d = p.locator('[role=dialog]:visible').last
        chk['obs_modal'] = (d.inner_text()[:300], d.get_by_role('button').all_inner_texts(), d.locator('textarea, input').count())
        R.shot(p, f'Paso 6: observación de PA1 (periodo culminado): {chk["obs_modal"]}'); cerrar_dialogos(p)
    b2 = fila(p, 'Beto Norte QA').get_by_role('button', name=re.compile('observación'))
    if b2.count():
        b2.first.click(); p.wait_for_timeout(1000); d = p.locator('[role=dialog]:visible').last
        chk['obs_vacia'] = (d.inner_text()[:200], d.get_by_role('button').all_inner_texts()); R.shot(p, f'Paso 6: sin observación: {chk["obs_vacia"]}'); cerrar_dialogos(p)
    tab(p, f'PA{PA}')
    chk['registrar'] = m.get_by_role('button', name=re.compile('Registrar niveles')).count()
    chk['editables_pa_actual'] = sum(1 for s in m.locator('tbody select').all() if s.is_enabled())
    chk['sync'] = [x for x in ['Sincronizada', 'Pendiente', 'Error', 'Sin registro'] if x in m.inner_text()]
    R.shot(p, f'Paso 7: PA{PA} (en curso): "Registrar niveles" = {chk["registrar"]}; desplegables editables = {chk["editables_pa_actual"]}; indicadores de sincronización: {chk["sync"]}', full=True)
    _fin(R, chk, n)


@caso('CP-RV-02', modo='parcial', notas='El nivel esperado por grado (tabla nivel_esperado_por_grado) no está en la API: se muestra la entrada que calcula el sistema.')
def cp_rv02():
    R = Run('CP-RV-02'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); Y = D.Y(); X = D.X()
    _, act = nueva_act(C); chk['pa1'] = preparar_pa1(C, act)
    tr = A.crear_alumno('Tomas', 'Traslado QA', Y, 3, A.CL(), FE.pa(1, Y)['fecha_inicio'])
    pm = A.permiso(D.id_usuario('docente-a'), Y, 3, id_pa(1, Y), 'registro_vuelo', A.ahora() + dt.timedelta(days=30))[0]
    chk['tr_pa1'] = rv_put(C, rv_items([(tr, 1, {'id_nivel_colocado': niv('H')})], act, cid=Y))
    chk['tr_mover'] = A.api('PATCH', f'/alumnos/{tr}', A.sup(), {'id_colegio': X, 'id_grado': A.id_grado(3), 'cambio_grupo_desde': FE.pa(2)['fecha_inicio']})[0]
    A.cerrar_abiertas(C)
    R.consola(ctx, 'Precondición', [f'Ana Norte QA: K en PA1 con proyección N → {chk["pa1"]}; Beto Norte QA sin decisión en PA1',
                                    f'Tomas Traslado QA: H en PA1 en el colegio Sur (permiso {pm}) → {chk["tr_pa1"]}; pasa al colegio Norte desde el inicio del PA2 → HTTP {chk["tr_mover"]}'])
    login(p, sup_ui()); res = {}
    for g, prog, nom in [(1, 'Alfabetización', 'Grado1P1'), (2, 'Comprensión Lectora', 'Grado2P2'), (3, 'Comprensión Lectora', 'Beto Norte QA'),
                         (4, 'Comprensión Lectora', 'Grado4P2'), (5, 'Comprensión Lectora', 'Grado5P2'), (6, 'Comprensión Lectora', 'Grado6P2')]:
        abrir_rv(p, grado=f'{g}.º', sub=prog, colegio=NX(), pa='PA1')
        c = celdas(p, nom); tit = fila(p, nom).locator('td[title]').first.get_attribute('title') if fila(p, nom).count() and fila(p, nom).locator('td[title]').count() else None
        res[g] = {'entrada': c[1] if c and len(c) > 1 else None, 'texto': tit}
    chk['entradas'] = res
    R.shot(p, f'Paso 1: entrada de PA1 por grado: {res}', full=True)
    abrir_rv(p, colegio=NX(), pa='PA2')
    for nom in ['Ana Norte QA', 'Beto Norte QA', 'Tomas Traslado QA']:
        f = fila(p, nom)
        chk[nom] = (celdas(p, nom), f.locator('td[title]').first.get_attribute('title') if f.count() and f.locator('td[title]').count() else None)
    R.shot(p, f'Pasos 2-5: PA2: Ana {chk["Ana Norte QA"]}; Beto {chk["Beto Norte QA"]}; Tomas {chk["Tomas Traslado QA"]}', full=True)
    chk['api'] = {nm: pa_por_api(A.sup(), nm, 2) for nm in ['Ana Norte QA', 'Beto Norte QA', 'Tomas Traslado QA']}
    R.consola(ctx, 'Pasos 2-5: PA2 por la API (entrada | sugerencia | colocado)', [f'{k}: {v}' for k, v in chk['api'].items()])
    R.save(checks=chk); n.close()


@caso('CP-RV-03')
def cp_rv03():
    R = Run('CP-RV-03'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); PA = PA_ACT()
    D1 = D.cuenta('rv-uno'); x = D.X()
    a1 = [A.crear_alumno(f'Uno{i}', 'Equivalencia QA', x, 1, A.ALFA(), D.estado()['fechas']['inicio_anio']) for i in range(5)]
    a3 = [D.alumno(f'Extra{i:02d}') for i in range(1, 7)]
    _, act1 = nueva_act(D1)
    chk['g1'] = rv_put(D1, rv_items([(a, PA, {'id_nivel_colocado': niv(l)}) for a, l in zip(a1, ['aa', 'A', 'B', 'C', 'D'])], act1, grado=1, prog=A.ALFA()))
    A.cerrar_abiertas(D1)
    _, act = nueva_act(C)
    chk['g3'] = rv_put(C, rv_items([(a, PA, {'id_nivel_colocado': niv(l)}) for a, l in zip(a3, ['F', 'G', 'I', 'J', 'K', 'aa'])], act))
    s5, r5 = A.api('PUT', '/registro-vuelo', C, rv_items([(a3[0], PA, {'nivel_programa': 'Avanzado'})], act))
    chk['manual'] = (s5, r5.get('motivo') if isinstance(r5, dict) else r5, (r5.get('errores') or [{}])[0] if isinstance(r5, dict) else None)
    A.cerrar_abiertas(C)
    login(p, sup_ui()); abrir_rv(p, grado='1.º', sub='Alfabetización', colegio=NX(), pa=f'PA{PA}')
    chk['ui_1'] = [(f'Uno{i}', (celdas(p, f'Uno{i} Equivalencia QA') or [None] * 5)[3:5]) for i in range(5)]
    R.shot(p, f'Paso 1: 1.º (aa, A, B, C, D) en PA{PA}: {chk["ui_1"]}', full=True)
    abrir_rv(p, colegio=NX(), pa=f'PA{PA}')
    chk['ui_3'] = [(f'Extra{i:02d}', (celdas(p, f'Extra{i:02d} Rubrica QA') or [None] * 5)[3:5]) for i in range(1, 7)]
    R.shot(p, f'Pasos 2-3: 3.º (F, G, I, J, K, aa): {chk["ui_3"]}', full=True)
    p.goto(BASE + f'/estudiantes/{a3[3]}'); p.wait_for_timeout(2500)
    chk['ficha'] = re.findall(r'NIVEL COLOCADO\n\n([^\n]+)\n\n([^\n]+)', p.locator('main').inner_text())
    R.shot(p, f'Paso 4: ficha de Extra04 (J en PA{PA}): tarjeta "Nivel colocado" {chk["ficha"]}')
    R.consola(ctx, 'Paso 5: Nivel del programa enviado a mano (token del Docente)', [f'PUT /api/registro-vuelo con "nivel_programa" → HTTP {chk["manual"][0]} {chk["manual"][1]} {chk["manual"][2]}'])
    R.save(checks=chk); n.close()


@caso('CP-RV-04')
def cp_rv04():
    from casos.rub import meses_de_pa
    R = Run('CP-RV-04'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    m1, m2 = meses_de_pa(1), meses_de_pa(2)
    if len(m1) < 2 or not m2:
        R.nota(f'Faltan meses de PA1 ({m1}) o PA2 ({m2}) en el calendario de QA.'); R.save(checks=chk); n.close(); return
    _, act = nueva_act(C)
    A1, A2, A3, A4 = (D.alumno(f'Extra{i:02d}') for i in (8, 9, 10, 11))
    chk['rub'] = [rub_put(C, rub_items([(A1, 3, 2)], act, mes=m1[0])), rub_put(C, rub_items([(A1, 2, 4)], act, mes=m1[1])),
                  rub_put(C, rub_items([(A2, 2, '-')], act, mes=m1[0])), rub_put(C, rub_items([(A2, 3, 3)], act, mes=m2[0])),
                  rub_put(C, rub_items([(A3, 1, 1)], act, mes=m2[0])), rub_put(C, rub_items([(A4, 4, 4)], act, mes=m2[0]))]
    chk['pa1'] = rv_put(C, rv_items([(A3, 1, {'id_nivel_colocado': niv('aa')}), (A4, 1, {'id_nivel_colocado': niv('Z')})], act))
    A.cerrar_abiertas(C)
    M = lambda m: FE.mes_nombre(m).lower()  # noqa: E731
    R.consola(ctx, 'Precondición (por la API, Docente A con permisos de PA1 y PA2)',
              [f'Extra08: {M(m1[0])} F3 C2 y {M(m1[1])} F2 C4, ambas de PA1', f'Extra09: {M(m1[0])} solo F2 (incompleta, PA1) y {M(m2[0])} F3 C3 (completa, PA2)',
               f'Extra10: aa en PA1 y {M(m2[0])} F1 C1 en PA2', f'Extra11: Z en PA1 y {M(m2[0])} F4 C4 en PA2', f'Rúbricas: {[r[1] for r in chk["rub"]]}', f'Niveles de PA1: {chk["pa1"]}'])
    con_actividad(p, C); abrir_rv(p, pa='PA1')
    chk['ui_pa1'] = {k: (celdas(p, k) or [])[1:4] for k in ['Extra08 Rubrica QA', 'Extra09 Rubrica QA']}
    R.shot(p, f'Pasos 1-2: PA1: {chk["ui_pa1"]}', full=True)
    b = fila(p, 'Extra08').get_by_role('button', name=re.compile('Ver la rúbrica'))
    if b.count():
        b.first.click(); p.wait_for_timeout(1000); chk['ver_rubrica'] = p.locator('[role=dialog]:visible').last.inner_text()
        R.shot(p, f'Paso 1: "Ver rúbrica" de Extra08: {chk["ver_rubrica"][:250]}'); cerrar_dialogos(p)
    abrir_rv(p, pa='PA2')
    chk['ui_pa2'] = {k: (celdas(p, k) or [])[1:4] for k in ['Extra09 Rubrica QA', 'Extra10 Rubrica QA', 'Extra11 Rubrica QA']}
    R.shot(p, f'Pasos 2-4: PA2: {chk["ui_pa2"]}', full=True)
    chk['api'] = {'Extra08 PA1': pa_por_api(C, 'Extra08 Rubrica QA', 1), 'Extra09 PA1': pa_por_api(C, 'Extra09 Rubrica QA', 1),
                  'Extra10 PA2': pa_por_api(C, 'Extra10 Rubrica QA', 2), 'Extra11 PA2': pa_por_api(C, 'Extra11 Rubrica QA', 2)}
    R.consola(ctx, 'Pasos 1-4: por la API (entrada | sugerencia | colocado)', [f'{k}: entrada {(v or {}).get("entrada")}; sugerencia {(v or {}).get("sug")}; colocado {(v or {}).get("colocado")}' for k, v in chk['api'].items()])
    _fin(R, chk, n)


@caso('CP-RV-05')
def cp_rv05():
    R = Run('CP-RV-05'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); PAM = pa_de_mes(mes_actual())
    D1 = D.cuenta('rv-uno'); con_actividad(p, D1); abrir_rv(p, grado='1.º', sub='Alfabetización'); m = p.locator('main')
    ed = {}
    for k in ['PA1', 'PA2', 'PA3', 'PA4']:
        tab(p, k)
        ed[k] = (sum(1 for s in m.locator('tbody select').all() if s.is_enabled()), [l for l in m.inner_text().split('\n') if 'autorizaci' in l.lower() or 'habilitaci' in l.lower()][:1])
    chk['paso1'] = {'registrar': m.get_by_role('button', name=re.compile('Registrar niveles')).count(), 'editables_por_pa': ed}
    R.shot(p, f'Paso 1 (Docente de 1.º, solo asignación del PA vigente): {chk["paso1"]}', full=True)
    A.cerrar_abiertas(D1); n.close()
    _, act = nueva_act(C)
    CLs = [(1, 2, 2), (2, 3, 3), (3, 4, 2), (4, 1, 4), (5, 3, 1), (6, 3, 2), (7, 4, 4)]
    r1 = rub_put(C, rub_items([(D.alumno(f'Extra{i:02d}'), f, c) for i, f, c in CLs], act))
    r2 = rv_put(C, rv_items([(D.alumno(f'Extra{i:02d}'), PAM - 1, {'id_nivel_colocado': niv('J')}) for i, *_ in CLs], act)) if PAM and PAM > 1 else None
    chk['prep'] = (r1, r2); A.cerrar_abiertas(C)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    R.consola(ctx, f'Precondición de los pasos 2-7: rúbricas de {FE.mes_nombre(mes_actual()).lower()} (PA{PAM}) y entrada J en PA{PAM} para Extra01-Extra07', [str(chk['prep'])])
    con_actividad(p, C); abrir_rv(p, pa=f'PA{PAM}'); m = p.locator('main')
    nom = 'Extra02 Rubrica QA'
    s = p.get_by_label(f'Nivel colocado de {nom}', exact=True)
    chk['control'] = {'tag': s.evaluate('e=>e.tagName'), 'opciones': s.evaluate("s=>[...s.options].map(o=>o.text)")[:8], 'optgroups': s.locator('optgroup').count()}
    s.click(); p.wait_for_timeout(600)
    chk['panel'] = p.locator('[role=dialog]:visible, [role=listbox]:visible').count()
    p.keyboard.press('Escape')
    chk['antes'] = celdas(p, nom)
    R.shot(p, f'Paso 2: control de Nivel colocado: {chk["control"]}; panel "Nivel colocado" = {chk["panel"]}; fila {chk["antes"]}', full=True)
    chk['colocar'] = elegir_rv(p, nom, 'Nivel colocado', 'M'); chk['tras_colocar'] = celdas(p, nom)
    R.shot(p, f'Paso 3: Nivel colocado M → {chk["colocar"]}; fila {chk["tras_colocar"]}; avisos {toasts_txt(p)}')
    chk['proy_menor'] = elegir_rv(p, nom, 'Proyección', 'H'); chk['tras_proy'] = celdas(p, nom)
    chk['proy_sin'] = elegir_rv(p, nom, 'Proyección', 'Sin proyectar'); chk['tras_sin_proy'] = celdas(p, nom)
    R.shot(p, f'Paso 4: proyección H (inferior a M) → {chk["proy_menor"]} {chk["tras_proy"]}; "Sin proyectar" → {chk["proy_sin"]} {chk["tras_sin_proy"]}')
    try:
        fila(p, nom).get_by_role('button', name=re.compile('observación')).first.click(); p.wait_for_timeout(800)
        d = p.locator('[role=dialog]:visible').last; d.locator('textarea').fill('Lee con seguridad textos del nivel M.')
        chk['obs_botones'] = d.get_by_role('button').all_inner_texts()
        with p.expect_response(lambda r: '/api/registro-vuelo' in r.url and r.request.method == 'PUT', timeout=8000) as ri:
            d.get_by_role('button', name=re.compile('Aplicar observación|Guardar observación')).click()
        chk['obs'] = ri.value.status
    except Exception as e:
        chk['obs'] = str(e)[:60]
    p.wait_for_timeout(1200); chk['avisos'] = toasts_txt(p)
    chk['guardar_decisiones'] = m.get_by_role('button', name=re.compile('Guardar decisiones')).count()
    R.shot(p, f'Pasos 5-6: observación (botones {chk.get("obs_botones")}) → {chk["obs"]}; "Guardar decisiones" = {chk["guardar_decisiones"]}; avisos {chk["avisos"]}', full=True)
    chk['api'] = pa_por_api(C, nom, PAM)
    R.consola(ctx, 'Paso 7: lo guardado (API)', [f'Registro de Extra02 en PA{PAM}: {chk["api"]}'])
    R.nota('Paso 7: Docente, actividad, permiso, rúbrica de referencia y auditoría del registro solo se ven en la base de datos; en QA se muestra lo que devuelve la API.')
    _fin(R, chk, n)


@caso('CP-RV-06')
def cp_rv06():
    R = Run('CP-RV-06'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    nom = 'Extra09 Rubrica QA'; chk['resumen_antes'] = resumen_rv()
    con_actividad(p, C); abrir_rv(p, pa='PA1')
    chk['proy'] = elegir_rv(p, nom, 'Proyección', 'H'); chk['fila_proy'] = celdas(p, nom)
    chk['resumen_proy'] = resumen_rv()
    R.shot(p, f'Paso 1: solo proyección H en PA1 → {chk["proy"]}; fila {chk["fila_proy"]}', full=True)
    R.consola(ctx, 'Paso 1: resumen de la Supervisora (vencidos e incompletos)', [f'Antes: {chk["resumen_antes"]}', f'Con solo la proyección: {chk["resumen_proy"]}'])
    entrada = (pa_por_api(C, nom, 1) or {}).get('entrada', (None,))[0] or 'F'
    chk['colocar_igual'] = elegir_rv(p, nom, 'Nivel colocado', entrada); chk['fila_colocado'] = celdas(p, nom)
    R.shot(p, f'Paso 2: Nivel colocado {entrada} (igual a la entrada) → {chk["colocar_igual"]}; fila {chk["fila_colocado"]}', full=True)
    chk['sin_cambios'] = elegir_rv(p, nom, 'Nivel colocado', entrada); chk['guardar_decisiones'] = p.locator('main').get_by_role('button', name=re.compile('Guardar decisiones')).count()
    R.shot(p, f'Paso 3: volver a elegir {entrada} (sin cambios) → {chk["sin_cambios"]}; botón "Guardar decisiones" = {chk["guardar_decisiones"]}; avisos {toasts_txt(p)}')
    chk['api'] = pa_por_api(C, nom, 1); chk['resumen_despues'] = resumen_rv()
    R.consola(ctx, 'Paso 4: avance anual y resumen', [f'API PA1: {chk["api"]}', f'Resumen de la Supervisora: {chk["resumen_despues"]}'])
    _fin(R, chk, n)


@caso('CP-RV-07', notas='Usa un calendario particular del colegio Sur con hoy dentro del PR2 (como en local).')
def cp_rv07():
    R = Run('CP-RV-07'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; PA = PA_ACT()
    D1 = D.cuenta('rv-uno'); con_actividad(p, D1); abrir_rv(p, grado='1.º', sub='Alfabetización', pa='PA2'); m = p.locator('main')
    chk['anterior'] = ([l for l in m.inner_text().split('\n') if 'autorizaci' in l.lower()][:1], sum(1 for s in m.locator('tbody select').all() if s.is_enabled()))
    R.shot(p, f'Paso 1: PA2 para el Docente del PA vigente: {chk["anterior"]}', full=True)
    a = D.alumno('Grado1P1 Entrada QA')
    chk['futuro'] = rv_put(D1, rv_items([(a, PA, {'id_nivel_colocado': niv('A')})], act_de(D1), grado=1, prog=A.ALFA()))
    A.cerrar_abiertas(D1); n.close()
    Y = D.Y(); CR = D.cuenta('retro'); NY = D.nombre_colegio('sur')
    s, r = FE.poner_calendario_en_pr(Y, True)
    rr = A.crear_alumno('Raul', 'Retro Vuelo QA', Y, 3, A.CL(), FE.pa(1, Y)['fecha_inicio'])
    asg = A.asignar(D.id_usuario('retro'), [(Y, [3])], 'retroactivo')
    _, actr = nueva_act(CR)
    chk['pr_pa2'] = rv_put(CR, rv_items([(rr, 2, {'id_nivel_colocado': niv('G')})], actr, cid=Y))
    chk['pr_pa3_futuro'] = rv_put(CR, rv_items([(rr, 3, {'id_nivel_colocado': niv('H')})], actr, cid=Y))
    n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    R.consola(ctx, 'Pasos 2-3: colegio Sur con calendario particular (hoy en el PR2, PA3 futuro); Docente Retro con asignación Retroactiva',
              [f'Calendario → HTTP {s}; asignación → HTTP {asg[0]}', f'Paso 2: decisión de un PA futuro (PA3 del colegio Sur) → {chk["pr_pa3_futuro"]}',
               f'Paso 2 (calendario general): decisión del PA{PA} por el Docente de 1.º → {chk["futuro"]}', f'Paso 3: Retro registra PA2 durante el PR2 → {chk["pr_pa2"]}'])
    login(p, CR); p.wait_for_timeout(1500); abrir_rv(p, colegio=NY, pa='PA2')
    chk['ui_pr'] = (celdas(p, 'Raul Retro Vuelo QA'), sum(1 for x in p.locator('main tbody select').all() if x.is_enabled()))
    R.shot(p, f'Paso 3: Retro en PA2 durante el PR2: {chk["ui_pr"]}', full=True)
    s3, _ = FE.poner_calendario_en_pr(Y, False, A.calendario(Y)); chk['mover'] = s3
    _, actr = nueva_act(CR)
    v = (pa_por_api(A.sup(), 'Raul Retro Vuelo QA', 2, cid=Y) or {}).get('version')
    it = rv_items([(rr, 2, {'id_nivel_colocado': niv('H')})], actr, cid=Y); it[0]['version'] = v
    chk['fin_pr'] = rv_put(CR, it)
    pm = A.permiso(D.id_usuario('retro'), Y, 3, id_pa(2, Y), 'registro_vuelo', A.ahora() + dt.timedelta(days=30)); chk['permiso'] = pm[0]
    it = rv_items([(rr, 2, {'id_nivel_colocado': niv('H')})], actr, cid=Y); it[0]['version'] = v
    chk['con_permiso'] = rv_put(CR, it)
    chk['api'] = pa_por_api(A.sup(), 'Raul Retro Vuelo QA', 2, cid=Y)
    R.consola(ctx, 'Paso 4: fin del PR2 y permiso', [f'Calendario con el PR2 terminado → HTTP {s3}', f'Retro corrige PA2 a H sin permiso → {chk["fin_pr"]}',
                                                    f'Permiso de Registro de Vuelo de PA2 → HTTP {pm[0]}', f'Retro corrige PA2 a H con el permiso → {chk["con_permiso"]}', f'PA2 de Raul (API): {chk["api"]}'])
    n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); login(p, CR); p.wait_for_timeout(1500); abrir_rv(p, colegio=NY, pa='PA2')
    chk['ui_permiso'] = [l for l in p.locator('main').inner_text().split('\n') if 'Corrección excepcional' in l or 'autorizaci' in l.lower()][:2]
    R.shot(p, f'Paso 4: Retro en PA2 con el permiso: {chk["ui_permiso"]}', full=True)
    _fin(R, chk, n, CR)


@caso('CP-RV-08')
def cp_rv08():
    R = Run('CP-RV-08'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c()
    a = D.alumno('Extra03'); _, act = nueva_act(C)
    chk['pre'] = [rv_put(C, rv_items([(a, 1, {'id_nivel_colocado': niv('K')})], act)),
                  rv_put(C, rv_items([(a, 2, {'id_nivel_colocado': niv('M'), 'id_nivel_proyeccion': niv('O'), 'observacion': 'Decisión de PA2 con entrada K.'})], act))]
    chk['pa2_antes'] = pa_por_api(C, 'Extra03 Rubrica QA', 2); A.cerrar_abiertas(C)
    R.consola(ctx, 'Precondición: Extra03 con K en PA1 y M en PA2 (proyección O y observación)', [str(chk['pre']), f'PA2 (API): {chk["pa2_antes"]}'])
    con_actividad(p, C); abrir_rv(p, pa='PA1')
    chk['corregir'] = elegir_rv(p, 'Extra03 Rubrica QA', 'Nivel colocado', 'L')
    R.shot(p, f'Paso 1: PA1 de Extra03 corregido de K a L → {chk["corregir"]}', full=True)
    tab(p, 'PA2')
    f = fila(p, 'Extra03')
    chk['ui_pa2'] = (celdas(p, 'Extra03 Rubrica QA'), f.inner_text().replace('\n', ' | ')[:300], f.locator('[title]').evaluate_all("els=>els.map(e=>e.title)"))
    chk['aviso_pantalla'] = [l for l in p.locator('main').inner_text().split('\n') if 'cambi' in l.lower()][:3]
    R.shot(p, f'Pasos 2-3: PA2 de Extra03: {chk["ui_pa2"][0]}; títulos {chk["ui_pa2"][2]}; avisos {chk["aviso_pantalla"]}', full=True)
    chk['pa2_despues'] = pa_por_api(C, 'Extra03 Rubrica QA', 2)
    R.consola(ctx, 'Pasos 2-4: PA2 por la API', [f'Antes: {chk["pa2_antes"]}', f'Después: {chk["pa2_despues"]}'])
    _fin(R, chk, n)


@caso('CP-RV-09')
def cp_rv09():
    R = Run('CP-RV-09'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = _c(); PA = PA_ACT()
    con_actividad(p, C); abrir_rv(p, pa=f'PA{PA}')
    ctx.set_offline(True); p.wait_for_timeout(1000)
    chk['aviso_offline'] = [l for l in p.locator('main').inner_text().split('\n') if 'dispositivo' in l.lower() or 'desactualizada' in l.lower() or 'conexión' in l.lower()][:3]
    R.shot(p, f'Paso 1: sin conexión: {chk["aviso_offline"]}', full=True)
    for nm, l in [('Extra04 Rubrica QA', 'J'), ('Extra05 Rubrica QA', 'K')]:
        p.get_by_label(f'Nivel colocado de {nm}', exact=True).select_option(label=l); p.wait_for_timeout(800)
    chk['offline'] = {'filas': {k: (celdas(p, k) or [])[3:] for k in ['Extra04 Rubrica QA', 'Extra05 Rubrica QA']}, 'avisos': toasts_txt(p),
                      'barra': p.locator('header').first.inner_text()[-80:], 'indicador': [l for l in p.locator('main').inner_text().split('\n') if 'Pendiente' == l.strip()][:2]}
    R.shot(p, f'Paso 2: decisiones sin conexión: {chk["offline"]}', full=True)
    chk['idb'] = cola_idb(p)
    R.consola(ctx, 'Paso 3: operaciones en IndexedDB', chk['idb'] or ['(ninguna)'])
    ctx.set_offline(False); p.wait_for_timeout(9000)
    chk['api'] = {k: pa_por_api(C, f'{k} Rubrica QA', PA) for k in ['Extra04', 'Extra05']}
    R.consola(ctx, 'Paso 4: lo guardado tras reconectar (API)', [f'{k}: {v}' for k, v in chk['api'].items()])
    R.nota('Paso 4: la hora de recepción y de realización de cada operación solo se ve en la base de datos.')
    cortes = []

    def cortar(route):
        resp = route.fetch(); cortes.append((resp.status, route.request.post_data[:300])); route.abort()
    p.route('**/api/registro-vuelo', lambda route: cortar(route) if route.request.method == 'PUT' and not cortes else route.continue_())
    p.get_by_label('Nivel colocado de Extra06 Rubrica QA', exact=True).select_option(label='G'); p.wait_for_timeout(3000)
    chk['corte'] = {'avisos': toasts_txt(p), 'fila': (celdas(p, 'Extra06 Rubrica QA') or [])[3:], 'barra': p.locator('header').first.inner_text()[-80:], 'servidor': [c[0] for c in cortes]}
    R.shot(p, f'Paso 5: se corta la red después de que el servidor guardó: {chk["corte"]}', full=True)
    p.unroute('**/api/registro-vuelo'); p.wait_for_timeout(9000)
    ido = json.loads(cortes[0][1])[0]['id_operacion'] if cortes else None
    chk['verif'] = {'operacion': A.api('GET', f'/sincronizacion/operaciones/{ido}', C) if ido else None, 'registro': pa_por_api(C, 'Extra06 Rubrica QA', PA),
                    'barra': p.locator('header').first.inner_text()[-80:]}
    R.consola(ctx, 'Paso 5: verificación al reconectar', [f'id_operacion: {ido}', f'{chk["verif"]}'])
    ctx.set_offline(True); abrir_rv(p, grado='3.º', sub='Alfabetización'); p.wait_for_timeout(1500)
    chk['sin_copia'] = p.locator('main').inner_text()[-250:]
    R.shot(p, f'Paso 7: sin conexión, grupo no descargado: {chk["sin_copia"][-150:]}', full=True)
    p.reload(); p.wait_for_timeout(3000); chk['reabrir'] = p.locator('body').inner_text()[:200]
    R.shot(p, f'Paso 6: reabrir la aplicación sin conexión: {chk["reabrir"][:150]}')
    ctx.set_offline(False)
    _fin(R, chk, n)
