"""Usuarios (CU016): CP-USR-01, 02, 03, 04, 05, 09 y 10, adaptados a QA. CP-USR-08 queda solo en local.

- Supervisora en la interfaz: supervisor-2. Las cuentas nuevas usan alias de tu correo
  (…+sicedu-usr02-<hora>…) y DNI únicos; reciben el correo de bienvenida pero no hacen primer ingreso.
- Los pasos que necesitan entrar con el Docente usan cuentas de la suite con clave conocida:
  Docente B (CP-USR-04) y Docente Retro (CP-USR-10). CP-USR-03 crea un Docente nuevo en cada corrida y, para
  el paso 6, pide pegar su contraseña temporal (Enter la salta).
- Las asignaciones por periodo que en local se leían en la base de datos se leen con
  GET /api/asignaciones?id_docente=…. El "periodo anterior" se consigue con un calendario particular:
  el colegio queda en el receso posterior a PA2, se asigna "Retroactivo" (PA2) y luego el receso termina.
- CP-USR-05 NO modifica ni intenta inactivar al Supervisor original (es la cuenta que usa todo el
  equipo): solo verifica que los controles estén bloqueados. Sus pasos de API quedan como NOTA.
"""
import datetime as dt
import re

from lib import api as A
from lib import config
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import SOLO_LOCAL, caso
from lib.ui import (BASE, Nav, Run, backend_caido, cerrar_dialogos, cola_idb, con_actividad, dlg, ir, llenar_login, login, logout,
                    main_txt, respuesta_de, toasts_txt, token_navegador)

from casos._comun import crear_colegio, dni_unico, fin, hay_dialogo, hhmmss, sup_ui
from casos.asi import abrir_asis, marcar_asis, put_asis

SOLO_LOCAL['CP-USR-08'] = ('Necesita cambiar la configuración del correo del backend (credenciales SMTP inválidas) y mover 48 horas '
                           'atrás la emisión de la contraseña temporal en la base de datos (o esperar 48 horas).')

UNO = dt.timedelta(days=1)


# ── Ayudas de la pantalla Usuarios ─────────────────────────────────────────────────

def filas(p):
    return p.locator('main tbody tr')


def pie(p):
    m = re.search(r'Mostrando (\d+) a (\d+) de (\d+)', main_txt(p))
    return m.groups() if m else None


def abrir_usuarios(p):
    p.goto(BASE + '/usuarios'); p.wait_for_load_state('networkidle'); p.wait_for_timeout(1500)
    try:
        filas(p).first.wait_for(timeout=6000)
    except Exception:
        pass


def fila_usr(p, texto):
    return filas(p).filter(has_text=texto).first


def buscar(p, t):
    p.get_by_label('Buscar').fill(t); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1300)


def S(p, i):
    """Filtros: 0 rol, 1 colegio, 2 estado."""
    return p.locator('main select').nth(i)


def errores(p):
    if not hay_dialogo(p):
        return ['(el modal se cerró)']
    return [l.strip() for l in dlg(p).inner_text().split('\n') if re.search(r'obligatori|Ingresa|Selecciona|debe|Ya existe|ya existe|ya tiene|No se puede|registrad|dígitos|inválid|Elige', l)][:6]


def guardar_dlg(p, capturar=False):
    d = dlg(p)
    if capturar:
        res = respuesta_de(p, lambda: d.get_by_role('button', name='Guardar').click(), '/api/usuarios', metodo='POST')
    else:
        d.get_by_role('button', name='Guardar').click(); res = None
    p.wait_for_timeout(1800)
    out = (hay_dialogo(p), (errores(p) if hay_dialogo(p) else []) + toasts_txt(p))
    if capturar:
        st, cuerpo, _ = res
        cuerpo = {k: v for k, v in (cuerpo or {}).items() if 'contrase' not in k} if isinstance(cuerpo, dict) else cuerpo
        return out + ((st, cuerpo),)
    return out


def form_basico(d, nom, ape, dni, correo, rol):
    d.get_by_label('Nombres').fill(nom); d.get_by_label('Apellidos').fill(ape); d.get_by_label('DNI').fill(dni)
    d.get_by_label('Correo institucional').fill(correo)
    d.get_by_label(re.compile(r'^Rol\s*\*?$')).select_option(label=rol); d.page.wait_for_timeout(600)


def agregar_colegio(d, i, colegio, grados, inicio=None):
    """i: posición del bloque (1, 2…)."""
    d.get_by_role('button', name='Añadir colegio').click(); d.page.wait_for_timeout(400)
    sel = d.get_by_label(re.compile(r'^Colegio\s*\*?$')).nth(i - 1)
    opciones = [o.strip() for o in sel.locator('option').all_inner_texts()]
    sel.select_option(label=next((o for o in opciones if o.startswith(colegio)), colegio)); d.page.wait_for_timeout(900)
    for g in grados:
        d.get_by_label(f'{g} en el colegio {i}').check()
    if inicio:
        poner_inicio(d, i, inicio)


def marcar_grado_en(d, colegio, grado, inicio=None):
    """Marca el grado en el bloque del colegio si ya está en el formulario; si no, añade el colegio."""
    sels = d.get_by_label(re.compile(r'^Colegio\s*\*?$'))
    for i in range(sels.count()):
        if sels.nth(i).evaluate("s=>s.selectedIndex>=0?s.options[s.selectedIndex].text:''").startswith(colegio):
            d.get_by_label(f'{grado} en el colegio {i + 1}').check(); return
    agregar_colegio(d, sels.count() + 1, colegio, [grado], inicio)


def poner_inicio(d, i, inicio):
    bloque = d.locator('div.rounded-xl').nth(i - 1)
    s = bloque.get_by_label(re.compile(r'^Inicio de asignación'))
    s.select_option(label=inicio); d.page.wait_for_timeout(300)


def form_docente(d, nom, ape, dni, correo, colegios):
    """colegios: [(nombre, [grados], inicio|None)]"""
    form_basico(d, nom, ape, dni, correo, 'Docente')
    for i, (col, grados, inicio) in enumerate(colegios, 1):
        agregar_colegio(d, i, col, grados, inicio)


_ID_DOCENTE = {}


def _id_docente(id_usuario):
    if id_usuario in _ID_DOCENTE:
        return _ID_DOCENTE[id_usuario]
    u = A.api('GET', f'/usuarios/{id_usuario}', A.sup())[1] or {}
    for activo in ('true', 'false'):
        for d in A.todas_las_paginas('/seguimiento/docentes?' + A.q(activo=activo), A.sup()):
            if d.get('nombres') == u.get('nombres') and d.get('apellidos') == u.get('apellidos'):
                _ID_DOCENTE[id_usuario] = d['id_docente']
                return d['id_docente']
    return None


def asignaciones(id_usuario=None, etiqueta=None, correo=None):
    """(colegio, grado, PA, vigente) por la API (GET /asignaciones; en local, la tabla docente_colegio_grado)."""
    if etiqueta:
        id_usuario = D.id_usuario(etiqueta)
    if correo:
        u = A.usuario_por_correo(correo)
        id_usuario = u['id'] if u else None
    if not id_usuario:
        return None
    idd = _id_docente(id_usuario)
    if not idd:
        return ['(no se encontró su id_docente en Seguimiento)']
    r = A.api('GET', '/asignaciones?' + A.q(id_docente=idd), A.sup())[1] or []
    return sorted(((a.get('colegio'), a.get('grado'), f'PA{a.get("periodo")}', 'vigente' if a.get('vigente') else 'no vigente') for a in r), key=str)


def correo_nuevo(tag):
    return config.correo_de(f'{tag}-{hhmmss()}')


def colegio_con_pa_anterior(R, ctx, nombre_base, grados):
    """Colegio cuyo receso posterior a PA2 terminó ayer (hoy en PA3), para tener una asignación del PA anterior:
    primero se deja hoy dentro del receso, se asigna "Retroactivo" y después se cierra el receso."""
    cid = crear_colegio(f'QA AUTO {hhmmss()} {nombre_base}', {g: min(A.hoy().isoweekday(), 5) for g in grados})
    s1, r1 = FE.poner_calendario_en_pr(cid, True)
    return cid, (s1, r1 if s1 >= 300 else None)


def cerrar_receso(cid):
    cal = A.calendario(cid)
    return FE.poner_calendario_en_pr(cid, False, existente={'id_calendario': cal['id_calendario'], 'version': cal['version']})


# ── CP-USR-01 ───────────────────────────────────────────────────────────────────────

@caso('CP-USR-01')
def cp_usr01():
    R = Run('CP-USR-01'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    tot = (A.api('GET', '/usuarios', A.sup())[1] or {}).get('total', 0)
    pre = [f'Usuarios activos en QA: {tot}']
    if tot < 41:
        from casos.seg import asegurar_docentes
        pre += asegurar_docentes(41)
    else:
        from casos.seg import asegurar_docentes
        pre += asegurar_docentes(0)   # solo la cuenta inactiva y la que nunca entró
    R.consola(ctx, 'Precondición (por la API)', pre)
    login(p, sup_ui()); ir(p, 'Usuarios'); p.wait_for_timeout(2000)
    chk['cabeceras'] = [t.strip() for t in p.locator('main thead th').all_inner_texts()]
    rows = [r.split('\t') for r in filas(p).all_inner_texts()]
    i_rol = next((k for k, h in enumerate(chk['cabeceras']) if h.upper().startswith('ROL')), 4)
    roles = [r[i_rol] if len(r) > i_rol else '' for r in rows]
    chk['orden_roles'] = [k for i, k in enumerate(roles) if i == 0 or roles[i - 1] != k]
    tks = token_navegador(p)
    api_items = A.todas_las_paginas('/usuarios', tks)
    chk['orden_api'] = [(u['apellidos'] + ' ' + u['nombres'], u['rol']) for u in api_items][:10]
    chk['colegios'] = sorted(set((r[i_rol], r[i_rol + 1][:40]) for r in rows if len(r) > i_rol + 1))[:8]
    fd = fila_usr(p, D.cuenta('docente-a').correo); fdir = fila_usr(p, D.cuenta('directivo').correo)
    if not fd.count():
        buscar(p, D.cuenta('docente-a').correo); fd = fila_usr(p, D.cuenta('docente-a').correo)
    chk['controles_docente'] = [(x.get_attribute('aria-label') or x.inner_text()).strip() for x in fd.locator('button,a').all()]
    buscar(p, D.cuenta('directivo').correo); fdir = fila_usr(p, D.cuenta('directivo').correo)
    chk['controles_directivo'] = [(x.get_attribute('aria-label') or x.inner_text()).strip() for x in fdir.locator('button,a').all()]
    p.get_by_role('button', name='Limpiar').click(); p.wait_for_timeout(1500)
    chk['pie'] = pie(p)
    R.shot(p, f'Pasos 1-4: columnas {chk["cabeceras"]}; grupos por rol {chk["orden_roles"]}; controles Docente {chk["controles_docente"]}; Directivo {chk["controles_directivo"]}', full=True)
    R.consola(ctx, 'Paso 2: orden (API, apellidos y nombres)', [f'{x}' for x in chk['orden_api']] + [f'Pantalla, primeras filas: {[r[0] for r in rows[:10]]}'])
    buscar(p, D.cuenta('docente-a').correo)
    b = fila_usr(p, D.cuenta('docente-a').correo).get_by_role('button', name=re.compile('Ver detalle|Otorgar permisos'))
    if b.count():
        b.first.click(); p.wait_for_timeout(1800)
    chk['detalle'] = (p.url.replace(BASE, ''), main_txt(p)[:220].replace('\n', ' | '), p.get_by_role('tab').all_inner_texts())
    R.shot(p, f'Paso 5: detalle del Docente: {chk["detalle"]}')
    abrir_usuarios(p); chk['pie'] = pie(p)
    sig = p.get_by_role('button', name='Siguiente')
    if sig.count() and sig.first.is_enabled():
        sig.first.click(); p.wait_for_timeout(1200); chk['pag2'] = (pie(p), filas(p).count())
    R.shot(p, f'Paso 6: pie {chk["pie"]}; página 2 {chk.get("pag2")}')
    abrir_usuarios(p)
    S(p, 0).select_option(label='Docente'); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1300)
    chk['f_rol'] = (pie(p), (A.api('GET', '/usuarios?' + A.q(rol='Docente'), tks)[1] or {}).get('total'))
    S(p, 0).select_option(index=0)
    S(p, 2).select_option(label='Inactivos'); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1300)
    chk['f_inac'] = ([r.split('\t')[0] for r in filas(p).all_inner_texts()][:8], [u['nombres'] + ' ' + u['apellidos'] for u in (A.api('GET', '/usuarios?activo=false', tks)[1] or {}).get('items', [])][:8])
    S(p, 2).select_option(label='Activos')
    buscar(p, 'QA Auto Docente')
    chk['f_palabras'] = ([r.split('\t')[0] for r in filas(p).all_inner_texts()][:8], (A.api('GET', '/usuarios?' + A.q(q='QA Auto Docente'), tks)[1] or {}).get('total'))
    parte = 'sicedu-docente'
    buscar(p, parte)
    chk['f_correo'] = ([r.split('\t')[0] for r in filas(p).all_inner_texts()][:8], (A.api('GET', '/usuarios?' + A.q(q=parte), tks)[1] or {}).get('total'))
    R.shot(p, f'Paso 7: parte del correo "{parte}": {chk["f_correo"]}')
    R.consola(ctx, 'Paso 7: filtros comparados con la API (en local, con la base de datos)',
              [f'Rol Docente (pie | API): {chk["f_rol"]}', f'Inactivos (pantalla | API): {chk["f_inac"]}',
               f'"QA Auto Docente" en otro orden (pantalla | API): {chk["f_palabras"]}', f'Correo "{parte}" (pantalla | API): {chk["f_correo"]}'])
    fin(R, chk, n)


# ── CP-USR-02 ───────────────────────────────────────────────────────────────────────

@caso('CP-USR-02')
def cp_usr02():
    R = Run('CP-USR-02'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    NX, NY = D.nombre_colegio('norte'), D.nombre_colegio('sur'); X = D.X()
    per = A.periodo_actual(X); chk['periodo'] = per
    if not per or per.get('tipo') != 'PA':
        R.nota(f'Precondición: hoy no está en un PA del calendario ({per}); el caso pide un día de PA.')
    login(p, sup_ui()); abrir_usuarios(p); p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(800); d = dlg(p)
    chk['campos'] = [l for l in ['NOMBRES', 'APELLIDOS', 'DNI', 'CORREO', 'ROL'] if l in d.inner_text().upper()]
    d.get_by_label(re.compile(r'^Rol\s*\*?$')).select_option(label='Docente'); p.wait_for_timeout(600); t = d.inner_text()
    chk['docente'] = {'anio': 'AÑO ESCOLAR' in t.upper(), 'colegios': 'Colegios asignados' in t or 'COLEGIOS ASIGNADOS' in t.upper(),
                      'aniadir': d.get_by_role('button', name='Añadir colegio').count()}
    R.shot(p, f'Paso 1-2: campos {chk["campos"]}; rol Docente: {chk["docente"]}')
    d.get_by_label(re.compile(r'^Rol\s*\*?$')).select_option(label='Directivo'); p.wait_for_timeout(500)
    chk['directivo_sin_asig'] = 'COLEGIOS ASIGNADOS' not in d.inner_text().upper()
    R.shot(p, f'Paso 2: rol Directivo, sin campos de asignación = {chk["directivo_sin_asig"]}')
    cerrar_dialogos(p); p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(800); d = dlg(p)
    c_doc = correo_nuevo('usr02-docente')
    form_docente(d, 'Docente', f'QA Dos {hhmmss()}', dni_unico(1), c_doc, [(NY, ['1.º', '2.º'], None), (NX, ['5.º'], None)])
    R.shot(p, f'Paso 3: Docente con dos colegios: Sur 1.º y 2.º, Norte 5.º ({c_doc})')
    chk['crear_doc'] = guardar_dlg(p, capturar=True); chk['asig'] = asignaciones(correo=c_doc)
    abrir_usuarios(p); buscar(p, c_doc); chk['fila'] = [r.replace('\t', ' | ')[:180] for r in filas(p).all_inner_texts()]
    R.shot(p, f'Paso 3: {chk["crear_doc"][:2]}; fila {chk["fila"]}')
    c_conf = correo_nuevo('usr02-conflicto')
    p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(800); d = dlg(p)
    form_docente(d, 'Docente', f'Conflicto QA {hhmmss()}', dni_unico(2), c_conf, [(NY, ['3.º'], None), (NX, ['3.º'], None)])
    chk['conflicto'] = guardar_dlg(p)
    chk['conflicto_api'] = (A.usuario_por_correo(c_conf), [a for a in (A.api('GET', '/asignaciones?' + A.q(id_colegio=D.Y()), A.sup())[1] or []) if a.get('id_grado') == A.id_grado(3)])
    R.shot(p, f'Paso 4: Sur 3.º libre + Norte 3.º ocupado por Docente A (conflicto en el segundo colegio): {chk["conflicto"]}')
    cerrar_dialogos(p); p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(800); d = dlg(p)
    c_dir = correo_nuevo('usr02-directivo'); dni_dir = dni_unico(3)
    form_basico(d, 'Directivo', f'QA Dos {hhmmss()}', dni_dir, c_dir, 'Directivo')
    chk['crear_dir'] = guardar_dlg(p, capturar=True); cerrar_dialogos(p); buscar(p, c_dir)
    chk['fila_dir'] = [r.replace('\t', ' | ')[:140] for r in filas(p).all_inner_texts()]
    R.shot(p, f'Paso 5: Directivo: {chk["crear_dir"][:2]}; fila {chk["fila_dir"]}')
    dup = {}
    otro = correo_nuevo('usr02-otro')
    for etiqueta, dni, correo in [('correo repetido', dni_unico(4), c_dir), ('DNI repetido', dni_dir, otro), ('DNI de 7', '7000001', otro),
                                  ('DNI de 9', '700000123', otro), ('DNI con letras', '7000ABCD', otro)]:
        cerrar_dialogos(p); p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(700); d = dlg(p)
        form_basico(d, 'Otro', 'QA', dni, correo, 'Directivo'); dup[etiqueta] = guardar_dlg(p)
    chk['duplicados'] = dup; chk['otro_creado'] = A.usuario_por_correo(otro) is not None
    R.shot(p, f'Paso 6: duplicados e inválidos: {dup}; se creó la cuenta "otro": {chk["otro_creado"]}'); cerrar_dialogos(p)
    u = A.usuario_por_correo(c_doc) or {}
    chk['marca'] = {'debe_cambiar_contrasena': u.get('debe_cambiar_contrasena'), 'correo_enviado': (chk['crear_doc'][2][1] or {}).get('correo_enviado') if isinstance(chk['crear_doc'][2][1], dict) else None}
    R.nota('Paso 7: el contenido del correo de bienvenida (contraseña temporal de 48 horas) se revisa en tu bandeja: '
           f'llega a {c_doc}. La suite verifica la marca de cambio obligatorio y que el servidor informó el envío.')
    buscar(p, c_doc); fila_usr(p, c_doc).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(1000); d = dlg(p)
    chk['prellenado'] = [s.evaluate("s=>s.selectedIndex>=0?s.options[s.selectedIndex].text:''") for s in d.locator('select').all()]
    marcar_grado_en(d, NX, '3.º')
    chk['editar_ocupado'] = guardar_dlg(p); chk['asig_tras'] = asignaciones(correo=c_doc)
    R.shot(p, f'Paso 8: edición con Norte 3.º (ocupado): {chk["editar_ocupado"]}; prellenado {chk["prellenado"]}')
    cerrar_dialogos(p)
    s8 = A.api('PATCH', f'/usuarios/{u.get("id")}', A.sup(), {'asignacion': A.asignacion([(D.Y(), [1, 2]), (X, [5, 3])])})
    chk['api'] = (s8[0], str(s8[1])[:250]); chk['asig_tras_api'] = asignaciones(correo=c_doc)
    R.consola(ctx, 'Pasos 3, 7 y 8: asignaciones, marca y API (en local, la base de datos y el buzón)',
              [f'Asignaciones del Docente nuevo (colegio | grado | PA | retroactiva): {chk["asig"]}', f'Cuenta del conflicto creada: {chk["conflicto_api"][0]}',
               f'Marca de cambio obligatorio / correo enviado: {chk["marca"]}', f'Asignaciones tras la edición rechazada: {chk["asig_tras"]}',
               f'PATCH /api/usuarios con Norte 3.º → HTTP {chk["api"][0]} {chk["api"][1]}', f'Asignaciones tras el PATCH: {chk["asig_tras_api"]}'])
    fin(R, chk, n)


# ── CP-USR-03 ───────────────────────────────────────────────────────────────────────

@caso('CP-USR-03')
def cp_usr03():
    """Usa un Docente nuevo en cada corrida: las asignaciones de PA ya culminados se conservan para siempre, y las de
    corridas anteriores apuntan a colegios ya inactivados (ver la observación de la tanda 2 sobre Docente B)."""
    import time
    from lib import correo as CO
    R = Run('CP-USR-03'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    X = D.X(); NX, NY = D.nombre_colegio('norte'), D.nombre_colegio('sur')
    Q, s_cal = colegio_con_pa_anterior(R, ctx, 'Rotación', [2, 3])
    NQ = A.colegio(Q)['nombre']
    cor = correo_nuevo('usr03-rotacion'); t0 = time.time() - 2
    s_new, r_new = A.api('POST', '/usuarios', A.sup(), {'nombres': 'Docente', 'apellidos': f'Rotación QA {hhmmss()}', 'dni': dni_unico(21), 'correo': cor, 'id_rol': 1,
                                                       'asignacion': A.asignacion([(X, [5]), (Q, [3])], 'retroactivo')})
    uid = (r_new or {}).get('usuario', {}).get('id') if isinstance(r_new, dict) else None
    s_fin = cerrar_receso(Q)
    chk['antes'] = asignaciones(uid)
    R.consola(ctx, 'Paso 1: asignaciones del Docente de prueba por periodo (API)',
              [f'{NQ}: calendario con hoy en el receso posterior a PA2 → {s_cal}', f'Docente nuevo {cor} con "Retroactivo" (Norte 5.º y {NQ} 3.º) → HTTP {s_new}',
               f'Fin del receso (hoy en PA3) → HTTP {s_fin[0]}'] + [str(x) for x in (chk['antes'] or [])])
    login(p, sup_ui()); abrir_usuarios(p); buscar(p, cor)
    fila_usr(p, cor).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(1000); d = dlg(p)
    chk['prellenado'] = ([s.evaluate("s=>s.selectedIndex>=0?s.options[s.selectedIndex].text:''") for s in d.locator('select').all()],
                         [c.get_attribute('aria-label') for c in d.locator('input[type=checkbox]:checked').all()])
    R.shot(p, f'Paso 2: formulario prellenado: {chk["prellenado"]}')
    sels = d.get_by_label(re.compile(r'^Colegio\s*\*?$'))
    idx = next((i for i in range(sels.count()) if NQ in sels.nth(i).evaluate("s=>s.options[s.selectedIndex].text")), None)
    if idx is not None:
        opciones = [o.strip() for o in sels.nth(idx).locator('option').all_inner_texts()]
        sels.nth(idx).select_option(label=next(o for o in opciones if o.startswith(NY))); p.wait_for_timeout(800)
        d.get_by_label(f'2.º en el colegio {idx + 1}').check()
    chk['guardar'] = guardar_dlg(p); chk['despues'] = asignaciones(uid)
    R.shot(p, f'Paso 3: {NQ} → Sur 2.º: {chk["guardar"]}')
    cerrar_dialogos(p); abrir_usuarios(p); buscar(p, cor)
    fila_usr(p, cor).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(1000); d = dlg(p)
    sels = d.get_by_label(re.compile(r'^Colegio\s*\*?$'))
    nombres = [sels.nth(i).evaluate("s=>s.options[s.selectedIndex].text") for i in range(sels.count())]
    chk['bloques_edicion'] = nombres
    j = next((i for i, x in enumerate(nombres) if x.startswith(NY)), None)
    if j is not None:
        d.get_by_label(f'Quitar el colegio {j + 1}').click(); p.wait_for_timeout(400)
    chk['quitar'] = guardar_dlg(p); chk['tras_quitar'] = asignaciones(uid)
    R.shot(p, f'Paso 5: bloques al editar {nombres}; quitar el Sur: {chk["quitar"]}')
    R.consola(ctx, 'Pasos 4-5: asignaciones después de cada cambio (API)', ['Tras reemplazar el colegio:'] + [str(x) for x in (chk['despues'] or [])]
              + ['Tras quitar el Sur:'] + [str(x) for x in (chk['tras_quitar'] or [])])
    cerrar_dialogos(p)
    temporal = CO.contrasena_temporal(cor, t0)
    if temporal:
        s1, r1 = A.api('POST', '/password/primer-ingreso', body={'correo': cor, 'contraseña_temporal': temporal, 'contraseña_nueva': config.CLAVE_CUENTAS,
                                                               'confirmar_contraseña_nueva': config.CLAVE_CUENTAS})
        if s1 == 200:
            A.api('POST', '/logout', r1['access_token'])
            from lib.ui import logout as _logout
            _logout(p); login(p, A.Cuenta(cor, config.CLAVE_CUENTAS, 'Docente Rotación')); p.wait_for_timeout(1500)
            chk['inicio'] = main_txt(p)[:300]
            R.shot(p, f'Paso 6: Inicio del Docente de prueba: {chk["inicio"][:200]}')
            ir(p, 'Alumnos'); p.wait_for_timeout(1500)
            chk['alumnos_colegios'] = sorted(set(r.split('\t')[1] for r in filas(p).all_inner_texts() if '\t' in r))
            R.shot(p, f'Paso 6: Alumnos: colegios {chk["alumnos_colegios"]}')
        else:
            R.nota(f'Paso 6: el primer ingreso del Docente de prueba fue rechazado ({s1}); no se pudo entrar con él.')
    else:
        R.nota('Paso 6: no se pegó la contraseña temporal del Docente de prueba; no se entró con él.')
    fin(R, chk, n)


# ── CP-USR-04 ───────────────────────────────────────────────────────────────────────

@caso('CP-USR-04')
def cp_usr04():
    R = Run('CP-USR-04'); n = Nav(); chk = {}
    B = D.cuenta('docente-b'); uid = D.id_usuario('docente-b'); X = D.X()
    try:
        _usr04(R, n, chk, B, uid, X)
    finally:
        u = A.usuario_por_correo(B.correo)
        if u and not u.get('activo', True):
            A.api('PATCH', f'/usuarios/{uid}/activar', A.sup(), {})
        backend_caido(n.ctx(), False) if False else None
    fin(R, chk, n, B)


def _usr04(R, n, chk, B, uid, X):
    c0 = n.ctx()
    Q, s_cal = colegio_con_pa_anterior(R, c0, 'Inactivar', [5])
    NQ = A.colegio(Q)['nombre']
    s_asg = A.asignar(uid, [(X, [4]), (Q, [5])], 'retroactivo'); s_fin = cerrar_receso(Q)
    pa_ant = FE.pa_anterior(X)
    s_perm = A.permiso(uid, X, 4, pa_ant['id_periodo_academico'], 'rubrica', A.ahora() + dt.timedelta(days=3))
    antes = asignaciones(uid)
    R.consola(c0, 'Precondición: Docente B con asignaciones en el PA anterior, el vigente y los posteriores, y un permiso vigente',
              [f'{NQ}: receso → {s_cal}; "Retroactivo" (Norte 4.º y {NQ} 5.º) → HTTP {s_asg[0]}; fin del receso → HTTP {s_fin[0]}',
               f'Permiso de Rúbrica del PA{pa_ant["numero"]} (Norte 4.º) → HTTP {s_perm[0]}'] + [str(x) for x in (antes or [])])
    c1 = n.ctx(); p1 = c1.new_page(); login(p1, B); tk = token_navegador(p1)
    R.shot(p1, 'Paso 1: sesión de Docente B en una ventana aparte; token copiado')
    c2 = n.ctx(); p = c2.new_page(); login(p, sup_ui()); abrir_usuarios(p); buscar(p, B.correo)
    fila_usr(p, B.correo).get_by_role('button', name=re.compile('^Inactivar')).first.click(); p.wait_for_timeout(800)
    chk['confirmacion'] = dlg(p).inner_text()[:300] if hay_dialogo(p) else None
    R.shot(p, f'Paso 2: confirmación: {chk["confirmacion"]}')
    if hay_dialogo(p):
        dlg(p).get_by_role('button', name=re.compile('Inactivar|Confirmar')).last.click(); p.wait_for_timeout(1500)
    chk['inactivar'] = toasts_txt(p); despues = asignaciones(uid)
    s, r = A.api('GET', '/me', tk)
    u = A.api('GET', f'/usuarios/{uid}', A.sup())[1] or {}
    chk['api'] = {'activo': u.get('activo'), 'antes': antes, 'despues': despues, 'me': (s, r)}
    R.consola(c2, 'Pasos 3-4: el usuario y sus asignaciones (API) y el token de la otra ventana',
              [f'activo = {u.get("activo")}', 'Asignaciones antes:'] + [str(x) for x in (antes or [])] + ['Asignaciones después:'] + [str(x) for x in (despues or [])]
              + [f'GET /api/me con el token → HTTP {s} {str(r)[:160]}'])
    R.nota('Paso 4: el tipo de cierre de la sesión ("Invalidada por desactivación") está en la auditoría de la base de datos; en QA no hay una consulta para verlo.')
    p3 = c1.new_page(); p3.goto(BASE + '/login'); p3.wait_for_load_state('networkidle')
    llenar_login(p3, B.correo, B.clave); p3.click('button[type=submit]'); p3.wait_for_timeout(2000)
    chk['login'] = (p3.url.replace(BASE, ''), [l for l in p3.locator('body').inner_text().split('\n') if re.search('inactiv|desactivad|no está activa', l, re.I)][:2])
    R.shot(p3, f'Paso 5: inicio de sesión con la cuenta inactiva: {chk["login"]}')
    s6, r6 = A.api('POST', '/login', body={'correo': B.correo, 'password': B.clave})
    chk['permiso_inactivo'] = (s6, (r6 or {}).get('detail') if isinstance(r6, dict) else r6)
    R.consola(c2, 'Paso 6: uso del permiso vigente', [f'POST /api/login → HTTP {s6} {chk["permiso_inactivo"][1]}: sin sesión, el permiso no puede usarse.'])
    # Paso 10 (con la cuenta inactiva): "Otorgar permisos"
    abrir_usuarios(p); S(p, 2).select_option(label='Inactivos'); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1300)
    f = fila_usr(p, B.correo); chk['acciones_inactivo'] = f.locator('button').all_inner_texts()
    b = f.get_by_role('button', name=re.compile('^Otorgar permisos'))
    if b.count():
        b.first.click(); p.wait_for_timeout(1500); bo = p.locator('main').get_by_role('button', name='Otorgar permiso')
        chk['otorgar_inactivo'] = (bo.count(), bo.first.is_disabled() if bo.count() else None, [l for l in main_txt(p).split('\n') if 'Activa la cuenta' in l])
    R.shot(p, f'Paso 10: cuenta inactiva: acciones {chk["acciones_inactivo"]}; "Otorgar permiso": {chk.get("otorgar_inactivo")}')
    # Paso 7: el grado liberado a otro Docente
    sg = D.id_usuario('sin-grupos')
    s7 = A.asignar(sg, [(D.Y(), [6]), (X, [4])])
    chk['reasignar'] = (s7[0], str(s7[1])[:200])
    A.asignar(sg, [(D.Y(), [6])])
    R.consola(c2, 'Paso 7: el Norte 4.º liberado se asigna a Docente Sin Grupos', [f'PATCH /api/usuarios (Sur 6.º y Norte 4.º) → HTTP {s7[0]} {chk["reasignar"][1]}',
                                                                              'Después se le devuelve solo el Sur 6.º.'])
    # Paso 8: reactivar
    abrir_usuarios(p); S(p, 2).select_option(label='Inactivos'); p.get_by_role('button', name='Filtrar').click(); p.wait_for_timeout(1300)
    b = fila_usr(p, B.correo).get_by_role('button', name=re.compile('Activar|Reactivar'))
    if b.count():
        b.first.click(); p.wait_for_timeout(800)
        if hay_dialogo(p):
            dlg(p).get_by_role('button', name=re.compile('Activar|Confirmar')).last.click(); p.wait_for_timeout(1500)
    u = A.api('GET', f'/usuarios/{uid}', A.sup())[1] or {}
    s8, r8 = A.api('POST', '/login', body={'correo': B.correo, 'password': B.clave})
    hab = A.api('GET', '/me/habilitaciones', r8['access_token'])[1] if s8 == 200 else None
    perms = (A.api('GET', f'/usuarios/{uid}/permisos', A.sup())[1] or {}).get('items', [])
    chk['reactivar'] = {'avisos': toasts_txt(p), 'activo': u.get('activo'), 'login': s8, 'asignaciones': asignaciones(uid),
                        'permisos': [(x.get('modulo'), x.get('estado'), x.get('inicio'), x.get('fin')) for x in perms][:4]}
    if s8 == 200:
        A.api('POST', '/logout', r8['access_token'])
    R.shot(p, f'Paso 8: reactivado: {chk["reactivar"]["avisos"]}; activo {chk["reactivar"]["activo"]}; login HTTP {s8}')
    R.consola(c2, 'Pasos 8 y 10: tras reactivar (API)', [f'Asignaciones: {chk["reactivar"]["asignaciones"]}', f'Permisos (módulo | estado | inicio | fin): {chk["reactivar"]["permisos"]}',
                                                         f'GET /api/me/habilitaciones: {str(hab)[:500]}'])
    # Paso 9: fallo del backend al cambiar el estado
    A.asignar(uid, [(X, [4])])
    abrir_usuarios(p); buscar(p, B.correo); backend_caido(c2, True)
    try:
        fila_usr(p, B.correo).get_by_role('button', name=re.compile('^Inactivar')).first.click(timeout=5000); p.wait_for_timeout(600)
        if hay_dialogo(p):
            dlg(p).get_by_role('button', name=re.compile('Inactivar|Confirmar')).last.click(); p.wait_for_timeout(1800)
        chk['falla'] = (toasts_txt(p), [l for l in main_txt(p).split('\n') if 'No se pudo' in l][:2],
                        fila_usr(p, B.correo).get_by_role('button', name=re.compile('Inactivar|Activar')).all_inner_texts())
    except Exception as e:
        chk['falla'] = 'sin datos: ' + str(e)[:80]
    backend_caido(c2, False)
    chk['falla_api'] = (A.api('GET', f'/usuarios/{uid}', A.sup())[1] or {}).get('activo')
    R.shot(p, f'Paso 9: backend sin responder al cambiar el estado: {chk["falla"]}; activo según la API {chk["falla_api"]}')


# ── CP-USR-05 ───────────────────────────────────────────────────────────────────────

@caso('CP-USR-05', modo='parcial', notas='No se modifica ni se intenta inactivar al Supervisor original real.')
def cp_usr05():
    R = Run('CP-USR-05'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; S2 = sup_ui(); id_s2 = D.id_usuario('supervisor-2')
    orig = next((u for u in A.todas_las_paginas('/usuarios?' + A.q(rol='Supervisor'), A.sup()) if u.get('es_supervisor_original')), None)
    if not orig:
        R.nota('No se encontró la cuenta marcada como Supervisor original en QA.'); R.save(checks=chk); n.close(); return
    chk['original'] = {k: orig.get(k) for k in ('id', 'nombres', 'apellidos', 'rol', 'activo')}
    try:
        login(p, S2); abrir_usuarios(p); buscar(p, orig['correo']); f = fila_usr(p, orig['correo'])
        chk['fila'] = f.inner_text().replace('\t', ' | ')[:160] if f.count() else None
        bi = f.get_by_role('button', name=re.compile('Inactivar'))
        chk['switch_original'] = {'controles': bi.count(), 'deshabilitado': bi.first.is_disabled() if bi.count() else None,
                                  'title': bi.first.get_attribute('title') if bi.count() else None}
        R.shot(p, f'Paso 2: switch del Supervisor original: {chk["switch_original"]} (no se pulsa: es la cuenta del equipo)')
        e = f.get_by_role('button', name=re.compile('^Editar'))
        if e.count() and e.first.is_enabled():
            e.first.click(); p.wait_for_timeout(800); d = dlg(p)
            rol = d.get_by_label(re.compile(r'^Rol\s*\*?$'))
            chk['form_original'] = {'rol_bloqueado': rol.is_disabled() if rol.count() else None, 'nombres_editable': d.get_by_label('Nombres').is_editable(),
                                    'apellidos_editable': d.get_by_label('Apellidos').is_editable()}
            R.shot(p, f'Paso 3: formulario del original: {chk["form_original"]}; se cierra con "Cancelar" sin guardar')
            cerrar_dialogos(p)
        R.nota('Paso 3: no se guarda un cambio de nombres en el Supervisor original de QA (lo usa todo el equipo); solo se verifica que el Rol esté bloqueado y los nombres editables.')
        abrir_usuarios(p); buscar(p, S2.correo); bi = fila_usr(p, S2.correo).get_by_role('button', name=re.compile('Inactivar'))
        chk['propia'] = {'controles': bi.count(), 'deshabilitado': bi.first.is_disabled() if bi.count() else None}
        if bi.count() and bi.first.is_enabled():
            bi.first.click(); p.wait_for_timeout(800)
            if hay_dialogo(p):
                dlg(p).get_by_role('button', name=re.compile('Inactivar|Confirmar')).last.click(); p.wait_for_timeout(1300)
            chk['propia']['resultado'] = toasts_txt(p)
        R.shot(p, f'Paso 4: switch de la propia cuenta (supervisor-2): {chk["propia"]}')
        tk = token_navegador(p)
        a = A.api('PATCH', f'/usuarios/{id_s2}/desactivar', tk, {})
        chk['api_propia'] = (a[0], str(a[1])[:200])
        R.nota('Paso 5: no se envían a la API la desactivación ni el cambio de rol del Supervisor original de QA. Se envió la autodesactivación de supervisor-2.')
        estado = {u['correo']: (u['activo'], u['rol']) for u in A.todas_las_paginas('/usuarios?' + A.q(rol='Supervisor'), A.sup()) if u['correo'] in (orig['correo'], S2.correo)}
        chk['estado'] = estado
        R.consola(ctx, 'Pasos 5-6: API (sin tocar al original) y estado de las dos cuentas',
                  [f'PATCH /api/usuarios/{{supervisor-2}}/desactivar con su propio token → HTTP {a[0]} {chk["api_propia"][1]}',
                   f'Cuentas (activo | rol): {estado}'])
    finally:
        u = A.api('GET', f'/usuarios/{id_s2}', A.sup())[1] or {}
        if u and u.get('activo') is False:
            A.api('PATCH', f'/usuarios/{id_s2}/activar', A.sup(), {})
            R.nota('supervisor-2 quedó inactiva por la prueba y se reactivó con la Supervisora E2E.')
    fin(R, chk, n)


# ── CP-USR-09 ───────────────────────────────────────────────────────────────────────

def _periodos_pr4(cid):
    """Calendario en que los cuatro PA ya terminaron y hoy está en el receso posterior a PA4."""
    hoy = A.hoy()
    gen = {(p['tipo'], p['numero']): (A.fecha(p['fecha_inicio']), A.fecha(p['fecha_fin'])) for p in A.calendario(cid)['periodos']}
    d = lambda k: hoy - dt.timedelta(days=k)  # noqa: E731
    per = [('PA', 1, *gen[('PA', 1)]), ('PR', 1, *gen[('PR', 1)]), ('PA', 2, gen[('PA', 2)][0], d(40)), ('PR', 2, d(39), d(38)),
           ('PA', 3, d(37), d(20)), ('PR', 3, d(19), d(18)), ('PA', 4, d(17), d(3)), ('PR', 4, d(2), gen[('PR', 4)][1])]
    return [{'tipo': t, 'numero': nn, 'fecha_inicio': a.isoformat(), 'fecha_fin': b.isoformat()} for t, nn, a, b in per]


@caso('CP-USR-09')
def cp_usr09():
    R = Run('CP-USR-09'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    h = hhmmss()
    Xc = crear_colegio(f'QA AUTO {h} Receso X', {1: 1, 3: 3}); Yc = crear_colegio(f'QA AUTO {h} Periodo Y', {1: 1}); Zc = crear_colegio(f'QA AUTO {h} Fin Z', {1: 1})
    NX_, NY_, NZ_ = (A.colegio(c)['nombre'] for c in (Xc, Yc, Zc))
    cx = FE.poner_calendario_en_pr(Xc, True); cy = FE.poner_calendario_en_pr(Yc, False)
    cz = A.api('POST', '/calendarios/particulares', A.sup(), {'id_colegio': Zc, 'id_anio_escolar': A.anio(), 'periodos': _periodos_pr4(Zc), 'dias_no_lectivos': []})
    chk['cal'] = (cx[0], cy[0], cz[0], A.periodo_actual(Xc), A.periodo_actual(Yc), A.periodo_actual(Zc))
    R.consola(ctx, 'Precondición: calendarios particulares (API)', [f'{NX_}: hoy en el receso posterior a PA2 → HTTP {cx[0]}; periodo de hoy {chk["cal"][3]}',
                                                                   f'{NY_}: hoy en PA3 → HTTP {cy[0]}; {chk["cal"][4]}', f'{NZ_}: hoy en el receso posterior a PA4 → HTTP {cz[0]}; {chk["cal"][5]}'])
    login(p, sup_ui()); abrir_usuarios(p); p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(800); d = dlg(p)
    cR = correo_nuevo('usr09-r')
    form_docente(d, 'Docente', f'R QA {h}', dni_unico(11), cR, [(NX_, ['1.º'], None), (NY_, ['1.º'], None)])
    t = d.inner_text()
    chk['bloque'] = {'n_inicio': t.upper().count('INICIO DE ASIGNACIÓN'), 'ayudas': [l for l in t.split('\n') if 'Permite completar' in l or 'Podrá registrar' in l or 'Podrás registrar' in l],
                     'opciones': [s.evaluate("s=>[...s.options].map(o=>[o.text,o.disabled])") for s in d.get_by_label(re.compile(r'^Inicio de asignación')).all()]}
    R.shot(p, f'Pasos 1-2: X (receso) e Y (PA3): bloques "Inicio de asignación" = {chk["bloque"]["n_inicio"]}; ayudas {chk["bloque"]["ayudas"]}; opciones {chk["bloque"]["opciones"]}', full=True)
    chk['sin_inicio'] = guardar_dlg(p); chk['sin_inicio_api'] = A.usuario_por_correo(cR) is not None
    R.shot(p, f'Paso 3: sin elegir el inicio: {chk["sin_inicio"]}; cuenta creada {chk["sin_inicio_api"]}')
    poner_inicio(dlg(p), 1, 'Retroactivo')
    chk['crear_r'] = guardar_dlg(p); chk['asig_r'] = asignaciones(correo=cR)
    R.shot(p, f'Paso 4: R con "Retroactivo": {chk["crear_r"]}; asignaciones {chk["asig_r"]}')
    cerrar_dialogos(p); p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(800); d = dlg(p)
    cP = correo_nuevo('usr09-p')
    form_docente(d, 'Docente', f'P QA {h}', dni_unico(12), cP, [(NX_, ['3.º'], 'Próximo')])
    chk['crear_p'] = guardar_dlg(p); chk['asig_p'] = asignaciones(correo=cP)
    R.shot(p, f'Paso 5: P con "Próximo": {chk["crear_p"]}; asignaciones {chk["asig_p"]}')
    cerrar_dialogos(p); p.get_by_role('button', name='Agregar').first.click(); p.wait_for_timeout(800); d = dlg(p)
    form_docente(d, 'Docente', f'Z QA {h}', dni_unico(13), correo_nuevo('usr09-z'), [(NZ_, ['1.º'], None)])
    chk['z'] = ([s.evaluate("s=>[...s.options].map(o=>[o.text,o.disabled])") for s in d.get_by_label(re.compile(r'^Inicio de asignación')).all()],
                [l for l in d.inner_text().split('\n') if 'año escolar' in l.lower() or 'receso' in l.lower()][:4])
    R.shot(p, f'Paso 6: colegio en el receso posterior a PA4: {chk["z"]}')
    cerrar_dialogos(p)
    sr, rr = A.api('POST', '/usuarios', A.sup(), {'nombres': 'Docente', 'apellidos': f'Titular QA {h}', 'dni': dni_unico(14), 'correo': correo_nuevo('usr09-titular'), 'id_rol': 1,
                                                  'asignacion': A.asignacion([(Xc, [1])], 'retroactivo')})
    chk['retro_titular'] = (sr, rr.get('detail') if isinstance(rr, dict) else rr)
    uR = (A.usuario_por_correo(cR) or {}).get('id')
    abrir_usuarios(p); buscar(p, cR); fila_usr(p, cR).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(1000); d = dlg(p)
    k = d.get_by_label(re.compile(r'^Colegio\s*\*?$')).count() + 1
    agregar_colegio(d, k, NZ_, ['1.º'], 'Retroactivo')
    chk['agregar_z'] = guardar_dlg(p); chk['asig_r2'] = asignaciones(uR)
    R.shot(p, f'Paso 8: R + colegio Z: {chk["agregar_z"]}')
    cerrar_dialogos(p); buscar(p, cR); fila_usr(p, cR).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(1000); d = dlg(p)
    sels = d.get_by_label(re.compile(r'^Colegio\s*\*?$')); nombres = [sels.nth(i).evaluate("s=>s.options[s.selectedIndex].text") for i in range(sels.count())]
    j = next((i for i, x in enumerate(nombres) if x.startswith(NY_)), None)
    if j is not None:
        d.get_by_label(f'Quitar el colegio {j + 1}').click(); p.wait_for_timeout(400)
    chk['quitar_y'] = guardar_dlg(p); chk['asig_r3'] = asignaciones(uR)
    R.shot(p, f'Paso 8: quitar Y: {chk["quitar_y"]}')
    cerrar_dialogos(p); buscar(p, cR); fila_usr(p, cR).get_by_role('button', name=re.compile('^Editar')).first.click(); p.wait_for_timeout(1000); d = dlg(p)
    k = d.get_by_label(re.compile(r'^Colegio\s*\*?$')).count() + 1
    agregar_colegio(d, k, D.nombre_colegio('norte'), ['3.º'])
    chk['conflicto'] = guardar_dlg(p); chk['asig_r4'] = asignaciones(uR)
    R.shot(p, f'Paso 9: conflicto solo en el colegio agregado (Norte 3.º de Docente A): {chk["conflicto"]}')
    cerrar_dialogos(p)
    s10 = A.api('PATCH', f'/usuarios/{uR}', A.sup(), {'asignacion': A.asignacion([(Xc, [1]), (Zc, [1])], 'retroactivo')})
    chk['retro_titular_propio'] = (s10[0], asignaciones(uR))
    R.consola(ctx, 'Pasos 4-10: asignaciones (API; en local, la base de datos)',
              [f'R: {chk["asig_r"]}', f'P: {chk["asig_p"]}', f'"Retroactivo" sobre X 1.º, que ya tiene a R en PA2 → HTTP {sr} {str(chk["retro_titular"][1])[:200]}',
               f'R tras agregar Z: {chk["asig_r2"]}', f'R tras quitar Y: {chk["asig_r3"]}', f'R tras el conflicto (sin cambios): {chk["asig_r4"]}',
               f'Paso 10: R vuelve a guardar "Retroactivo" en X 1.º, del que ya era titular en PA2 → HTTP {s10[0]}; {chk["retro_titular_propio"][1]}'])
    fin(R, chk, n)


# ── CP-USR-10 ───────────────────────────────────────────────────────────────────────

@caso('CP-USR-10', modo='parcial', notas='El fin del receso se simula cambiando el calendario del colegio, no el reloj del servidor.')
def cp_usr10():
    R = Run('CP-USR-10'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    CR = D.cuenta('retro'); uid = D.id_usuario('retro'); Y = D.Y()
    s_cal = FE.poner_calendario_en_pr(Y, True)
    desde = FE.pa(1, Y)['fecha_inicio']
    rita = A.crear_alumno('Rita', 'Retro Asistencia QA', Y, 5, A.CL(), desde); rosa = A.crear_alumno('Rosa', 'Retro Asistencia QA', Y, 5, A.CL(), desde)
    s_asg = A.asignar(uid, [(Y, [5])], 'retroactivo')
    pa2 = FE.pa(2, Y); cl = FE.clases_habituales(5, pa2['fecha_inicio'], pa2['fecha_fin'], Y)
    F, F2 = cl[-1], (cl[-2] if len(cl) > 1 else cl[-1])
    chk['asig'] = asignaciones(uid)
    R.consola(ctx, 'Precondición (API): colegio Sur con hoy en el receso posterior a PA2 y Docente Retro con asignación "Retroactivo" en 5.º',
              [f'Calendario particular → HTTP {s_cal[0]}; asignación → HTTP {s_asg[0]}', f'Asignaciones (colegio | grado | PA | retroactiva): {chk["asig"]}',
               f'Clases de PA2 usadas: {FE.legible(F)} y {FE.legible(F2)}'])
    con_actividad(p, CR); abrir_asis(p, F, grado='5.º', colegio=D.nombre_colegio('sur'), sub='Comprensión Lectora')
    ctx.set_offline(True); p.wait_for_timeout(500)
    marcar_asis(p, 'Rita Retro Asistencia QA', 'Presente', esperar=False)
    chk['pendiente'] = (len(cola_idb(p)), p.locator('header').first.inner_text().replace('\n', ' ')[:80])
    R.shot(p, f'Precondición: {FE.legible(F)} (PA2) durante el receso: Rita marcada sin conexión → pendientes {chk["pendiente"]}')
    tk = token_navegador(p); act = A.actividad_en_curso(tk)
    s_fin = cerrar_receso(Y)
    R.nota('Paso 1: el fin del receso se simula cambiando el calendario del colegio (el receso termina ayer); en local se adelantaba el reloj del servidor.')
    s2 = put_asis(tk, F2, [(rosa, 'presente', None)], act, grado=5, colegio=Y)
    g = A.api('GET', '/asistencias?' + A.q(id_colegio=Y, id_grado=A.id_grado(5), id_seccion=A.seccion(Y, 5), fecha=A.iso(F2)), tk)
    chk['fin_pr'] = (s_fin[0], s2, (g[0], (g[1] or {}).get('escritura') if isinstance(g[1], dict) else g[1]))
    R.consola(ctx, 'Pasos 1-2: receso terminado', [f'Calendario movido (hoy en PA3) → HTTP {s_fin[0]}; periodo de hoy {A.periodo_actual(Y)}',
                                                  f'Asistencia de Rosa del {FE.legible(F2)} (PA2) → {s2}', f'GET /api/asistencias {FE.legible(F2)} → escritura {chk["fin_pr"][2]}'])
    ctx.set_offline(False); p.wait_for_timeout(10000)
    chk['sync'] = {'rita': [x for x in (A.api('GET', '/asistencias?' + A.q(id_colegio=Y, id_grado=A.id_grado(5), id_seccion=A.seccion(Y, 5), fecha=A.iso(F)), A.sup())[1] or {}).get('alumnos', []) if x['nombre'].startswith('Rita')],
                   'cola': len(cola_idb(p)), 'avisos': toasts_txt(p)}
    p.reload(); p.wait_for_timeout(3000); abrir_asis(p, F2, grado='5.º', colegio=D.nombre_colegio('sur'), sub='Comprensión Lectora')
    chk['ui_tras'] = main_txt(p)[:300]
    R.shot(p, f'Pasos 2-3: reconectado: sincronización {chk["sync"]}', full=True)
    chk['asig_tras'] = asignaciones(uid)
    sp = A.permiso(uid, Y, 5, pa2['id_periodo_academico'], 'asistencias', A.ahora() + dt.timedelta(days=2))
    p.reload(); p.wait_for_timeout(3000); abrir_asis(p, F2, grado='5.º', colegio=D.nombre_colegio('sur'), sub='Comprensión Lectora')
    chk['con_permiso'] = (sp[0], marcar_asis(p, 'Rosa Retro Asistencia QA', 'Presente'))
    R.shot(p, f'Pasos 4-5: asignación histórica {chk["asig_tras"]}; permiso de Asistencias de PA2 (HTTP {sp[0]}): Rosa → {chk["con_permiso"][1]}')
    R.consola(ctx, 'Pasos 4-5: API', [f'Asignaciones de Retro: {chk["asig_tras"]}', f'Rita en la lista del {FE.legible(F)}: {chk["sync"]["rita"]}'])
    fin(R, chk, n, CR)
