"""Calendario académico (CU027): CP-CAL-01 a CP-CAL-09, adaptados a QA.

El calendario general de QA lo comparte todo el equipo: la suite nunca lo edita. Las ediciones,
validaciones y rechazos se prueban con las fechas particulares de los colegios del caso (empiezan
como una copia del calendario general). CP-CAL-04 (editar el general) queda solo en local.
"""
import datetime as dt
import json
import re

from lib import api as A
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import SOLO_LOCAL, caso
from lib.ui import BASE, Nav, Run, con_actividad, ir, login, main_txt, textos, toasts_txt

from casos._comun import fin, sup_ui
from casos.asi import abrir_asis, controles, de_alumno, put_asis
from casos.rub import abrir_rubrica, rub_items, rub_put

SOLO_LOCAL['CP-CAL-04'] = ('Edita el calendario general, que en QA usan todos los colegios y todo el equipo; un día no lectivo nuevo '
                           'cambiaría las clases de los demás.')

UN_DIA = dt.timedelta(days=1)
KW = ['correctamente', 'No se', 'no se', 'debe', 'Debe', 'inválid', 'superpon', 'orden', 'obligatori', 'Sin conexión', 'Conéctate', 'receso', 'No hay',
      'Primero', 'Este colegio', 'Al guardar', 'calendario propio', 'fechas particulares', 'Calendario general', 'posterior', 'anterior', 'dentro',
      'registr', 'impid', 'copia', 'comprendido', 'abarcar', 'empezar', 'confirmar']


# ── Ayudas ──────────────────────────────────────────────────────────────────────────

def dlg(p):
    return p.locator('[role=dialog]:visible').last


def avisos(p):
    m = p.locator('main') if p.locator('main').count() else p.locator('body')
    out = [l.strip() for l in m.inner_text().split('\n') if l.strip() and len(l) < 400 and any(k in l for k in KW) and 'De estas fechas dependen' not in l
           and not re.match(r'^P[AR]\d', l.strip())]
    if p.locator('[role=dialog]:visible').count():
        out.append('[modal] ' + dlg(p).inner_text().replace('\n', ' | ')[:400])
    return list(dict.fromkeys(out + toasts_txt(p)))


def abrir_cal(p):
    p.goto(BASE + '/colegios'); p.wait_for_load_state('networkidle'); p.wait_for_timeout(1000)
    p.get_by_role('button', name='Calendario académico').first.click(); p.wait_for_timeout(1500)


def alcance(p, a, colegio=None):
    p.locator('main select').nth(1).select_option(label=a); p.wait_for_timeout(900)
    if colegio:
        p.locator('main select').nth(2).select_option(label=colegio); p.wait_for_timeout(1500)


def filtros(p):
    return [s.evaluate("s => s.selectedIndex >= 0 ? s.options[s.selectedIndex].text : s.value") for s in p.locator('main select').all()]


def boton(p, nombre):
    return p.locator('main').get_by_role('button', name=nombre, exact=True)


def fecha(p, etiqueta, v):
    p.get_by_label(etiqueta, exact=True).fill(v.isoformat() if isinstance(v, dt.date) else v); p.wait_for_timeout(100)


def valor(p, etiqueta):
    return p.get_by_label(etiqueta, exact=True).input_value()


def editando(p):
    return p.locator('main input[type=date]').count() > 0


def guardar_cal(p, confirmar_con=re.compile('Confirmar')):
    b = boton(p, 'Guardar').first
    if b.is_disabled():
        return ['(Guardar deshabilitado)'] + avisos(p)
    b.click(); p.wait_for_timeout(1800); r = avisos(p)
    if confirmar_con and p.locator('[role=dialog]:visible').count():
        dlg(p).get_by_role('button', name=confirmar_con).last.click(); p.wait_for_timeout(1800); r += ['→'] + avisos(p)
    return r


def cancelar_edicion(p):
    if boton(p, 'Cancelar').count():
        boton(p, 'Cancelar').click(); p.wait_for_timeout(600)
        if p.locator('[role=dialog]:visible').count():
            dlg(p).get_by_role('button', name=re.compile('Descartar')).last.click(); p.wait_for_timeout(600)


def periodos_ui(p):
    return [r.replace('\t', ' | ').replace('\n', ' ') for r in p.locator('main table').first.locator('tbody tr').all_inner_texts()]


def nolectivos_ui(p):
    t = p.locator('main table')
    return [r.replace('\t', ' | ') for r in t.nth(1).locator('tbody tr').all_inner_texts()] if t.count() > 1 else []


def nuevo_dia(p, motivo, ini, fin_=None):
    boton(p, 'Añadir día').click(); p.wait_for_timeout(300)
    k = p.locator('main input[aria-label^="Motivo del día no lectivo"]').count()
    if motivo is not None:
        fecha(p, f'Motivo del día no lectivo {k}', motivo)
    if ini:
        fecha(p, f'Inicio del día no lectivo {k}', ini); fecha(p, f'Fin del día no lectivo {k}', fin_ or ini)
    return k


def quitar_ultimo(p):
    p.locator('main').get_by_role('button', name='Quitar').last.click(); p.wait_for_timeout(200)


def junto_al_campo(p):
    return [t.strip()[:160] for t in p.locator('main table td, main table + *').all_inner_texts()
            if re.search(r'debe|Debe|obligatori|superpone|comprendido|abarcar|empezar|posterior|Ingresa|Selecciona', t)][:6]


def general():
    return A.calendario(None)


def resumen(c):
    return {'origen': c.get('origen'), 'version': c.get('version'), 'periodos': [(x['tipo'] + str(x['numero']), x['fecha_inicio'], x['fecha_fin']) for x in c['periodos']],
            'no_lectivos': [(x['motivo'], x['fecha_inicio']) for x in c['dias_no_lectivos']]}


def G():
    """Periodos del calendario general como {('PA', 1): (inicio, fin)}."""
    return {(x['tipo'], x['numero']): (A.fecha(x['fecha_inicio']), A.fecha(x['fecha_fin'])) for x in general()['periodos']}


def body_periodos(per):
    return [{'tipo': t, 'numero': n, 'fecha_inicio': a.isoformat(), 'fecha_fin': b.isoformat()} for (t, n), (a, b) in sorted(per.items(), key=lambda x: x[1][0])]


def particular(cid, per=None, dias=None):
    """Fechas particulares del colegio cid: copia del general con los periodos `per` cambiados."""
    g = general(); base = G()
    base.update(per or {})
    dn = [{'motivo': x['motivo'], 'fecha_inicio': x['fecha_inicio'], 'fecha_fin': x['fecha_fin']} for x in g['dias_no_lectivos']] + (dias or [])
    return A.api('POST', '/calendarios/particulares', A.sup(), {'id_colegio': cid, 'id_anio_escolar': A.anio(), 'periodos': body_periodos(base), 'dias_no_lectivos': dn})


def editar_particular(p, colegio):
    alcance(p, 'Por colegio', colegio)
    boton(p, 'Editar calendario').click(); p.wait_for_timeout(1000)


# ── CP-CAL-01 ───────────────────────────────────────────────────────────────────────

@caso('CP-CAL-01')
def cp_cal01():
    R = Run('CP-CAL-01'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    Y = D.Y(); g = G(); per = dict(g); a, b = g[('PA', 2)]; per[('PA', 2)] = (a, b + 7 * UN_DIA); per[('PR', 2)] = (g[('PR', 2)][0] + 7 * UN_DIA, g[('PR', 2)][1])
    s, r = particular(Y, per)
    R.consola(ctx, 'Precondición: el colegio Sur del caso con fechas particulares (API)', [f'PA2 una semana más largo → HTTP {s} {"" if s < 300 else str(r)[:200]}'])
    login(p, sup_ui()); p.goto(BASE + '/colegios'); p.wait_for_load_state('networkidle'); p.wait_for_timeout(1000); url0 = p.url
    p.get_by_role('button', name='Calendario académico').first.click(); p.wait_for_timeout(1500)
    chk['vista'] = {'misma_url': p.url == url0, 'url': p.url.replace(BASE, ''), 'barra_lateral': p.locator('aside nav').is_visible(), 'volver': boton(p, 'Volver a Colegios').count()}
    R.shot(p, f'Paso 1: vista del calendario: {chk["vista"]}')
    chk['filtros'] = [s_.evaluate("s => [s.options[s.selectedIndex].text, [...s.options].map(o => o.text)]") for s_ in p.locator('main select').all()]
    t = main_txt(p); chk['periodo_actual'] = [l for l in t.split('\n') if re.search(r'periodo:|Sin periodo aplicable|Periodo actual', l)][:3]
    R.shot(p, f'Paso 2: filtros {chk["filtros"]}; periodo actual {chk["periodo_actual"]}')
    chk['periodos'] = periodos_ui(p); chk['solo_lectura'] = not editando(p)
    R.shot(p, f'Paso 3: tabla "Periodos" ({len(chk["periodos"])} filas; solo lectura {chk["solo_lectura"]}): {chk["periodos"][:3]}…', full=True)
    chk['no_lectivos'] = {'encabezados': p.locator('main table').nth(1).locator('th').all_inner_texts() if p.locator('main table').count() > 1 else [],
                          'filas': len(nolectivos_ui(p))}
    R.shot(p, f'Pasos 4-5: "Días no lectivos" {chk["no_lectivos"]}; el periodo actual está marcado: {"Periodo actual" in t}', full=True)
    alcance(p, 'Por colegio'); chk['campo_colegio'] = p.locator('main select').count() == 3 and bool(re.search(r'COLEGIO\s*\*', main_txt(p), re.I))
    alcance(p, 'Por colegio', D.nombre_colegio('norte'))
    chk['norte'] = [l for l in main_txt(p).split('\n') if re.search(r'calendario general|Calendario general', l)][:3]
    R.shot(p, f'Paso 6: campo "Colegio" obligatorio {chk["campo_colegio"]}; colegio Norte (sin fechas particulares): {chk["norte"]}')
    alcance(p, 'Por colegio', D.nombre_colegio('sur'))
    chk['sur'] = ([l for l in main_txt(p).split('\n') if re.search(r'particular|propio', l, re.I)][:3], [r_ for r_ in periodos_ui(p) if r_.startswith('PA2')])
    R.shot(p, f'Paso 6: colegio Sur (con fechas particulares): {chk["sur"]}')
    claves = p.evaluate("""() => new Promise(res => { const r = indexedDB.open('keyval-store'); r.onerror = () => res('sin keyval-store');
        r.onsuccess = () => { const db = r.result; if (!db.objectStoreNames.length) return res([]); const st = db.transaction(db.objectStoreNames[0]).objectStore(db.objectStoreNames[0]);
          const k = st.getAllKeys(); k.onsuccess = () => res(k.result.map(String)); }; })""")
    raw = p.evaluate("""() => new Promise(res => { const r = indexedDB.open('keyval-store'); r.onsuccess = () => { const db = r.result; if (!db.objectStoreNames.length) return res('');
        const st = db.transaction(db.objectStoreNames[0]).objectStore(db.objectStoreNames[0]); const g = st.getAll(); g.onsuccess = () => res(JSON.stringify(g.result)); }; })""")
    i = raw.find('calendario'); chk['idb'] = {'claves': claves, 'tiene_calendario': i >= 0, 'extracto': raw[max(0, i - 60): i + 200] if i >= 0 else ''}
    chk['local_storage'] = p.evaluate('JSON.stringify(localStorage)')[:600]
    R.consola(ctx, 'Paso 7: IndexedDB y Local Storage', [f'IndexedDB: claves {claves}; copia del calendario {chk["idb"]["tiene_calendario"]}', chk['idb']['extracto'],
                                                       f'Local Storage: {chk["local_storage"]}'])
    boton(p, 'Volver a Colegios').click(); p.wait_for_timeout(1000)
    p.get_by_role('button', name='Calendario académico').first.click(); p.wait_for_timeout(1500)
    chk['restaurado'] = filtros(p)
    R.shot(p, f'Paso 8: al regresar, filtros {chk["restaurado"]}')
    fin(R, chk, n)


# ── CP-CAL-02 ───────────────────────────────────────────────────────────────────────

@caso('CP-CAL-02', modo='parcial', notas='No se crea el año 2027 en QA: se verifica si el selector permite elegir un año sin calendario.')
def cp_cal02():
    R = Run('CP-CAL-02'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    login(p, sup_ui()); abrir_cal(p)
    s0 = p.locator('main select').nth(0)
    chk['control_anio'] = {'opciones': s0.evaluate("s=>[...s.options].map(o=>o.text)"), 'otros_controles': p.locator('main input:not([type=date])').count()}
    R.shot(p, f'Paso 1: control de año: {chk["control_anio"]}')
    sig = str(A.hoy().year + 1)
    if sig not in chk['control_anio']['opciones']:
        R.consola(ctx, 'Paso 1', [f'El selector de año solo ofrece los años que ya existen ({chk["control_anio"]["opciones"]}): no se puede elegir {sig} '
                                  'para ver el estado vacío ni para crear su calendario.'])
        R.nota('Pasos 2-5: dependen de poder elegir un año sin calendario; quedan sin ejecutar.')
        fin(R, chk, n); return
    s0.select_option(label=sig); p.wait_for_timeout(1200)
    chk['vacio_general'] = avisos(p) + p.locator('main').get_by_role('button').all_inner_texts()
    R.shot(p, f'Paso 1: {sig} con alcance General: {chk["vacio_general"]}')
    alcance(p, 'Por colegio', D.nombre_colegio('norte')); chk['vacio_colegio'] = avisos(p) + p.locator('main').get_by_role('button').all_inner_texts()
    R.shot(p, f'Paso 2: Por colegio: {chk["vacio_colegio"]}')
    b = p.locator('main').get_by_role('button', name='Ir al calendario general')
    if b.count():
        b.first.click(); p.wait_for_timeout(1000)
    chk['ir_general'] = filtros(p)
    R.shot(p, f'Paso 2: tras "Ir al calendario general": {chk["ir_general"]}')
    c = p.locator('main').get_by_role('button', name=re.compile('Crear calendario'))
    if c.count():
        c.first.click(); p.wait_for_timeout(1000)
        chk['form'] = {'filtros_bloqueados': [x.is_disabled() for x in p.locator('main select').all()], 'fechas': p.locator('main input[type=date]').count(),
                       'vacias': all(not i.input_value() for i in p.locator('main input[type=date]').all()), 'botones': p.locator('main').get_by_role('button').all_inner_texts()}
        R.shot(p, f'Paso 3: formulario de creación (no se guarda): {chk["form"]}', full=True)
        cancelar_edicion(p)
    R.nota(f'Pasos 4-5: crear el año escolar {sig} y su calendario general cambiaría QA para todo el equipo; no se guarda.')
    fin(R, chk, n)


# ── CP-CAL-03 ───────────────────────────────────────────────────────────────────────

@caso('CP-CAL-03', modo='parcial', notas='Se valida sobre las fechas particulares del colegio Norte del caso, no sobre el calendario general.')
def cp_cal03():
    R = Run('CP-CAL-03'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    X = D.X(); g = G(); s, _ = particular(X); antes = resumen(A.calendario(X))
    R.consola(ctx, 'Precondición: fechas particulares del colegio Norte, copia del calendario general (API)', [f'HTTP {s}'])
    login(p, sup_ui()); abrir_cal(p); editar_particular(p, D.nombre_colegio('norte'))
    R.shot(p, 'Editar las fechas particulares del colegio Norte', full=True)
    dn = A.calendario(X)['dias_no_lectivos']; existente = A.fecha(dn[-1]['fecha_inicio']) if dn else None

    def prueba(clave, acciones, deshacer):
        # Cada prueba parte de las fechas guardadas: se cancela la edición anterior y se vuelve a editar
        if editando(p):
            cancelar_edicion(p)
        boton(p, 'Editar calendario').click(); p.wait_for_timeout(1000)
        acciones(); r = guardar_cal(p)
        chk[clave] = {'avisos': [x for x in r if not x.startswith('Un receso de un solo')], 'junto_al_campo': junto_al_campo(p),
                      'marcados': p.locator('main [aria-invalid=true]').evaluate_all("els => els.map(e => e.getAttribute('aria-label'))"), 'sigue_editando': editando(p)}
        R.shot(p, f'{clave}: {chk[clave]}', full=True)
        if editando(p):
            cancelar_edicion(p)
    pa1, pa2, pa3, pr2, pr4 = g[('PA', 1)], g[('PA', 2)], g[('PA', 3)], g[('PR', 2)], g[('PR', 4)]
    prueba('Paso 1: fin de PA3 vacío', lambda: fecha(p, 'Fin de PA3', ''), lambda: fecha(p, 'Fin de PA3', pa3[1]))
    prueba('Paso 2: inicio de PA2 posterior a su fin', lambda: fecha(p, 'Inicio de PA2', pa2[1] + 5 * UN_DIA), lambda: fecha(p, 'Inicio de PA2', pa2[0]))
    prueba('Paso 3: PA3 superpuesto con el receso anterior', lambda: fecha(p, 'Inicio de PA3', pr2[1] - 3 * UN_DIA), lambda: fecha(p, 'Inicio de PA3', pa3[0]))
    prueba('Paso 4: PA2 antes que PA1', lambda: (fecha(p, 'Inicio de PA2', pa1[0] - 40 * UN_DIA), fecha(p, 'Fin de PA2', pa1[0] - 10 * UN_DIA)),
           lambda: (fecha(p, 'Inicio de PA2', pa2[0]), fecha(p, 'Fin de PA2', pa2[1])))
    prueba(f'Paso 5a: día no lectivo fuera de todo periodo ({FE.legible(pr4[1] + 10 * UN_DIA)})', lambda: nuevo_dia(p, 'Fuera QA', pr4[1] + 10 * UN_DIA), lambda: quitar_ultimo(p))
    if existente:
        prueba(f'Paso 5b: día superpuesto con el {FE.legible(existente)}', lambda: nuevo_dia(p, 'Superpuesto QA', existente), lambda: quitar_ultimo(p))
    prueba('Paso 5c: día sin motivo', lambda: nuevo_dia(p, '', g[('PA', 4)][1] - 3 * UN_DIA), lambda: quitar_ultimo(p))
    doce = dt.date(pa1[0].year + 1, pa1[0].month, min(pa1[0].day + 4, 28))
    prueba(f'Paso 8: fin del receso posterior a PA4 el {FE.legible(doce)} (más de 12 meses)', lambda: fecha(p, 'Fin de PR4', doce), lambda: fecha(p, 'Fin de PR4', pr4[1]))
    chk['sin_cambios_1_8'] = resumen(A.calendario(X)) == antes
    pr3 = g[('PR', 3)]; fin_pr4 = dt.date(pr4[0].year + 1, 1, 10)
    dentro_pr4 = pr4[0] + 2 * UN_DIA; un_dia = g[('PA', 4)][1] - 6 * UN_DIA
    while un_dia.isoweekday() > 5:
        un_dia -= UN_DIA

    def validos():
        fecha(p, 'Fin de PR3', pr3[0]); fecha(p, 'Inicio de PA4', pr3[0] + UN_DIA); fecha(p, 'Fin de PR4', fin_pr4)
        nuevo_dia(p, 'Un día QA', un_dia); nuevo_dia(p, 'Dentro de PR QA', dentro_pr4)
    prueba(f'Pasos 6-7: receso de un día ({FE.legible(pr3[0])}), PR4 hasta el {FE.legible(fin_pr4)}, día de una fecha y día dentro del PR4', validos, lambda: None)
    c = resumen(A.calendario(X)); chk['guardado_6_7'] = (c['periodos'][5:], [x for x in c['no_lectivos'] if 'QA' in x[0]])
    R.consola(ctx, 'Pasos 1-8: fechas guardadas del colegio Norte (API)', [f'Sin cambios tras los pasos 1 a 5 y 8: {chk["sin_cambios_1_8"]}',
              f'Guardado en los pasos 6-7 (PR3, PA4 y PR4 | días QA): {chk["guardado_6_7"]}'])
    R.nota('Paso 9: el PA1 en otro año se valida al crear el calendario de un año nuevo; en QA no se crea un año.')
    fin(R, chk, n)


# ── CP-CAL-05 ───────────────────────────────────────────────────────────────────────

@caso('CP-CAL-05', modo='parcial', notas='El paso 4 (editar el calendario general) no se hace en QA.')
def cp_cal05():
    R = Run('CP-CAL-05'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    Y = D.Y(); nom = D.nombre_colegio('sur'); g0 = resumen(general()); g = G()
    login(p, sup_ui()); abrir_cal(p); alcance(p, 'Por colegio', nom)
    boton(p, 'Crear fechas particulares').click(); p.wait_for_timeout(1000)
    chk['form'] = {'precargado': valor(p, 'Inicio de PA1'), 'general': g[('PA', 1)][0].isoformat(), 'filtros_bloqueados': [x.is_disabled() for x in p.locator('main select').all()],
                   'aviso': [l for l in avisos(p) if 'Al guardar' in l or 'calendario propio' in l]}
    R.shot(p, f'Paso 1: propuesta: {chk["form"]}', full=True)
    a, b = g[('PA', 2)]; fecha(p, 'Fin de PA2', b + 7 * UN_DIA); fecha(p, 'Inicio de PR2', g[('PR', 2)][0] + 7 * UN_DIA)
    chk['guardar'] = guardar_cal(p)
    chk['etiqueta'] = [l for l in main_txt(p).split('\n') if re.search(r'particular|Calendario general', l)][:3]
    chk['general_igual'] = resumen(general()) == g0; chk['api'] = A.calendario(Y).get('origen')
    R.shot(p, f'Paso 2: {chk["guardar"]}; etiqueta {chk["etiqueta"]}; origen según la API {chk["api"]}; el general no cambió {chk["general_igual"]}', full=True)
    chk['botones'] = p.locator('main').get_by_role('button').all_inner_texts()
    R.shot(p, f'Paso 3: botones en consulta: {chk["botones"]}')
    R.nota('Paso 4: editar el calendario general para comprobar que el colegio no recibe el cambio modificaría QA para todo el equipo; no se hace.')
    u = p.locator('main').get_by_role('button', name=re.compile('Usar calendario general'))
    if u.count():
        u.first.click(); p.wait_for_timeout(800)
        chk['modal'] = dlg(p).inner_text()[:400] if p.locator('[role=dialog]:visible').count() else None
        R.shot(p, f'Paso 5: modal: {chk["modal"]}')
        if chk['modal']:
            dlg(p).get_by_role('button', name='Cancelar').last.click(); p.wait_for_timeout(800)
            chk['tras_cancelar'] = A.calendario(Y).get('origen')
            R.shot(p, f'Paso 5: tras "Cancelar" el colegio sigue con origen {chk["tras_cancelar"]}')
            u.first.click(); p.wait_for_timeout(600)
            c = dlg(p).get_by_role('button', name='Confirmar').last; c.click(); p.wait_for_timeout(120)
            chk['deshabilitado'] = p.locator('[role=dialog]:visible button:disabled').count() > 0
            p.wait_for_timeout(2000); chk['confirmado'] = avisos(p)
    chk['etiqueta2'] = [l for l in main_txt(p).split('\n') if re.search(r'particular|Calendario general', l)][:3]
    chk['api2'] = A.calendario(Y).get('origen'); chk['iguales_al_general'] = resumen(A.calendario(Y))['periodos'] == g0['periodos']
    R.shot(p, f'Paso 6: {chk.get("confirmado")}; botón deshabilitado al procesar {chk.get("deshabilitado")}; etiqueta {chk["etiqueta2"]}; origen {chk["api2"]}')
    R.consola(ctx, 'Paso 6: el colegio Sur según la API', [f'Origen {chk["api2"]}; periodos iguales al general: {chk["iguales_al_general"]}'])
    R.nota('Paso 7: el historial del calendario particular y la auditoría están en la base de datos; en QA no hay una consulta para verlos.')
    fin(R, chk, n)


# ── CP-CAL-06 ───────────────────────────────────────────────────────────────────────

@caso('CP-CAL-06', modo='parcial', notas='Los rechazos se prueban sobre fechas particulares de los colegios del caso.')
def cp_cal06():
    R = Run('CP-CAL-06'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    X, Y = D.X(), D.Y(); g = G()
    # Colegio A (Norte): fechas particulares iguales al general y una asistencia el último día de clase del PA anterior (con permiso)
    particular(X)
    C = D.cuenta('docente-a'); pa = FE.pa_anterior(X); uid = D.id_usuario('docente-a')
    b = {'id_anio_escolar': A.anio(), 'id_colegio': X, 'id_grado': A.id_grado(3), 'id_periodo_academico': pa['id_periodo_academico'], 'modulo': 'asistencias',
         'fin': A.iso(A.ahora() + dt.timedelta(days=1)), 'motivo': 'Prueba QA automatizada', 'desde_ahora': True}
    sp = A.api('POST', f'/usuarios/{uid}/permisos', A.sup(), b)[0]
    fa = FE.clases_del_pa(3, pa['numero'], X)[-1]
    A.cerrar_abiertas(C); act = A.iniciar_actividad(C)
    sa = put_asis(C, fa, [(D.alumno('Ana Norte QA'), 'presente', None)], act)
    # Colegio B (Sur): PA anterior una semana más largo y una asistencia en esa semana
    pk = pa['numero']; per = {('PA', pk): (g[('PA', pk)][0], g[('PA', pk)][1] + 7 * UN_DIA)}
    sig = [k for k in g if g[k][0] > g[('PA', pk)][1]]
    for k in sorted(sig, key=lambda k: g[k][0]):
        a_, b_ = g[k]
        if a_ <= g[('PA', pk)][1] + 7 * UN_DIA:
            per[k] = (g[('PA', pk)][1] + 8 * UN_DIA, max(b_, g[('PA', pk)][1] + 8 * UN_DIA)) if k[0] == 'PR' else (g[('PA', pk)][1] + 10 * UN_DIA, b_)
    sy = particular(Y, per)
    R5 = D.cuenta('retro'); u5 = D.id_usuario('retro'); semana = [g[('PA', pk)][1] + i * UN_DIA for i in range(1, 8)]
    pa_y = FE.pa_anterior(Y) or pa
    b['id_colegio'] = Y; b['id_grado'] = A.id_grado(5); b['id_periodo_academico'] = pa_y['id_periodo_academico']
    sp2 = A.api('POST', f'/usuarios/{u5}/permisos', A.sup(), b)[0]
    fy = next((d for d in semana if d in FE.clases_habituales(5, d, d, Y)), None)
    A.cerrar_abiertas(R5); act5 = A.iniciar_actividad(R5)
    al5 = A.alumnos(Y, 5)
    sb = put_asis(R5, fy, [(al5[0]['id'], 'presente', None)], act5, grado=5, colegio=Y) if fy and al5 else 'sin clase del 5.º en la semana extra'
    A.finalizar_actividad(R5, act5); A.finalizar_actividad(C, act)
    a0, b0 = de_alumno(fa, 'Ana Norte QA'), resumen(A.calendario(Y))
    R.consola(ctx, 'Precondición (API)', [f'Colegio A (Norte): fechas particulares iguales al general; permiso de Docente A para PA{pk} → HTTP {sp}; '
                                          f'asistencia del {FE.legible(fa)} (último día de clase de PA{pk}) → {sa}',
                                          f'Colegio B (Sur): PA{pk} una semana más largo → HTTP {sy[0]} {"" if sy[0] < 300 else str(sy[1])[:200]}; '
                                          f'permiso del Docente Retroactivo → HTTP {sp2}; asistencia del {FE.legible(fy) if fy else "-"} → {sb}'])
    login(p, sup_ui()); abrir_cal(p); editar_particular(p, D.nombre_colegio('norte'))
    nuevo_dia(p, 'Día con asistencias QA', fa); chk['paso1'] = guardar_cal(p)
    R.shot(p, f'Paso 1: día no lectivo en la fecha de la asistencia: {chk["paso1"]}', full=True)
    if editando(p):
        quitar_ultimo(p)
    else:
        boton(p, 'Editar calendario').click(); p.wait_for_timeout(800)
    fecha(p, f'Fin de PA{pk}', fa - UN_DIA); fecha(p, f'Inicio de PR{pk}', fa)
    chk['paso2'] = guardar_cal(p)
    R.shot(p, f'Paso 2: fin de PA{pk} antes de la asistencia: {chk["paso2"]}', full=True)
    chk['paso3'] = {'sigue_editando': editando(p), 'propuesta': valor(p, f'Fin de PA{pk}') if editando(p) else None,
                    'guardado_igual': resumen(A.calendario(X))['periodos'] == resumen(general())['periodos']}
    R.shot(p, f'Paso 3: {chk["paso3"]}')
    cancelar_edicion(p)
    alcance(p, 'Por colegio', D.nombre_colegio('sur'))
    u = p.locator('main').get_by_role('button', name=re.compile('Usar calendario general'))
    if u.count():
        u.first.click(); p.wait_for_timeout(600)
        if p.locator('[role=dialog]:visible').count():
            dlg(p).get_by_role('button', name='Confirmar').last.click(); p.wait_for_timeout(2000)
    chk['paso4'] = {'modal_abierto': p.locator('[role=dialog]:visible').count(), 'avisos': avisos(p), 'origen': A.calendario(Y).get('origen')}
    R.shot(p, f'Paso 4: "Usar calendario general" en el colegio Sur: {chk["paso4"]}', full=True)
    chk['paso5'] = {'asistencia_A': (a0, de_alumno(fa, 'Ana Norte QA')), 'calendario_B_igual': resumen(A.calendario(Y)) == b0}
    R.consola(ctx, 'Paso 5: registros y calendarios por la API', [f'Asistencia de Ana antes y después: {chk["paso5"]["asistencia_A"]}',
                                                                f'Calendario del colegio Sur sin cambios: {chk["paso5"]["calendario_B_igual"]}'])
    fin(R, chk, n, C, R5)


# ── CP-CAL-07 ───────────────────────────────────────────────────────────────────────

@caso('CP-CAL-07', modo='parcial', notas='Se usa el colegio Norte del caso; el backend "detenido" se simula cortando la respuesta en el navegador.')
def cp_cal07():
    R = Run('CP-CAL-07'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    X = D.X(); nom = D.nombre_colegio('norte'); particular(X); g = G()
    login(p, sup_ui()); abrir_cal(p); alcance(p, 'Por colegio', nom)
    R.shot(p, 'Precondición: calendario consultado con conexión')
    ctx.set_offline(True); p.wait_for_timeout(500)
    boton(p, 'Volver a Colegios').click(); p.wait_for_timeout(1200)
    try:
        p.get_by_role('button', name='Calendario académico').first.click(timeout=4000); p.wait_for_timeout(2000)
    except Exception as e:
        chk['abrir_offline'] = str(e).split('\n')[0][:80]
    chk['offline'] = {'avisos': avisos(p), 'filas': len(periodos_ui(p)) if p.locator('main table').count() else 0, 'solo_lectura': not editando(p)}
    R.shot(p, f'Paso 1: calendario sin conexión: {chk["offline"]}', full=True)
    e = boton(p, 'Editar calendario')
    chk['editar'] = {'visible': e.count(), 'deshabilitado': e.first.is_disabled() if e.count() else None, 'aviso': [x for x in avisos(p) if 'Conéctate' in x]}
    R.shot(p, f'Paso 2: "Editar calendario": {chk["editar"]}')
    R.nota('Paso 3: en QA el selector de año solo ofrece el año actual; no hay otro año que elegir.')
    ctx.set_offline(False); abrir_cal(p); alcance(p, 'Por colegio', nom)
    boton(p, 'Editar calendario').click(); p.wait_for_timeout(800)
    nueva = g[('PR', 4)][1] - UN_DIA; fecha(p, 'Fin de PR4', nueva)
    ctx.set_offline(True); p.wait_for_timeout(1500)
    chk['edicion_offline'] = {'avisos': avisos(p), 'guardar_deshabilitado': boton(p, 'Guardar').first.is_disabled()}
    R.shot(p, f'Paso 4: edición sin conexión: {chk["edicion_offline"]}')
    ls = p.evaluate('JSON.stringify(localStorage)')
    raw = p.evaluate("""() => new Promise(res => { const r = indexedDB.open('keyval-store'); r.onsuccess = () => { const db = r.result; if (!db.objectStoreNames.length) return res('');
        const st = db.transaction(db.objectStoreNames[0]).objectStore(db.objectStoreNames[0]); const g = st.getAll(); g.onsuccess = () => res(JSON.stringify(g.result)); }; })""")
    chk['almacen'] = {'local_storage_con_fecha': nueva.isoformat() in ls, 'idb_con_fecha': nueva.isoformat() in raw}
    R.consola(ctx, 'Paso 5: almacenamiento local durante la edición', [f'La fecha editada ({nueva}) aparece en Local Storage: {chk["almacen"]["local_storage_con_fecha"]}; '
                                                                    f'en IndexedDB: {chk["almacen"]["idb_con_fecha"]}', f'Local Storage: {ls[:400]}'])
    ctx.set_offline(False); p.wait_for_timeout(1200)

    def cortar(route):
        if route.request.method in ('PUT', 'POST', 'PATCH'):
            try:
                route.fetch()
            except Exception:
                pass
            route.abort()
        else:
            route.continue_()
    p.route(re.compile(r'.*/api/calendarios.*'), cortar)
    chk['caida'] = {'avisos': guardar_cal(p), 'guardar_bloqueado': boton(p, 'Guardar').first.is_disabled() if boton(p, 'Guardar').count() else None}
    R.shot(p, f'Paso 6: guardado sin respuesta del servidor (la petición llega, la respuesta se corta): {chk["caida"]}')
    p.unroute(re.compile(r'.*/api/calendarios.*')); p.wait_for_timeout(8000)
    chk['recupera'] = {'avisos': avisos(p), 'editando': editando(p), 'fin_pr4_guardado': resumen(A.calendario(X))['periodos'][-1]}
    R.shot(p, f'Paso 7: con el servidor respondiendo otra vez: {chk["recupera"]}')
    fin(R, chk, n)


# ── CP-CAL-09 ───────────────────────────────────────────────────────────────────────

@caso('CP-CAL-09', notas='El día no lectivo "Feriado regional" se pone en las fechas particulares del colegio Norte del caso, en el PA vigente.')
def cp_cal09():
    from casos.lec import abrir_lec
    R = Run('CP-CAL-09'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    X = D.X(); C = D.cuenta('docente-a'); hoy = A.hoy(); pa = FE.pa_actual(X)
    pasadas = [d for d in FE.clases_habituales(3, pa['fecha_inicio'], hoy - UN_DIA, X)]
    if not pasadas:
        R.nota('El PA vigente todavía no tiene una clase pasada del 3.º.'); fin(R, chk, n); return
    feriado = pasadas[-1]
    s, r = particular(X, dias=[{'motivo': 'Feriado regional', 'fecha_inicio': feriado.isoformat(), 'fecha_fin': feriado.isoformat()}])
    pr = G()[('PR', pa['numero'] - 1)] if pa['numero'] > 1 else None
    R.consola(ctx, 'Precondición (API)', [f'Día no lectivo "Feriado regional" el {FE.legible(feriado)} (clase del 3.º en PA{pa["numero"]}, ya pasada) → HTTP {s} '
                                          f'{"" if s < 300 else str(r)[:200]}'])
    con_actividad(p, C)
    abrir_asis(p, feriado); t = main_txt(p)
    chk['paso1'] = {'mensaje': [l for l in t.split('\n') if 'no lectivo' in l.lower()][:2], 'controles': controles(p)}
    R.shot(p, f'Paso 1: Asistencias del {FE.legible(feriado)}: {chk["paso1"]}')
    if pr:
        abrir_asis(p, pr[0]); chk['paso2'] = {'mensaje': [l for l in main_txt(p).split('\n') if 'receso' in l.lower()][:2], 'controles': controles(p)}
        R.shot(p, f'Paso 2: fecha del receso anterior ({FE.legible(pr[0])}): {chk["paso2"]}')
    sem, mes, *_ = FE.semana_de(feriado)
    if sem:
        abrir_lec(p, sem, mes); t = main_txt(p)
        chk['paso3'] = {'no_realizada': 'No realizada' in t, 'feriado': [l for l in t.split('\n') if 'Feriado' in l or 'no lectivo' in l.lower()][:3]}
        R.shot(p, f'Paso 3: Seguimiento de Lectura de esa semana: {chk["paso3"]}', full=True)
    pa_ant = FE.pa_anterior(X)
    if pa_ant:
        from casos.rub import meses_de_pa
        mes_ant = meses_de_pa(pa_ant['numero'], X)[-1]
        abrir_rubrica(p, mes=mes_ant); chk['paso4_ui'] = {'selects_habilitados': p.locator('main tbody select:enabled').count(), 'avisos': textos(p, 'permiso', 'periodo', 'cerrado')[:3]}
        act = A.actividad_en_curso(C)
        chk['paso4_api'] = rub_put(C, rub_items([(D.alumno('Ana Norte QA'), 3, 3)], act, mes=mes_ant))
        R.shot(p, f'Paso 4: Rúbrica de {FE.mes_nombre(mes_ant)} (PA{pa_ant["numero"]}, cerrado) sin permiso: {chk["paso4_ui"]}')
        R.consola(ctx, 'Paso 4: la misma evaluación por la API', [f'PUT /api/rubricas → {chk["paso4_api"]}'])
    fin(R, chk, n, C)
