"""Permisos de corrección (CU028): CP-PER-01 a 05 y CP-PER-10, adaptados a QA.

- El Docente de los casos es Docente B (4.º del colegio Norte del caso); Supervisora en la interfaz:
  supervisor-2 (la Supervisora E2E otorga los permisos de la precondición por la API).
- El "colegio X" de CP-PER-02 a 04 es un colegio propio con un calendario particular en que hoy está
  en el receso posterior a PA2: PA1 tiene el plazo ordinario cerrado y PA2 está en su PR.
- Los permisos vencidos no se pueden fechar en el pasado: se otorgan con un fin cercano (1 a 3 minutos)
  y el caso espera a que venzan.
- Lo que en local se leía en la tabla permiso_correccion se lee con GET /usuarios/{id}/permisos.
"""
import datetime as dt
import json
import re
import time

from lib import api as A
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import caso
from lib.ui import (BASE, Nav, Run, cerrar_dialogos, cola_idb, con_actividad, dlg, idb_todo, ir, login, main_txt, toasts_txt,
                    token_navegador)

from casos._comun import crear_colegio, fin, hay_dialogo, hhmmss, sup_ui
from casos.asi import abrir_asis, marcar_asis, put_asis
from casos.rub import meses_de_pa, rub_items, rub_put
from casos.usr import abrir_usuarios, buscar, fila_usr


def _b():
    return D.cuenta('docente-b')


def dl(t):
    return t.strftime('%Y-%m-%dT%H:%M')


def ahora():
    return A.ahora().replace(microsecond=0)


# ── Pantalla de permisos ───────────────────────────────────────────────────────────

def abrir_permisos(p, correo):
    abrir_usuarios(p); buscar(p, correo)
    fila_usr(p, correo).get_by_role('button', name=re.compile('^Otorgar permisos')).first.click(); p.wait_for_timeout(1800)


def tabla_perm(p):
    return [r.replace('\t', ' | ') for r in p.locator('main tbody tr').all_inner_texts()]


def filtro(p, etiqueta, valor):
    s = p.locator('main').get_by_label(etiqueta, exact=True)
    opciones = [o.strip() for o in s.locator('option').all_inner_texts()]
    s.select_option(label=next((o for o in opciones if o.startswith(valor)), valor)); p.wait_for_timeout(400)


def aplicar(p):
    b = p.locator('main').get_by_role('button', name='Filtrar')
    if b.count():
        b.first.click()
    p.wait_for_timeout(1500)


def abrir_otorgar(p):
    p.locator('main').get_by_role('button', name='Otorgar permiso').first.click(); p.wait_for_timeout(900)
    return dlg(p)


def _lab(d, etiqueta):
    return d.get_by_label(re.compile('^' + re.escape(etiqueta) + r'\s*\*?$'))


def _sel(d, etiqueta, valor):
    s = _lab(d, etiqueta)
    opciones = [o.strip() for o in s.locator('option').all_inner_texts()]
    s.select_option(label=next((o for o in opciones if o.startswith(valor)), valor)); d.page.wait_for_timeout(900)


def ahora_mismo(d, valor):
    c = d.get_by_label('Empezar ahora mismo')
    if c.count() and c.first.is_checked() != valor:
        c.first.click(); d.page.wait_for_timeout(300)


def llenar_otorgar(d, colegio, grado, periodo, modulo, fin_, motivo, desde_ahora=True, inicio=None):
    _sel(d, 'Año escolar', str(A.hoy().year)); _sel(d, 'Colegio', colegio)
    if grado:
        _sel(d, 'Grado', grado)
    if periodo:
        _sel(d, 'Periodo académico', periodo)
    if modulo:
        _sel(d, 'Módulo autorizado', modulo)
    ahora_mismo(d, desde_ahora)
    if inicio is not None:
        d.get_by_label('Inicio de vigencia').fill(inicio)
    if fin_ is not None:
        d.get_by_label('Fin de vigencia').fill(fin_)
    if motivo is not None:
        d.locator('textarea').first.fill(motivo)


def errores_dlg(p):
    if not hay_dialogo(p):
        return ['(el modal se cerró)']
    t = dlg(p).inner_text().split('\n')
    return [l.strip() for l in t if l.strip() and re.search(r'Ingresa|Selecciona|debe|posterior|Ya existe|todavía|inactiva|calendario|Sin conexión|No se pudo|ya fue|ya venció|obligatori|descartar|admite', l)]


def otorgar(p):
    d = dlg(p); b = d.get_by_role('button', name='Otorgar permiso', exact=True).last
    if b.is_disabled():
        return ['(Otorgar deshabilitado)'] + errores_dlg(p)
    b.click(); p.wait_for_timeout(150)
    des = b.is_disabled() if hay_dialogo(p) else None
    p.wait_for_timeout(1800)
    return [f'(botón deshabilitado al procesar: {des})'] + errores_dlg(p) + toasts_txt(p)


def revocar_fila(p, i=0):
    p.locator('main tbody tr').nth(i).get_by_role('button', name='Revocar').click(); p.wait_for_timeout(800)
    return dlg(p)


def ver_permiso(p, i=0):
    p.locator('main tbody tr').nth(i).get_by_role('button', name='Ver permiso').click(); p.wait_for_timeout(800)
    return dlg(p)


def permisos_api(uid):
    """Lo que en local salía de permiso_correccion."""
    items = A.todas_las_paginas(f'/usuarios/{uid}/permisos', A.sup())
    return [{k: x.get(k) for k in ('id', 'colegio', 'grado', 'periodo_academico', 'modulo', 'estado', 'inicio', 'fin', 'motivo', 'otorgado_por', 'otorgado_en',
                                   'revocado_por', 'revocado_en', 'motivo_revocacion') if k in x} for x in items]


def perm(uid, cid, grado, id_pa, modulo, fin_, inicio=None, motivo='Prueba QA automatizada'):
    b = {'id_anio_escolar': A.anio(), 'id_colegio': cid, 'id_grado': A.id_grado(grado), 'id_periodo_academico': id_pa, 'modulo': modulo,
         'fin': A.iso(fin_), 'motivo': motivo}
    if inicio:
        b['inicio'] = A.iso(inicio); b['desde_ahora'] = False
    else:
        b['desde_ahora'] = True
    return A.api('POST', f'/usuarios/{uid}/permisos', A.sup(), b)


def revocar_api(uid, pid, motivo='Revocado QA'):
    return A.api('POST', f'/usuarios/{uid}/permisos/{pid}/revocar', A.sup(), {'motivo': motivo})


def colegio_receso(R, ctx, grados=(3,)):
    """Colegio X: hoy en el receso posterior a PA2 (PA1 cerrado, PA2 en su PR), con alumnos en sus grados."""
    cid = crear_colegio(f'QA AUTO {hhmmss()} Receso X', {g: min(A.hoy().isoweekday(), 5) for g in grados})
    s, r = FE.poner_calendario_en_pr(cid, True)
    for g in grados:
        A.crear_alumno('Alumno', f'Receso QA {g}', cid, g, A.CL(), FE.pa(1, cid)['fecha_inicio'])
    nombre = A.colegio(cid)['nombre']
    R.consola(ctx, 'Precondición: colegio X (API)', [f'{nombre}: calendario particular con hoy en el receso posterior a PA2 → HTTP {s} {"" if s < 300 else str(r)[:200]}',
                                                    f'Periodo de hoy: {A.periodo_actual(cid)}'])
    return cid, nombre


def pa_cerrado(cid=None):
    p = FE.pa_anterior(cid or D.X())
    return p


# ── CP-PER-01 ───────────────────────────────────────────────────────────────────────

@caso('CP-PER-01')
def cp_per01():
    R = Run('CP-PER-01'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    B = _b(); uid = D.id_usuario('docente-b'); X = D.X(); pa = pa_cerrado(X); t = ahora()
    vig = perm(uid, X, 4, pa['id_periodo_academico'], 'asistencias', t + dt.timedelta(days=3))
    prog = perm(uid, X, 4, pa['id_periodo_academico'], 'rubrica', t + dt.timedelta(days=5), inicio=t + dt.timedelta(days=2))
    rev = perm(uid, X, 4, pa['id_periodo_academico'], 'registro_vuelo', t + dt.timedelta(days=4))
    srev = revocar_api(uid, rev[1]['id'], 'Corrección completada') if rev[0] == 201 else None
    ven = perm(uid, X, 4, pa['id_periodo_academico'], 'lectura', t + dt.timedelta(seconds=70))
    R.consola(ctx, f'Precondición (API): permisos de Docente B en el 4.º del colegio Norte, PA{pa["numero"]}',
              [f'Vigente (Asistencias) → HTTP {vig[0]}', f'Programado (Rúbrica, empieza en 2 días) → HTTP {prog[0]}',
               f'Revocado (Registro de Vuelo) → HTTP {rev[0]}, revocación HTTP {srev and srev[0]}',
               f'Seguimiento de Lectura con fin en 70 segundos (para el estado Vencido) → HTTP {ven[0]}; se espera a que venza'])
    while ahora() < t + dt.timedelta(seconds=75):
        time.sleep(2)
    login(p, sup_ui()); abrir_permisos(p, B.correo)
    chk['filtros'] = [(s.evaluate("s=>s.selectedIndex>=0?s.options[s.selectedIndex].text:''"), s.evaluate("s=>[...s.options].map(o=>o.text).slice(0,6)"))
                      for s in p.locator('main select').all()]
    chk['cabeceras'] = [x.strip() for x in p.locator('main thead th').all_inner_texts()]; chk['filas'] = tabla_perm(p)
    chk['revocar_por_fila'] = [(f.split(' | ')[-2] if ' | ' in f else f, p.locator('main tbody tr').nth(i).get_by_role('button', name='Revocar').count()) for i, f in enumerate(chk['filas'])]
    R.shot(p, f'Pasos 1-3: filtros {[f[0] for f in chk["filtros"]]}; columnas {chk["cabeceras"]}; "Revocar" por fila {chk["revocar_por_fila"]}', full=True)
    api_p = permisos_api(uid)
    R.consola(ctx, 'Paso 4: orden y horas (tabla y API; en local, la base de datos)', chk['filas'] + ['API (estado | inicio | fin | otorgado):'] +
              [f'{x.get("modulo")} {x.get("estado")} {x.get("inicio")} {x.get("fin")} {x.get("otorgado_en")}' for x in api_p])
    i = next((k for k, f in enumerate(chk['filas']) if 'Revocado' in f), None)
    if i is not None:
        dd = ver_permiso(p, i); chk['ver_revocado'] = dd.inner_text().replace('\n', ' | ')[:700]; chk['ver_botones'] = dd.get_by_role('button').all_inner_texts()
        R.shot(p, f'Paso 5: detalle del revocado: botones {chk["ver_botones"]}')
        cerrar_dialogos(p)
    filtro(p, 'Estado del permiso', 'Vencido'); aplicar(p); chk['f_vencido'] = tabla_perm(p)
    filtro(p, 'Módulo', 'Rúbrica'); aplicar(p)
    chk['f_vacio'] = [l for l in main_txt(p).split('\n') if 'No hay' in l] or tabla_perm(p)
    R.shot(p, f'Paso 6: Vencido {chk["f_vencido"]}; Vencido + Rúbrica: {chk["f_vacio"]}')
    p.locator('main').get_by_role('button', name='Volver a Usuarios').click(); p.wait_for_timeout(900)
    fila_usr(p, B.correo).get_by_role('button', name=re.compile('^Otorgar permisos')).first.click(); p.wait_for_timeout(1500)
    chk['restaurado'] = [s.evaluate("s=>s.selectedIndex>=0?s.options[s.selectedIndex].text:''") for s in p.locator('main select').all()]
    R.shot(p, f'Paso 7: filtros al regresar: {chk["restaurado"]}')
    fin(R, chk, n)


# ── CP-PER-02 ───────────────────────────────────────────────────────────────────────

@caso('CP-PER-02')
def cp_per02():
    R = Run('CP-PER-02'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    B = _b(); uid = D.id_usuario('docente-b')
    Xr, NXr = colegio_receso(R, ctx)
    from casos.usr import asignaciones
    a0 = asignaciones(uid); c0 = A.calendario(Xr).get('version')
    login(p, sup_ui()); abrir_permisos(p, B.correo); d = abrir_otorgar(p)
    chk['modal'] = d.inner_text()[:220].replace('\n', ' | '); chk['nombre_docente'] = 'Docente B' in d.inner_text()
    chk['dependientes'] = [(s.get_attribute('aria-label') or '', s.is_disabled()) for s in d.locator('select').all()]
    chk['modulos'] = _lab(d, 'Módulo autorizado').evaluate("s=>[...s.options].map(o=>o.text)")
    R.shot(p, f'Pasos 1-2: {chk["modal"][:80]}; nombre del Docente visible = {chk["nombre_docente"]}; deshabilitados {chk["dependientes"]}; módulos {chk["modulos"]}')
    _sel(d, 'Año escolar', str(A.hoy().year)); _sel(d, 'Colegio', NXr)
    chk['periodos'] = _lab(d, 'Periodo académico').evaluate("s=>[...s.options].map(o=>o.text)")
    chk['grados'] = _lab(d, 'Grado').evaluate("s=>[...s.options].map(o=>o.text)")
    chk['aviso'] = 'sin modificar sus asignaciones históricas' in d.inner_text()
    R.shot(p, f'Paso 3: periodos {chk["periodos"]}; grados {chk["grados"]}; aviso de CU028 = {chk["aviso"]}')
    fin_ = ahora() + dt.timedelta(days=2)
    llenar_otorgar(d, NXr, '3.º', 'PA1', 'Asistencias', dl(fin_), 'Faltó registrar asistencias de mayo')
    t0 = ahora(); chk['otorgar'] = otorgar(p)
    if hay_dialogo(p):
        cerrar_dialogos(p)
        chk['api_respaldo'] = perm(uid, Xr, 3, FE.pa(1, Xr)['id_periodo_academico'], 'asistencias', fin_, motivo='Faltó registrar asistencias de mayo')[0]
        abrir_permisos(p, B.correo)
    chk['tabla'] = tabla_perm(p)
    R.shot(p, f'Pasos 4-5: {chk["otorgar"]}; tabla {chk["tabla"]}')
    chk['api'] = (permisos_api(uid), t0.strftime('%H:%M:%S'), asignaciones(uid) == a0, A.calendario(Xr).get('version') == c0)
    R.consola(ctx, 'Paso 6: el permiso por la API (en local, la base de datos)', [json.dumps(x, ensure_ascii=False) for x in chk['api'][0]] +
              [f'Hora del clic: {chk["api"][1]}', f'Asignaciones de Docente B sin cambios: {chk["api"][2]}; calendario sin cambios: {chk["api"][3]}'])
    filtro(p, 'Estado del permiso', 'Vencido'); aplicar(p)
    d = abrir_otorgar(p); llenar_otorgar(d, NXr, '3.º', 'PA1', 'Rúbrica', dl(fin_), 'Otro permiso QA')
    chk['filtro'] = otorgar(p) + [l for l in main_txt(p).split('\n') if 'no coincide' in l]
    R.shot(p, f'Paso 7: con el filtro "Vencido": {chk["filtro"]}')
    fin(R, chk, n)


# ── CP-PER-03 ───────────────────────────────────────────────────────────────────────

@caso('CP-PER-03')
def cp_per03():
    R = Run('CP-PER-03'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    B = _b(); uid = D.id_usuario('docente-b')
    Xr, NXr = colegio_receso(R, ctx)
    s_asg = A.asignar(uid, [(Xr, [3])], 'proximo')
    pa1 = FE.pa(1, Xr); mes = meses_de_pa(1, Xr)[-1]
    ini = ahora() + dt.timedelta(seconds=75); fin_ = ahora() + dt.timedelta(seconds=200)
    sp, rp = perm(uid, Xr, 3, pa1['id_periodo_academico'], 'rubrica', fin_, inicio=ini); pid = (rp or {}).get('id')
    chk['crear'] = (s_asg[0], sp, (rp or {}).get('estado'))
    R.nota('Paso 1: el plan pide inicio en 10 minutos y fin en 40; en la suite se acortó a +75 s y +200 s.')
    R.consola(ctx, f'Paso 1: Docente B solo con "Próximo" en {NXr} y un permiso de Rúbrica (3.º, PA1) programado',
              [f'Asignación "Próximo" → HTTP {s_asg[0]}', f'Permiso → HTTP {sp}, estado {chk["crear"][2]}, inicio {ini:%H:%M:%S}, fin {fin_:%H:%M:%S}'])
    A.cerrar_abiertas(B); login(p, B); p.wait_for_timeout(1200); b = p.get_by_role('button', name='Iniciar actividad')
    chk['antes'] = (b.count(), b.first.is_disabled() if b.count() else None, main_txt(p)[:250])
    R.shot(p, f'Paso 2: Inicio de Docente B antes del inicio del permiso: botón (cantidad, deshabilitado) {chk["antes"][:2]}')
    while ahora() < ini + dt.timedelta(seconds=3):
        time.sleep(2)
    p.reload(); p.wait_for_timeout(2500); b = p.get_by_role('button', name='Iniciar actividad')
    chk['vigente'] = ((A.api('GET', f'/usuarios/{uid}/permisos/{pid}', A.sup())[1] or {}).get('estado'), b.count(), b.first.is_disabled() if b.count() else None,
                      [l for l in main_txt(p).split('\n') if 'ermiso' in l][:4])
    R.shot(p, f'Paso 3: ya vigente: {chk["vigente"]}')
    if b.count() and b.first.is_enabled():
        b.first.click(); p.wait_for_timeout(1500)
    tk = token_navegador(p); act = A.actividad_en_curso(tk)
    al = A.alumnos(Xr, 3)[0]['id']
    s1, r1 = rub_put(tk, rub_items([(al, 2, 2)], act, mes=mes, cid=Xr)); chk['op_vigente'] = (s1, r1)
    try:
        ir(p, 'Rúbrica'); chk['rubrica_ui'] = main_txt(p)[:200]
    except Exception as e:
        chk['rubrica_ui'] = str(e)[:80]
    R.shot(p, f'Paso 3: actividad iniciada y Rúbrica abierta; guardar una evaluación de {FE.mes_nombre(mes)} → HTTP {s1} {r1}')
    while ahora() < fin_ + dt.timedelta(seconds=3):
        time.sleep(2)
    s2, r2 = rub_put(tk, rub_items([(al, 3, 3)], act, mes=mes, cid=Xr)); chk['op_vencida'] = (s2, r2)
    R.consola(ctx, 'Paso 4: guardar después del fin, con la actividad y la pantalla abiertas', [f'HTTP {s2} {json.dumps(r2, ensure_ascii=False)[:300]}'])
    p2 = n.ctx().new_page(); login(p2, sup_ui()); abrir_permisos(p2, B.correo); chk['tabla'] = tabla_perm(p2)
    chk['revocar'] = p2.locator('main tbody tr').first.get_by_role('button', name='Revocar').count()
    R.shot(p2, f'Paso 5: {chk["tabla"]}; botón "Revocar" en la fila: {chk["revocar"]}')
    fin(R, chk, n, B)


# ── CP-PER-04 ───────────────────────────────────────────────────────────────────────

@caso('CP-PER-04')
def cp_per04():
    R = Run('CP-PER-04'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    B = _b(); uid = D.id_usuario('docente-b')
    Xr, NXr = colegio_receso(R, ctx)
    t = ahora(); sp, rp = perm(uid, Xr, 3, FE.pa(1, Xr)['id_periodo_academico'], 'asistencias', t + dt.timedelta(days=2))
    n0 = len(permisos_api(uid))
    R.consola(ctx, 'Precondición: permiso vigente de CP-PER-02 (X, 3.º, PA1, Asistencias) por la API', [f'HTTP {sp}'])
    login(p, sup_ui()); abrir_permisos(p, B.correo); d = abrir_otorgar(p)
    fin_ = dl(t + dt.timedelta(days=3))
    llenar_otorgar(d, NXr, '3.º', 'PA1', 'Rúbrica', fin_, '   '); chk['motivo'] = otorgar(p)
    R.shot(p, f'Paso 1: motivo con espacios: {chk["motivo"]}')
    d.locator('textarea').first.fill('Motivo QA'); ahora_mismo(d, False); p.wait_for_timeout(300)
    try:
        d.get_by_label('Inicio de vigencia').fill(dl(t - dt.timedelta(hours=1))); chk['inicio_pasado'] = otorgar(p)
        d.get_by_label('Inicio de vigencia').fill(dl(t + dt.timedelta(days=1))); d.get_by_label('Fin de vigencia').fill(dl(t + dt.timedelta(days=1))); chk['fin_igual'] = otorgar(p)
    except Exception as e:
        chk['inicio_pasado'] = 'sin campo de inicio: ' + str(e)[:80]
    R.shot(p, f'Pasos 2-3: inicio pasado {chk["inicio_pasado"]}; fin igual al inicio {chk.get("fin_igual")}')
    s4, r4 = perm(uid, Xr, 3, FE.pa(2, Xr)['id_periodo_academico'], 'asistencias', t + dt.timedelta(days=2)); chk['api_pa2'] = (s4, r4)
    ahora_mismo(d, True); llenar_otorgar(d, NXr, '3.º', 'PA1', 'Asistencias', fin_, 'Superpuesto QA'); chk['superpuesto'] = otorgar(p)
    abierto = hay_dialogo(p)
    chk['conserva'] = (abierto, d.locator('textarea').first.input_value() if abierto else None,
                       d.get_by_role('button', name='Otorgar permiso', exact=True).last.is_enabled() if abierto else None, len(permisos_api(uid)) == n0)
    R.shot(p, f'Pasos 5-6: superposición {chk["superpuesto"]}; modal abierto / motivo / botón habilitado / sin permisos nuevos: {chk["conserva"]}')
    R.consola(ctx, 'Paso 4: PA2 (todavía en su PR) por la API', [f'HTTP {s4} {json.dumps(r4, ensure_ascii=False)[:300]}',
                                                                 f'Permisos de Docente B: {len(permisos_api(uid))} (antes {n0})'])
    fin(R, chk, n)


# ── CP-PER-05 ───────────────────────────────────────────────────────────────────────

@caso('CP-PER-05')
def cp_per05():
    R = Run('CP-PER-05'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    B = _b(); uid = D.id_usuario('docente-b'); X = D.X(); pa = pa_cerrado(X)
    clases = FE.clases_del_pa(4, pa['numero'], X); F1, F2 = clases[-1], clases[-2]
    sp, rp = perm(uid, X, 4, pa['id_periodo_academico'], 'asistencias', ahora() + dt.timedelta(days=2))
    al = [a['id'] for a in A.alumnos(X, 4)]
    A.cerrar_abiertas(B); act = A.iniciar_actividad(B)
    s0 = put_asis(B, F1, [(a, 'presente', None) for a in al], act, grado=4)
    chk['pre'] = (sp, s0)
    R.consola(ctx, f'Precondición (API): permiso de Asistencias del PA{pa["numero"]} para el 4.º del Norte y una asistencia guardada con él',
              [f'Permiso → HTTP {sp}', f'Asistencia del {FE.legible(F1)} → {s0}'])
    login(p, sup_ui()); abrir_permisos(p, B.correo)
    i = next((k for k, f in enumerate(tabla_perm(p)) if 'Asistencias' in f and 'Vigente' in f), 0)
    d = revocar_fila(p, i)
    chk['modal'] = (d.inner_text().replace('\n', ' | ')[:600], d.get_by_role('button').all_inner_texts(), 'La revocación impedirá nuevas operaciones' in d.inner_text())
    R.shot(p, f'Paso 1: botones {chk["modal"][1]}; aviso de CU028 = {chk["modal"][2]}')
    b = dlg(p).get_by_role('button', name='Confirmar revocación').last; chk['vacio'] = (b.is_disabled(),)
    if b.is_enabled():
        b.click(); p.wait_for_timeout(800); chk['vacio'] = (False, errores_dlg(p) + toasts_txt(p))
    R.shot(p, f'Paso 2: motivo vacío: {chk["vacio"]}')
    dlg(p).locator('textarea').first.fill('Corrección completada'); dlg(p).get_by_role('button', name='Confirmar revocación').last.click(); p.wait_for_timeout(1800)
    chk['revocado'] = (toasts_txt(p), tabla_perm(p)); R.shot(p, f'Paso 3: {chk["revocado"]}')
    s5 = put_asis(B, F2, [(al[0], 'presente', None)], act, grado=4)
    from casos.asi import asis_api
    chk['api'] = (permisos_api(uid), asis_api(F1, grado=4))
    chk['despues'] = s5
    R.consola(ctx, 'Pasos 4-5 (API; en local, la base de datos)', [f'Permisos: {json.dumps(chk["api"][0], ensure_ascii=False)[:700]}',
                                                                    f'Asistencias del {FE.legible(F1)} conservadas: {str(chk["api"][1])[:300]}',
                                                                    f'Con la actividad abierta, asistencia del {FE.legible(F2)} → {s5}'])
    j = next((k for k, f in enumerate(tabla_perm(p)) if 'Revocado' in f), 0)
    dd = ver_permiso(p, j); chk['acciones_revocado'] = dd.get_by_role('button').all_inner_texts()
    R.shot(p, f'Paso 6: acciones del permiso revocado: {chk["acciones_revocado"]}')
    fin(R, chk, n, B)


# ── CP-PER-10 ───────────────────────────────────────────────────────────────────────

@caso('CP-PER-10')
def cp_per10():
    R = Run('CP-PER-10'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    B = _b(); uid = D.id_usuario('docente-b'); X = D.X(); pa = pa_cerrado(X)
    clases = FE.clases_del_pa(4, pa['numero'], X); F1, F2 = clases[-1], clases[-2]
    fin1 = ahora() + dt.timedelta(seconds=150)
    s1, r1 = perm(uid, X, 4, pa['id_periodo_academico'], 'asistencias', fin1); pid1 = (r1 or {}).get('id')
    R.nota('Precondición: el plan pide un permiso que vence en 30 minutos; en la suite vence en 150 segundos.')
    R.consola(ctx, 'Precondición', [f'Permiso de Asistencias del PA{pa["numero"]} (Norte 4.º) que vence a las {fin1:%H:%M:%S} → HTTP {s1}'])
    resp = []

    def _r(r):
        if r.request.method == 'PUT' and '/api/asistencias' in r.url:
            try:
                resp.append([time.strftime('%H:%M:%S'), [(x.get('estado'), x.get('motivo')) for x in r.json().get('resultados', [])]])
            except Exception as e:
                resp.append(str(e)[:60])
    p.on('response', _r)
    con_actividad(p, B); abrir_asis(p, F1, grado='4.º', sub='Todos')
    ctx.set_offline(True); p.wait_for_timeout(800)
    marcar_asis(p, 'Grado4P1 Entrada QA', 'Ausente', esperar=False)
    raw = idb_todo(p); chk['idb1'] = [m.group(0) for m in re.finditer(r'"id_permiso":\s*\d+|"realizado_en":"[^"]+"', raw)][:4]
    R.shot(p, f'Paso 1: asistencia del {FE.legible(F1)} sin conexión; en IndexedDB {chk["idb1"]}')
    while ahora() < fin1 + dt.timedelta(seconds=3):
        time.sleep(2)
    ctx.set_offline(False); p.wait_for_timeout(8000)
    from casos.asi import asis_api
    chk['sync1'] = (asis_api(F1, grado=4), [x for x in permisos_api(uid) if x.get('id') == pid1])
    R.consola(ctx, 'Paso 2: sincronizada después del vencimiento (API)', [f'Permiso vencido a las {fin1:%H:%M:%S}', f'Asistencias del {FE.legible(F1)}: {str(chk["sync1"][0])[:500]}',
                                                                         f'Respuestas del servidor: {resp}'])
    s2, r2 = perm(uid, X, 4, pa['id_periodo_academico'], 'asistencias', ahora() + dt.timedelta(days=1)); pid2 = (r2 or {}).get('id')
    p.reload(); p.wait_for_timeout(2500); abrir_asis(p, F2, grado='4.º', sub='Todos')
    ctx.set_offline(True); p.wait_for_timeout(500); marcar_asis(p, 'Grado4P1 Entrada QA', 'Ausente', esperar=False)
    sr = revocar_api(uid, pid2, 'Revocado durante la prueba')[0]; time.sleep(2); marcar_asis(p, 'Grado4P2 Entrada QA', 'Ausente', esperar=False)
    chk['cola'] = re.findall(r'"id_permiso":\s*\d+', idb_todo(p))[:4]
    ctx.set_offline(False); p.wait_for_timeout(9000)
    chk['sync2'] = asis_api(F2, grado=4)
    raw = idb_todo(p); chk['resp'] = resp; chk['errores_idb'] = [raw[max(0, m.start() - 150): m.start() + 250] for m in re.finditer(r'rechaz|[Ee]rror', raw)][:3]
    chk['cola_final'] = cola_idb(p)[:3]
    R.shot(p, f'Paso 4: tras reconectar: avisos {toasts_txt(p)}', full=True)
    R.consola(ctx, 'Pasos 3-4', [f'Segundo permiso (id {pid2}) revocado entre las dos marcas → HTTP {sr}', f'Asistencias del {FE.legible(F2)} (API): {str(chk["sync2"])[:500]}',
                                 f'Respuestas del servidor: {resp}', f'Operaciones con error en IndexedDB: {chk["errores_idb"]}'])
    fin(R, chk, n, B)
