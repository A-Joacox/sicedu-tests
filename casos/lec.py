"""Seguimiento de Lectura (CU023 a CU026): CP-LEC-01 a CP-LEC-14, adaptados a QA.

Las semanas se calculan con GET /semanas: S_ACT es la semana de la última clase del 3.º (hoy o
antes), S_ANT la de la clase anterior, S_PA la de una clase del último PA culminado y S_FUT la
semana siguiente. Lo que en local se leía en la base de datos se lee con GET /lectura/tablas.
"""
import datetime as dt
import json
import re

from lib import api as A
from lib import correo as CO
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import caso
from lib.ui import (BASE, Nav, Run, cerrar_dialogos, cola_idb, con_actividad, filtros_ui, fila, idb_todo, ir,
                    llenar_login, login, logout, opciones, poner, textos, toasts_txt, token_navegador)
from casos.asi import (_c, abrir_asis, act_de, asis_api, aviso_sup, clases_api, de_alumno, ids_operacion, marcar_asis,
                       nueva_act, ops_api, put_asis, sup_ui, NX)

UN_DIA = dt.timedelta(days=1)


# ── Semanas del caso ────────────────────────────────────────────────────────────────

class Semanas:
    """Semanas de prueba del colegio Norte (3.º) calculadas al empezar el caso."""

    def __init__(self, grado=3, cid=None):
        cid = cid or D.X()
        self.F = FE.ultima_clase(grado, cid)                 # clase de la semana actual
        self.F_ant = self.F - dt.timedelta(days=7) if self.F else None
        self.ACT, self.mes_act, self.ini_act, self.fin_act = FE.semana_de(self.F, grado, cid) if self.F else (None, None, None, None)
        self.ANT, self.mes_ant, *_ = FE.semana_de(self.F_ant, grado, cid) if self.F_ant else (None, None)
        pa_ant = FE.pa_anterior(cid)
        cl = FE.clases_del_pa(grado, pa_ant['numero'], cid) if pa_ant else []
        self.F_pa = cl[-1] if cl else None
        self.pa_ant = pa_ant
        self.PA, self.mes_pa, *_ = FE.semana_de(self.F_pa, grado, cid) if self.F_pa else (None, None)
        fut = A.hoy() + dt.timedelta(days=7)
        self.FUT, self.mes_fut, *_ = FE.semana_de(fut, grado, cid)

    def txt(self):
        return {'actual': (self.ACT, FE.legible(self.F)), 'anterior': (self.ANT, FE.legible(self.F_ant)),
                'PA culminado': (self.PA, FE.legible(self.F_pa)), 'futura': self.FUT}


def sel_por_etiqueta(p, etiqueta):
    for x in p.locator('main select').all():
        lab = x.evaluate("e=>{const l=e.closest('label')||document.querySelector('label[for=\"'+e.id+'\"]');return (l?l.innerText:(e.getAttribute('aria-label')||'')).split('\\n')[0]}")
        if lab.strip().upper() == etiqueta.upper():
            return x
    return None


def poner_valor(p, etiqueta, valor):
    s = sel_por_etiqueta(p, etiqueta)
    if s is None or valor is None:
        return False
    if str(valor) not in s.locator('option').evaluate_all("os=>os.map(o=>o.value)"):
        return False
    s.select_option(value=str(valor)); p.wait_for_timeout(1500)
    return True


def abrir_lec(p, semana, mes, grado='3.º', sub='Comprensión Lectora', colegio=None, ir_=True):
    if ir_:
        ir(p, 'Seguimiento de Lectura'); p.wait_for_timeout(2000)
    if colegio:
        poner(p, 'Colegio', colegio)
    poner(p, 'Grado', grado)
    try:
        poner(p, 'Sección', 'Única')
    except Exception:
        pass
    poner(p, 'Subprograma', sub)
    if mes:
        poner(p, 'Mes', FE.mes_nombre(mes))
    if semana:
        poner_valor(p, 'Semana', semana)
    p.wait_for_timeout(2000)


def _params(semana, mes, grado, prog, colegio):
    x = colegio or D.X()
    return dict(id_colegio=x, id_grado=A.id_grado(grado), id_seccion=A.seccion(x, grado), id_programa=prog or A.CL(), id_anio_escolar=A.anio(), mes=mes, id_semana=semana)


def tabla_get(quien, semana, mes, grado=3, prog=None, colegio=None):
    return A.api('GET', '/lectura/tablas?' + A.q(**_params(semana, mes, grado, prog, colegio)), quien)


def tabla_post(quien, act, semana, mes, grado=3, prog=None, colegio=None, **extra):
    b = {**_params(semana, mes, grado, prog, colegio), 'id_operacion': A.uid(), 'id_actividad': act}
    b.update(extra)
    return A.api('POST', '/lectura/tablas', quien, b)


def filas_put(quien, id_tabla, act, lst):
    """lst: [(id_alumno, version, {campos})]"""
    items = [dict({'id_operacion': A.uid(), 'version': v, 'id_actividad': act, 'id_alumno': a}, **c) for a, v, c in lst]
    s, r = A.api('PUT', f'/lectura/tablas/{id_tabla}/filas', quien, items)
    return s, ([(z.get('estado'), z.get('motivo'), z.get('detail')) for z in r] if isinstance(r, list) else r)


def version_fila(quien, id_alumno, semana, mes, prog=None, colegio=None):
    s, r = tabla_get(quien, semana, mes, prog=prog, colegio=colegio)
    return next((f['version'] for f in r.get('filas', []) if f['id_alumno'] == id_alumno), None) if s == 200 else None


def lec_api(semana, mes, prog=None, colegio=None, grado=3):
    """Lo que en local salía de lectura_semanal: id, programa, semana, clase de referencia, estado, motivo, filas, versión."""
    s, r = tabla_get(A.sup(), semana, mes, grado=grado, prog=prog, colegio=colegio)
    if s != 200:
        return {'http': s, 'motivo': (r or {}).get('motivo') if isinstance(r, dict) else r}
    return {'id': r['id'], 'programa': r['id_programa'], 'semana': r['id_semana'], 'clase': (r.get('clase_referencia') or {}).get('fecha'),
            'tipo_clase': (r.get('clase_referencia') or {}).get('tipo'), 'estado': r['estado'], 'motivo': r.get('motivo_no_realizada'),
            'filas': len(r.get('filas', [])), 'version': r['version'], 'declaraciones': r.get('declaraciones')}


def filas_api(semana, mes, nombres=None, prog=None, colegio=None):
    s, r = tabla_get(A.sup(), semana, mes, prog=prog, colegio=colegio)
    if s != 200:
        return s
    out = []
    for f in r.get('filas', []):
        if nombres and f['nombre'].split(' ')[0] not in nombres:
            continue
        out.append((f['nombre'].split(' ')[0], f.get('lsn_titulo'), f.get('lsn_nota'), f.get('lsn_maximo'), f.get('cantidad_lsl'), f.get('observacion'), f.get('version'), f.get('estado_fila')))
    return out


def fila_lec(p, nombre):
    f = fila(p, nombre)
    if not f.count():
        return None
    tds = [t.inner_text().strip().replace('\n', ' ') for t in f.locator('td').all()]
    ins = f.locator('input, select'); dis = ins.evaluate_all("els=>els.map(e=>e.disabled)")
    vals = ins.evaluate_all("els=>els.map(e=>e.value)")
    return {'celdas': tds, 'valores': vals, 'deshabilitados': sum(dis), 'campos': len(dis)}


def escribir(p, nombre, campo, valor):
    """campo: titulo | nota | maximo | lsl. Escribe y sale del campo (el guardado es al salir)."""
    lab = {'titulo': f'Título del LSN de {nombre}', 'nota': f'Nota del LSN de {nombre}', 'maximo': f'Puntaje máximo del LSN de {nombre}',
           'lsl': f'Libros de sala de lectura de {nombre}'}[campo]
    e = p.get_by_label(lab, exact=True)
    if campo == 'maximo':
        e.select_option(value=str(valor), timeout=8000)
    else:
        e.fill(str(valor), timeout=8000); e.press('Tab')
    p.wait_for_timeout(1500)


def espiar(p, patron='/api/lectura'):
    lst = []
    p.on('response', lambda r: lst.append((A.ahora().strftime('%H:%M:%S'), r.request.method, r.url.split('/api')[-1][:70], r.status))
         if patron in r.url and r.request.method != 'GET' else None)
    return lst


MARCAS = [('Ana Norte QA', 'presente'), ('Beto Norte QA', 'presente'), ('Dante Norte QA', 'presente'), ('Elsa Norte QA', 'ausente')]


def preparar_asis(cuenta, act, fecha, marcas=None):
    return put_asis(cuenta, fecha, [(D.alumno(a), e, None) for a, e in (marcas or MARCAS) if e], act)


def boton(p, patron):
    return p.locator('main').get_by_role('button', name=re.compile(patron))


def prep_tabla(S, marcas=None, prog=None):
    C = _c(); _, act = nueva_act(C); preparar_asis(C, act, S.F, marcas)
    s, t = tabla_post(C, act, S.ACT, S.mes_act, prog=prog); A.cerrar_abiertas(C)
    return t.get('id') if isinstance(t, dict) else None


def _fin(R, chk, n, *cuentas):
    for c in (cuentas or (_c(),)):
        try:
            A.cerrar_abiertas(c)
        except Exception:
            pass
    R.save(checks=chk)
    if n:
        n.close()


def _sem_req(R, S, *attrs):
    falta = [a for a in attrs if getattr(S, a) is None]
    if falta:
        R.nota(f'No hay en el calendario de QA las semanas que el caso necesita: {falta}.')
    return not falta


# ───────────────────────────────────────────────────────────────────────────────────

@caso('CP-LEC-01')
def cp_lec01():
    R = Run('CP-LEC-01'); chk = {}; C = _c(); S = Semanas(); uid = D.id_usuario('docente-a'); Y = D.Y()
    chk['semanas'] = S.txt()
    pa_ant = FE.pa_anterior(Y)
    pr = A.permiso(uid, Y, 1, pa_ant['id_periodo_academico'], 'lectura', A.ahora() + dt.timedelta(days=30)) if pa_ant else (None, None)
    chk['permiso'] = pr[0]; pid = pr[1].get('id') if isinstance(pr[1], dict) else None
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C); ir(p, 'Seguimiento de Lectura'); p.wait_for_timeout(2500)
    chk['orden'] = [l for l, _ in filtros_ui(p)]; chk['colegios'] = opciones(p, 'Colegio'); chk['inicial'] = filtros_ui(p)
    R.shot(p, f'Pasos 1-2: filtros {chk["orden"]}; colegios {chk["colegios"]}; valores iniciales {chk["inicial"]}')
    chk['compatibles'] = {k: opciones(p, k) for k in ['Grado', 'Sección', 'Subprograma', 'Mes']}
    chk['semanas_ui'] = opciones(p, 'Semana')
    R.shot(p, f'Paso 3: opciones compatibles: {chk["compatibles"]}; semanas {chk["semanas_ui"]}')
    chk['propuesta'] = filtros_ui(p)
    poner(p, 'Colegio', NX()); poner(p, 'Subprograma', 'Comprensión Lectora'); poner(p, 'Mes', FE.mes_nombre(S.mes_act)); chk['semanas_mes'] = opciones(p, 'Semana')
    if S.ANT:
        poner(p, 'Mes', FE.mes_nombre(S.mes_ant)); poner_valor(p, 'Semana', S.ANT)
    chk['semana_anterior'] = (filtros_ui(p), textos(p, 'tabla', 'Clase de esta semana')[:3])
    R.shot(p, f'Paso 4: propuesta sin selecciones previas {chk["propuesta"]}; semanas del mes {chk["semanas_mes"]}; semana anterior elegida → {chk["semana_anterior"]}')
    ls = p.evaluate('JSON.stringify(localStorage)'); raw = idb_todo(p)
    chk['almacen'] = {'url': p.url.replace(BASE, ''), 'localStorage': ls[:500], 'idb_claves': list(json.loads(raw).keys()), 'idb_tamano': len(raw)}
    R.consola(ctx, 'Paso 5: Application (Local Storage, IndexedDB y URL)', [f'URL: {chk["almacen"]["url"]}', f'Local Storage: {ls[:700]}', f'IndexedDB: {chk["almacen"]["idb_claves"]} ({len(raw)} caracteres)'])
    nombre_sur = D.nombre_colegio('sur')
    if poner(p, 'Colegio', nombre_sur):
        p.wait_for_timeout(1500); chk['tras_cambiar_colegio'] = filtros_ui(p)
        R.shot(p, f'Paso 6: tras cambiar al colegio Sur (permiso de Lectura del 1.º): {chk["tras_cambiar_colegio"]}')
        sub = opciones(p, 'Subprograma') or []
        if sub:
            poner(p, 'Subprograma', sub[-1])
        sem = opciones(p, 'Semana') or []
        if len(sem) > 1:
            sel_por_etiqueta(p, 'Semana').select_option(index=len(sem) - 1); p.wait_for_timeout(1500)
        antes = filtros_ui(p); p.reload(); p.wait_for_timeout(3000); chk['recarga'] = (antes, filtros_ui(p))
        R.shot(p, f'Paso 6: completado {antes} → tras recargar {chk["recarga"][1]}')
    else:
        R.nota('Paso 6: el colegio Sur no aparece entre los colegios del Docente pese al permiso de Lectura.')
    if pid:
        chk['revocar'] = A.api('POST', f'/usuarios/{uid}/permisos/{pid}/revocar', A.sup(), {'motivo': 'Prueba QA'})[0]
        ir(p, 'Inicio'); p.wait_for_timeout(1000); ir(p, 'Seguimiento de Lectura'); p.wait_for_timeout(2500)
        chk['sin_grupo'] = (filtros_ui(p), opciones(p, 'Colegio'), p.url.replace(BASE, ''))
        p.reload(); p.wait_for_timeout(3000); chk['sin_grupo_recarga'] = (filtros_ui(p), opciones(p, 'Colegio'))
        R.shot(p, f'Paso 7: permiso de Lectura del colegio Sur revocado (HTTP {chk["revocar"]}): al volver {chk["sin_grupo"]}; tras recargar {chk["sin_grupo_recarga"]}')
    n.close()
    # Paso 8: Docente sin grupos (una cuenta Docente sin asignación)
    correo_sg = D.config.correo_de('sin-asignacion')
    existe = A.usuario_por_correo(correo_sg)
    if existe:
        chk['crear_sin_grupos'] = ('ya existía', existe['id'])
    else:
        s, r = A.api('POST', '/usuarios', A.sup(), {'nombres': 'Sin Asignacion', 'apellidos': 'QA Auto', 'dni': D._dni(correo_sg), 'correo': correo_sg, 'id_rol': 1})
        chk['crear_sin_grupos'] = (s, r if s >= 300 else 'creada')
    n = Nav(); ctx = n.ctx()
    R.consola(ctx, 'Paso 8: Docente sin grupos', [f'POST /api/usuarios de un Docente sin asignación → {json.dumps(chk["crear_sin_grupos"], ensure_ascii=False, default=str)[:400]}'])
    if chk['crear_sin_grupos'][0] == 201 or chk['crear_sin_grupos'][0] == 'ya existía':
        R.nota('Paso 8: la API permitió crear un Docente sin asignación; para entrar con esa cuenta se necesita su contraseña temporal (no se automatiza).')
    n.close()
    # Paso 9: Supervisora
    if S.ACT:
        _, act = nueva_act(C); preparar_asis(C, act, S.F); chk['tabla'] = tabla_post(C, act, S.ACT, S.mes_act)[0]; A.cerrar_abiertas(C)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); login(p, sup_ui()); ir(p, 'Seguimiento de Lectura'); p.wait_for_timeout(2500)
    chk['sup_colegios'] = len(opciones(p, 'Colegio') or [])
    abrir_lec(p, S.ACT, S.mes_act, colegio=NX(), ir_=False)
    chk['sup'] = {'filtros': filtros_ui(p), 'campos': fila_lec(p, 'Ana Norte QA'), 'botones': p.locator('main').get_by_role('button').all_inner_texts()[:8]}
    R.shot(p, f'Paso 9: Supervisora: {chk["sup_colegios"]} colegios; {NX()} 3.º semana de la clase del {FE.legible(S.F)}: {chk["sup"]}', full=True)
    _fin(R, chk, n)


@caso('CP-LEC-02')
def cp_lec02():
    R = Run('CP-LEC-02'); chk = {}; C = _c(); S = Semanas()
    n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    con_actividad(p, C); abrir_lec(p, None, S.mes_act); chk['online'] = filtros_ui(p)
    R.shot(p, f'Precondición: Seguimiento de Lectura con conexión: {chk["online"]}')
    ctx.set_offline(True); ir(p, 'Inicio'); p.wait_for_timeout(800)
    adelanto = "(()=>{const off=23*86400000;const _D=Date;class D extends _D{constructor(...a){if(a.length===0)super(_D.now()+off);else super(...a)}static now(){return _D.now()+off}};window.Date=D})()"
    p.evaluate(adelanto)
    ir(p, 'Seguimiento de Lectura'); p.wait_for_timeout(2500)
    chk['offline'] = {'filtros': filtros_ui(p), 'colegios': opciones(p, 'Colegio'), 'semanas': opciones(p, 'Semana'),
                      'texto': textos(p, 'conexión', 'Complete', 'semana')[:3], 'hora_equipo': p.evaluate('new Date().toString()')[:40]}
    R.shot(p, f'Paso 1: sin conexión y con el reloj del equipo adelantado 23 días: {chk["offline"]}', full=True)
    p.reload(); p.wait_for_timeout(4000)
    chk['reabrir'] = {'url': p.url.replace(BASE, ''), 'texto': p.locator('body').inner_text()[:300]}
    R.shot(p, f'Paso 2: volver a abrir sin conexión: {chk["reabrir"]["texto"][:200]}', full=True)
    ctx.set_offline(False); p.goto(BASE + '/inicio'); p.wait_for_timeout(3000)
    if '/login' in p.url:
        login(p, C)
    ir(p, 'Seguimiento de Lectura'); p.wait_for_timeout(2500)
    chk['borrado'] = p.evaluate("""(async()=>{const out=[];for(const d of await indexedDB.databases()){const db=await new Promise(r=>{const o=indexedDB.open(d.name);o.onsuccess=()=>r(o.result)});
        for(const s of db.objectStoreNames){const tx=db.transaction(s,'readwrite');const st=tx.objectStore(s);const ks=await new Promise(r=>{const q=st.getAllKeys();q.onsuccess=()=>r(q.result)});
          for(const k of ks){ if(/cache|catalog/i.test(String(k))){st.delete(k);out.push(String(k))}}}}return out})()""")
    ctx.set_offline(True); ir(p, 'Inicio'); p.wait_for_timeout(800); ir(p, 'Seguimiento de Lectura'); p.wait_for_timeout(2500)
    chk['sin_catalogo'] = {'filtros': filtros_ui(p), 'colegios': opciones(p, 'Colegio'), 'semanas': opciones(p, 'Semana')}
    R.shot(p, f'Paso 3: catálogos borrados de IndexedDB ({chk["borrado"]}), sin conexión: {chk["sin_catalogo"]}', full=True)
    ctx.set_offline(False); p.wait_for_timeout(4000); ir(p, 'Inicio'); p.wait_for_timeout(800); ir(p, 'Seguimiento de Lectura'); p.wait_for_timeout(2500)
    chk['reconectado'] = {'filtros': filtros_ui(p), 'colegios': opciones(p, 'Colegio')}
    R.shot(p, f'Paso 4: reconectado: {chk["reconectado"]}', full=True)
    c2 = n.ctx(); c2.add_init_script(adelanto)
    p2 = c2.new_page(); login(p2, C, esperar=False); p2.wait_for_timeout(5000)
    chk['login_reloj_adelantado'] = (p2.url.replace(BASE, ''), p2.locator('body').inner_text()[:200])
    R.shot(p2, f'Complemento: iniciar sesión con el reloj del equipo adelantado 23 días: {chk["login_reloj_adelantado"][0]}')
    _fin(R, chk, n)


@caso('CP-LEC-03')
def cp_lec03():
    R = Run('CP-LEC-03'); chk = {}; C = _c(); S = Semanas(); chk['semanas'] = S.txt()
    if not _sem_req(R, S, 'ACT'):
        R.save(checks=chk); return
    _, act = nueva_act(C); prep = {}
    if S.ANT:
        prep['asis_ant'] = put_asis(C, S.F_ant, [(D.alumno('Ana Norte QA'), 'presente', None)], act)
        s, t = tabla_post(C, act, S.ANT, S.mes_ant); prep['tabla_ant'] = s
        if s == 201:
            prep['lectura_ant'] = filas_put(C, t['id'], act, [(D.alumno('Ana Norte QA'), version_fila(C, D.alumno('Ana Norte QA'), S.ANT, S.mes_ant),
                                                               {'lsn_titulo': 'Semana anterior', 'lsn_nota': 4, 'lsn_maximo': 5, 'cantidad_lsl': 2})])
    prep['asis'] = preparar_asis(C, act, S.F)
    prep['inactivar_dante'] = A.desactivar_alumno(D.alumno('Dante Norte QA'), min(A.hoy(), S.F + UN_DIA))[0]
    A.cerrar_abiertas(C); chk['prep'] = prep
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C); abrir_lec(p, S.ACT, S.mes_act); m = p.locator('main')
    b = boton(p, 'Crear la tabla')
    chk['vacio'] = {'textos': textos(p, 'aún no tiene tabla', 'Se creará', 'Crear'), 'boton': b.count(),
                    'centrado': b.first.evaluate("e=>{const r=e.getBoundingClientRect(),c=e.closest('main').getBoundingClientRect();return Math.round((r.left+r.width/2)-(c.left+c.width/2))}") if b.count() else None}
    R.shot(p, f'Paso 1: semana de la clase del {FE.legible(S.F)} sin tabla: {chk["vacio"]}')
    if b.count():
        b.first.click(); p.wait_for_timeout(3000)
    chk['creada'] = {'titulo': m.locator('h2, h3').all_inner_texts()[:3], 'avisos': toasts_txt(p),
                     'inactivo': fila(p, 'Dante Norte QA').inner_text().replace('\n', ' ')[:80] if fila(p, 'Dante').count() else None, 'filas': m.locator('tbody tr').count()}
    R.shot(p, f'Paso 2: tabla creada: {chk["creada"]}', full=True)
    chk['clase'] = textos(p, 'Clase de esta semana', 'Clase de referencia', 'Clase programada')
    chk['columnas'] = [x.strip() for x in m.locator('thead th').all_inner_texts()]
    R.shot(p, f'Paso 3: {chk["clase"]}; columnas {chk["columnas"]}')
    chk['iniciales'] = {k: fila_lec(p, k) for k in ['Ana Norte QA', 'Elsa Norte QA']}
    R.shot(p, f'Paso 4: valores iniciales: {chk["iniciales"]}')
    chk['sin_asistencia'] = fila_lec(p, 'Carla Norte QA')
    try:
        p.get_by_label('Título del LSN de Carla Norte QA').hover(timeout=4000); p.wait_for_timeout(500); chk['ayuda'] = p.locator('[role=tooltip]').all_inner_texts()
    except Exception as e:
        chk['ayuda'] = str(e)[:60]
    R.shot(p, f'Paso 5: alumna sin asistencia (Carla): {chk["sin_asistencia"]}; ayuda {chk["ayuda"]}')
    chk['nivel'] = [c for c in chk['columnas'] if 'nivel' in c.lower()]
    R.shot(p, f'Paso 6: columnas de solo lectura y Nivel Académico: {chk["nivel"] or "no hay columna de Nivel Académico"}')
    chk['api'] = lec_api(S.ACT, S.mes_act); chk['ana'] = filas_api(S.ACT, S.mes_act, ['Ana'])
    R.consola(ctx, 'Paso 7: lo guardado (API)', [f'Tabla: {chk["api"]}', f'Fila de Ana (sin copiar la semana anterior): {chk["ana"]}'])
    R.nota('Paso 7: la cantidad de marcas de creación por fila solo se ve en la base de datos.')
    if S.ANT:
        poner(p, 'Mes', FE.mes_nombre(S.mes_ant)); poner_valor(p, 'Semana', S.ANT); p.wait_for_timeout(1500)
    abrir_lec(p, S.ACT, S.mes_act, ir_=False)
    chk['duplicar_ui'] = (textos(p, 'Ya existe', 'Clase de esta semana'), boton(p, 'Crear la tabla').count())
    r = tabla_post(C, act_de(C), S.ACT, S.mes_act); chk['duplicar_api'] = (r[0], (r[1] or {}).get('motivo'), (r[1] or {}).get('detail'))
    R.shot(p, f'Paso 8: volver a la misma combinación: {chk["duplicar_ui"]}; POST por la API → {chk["duplicar_api"]}')
    _fin(R, chk, n)


@caso('CP-LEC-04', modo='parcial', notas='Paso 6 (pertenencia borrada en la base) se aproxima con un alumno que se incorporó después de la clase.')
def cp_lec04():
    R = Run('CP-LEC-04'); chk = {}; C = _c(); S = Semanas(); chk['semanas'] = S.txt()
    if not _sem_req(R, S, 'ACT'):
        R.save(checks=chk); return
    _, act = nueva_act(C); preparar_asis(C, act, S.F); A.cerrar_abiertas(C)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); login(p, C); abrir_lec(p, S.ACT, S.mes_act)
    chk['sin_actividad'] = (aviso_sup(p), boton(p, 'Crear la tabla').count())
    R.shot(p, f'Paso 3: sin actividad, semana de la clase del {FE.legible(S.F)}: {chk["sin_actividad"]}')
    b = p.get_by_role('button', name='Iniciar actividad')
    if b.count():
        b.first.click(); p.wait_for_timeout(1500)
    abrir_lec(p, S.ACT, S.mes_act)
    s_ = sel_por_etiqueta(p, 'Subprograma')
    if s_:
        s_.select_option(index=0); p.wait_for_timeout(1500)
    chk['incompleto'] = (filtros_ui(p), textos(p, 'Complete', 'La tabla se arma'), boton(p, 'Crear la tabla').count())
    R.shot(p, f'Paso 1: filtro sin completar: {chk["incompleto"]}')
    abrir_lec(p, None, S.mes_fut, ir_=False); chk['semanas_fut'] = opciones(p, 'Semana')
    if S.FUT:
        poner_valor(p, 'Semana', S.FUT)
    chk['futura_ui'] = (filtros_ui(p), textos(p, 'adelantar', 'futura', 'aún no tiene', 'Sin clases'), boton(p, 'Crear la tabla').count())
    r = tabla_post(C, act_de(C), S.FUT, S.mes_fut); chk['futura_api'] = (r[0], (r[1] or {}).get('motivo') if isinstance(r[1], dict) else r[1], (r[1] or {}).get('detail') if isinstance(r[1], dict) else None)
    R.shot(p, f'Paso 2: semana futura: {chk["futura_ui"]}; POST por la API → {chk["futura_api"]}')
    if S.PA:
        abrir_lec(p, S.PA, S.mes_pa, ir_=False)
        r = tabla_post(C, act_de(C), S.PA, S.mes_pa)
        chk['solo_consulta'] = (aviso_sup(p), textos(p, 'aún no tiene', 'habilitación'), boton(p, 'Crear la tabla').count(), (r[0], (r[1] or {}).get('motivo') if isinstance(r[1], dict) else None))
        R.shot(p, f'Paso 4: semana de la clase del {FE.legible(S.F_pa)} (PA{S.pa_ant["numero"]}, sin habilitación): {chk["solo_consulta"]}')
    A.cerrar_abiertas(C); n.close()
    # Paso 5: grupo sin alumnos (2.º, su único alumno inactivo desde el inicio del PA)
    pa = FE.pa_actual(); S2 = Semanas(grado=2); S1 = Semanas(grado=1)
    A.desactivar_alumno(D.alumno('Grado2P2 Entrada QA'), pa['fecha_inicio'])
    D1 = D.cuenta('rv-uno')
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, D1)
    abrir_lec(p, S2.ACT, S2.mes_act, grado='2.º', sub='Comprensión Lectora')
    chk['sin_alumnos_ui'] = (filtros_ui(p), textos(p, 'aún no tiene', 'Se creará', 'Sin clases', 'No hay estudiantes'), boton(p, 'Crear la tabla').count())
    if boton(p, 'Crear la tabla').count():
        boton(p, 'Crear la tabla').first.click(); p.wait_for_timeout(2500); chk['sin_alumnos_ui'] += (toasts_txt(p),)
    r = tabla_post(D1, act_de(D1), S2.ACT, S2.mes_act, grado=2); chk['sin_alumnos_api'] = (r[0], (r[1] or {}).get('motivo') if isinstance(r[1], dict) else r[1])
    R.shot(p, f'Paso 5: 2.º del colegio con su único alumno inactivo: {chk["sin_alumnos_ui"]}; POST → {chk["sin_alumnos_api"]}', full=True)
    # Paso 6: 1.º cuyo único alumno se incorporó después de la clase de la semana anterior
    if S1.ANT:
        A.desactivar_alumno(D.alumno('Grado1P1 Entrada QA'), pa['fecha_inicio'])
        A.crear_alumno('Tardio', 'Primero QA', D.X(), 1, A.ALFA(), A.hoy())
        abrir_lec(p, S1.ANT, S1.mes_ant, grado='1.º', sub='Alfabetización', ir_=True)
        chk['sin_pertenencia_ui'] = (filtros_ui(p), textos(p, 'aún no tiene', 'Se creará', 'pertenencia', 'No hay estudiantes'), boton(p, 'Crear la tabla').count())
        r = tabla_post(D1, act_de(D1), S1.ANT, S1.mes_ant, grado=1, prog=A.ALFA())
        chk['sin_pertenencia_api'] = (r[0], (r[1] or {}).get('motivo') if isinstance(r[1], dict) else r[1])
        R.shot(p, f'Paso 6: 1.º en la semana del {FE.legible(S1.F_ant)}, con su único alumno incorporado hoy: {chk["sin_pertenencia_ui"]}; POST → {chk["sin_pertenencia_api"]}', full=True)
        R.nota('Paso 6: en local se borró la pertenencia en la base; en QA se usa un alumno que se incorporó después de la clase.')
    chk['tablas'] = {'2.º': lec_api(S2.ACT, S2.mes_act, grado=2)}
    R.consola(ctx, 'Paso 7: tablas creadas (API)', [json.dumps(chk['tablas'], ensure_ascii=False, default=str)])
    _fin(R, chk, n, D1, C)


@caso('CP-LEC-05')
def cp_lec05():
    R = Run('CP-LEC-05'); chk = {}; C = _c(); S = Semanas(); chk['semanas'] = S.txt()
    if not _sem_req(R, S, 'ACT', 'ANT'):
        R.save(checks=chk); return
    _, act = nueva_act(C); preparar_asis(C, act, S.F); put_asis(C, S.F_ant, [(D.alumno('Ana Norte QA'), 'presente', None)], act); A.cerrar_abiertas(C)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C); abrir_lec(p, S.ACT, S.mes_act)

    def alternar():
        poner(p, 'Mes', FE.mes_nombre(S.mes_ant)); poner_valor(p, 'Semana', S.ANT)
        poner(p, 'Mes', FE.mes_nombre(S.mes_act)); poner_valor(p, 'Semana', S.ACT); p.wait_for_timeout(1500)
    ctx.set_offline(True); p.wait_for_timeout(800); alternar()
    b = boton(p, 'Crear la tabla')
    chk['offline'] = {'boton': b.count(), 'habilitado': b.first.is_enabled() if b.count() else None, 'texto': textos(p, 'requiere conexión', 'aún no tiene', 'No se pudo')}
    R.shot(p, f'Paso 1: sin conexión, semana sin tabla: {chk["offline"]}')
    ctx.set_offline(False); p.wait_for_timeout(2500)

    def cortar(route):
        if route.request.method == 'POST':
            route.fetch(); route.abort('connectionreset')
        else:
            route.continue_()
    p.route('**/api/lectura/tablas', cortar); alternar()
    if boton(p, 'Crear la tabla').count():
        boton(p, 'Crear la tabla').first.click(); p.wait_for_timeout(3000)
    chk['corte'] = {'avisos': toasts_txt(p), 'texto': textos(p, 'Conexión inestable', 'No se pudo', 'aún no tiene'), 'api': lec_api(S.ACT, S.mes_act)}
    R.shot(p, f'Paso 5: el servidor crea la tabla y la respuesta se pierde: {chk["corte"]}')
    p.unroute('**/api/lectura/tablas')
    if boton(p, 'Crear la tabla').count():
        boton(p, 'Crear la tabla').first.click()
    p.wait_for_timeout(3000)
    chk['reintento'] = {'avisos': toasts_txt(p), 'texto': textos(p, 'Ya existe', 'Clase de esta semana'), 'api': lec_api(S.ACT, S.mes_act)}
    R.shot(p, f'Paso 5: al reintentar con conexión: {chk["reintento"]}')
    abrir_lec(p, S.ANT, S.mes_ant, ir_=False); ctx.set_offline(True); p.wait_for_timeout(500)
    chk['otra_sesion'] = tabla_post(C, act_de(C), S.ANT, S.mes_ant)[0]
    ctx.set_offline(False); p.wait_for_timeout(2500)
    poner(p, 'Mes', FE.mes_nombre(S.mes_act)); poner_valor(p, 'Semana', S.ACT); poner(p, 'Mes', FE.mes_nombre(S.mes_ant)); poner_valor(p, 'Semana', S.ANT); p.wait_for_timeout(2000)
    chk['tras_otra'] = (textos(p, 'Clase de esta semana', 'aún no tiene'), lec_api(S.ANT, S.mes_ant))
    R.shot(p, f'Paso 4: la tabla de la semana anterior creada desde otra sesión (HTTP {chk["otra_sesion"]}) mientras esta estaba sin conexión: {chk["tras_otra"]}')
    _fin(R, chk, n)


@caso('CP-LEC-06')
def cp_lec06():
    R = Run('CP-LEC-06'); chk = {}; C = _c(); S = Semanas()
    if not _sem_req(R, S, 'ACT'):
        R.save(checks=chk); return
    prep_tabla(S)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); red = espiar(p); con_actividad(p, C); abrir_lec(p, S.ACT, S.mes_act)
    F = lambda nombres: filas_api(S.ACT, S.mes_act, nombres)  # noqa: E731
    escribir(p, 'Ana Norte QA', 'titulo', 'El zorro y la luna'); chk['tras_titulo'] = (toasts_txt(p), fila_lec(p, 'Ana Norte QA'))
    escribir(p, 'Ana Norte QA', 'nota', 0); escribir(p, 'Ana Norte QA', 'maximo', 5); escribir(p, 'Ana Norte QA', 'lsl', 3); p.wait_for_timeout(2000)
    chk['ana'] = fila_lec(p, 'Ana Norte QA'); chk['red_ana'] = list(red)
    R.shot(p, f'Paso 1: Ana: título, nota 0, máximo 5 y LSL 3 → {chk["ana"]}; al salir del título: {chk["tras_titulo"]}')
    escribir(p, 'Beto Norte QA', 'lsl', 0); chk['beto'] = fila_lec(p, 'Beto Norte QA')
    R.shot(p, f'Paso 2: Beto solo con LSL 0 → {chk["beto"]}')
    chk['dante_vacio'] = fila_lec(p, 'Dante Norte QA')
    R.shot(p, f'Paso 3: LSL vacío → {chk["dante_vacio"]}')
    escribir(p, 'Dante Norte QA', 'titulo', 'Solo título'); chk['solo_titulo'] = (toasts_txt(p), fila_lec(p, 'Dante Norte QA'), F(['Dante']))
    R.shot(p, f'Paso 4: título sin nota ni máximo → {chk["solo_titulo"]}')
    escribir(p, 'Dante Norte QA', 'maximo', 5); escribir(p, 'Dante Norte QA', 'nota', 7); chk['nota7'] = (toasts_txt(p), fila_lec(p, 'Dante Norte QA'), F(['Dante']))
    R.shot(p, f'Paso 5: nota 7 con máximo 5 → {chk["nota7"]}')
    e = p.get_by_label('Libros de sala de lectura de Dante Norte QA', exact=True)
    try:
        e.fill('abc'); chk['abc'] = e.input_value()
    except Exception as ex:
        chk['abc'] = 'el campo no admite texto: ' + str(ex)[:60]
    e.fill('-1'); e.press('Tab'); p.wait_for_timeout(1500)
    chk['menos1'] = (toasts_txt(p), e.evaluate("e=>[e.validity.valid, e.validationMessage, getComputedStyle(e).borderColor]"), F(['Dante']))
    R.shot(p, f'Paso 6: LSL "abc" → {chk["abc"]}; LSL -1 → {chk["menos1"]}')
    escribir(p, 'Dante Norte QA', 'nota', 4); escribir(p, 'Dante Norte QA', 'lsl', 1)
    chk['boton_guardar'] = boton(p, 'Guardar').all_inner_texts()
    chk['api'] = F(['Ana', 'Beto', 'Dante'])
    R.shot(p, f'Paso 7: corregido; botón "Guardar reporte semanal" = {chk["boton_guardar"] or "no existe (guardado al salir de cada campo)"}; avisos {toasts_txt(p)}', full=True)
    R.consola(ctx, 'Paso 7: lo guardado (alumno | título | nota | máximo | LSL | observación | versión | estado)', [str(r) for r in (chk['api'] if isinstance(chk['api'], list) else [chk['api']])])
    n0 = len(red); f = p.get_by_label('Libros de sala de lectura de Ana Norte QA', exact=True); f.focus(); f.press('Tab'); p.wait_for_timeout(1500)
    chk['sin_cambios'] = (len(red) - n0, toasts_txt(p))
    escribir(p, 'Ana Norte QA', 'lsl', 4); chk['actualizar'] = F(['Ana'])
    R.shot(p, f'Paso 8: salir sin cambios → peticiones {chk["sin_cambios"]}; Ana LSL 3 → 4: {chk["actualizar"]}')
    R.consola(ctx, 'Red (escrituras de lectura)', [str(x) for x in red][-14:])
    _fin(R, chk, n)


@caso('CP-LEC-07', modo='parcial', notas='La sesión expirada del paso 3 se simula cerrando la sesión en el servidor.')
def cp_lec07():
    R = Run('CP-LEC-07'); chk = {}; C = _c(); S = Semanas()
    if not _sem_req(R, S, 'ACT'):
        R.save(checks=chk); return
    prep_tabla(S)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C)
    abrir_lec(p, S.ACT, S.mes_act); abrir_asis(p, S.F, sub='Comprensión Lectora'); ctx.set_offline(True); p.wait_for_timeout(500)
    marcar_asis(p, 'Carla Norte QA', 'Presente', esperar=False)
    abrir_lec(p, S.ACT, S.mes_act); chk['carla_offline'] = fila_lec(p, 'Carla Norte QA')
    try:
        escribir(p, 'Carla Norte QA', 'lsl', 2)
    except Exception as e:
        chk['carla_lsl'] = 'campo bloqueado: ' + str(e)[:50]
    fallo = False
    try:
        escribir(p, 'Ana Norte QA', 'lsl', 2)
    except Exception:
        chk['ana_offline'] = ('no se pudo escribir', filtros_ui(p)[:6], textos(p, 'Complete', 'conexión', 'tabla', 'Sin clases', 'No se pudo')[:4])
        R.shot(p, f'Paso 1: Seguimiento de Lectura sin conexión: {chk["ana_offline"]}', full=True)
        ctx.set_offline(False); p.wait_for_timeout(5000); fallo = True
    if not fallo:
        chk['avisos_offline'] = toasts_txt(p); raw = idb_todo(p); chk['cola'] = cola_idb(p)[:3]; ids = ids_operacion(raw)
        chk['cabecera'] = p.locator('header').first.inner_text().replace('\n', ' ')[:100]
        R.shot(p, f'Paso 1: sin conexión: Carla presente en Asistencias y su fila en Lectura {chk["carla_offline"]}; Ana LSL 2 → avisos {chk["avisos_offline"]}; cabecera "{chk["cabecera"]}"')
        R.consola(ctx, 'Paso 1: IndexedDB', [str(c)[:430] for c in chk['cola']])
        ctx.set_offline(False); p.wait_for_timeout(10000)
        chk['ops'] = ops_api(C, ids)
        chk['api'] = (filas_api(S.ACT, S.mes_act, ['Ana', 'Carla']), de_alumno(S.F, 'Carla Norte QA'), de_alumno(S.F, 'Ana Norte QA'))
        R.consola(ctx, 'Paso 2: tras reconectar (API)', [f'Operaciones de la cola (id | HTTP | estado | motivo): {chk["ops"]}', f'Lectura: {chk["api"][0]}', f'Asistencia de Carla y Ana: {chk["api"][1:]}'])
        R.nota('Paso 2: el orden de llegada de las operaciones (asistencia antes que lectura) solo se ve en la base de datos; en QA se ve su resultado.')
        abrir_lec(p, S.ACT, S.mes_act); tk_ses = token_navegador(p)
        ctx.set_offline(True); p.wait_for_timeout(500); escribir(p, 'Beto Norte QA', 'lsl', 5)
        A.api('POST', '/logout', tk_ses)
        R.nota('Paso 3: la sesión se cerró en el servidor con POST /logout (en local se expiraba en la base).')
        ctx.set_offline(False); p.wait_for_timeout(8000)
        chk['expirada'] = {'url': p.url.replace(BASE, ''), 'beto': filas_api(S.ACT, S.mes_act, ['Beto']), 'cola': len(cola_idb(p))}
        R.shot(p, f'Paso 3: sesión cerrada al reconectar: {chk["expirada"]}', full=True)
        D1 = D.cuenta('rv-uno')
        if '/login' not in p.url:
            p.goto(BASE + '/login'); p.wait_for_timeout(2000)
        llenar_login(p, D1.correo, D1.clave); p.click('button[type=submit]'); p.wait_for_timeout(5000)
        chk['otro_docente'] = {'url': p.url.replace(BASE, ''), 'cabecera': p.locator('header').first.inner_text().replace('\n', ' ')[:100] if p.locator('header').count() else None,
                               'cola': len(cola_idb(p)), 'beto': filas_api(S.ACT, S.mes_act, ['Beto'])}
        R.shot(p, f'Paso 3: entra otro Docente (Docente RV) en el mismo navegador: {chk["otro_docente"]}', full=True)
        try:
            logout(p)
        except Exception:
            pass
        p.wait_for_timeout(1500)
        if '/login' not in p.url:
            p.goto(BASE + '/login')
        llenar_login(p, C.correo, C.clave); p.click('button[type=submit]'); p.wait_for_timeout(8000); C.usar_token(token_navegador(p))
        chk['original'] = {'url': p.url.replace(BASE, ''), 'cola': len(cola_idb(p)), 'beto': filas_api(S.ACT, S.mes_act, ['Beto'])}
        R.shot(p, f'Paso 3: vuelve el Docente original: {chk["original"]}', full=True)
    b = p.get_by_role('button', name='Iniciar actividad')
    if b.count():
        b.first.click(); p.wait_for_timeout(1500)
    chk['inactivar'] = A.desactivar_alumno(D.alumno('Elsa Norte QA'), A.hoy())[0]
    if chk['inactivar'] >= 300:
        R.nota('Paso 4: no se pudo inactivar a Elsa desde hoy porque la clase de hoy ya tiene su lista guardada (409); el paso queda sin la alumna inactiva.')
    put_asis(C, S.F, [(D.alumno('Elsa Norte QA'), 'presente', None)], act_de(C))
    abrir_lec(p, S.ACT, S.mes_act)
    try:
        escribir(p, 'Elsa Norte QA', 'lsl', 1)
    except Exception:
        el = D.alumno('Elsa Norte QA'); t = lec_api(S.ACT, S.mes_act)
        chk['inactiva_ui'] = ('campo bloqueado en la pantalla', fila_lec(p, 'Elsa Norte QA'))
        chk['inactiva_api'] = filas_put(C, t.get('id'), act_de(C), [(el, version_fila(C, el, S.ACT, S.mes_act), {'cantidad_lsl': 1})])
    chk['inactiva'] = (fila_lec(p, 'Elsa Norte QA'), toasts_txt(p), filas_api(S.ACT, S.mes_act, ['Elsa']))
    R.shot(p, f'Paso 4: Elsa inactivada hoy (HTTP {chk["inactivar"]}) y con LSL 1: {chk["inactiva"]}; por la API: {chk.get("inactiva_api", "-")}')
    if S.PA:
        uid = D.id_usuario('docente-a'); act = act_de(C)
        pr = A.permiso(uid, D.X(), 3, S.pa_ant['id_periodo_academico'], 'lectura', A.ahora() + dt.timedelta(days=30)); pid = (pr[1] or {}).get('id')
        put_asis(C, S.F_pa, [(D.alumno('Ana Norte QA'), 'presente', None)], act); tabla_post(C, act, S.PA, S.mes_pa)
        A.api('POST', f'/usuarios/{uid}/permisos/{pid}/revocar', A.sup(), {'motivo': 'Prueba QA'})
        abrir_lec(p, S.PA, S.mes_pa, ir_=False)
        chk['sin_habilitacion'] = (aviso_sup(p), fila_lec(p, 'Ana Norte QA'))
        R.shot(p, f'Paso 5: tabla de la semana del {FE.legible(S.F_pa)} (PA{S.pa_ant["numero"]}) sin habilitación: {chk["sin_habilitacion"]}')
    abrir_lec(p, S.ACT, S.mes_act, ir_=False); A.finalizar_actividad(C, act_de(C))
    e = p.get_by_label('Libros de sala de lectura de Beto Norte QA', exact=True)
    try:
        e.fill('7', timeout=5000); e.press('Tab'); p.wait_for_timeout(2500)
        chk['sin_actividad'] = (toasts_txt(p), e.input_value(), filas_api(S.ACT, S.mes_act, ['Beto']))
    except Exception as ex:
        chk['sin_actividad'] = ('campo bloqueado', str(ex)[:60])
    R.shot(p, f'Paso 6: actividad finalizada en otra pestaña y LSL 7 para Beto: {chk["sin_actividad"]}')
    _fin(R, chk, n)


@caso('CP-LEC-08')
def cp_lec08():
    R = Run('CP-LEC-08'); chk = {}; C = _c(); S = Semanas()
    if not _sem_req(R, S, 'ACT'):
        R.save(checks=chk); return
    prep_tabla(S)
    Fad = FE.lectivo_sin_clase(3, desde=max(S.ini_act, FE.pa_actual()['fecha_inicio'] and A.fecha(FE.pa_actual()['fecha_inicio'])), hasta=min(A.hoy(), S.fin_act))
    if not Fad:
        R.nota('No hay otro día lectivo en la semana actual para la clase adicional.'); R.save(checks=chk); return
    _, act = nueva_act(C)
    chk['adicional'] = put_asis(C, Fad, [(D.alumno('Ana Norte QA'), 'ausente', None), (D.alumno('Elsa Norte QA'), 'presente', None)], act, adicional=True); A.cerrar_abiertas(C)
    asis_antes = (asis_api(S.F), asis_api(Fad))
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C); abrir_lec(p, S.ACT, S.mes_act)
    chk['clase'] = (textos(p, 'Clase de esta semana', 'Clase programada'), boton(p, 'Cambiar clase').count(),
                    {k: (fila_lec(p, k) or {}).get('celdas', [None, None])[1] for k in ['Ana Norte QA', 'Elsa Norte QA']})
    R.shot(p, f'Paso 1: {chk["clase"]}')
    if boton(p, 'Cambiar clase').count():
        boton(p, 'Cambiar clase').first.click(); p.wait_for_timeout(1500); d = p.locator('[role=dialog]:visible').last
        chk['modal'] = (d.inner_text()[:400], d.locator('option, [role=radio], input[type=radio]').evaluate_all("els=>els.map(e=>e.innerText||e.value||e.getAttribute('aria-label'))"))
        R.shot(p, f'Paso 2: "Cambiar clase": {chk["modal"]}')
        try:
            if 'No hay otra clase' in chk['modal'][0]:
                raise Exception('el modal no ofrece la clase adicional')
            s = d.locator('select')
            if s.count():
                s.first.select_option(index=s.first.locator('option').count() - 1)
            else:
                d.locator('input[type=radio], [role=radio]').last.click()
            p.wait_for_timeout(500); d.get_by_role('button', name=re.compile('Confirmar|Cambiar|Guardar')).last.click(); p.wait_for_timeout(2500)
        except Exception as e:
            chk['cambiar_error'] = str(e)[:80]; cerrar_dialogos(p)
    chk['tras_cambio'] = (textos(p, 'Clase de esta semana', 'Clase adicional'), toasts_txt(p),
                          {k: (fila_lec(p, k) or {}).get('celdas', [None, None])[1] for k in ['Ana Norte QA', 'Elsa Norte QA', 'Beto Norte QA']},
                          {k: (fila_lec(p, k) or {}).get('deshabilitados') for k in ['Ana Norte QA', 'Elsa Norte QA']})
    chk['asis_intactas'] = (asis_api(S.F), asis_api(Fad)) == asis_antes; chk['api'] = lec_api(S.ACT, S.mes_act)
    R.shot(p, f'Paso 3: clase adicional del {FE.legible(Fad)} elegida: {chk["tras_cambio"]}; asistencias sin cambios = {chk["asis_intactas"]}; tabla {chk["api"]}', full=True)
    if chk.get('cambiar_error'):
        cl = [c for c in clases_api(Fad) if c[1] == 'adicional']
        tg = tabla_get(C, S.ACT, S.mes_act)[1]
        chk['patch_api'] = A.api('PATCH', f'/lectura/tablas/{tg.get("id")}/clase-referencia', C, {'id_operacion': A.uid(), 'version': tg.get('version'), 'id_clase': cl[0][0]}) if cl else 'sin clase adicional'
        p.reload(); p.wait_for_timeout(3000); abrir_lec(p, S.ACT, S.mes_act)
        chk['tras_patch'] = (textos(p, 'Clase de esta semana', 'Clase adicional'), {k: (fila_lec(p, k) or {}).get('celdas', [None, None])[1] for k in ['Ana Norte QA', 'Elsa Norte QA']})
        R.consola(ctx, 'Paso 3: cambio de la clase de referencia por la API', [f'PATCH clase-referencia → {json.dumps(chk["patch_api"], ensure_ascii=False)[:500]}', f'Pantalla tras recargar: {chk["tras_patch"]}'])
    try:
        escribir(p, 'Elsa Norte QA', 'lsl', 2); p.wait_for_timeout(1500)
    except Exception as e:
        chk['elsa_error'] = str(e)[:60]
    chk['tras_lectura'] = (boton(p, 'Cambiar clase').count(), filas_api(S.ACT, S.mes_act, ['Elsa']))
    R.shot(p, f'Paso 4: tras guardar la lectura de Elsa: "Cambiar clase" = {chk["tras_lectura"][0]}; fila {chk["tras_lectura"][1]}')
    A.cerrar_abiertas(C); n.close()
    # Paso 5: clase del 1.º de la semana anterior trasladada a esta semana
    S1 = Semanas(grado=1); x = D.X()
    if not S1.ANT:
        R.nota('Paso 5: no hay una clase del 1.º en la semana anterior dentro del PA vigente.'); _fin(R, chk, None); return
    nueva = S1.F - UN_DIA
    while nueva > S1.F_ant and (nueva.isoweekday() > 5 or not A.es_lectivo(x, nueva)):
        nueva -= UN_DIA
    r = A.api('POST', f'/colegios/{x}/clases/reprogramaciones', A.sup(), {'id_grado': A.id_grado(1), 'id_seccion': A.seccion(x, 1), 'fecha_original': A.iso(S1.F_ant),
                                                                         'fecha_nueva': A.iso(nueva), 'motivo': 'Prueba QA'})
    chk['reprogramar'] = (r[0], (r[1] or {}).get('motivo') if isinstance(r[1], dict) else None)
    D1 = D.cuenta('rv-uno'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, D1)
    put_asis(D1, nueva, [(D.alumno('Grado1P1 Entrada QA'), 'presente', None)], act_de(D1), grado=1)
    abrir_lec(p, None, S1.mes_ant, grado='1.º', sub='Alfabetización'); chk['semanas_1'] = opciones(p, 'Semana')
    poner_valor(p, 'Semana', S1.ANT)
    chk['s_origen'] = (textos(p, 'Clase de esta semana', 'aún no tiene', 'Se creará', 'Sin clases', 'no tiene una clase'), boton(p, 'Crear la tabla').count())
    R.shot(p, f'Paso 5: 1.º, semana de origen (clase del {FE.legible(S1.F_ant)} trasladada al {FE.legible(nueva)}, HTTP {chk["reprogramar"]}): {chk["s_origen"]}; semanas {chk["semanas_1"]}')
    abrir_lec(p, S1.ACT, S1.mes_act, grado='1.º', sub='Alfabetización', ir_=False)
    chk['s_destino'] = textos(p, 'Clase de esta semana', 'aún no tiene', 'Se creará', 'Sin clases')
    if boton(p, 'Crear la tabla').count():
        boton(p, 'Crear la tabla').first.click(); p.wait_for_timeout(2500)
    chk['s_destino_creada'] = (textos(p, 'Clase de esta semana', 'Clase reprogramada', 'Clase programada'), lec_api(S1.ACT, S1.mes_act, prog=A.ALFA(), grado=1))
    R.shot(p, f'Paso 5: semana de destino: {chk["s_destino"]} → {chk["s_destino_creada"]}')
    _fin(R, chk, n, D1, C)


@caso('CP-LEC-09')
def cp_lec09():
    R = Run('CP-LEC-09'); chk = {}; C = _c(); S = Semanas()
    if not _sem_req(R, S, 'ACT'):
        R.save(checks=chk); return
    prep_tabla(S)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C); abrir_lec(p, S.ACT, S.mes_act)
    b = boton(p, 'no realizada')
    chk['opcion'] = (b.all_inner_texts(), b.first.evaluate("e=>{const t=document.querySelector('main table');return t?(e.compareDocumentPosition(t)&Node.DOCUMENT_POSITION_FOLLOWING?'antes de la tabla':'después de la tabla'):null}") if b.count() else None)
    R.shot(p, f'Paso 1: opción {chk["opcion"]}')
    b.first.click(); p.wait_for_timeout(1000); d = p.locator('[role=dialog]:visible').last
    chk['modal'] = (d.inner_text()[:500], d.get_by_role('button').all_inner_texts(), p.locator('main table').is_visible())
    R.shot(p, f'Paso 2: {chk["modal"]}')
    ta = d.locator('textarea'); ta.fill('   '); bm = d.get_by_role('button', name=re.compile('Guardar|Confirmar|Marcar')).last
    habil = bm.is_enabled()
    if habil:
        bm.click(); p.wait_for_timeout(1200)
    chk['vacio'] = ('botón habilitado' if habil else 'botón deshabilitado con solo espacios', d.inner_text()[:300] if d.is_visible() else 'modal cerrado', toasts_txt(p), lec_api(S.ACT, S.mes_act).get('estado'))
    R.shot(p, f'Paso 3: justificación con solo espacios: {chk["vacio"]}')
    d.get_by_role('button', name='Cancelar').click(); p.wait_for_timeout(800)
    chk['cancelar'] = (p.locator('[role=dialog]:visible').count(), lec_api(S.ACT, S.mes_act).get('estado'), (fila_lec(p, 'Ana Norte QA') or {}).get('deshabilitados'))
    R.shot(p, f'Paso 4: Cancelar: {chk["cancelar"]}')
    boton(p, 'no realizada').first.click(); p.wait_for_timeout(800); d = p.locator('[role=dialog]:visible').last
    d.locator('textarea').fill('Paro de transportistas: no hubo clases.'); d.get_by_role('button', name=re.compile('Guardar|Confirmar|Marcar')).last.click(); p.wait_for_timeout(2500)
    chk['marcada'] = (toasts_txt(p), textos(p, 'no realizada', 'Paro'), fila_lec(p, 'Ana Norte QA'))
    R.shot(p, f'Paso 5: marcada como no realizada: {chk["marcada"]}', full=True)
    t = lec_api(S.ACT, S.mes_act)
    con_valores = [f for f in (filas_api(S.ACT, S.mes_act) or []) if isinstance(f, tuple) and any(v is not None for v in f[1:5])]
    chk['api'] = (t, len(con_valores))
    R.consola(ctx, 'Paso 6: lo guardado (API)', [f'Tabla (estado, motivo, declaraciones): {t}', f'Filas con valores de lectura: {len(con_valores)}'])
    ana = D.alumno('Ana Norte QA'); chk['detalle'] = A.api('GET', f'/alumnos/{ana}/resumen', A.sup())[1]
    p.goto(BASE + f'/estudiantes/{ana}'); p.wait_for_timeout(3000); chk['detalle_ui'] = textos(p, 'libros', 'Libros', 'lectura')
    R.shot(p, f'Paso 7: detalle de Ana: {chk["detalle_ui"]}', full=True)
    _fin(R, chk, n)


@caso('CP-LEC-10')
def cp_lec10():
    R = Run('CP-LEC-10'); chk = {}; C = _c(); S = Semanas()
    if not _sem_req(R, S, 'ACT', 'ANT'):
        R.save(checks=chk); return
    _, act = nueva_act(C); put_asis(C, S.F_ant, [(D.alumno('Ana Norte QA'), 'presente', None)], act); preparar_asis(C, act, S.F)
    s, t_ant = tabla_post(C, act, S.ANT, S.mes_ant)
    filas_put(C, t_ant['id'], act, [(D.alumno('Ana Norte QA'), version_fila(C, D.alumno('Ana Norte QA'), S.ANT, S.mes_ant), {'cantidad_lsl': 2})])
    s, t_act = tabla_post(C, act, S.ACT, S.mes_act); A.cerrar_abiertas(C)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C); abrir_lec(p, S.ANT, S.mes_ant)
    b = boton(p, 'no realizada'); chk['con_lecturas'] = {'boton': b.count(), 'habilitado': b.first.is_enabled() if b.count() else None}
    if b.count() and b.first.is_enabled():
        b.first.click(); p.wait_for_timeout(800); d = p.locator('[role=dialog]:visible').last; d.locator('textarea').fill('Prueba QA')
        d.get_by_role('button', name=re.compile('Guardar|Confirmar|Marcar')).last.click(); p.wait_for_timeout(2000)
        chk['con_lecturas']['resultado'] = (toasts_txt(p), lec_api(S.ANT, S.mes_ant).get('estado'))
    R.shot(p, f'Paso 1: semana anterior con lecturas guardadas: {chk["con_lecturas"]}')
    abrir_lec(p, S.ACT, S.mes_act, ir_=False); e = p.get_by_label('Libros de sala de lectura de Beto Norte QA', exact=True); e.fill('3')
    boton(p, 'no realizada').first.click(); p.wait_for_timeout(1500)
    chk['sin_guardar'] = (p.locator('[role=dialog]:visible').count(), toasts_txt(p), e.input_value(), filas_api(S.ACT, S.mes_act, ['Beto']))
    R.shot(p, f'Paso 2: LSL 3 de Beto escrito sin salir del campo y clic en "Marcar como no realizada": {chk["sin_guardar"]}')
    cerrar_dialogos(p)
    actp = act_de(C)
    chk['api_con_datos'] = A.api('POST', f'/lectura/tablas/{t_act["id"]}/no-realizada', C, {'id_operacion': A.uid(), 'version': tabla_get(C, S.ACT, S.mes_act)[1].get('version'), 'motivo': 'Prueba QA', 'id_actividad': actp})
    R.consola(ctx, 'Paso 3: la tabla de la semana actual ya tiene la lectura de Beto', [f'POST no-realizada → {chk["api_con_datos"]}'])
    if S.PA:
        uid = D.id_usuario('docente-a'); pr = A.permiso(uid, D.X(), 3, S.pa_ant['id_periodo_academico'], 'lectura', A.ahora() + dt.timedelta(days=30))
        put_asis(C, S.F_pa, [(D.alumno('Ana Norte QA'), 'presente', None)], actp); tabla_post(C, actp, S.PA, S.mes_pa)
        A.api('POST', f'/usuarios/{uid}/permisos/{pr[1]["id"]}/revocar', A.sup(), {'motivo': 'Prueba QA'})
        abrir_lec(p, S.PA, S.mes_pa, ir_=False); chk['sin_hab'] = (aviso_sup(p), boton(p, 'no realizada').count())
        R.shot(p, f'Paso 4: semana del {FE.legible(S.F_pa)} (PA{S.pa_ant["numero"]}) sin habilitación: {chk["sin_hab"]}')
    s, t3 = tabla_post(C, actp, S.ACT, S.mes_act, prog=A.ALFA()); abrir_lec(p, S.ACT, S.mes_act, sub='Alfabetización', ir_=False)
    A.finalizar_actividad(C, actp); p.reload(); p.wait_for_timeout(2500); abrir_lec(p, S.ACT, S.mes_act, sub='Alfabetización')
    chk['sin_actividad'] = (aviso_sup(p), boton(p, 'no realizada').count())
    R.shot(p, f'Paso 5: sin actividad (tabla de Alfabetización solo inicializada): {chk["sin_actividad"]}')
    _, act2 = nueva_act(C); v = tabla_get(C, S.ACT, S.mes_act, prog=A.ALFA())[1].get('version')
    chk['marcar_alfa'] = A.api('POST', f'/lectura/tablas/{t3["id"]}/no-realizada', C, {'id_operacion': A.uid(), 'version': v, 'motivo': 'Prueba QA', 'id_actividad': act2})[0]
    a3 = D.alumno('Alumno03 Volumen QA'); put_asis(C, S.F, [(a3, 'presente', None)], act2)
    chk['api_lectura'] = filas_put(C, t3['id'], act2, [(a3, version_fila(C, a3, S.ACT, S.mes_act, prog=A.ALFA()), {'cantidad_lsl': 2})])
    R.consola(ctx, 'Pasos 3 y 6: por la API', [f'Tabla de Alfabetización solo inicializada → POST no-realizada HTTP {chk["marcar_alfa"]}', f'PUT de una lectura en la tabla marcada → {chk["api_lectura"]}'])
    _fin(R, chk, n)


@caso('CP-LEC-11')
def cp_lec11():
    R = Run('CP-LEC-11'); chk = {}; C = _c(); S = Semanas()
    if not _sem_req(R, S, 'ACT'):
        R.save(checks=chk); return
    idt = prep_tabla(S)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C); abrir_lec(p, S.ACT, S.mes_act)
    ctx.set_offline(True); p.wait_for_timeout(800); b = boton(p, 'no realizada')
    chk['offline'] = {'boton': b.all_inner_texts(), 'habilitado': b.first.is_enabled() if b.count() else None, 'texto': textos(p, 'requiere conexión')}
    R.shot(p, f'Paso 1: sin conexión: {chk["offline"]}')
    ctx.set_offline(False); p.wait_for_timeout(2500)
    act = act_de(C); ana = D.alumno('Ana Norte QA')
    chk['otra_sesion'] = filas_put(C, idt, act, [(ana, version_fila(C, ana, S.ACT, S.mes_act), {'cantidad_lsl': 1})])
    boton(p, 'no realizada').first.click(); p.wait_for_timeout(800); d = p.locator('[role=dialog]:visible').last
    d.locator('textarea').fill('No hubo lectura por simulacro.'); d.get_by_role('button', name=re.compile('Guardar|Confirmar|Marcar')).last.click(); p.wait_for_timeout(2500)
    chk['conflicto'] = (toasts_txt(p), textos(p, 'Conflicto', 'versión actual', 'registros de lectura'), lec_api(S.ACT, S.mes_act).get('estado'))
    R.shot(p, f'Pasos 3-4: otra sesión guardó una lectura ({chk["otra_sesion"]}) antes de marcar: {chk["conflicto"]}', full=True)
    _fin(R, chk, n)


@caso('CP-LEC-12')
def cp_lec12():
    R = Run('CP-LEC-12'); chk = {}; C = _c(); S = Semanas()
    if not _sem_req(R, S, 'ACT'):
        R.save(checks=chk); return
    idt = prep_tabla(S, marcas=[('Ana Norte QA', 'presente'), ('Beto Norte QA', 'tardanza'), ('Elsa Norte QA', 'ausente')])
    _, act = nueva_act(C); ana = D.alumno('Ana Norte QA')
    chk['prep'] = filas_put(C, idt, act, [(ana, version_fila(C, ana, S.ACT, S.mes_act), {'lsn_titulo': 'El cóndor', 'lsn_nota': 4, 'lsn_maximo': 5, 'cantidad_lsl': 2})]); A.cerrar_abiertas(C)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C); abrir_lec(p, S.ACT, S.mes_act)
    chk['filas'] = {k: fila_lec(p, k) for k in ['Beto Norte QA', 'Carla Norte QA']}
    R.shot(p, f'Paso 1: Beto (Tardanza) y Carla (sin asistencia): {chk["filas"]}')
    act = act_de(C); car = D.alumno('Carla Norte QA'); elsa = D.alumno('Elsa Norte QA')
    chk['api_sin_asistencia'] = filas_put(C, idt, act, [(car, version_fila(C, car, S.ACT, S.mes_act), {'cantidad_lsl': 2})])
    chk['api_ausente'] = filas_put(C, idt, act, [(elsa, version_fila(C, elsa, S.ACT, S.mes_act), {'cantidad_lsl': 2})])
    R.consola(ctx, 'Paso 2: lecturas por la API', [f'Carla (sin asistencia) → {chk["api_sin_asistencia"]}', f'Elsa (Ausente) → {chk["api_ausente"]}'])
    abrir_asis(p, S.F, sub='Comprensión Lectora'); chk['ausente'] = marcar_asis(p, 'Ana Norte QA', 'Ausente')
    R.shot(p, f'Paso 3: Ana pasa a Ausente en Asistencias → {chk["ausente"]}')
    abrir_lec(p, S.ACT, S.mes_act); chk['revisar'] = (fila_lec(p, 'Ana Norte QA'), textos(p, 'Revis'))
    fa = next((f for f in tabla_get(C, S.ACT, S.mes_act)[1].get('filas', []) if f['nombre'].startswith('Ana')), {})
    chk['revisar_api'] = {k: fa.get(k) for k in ['asistencia', 'estado_fila', 'revisar_asistencia', 'total_libros']}
    p.reload(); p.wait_for_timeout(3000); abrir_lec(p, S.ACT, S.mes_act); chk['revisar_recarga'] = (fila_lec(p, 'Ana Norte QA'), textos(p, 'Revis'))
    R.shot(p, f'Paso 4: al volver a la tabla {chk["revisar"]}; API {chk["revisar_api"]}; tras recargar {chk["revisar_recarga"]}')
    g = p.get_by_role('button', name=re.compile('observación de Ana Norte QA')).first; chk['obs_boton'] = g.is_enabled()
    g.click(); p.wait_for_timeout(800); d = p.locator('[role=dialog]:visible').last; d.locator('textarea').fill('Revisar: figura ausente pero leyó en la sala.')
    d.get_by_role('button', name=re.compile('Guardar')).last.click(); p.wait_for_timeout(2500)
    chk['obs'] = (toasts_txt(p), filas_api(S.ACT, S.mes_act, ['Ana']))
    R.shot(p, f'Paso 5: observación de Ana (botón habilitado = {chk["obs_boton"]}): {chk["obs"]}')
    _fin(R, chk, n)


@caso('CP-LEC-13', notas='Usa un calendario particular del colegio Sur con hoy dentro del PR2 (como en local).')
def cp_lec13():
    R = Run('CP-LEC-13'); chk = {}; Y = D.Y(); CR = D.cuenta('retro')
    s, r = FE.poner_calendario_en_pr(Y, True); chk['calendario'] = (s, r.get('detail') if isinstance(r, dict) and s >= 300 else None)
    if s >= 300:
        R.nota(f'No se pudo crear el calendario particular: {r}'); R.save(checks=chk); return
    cal = A.calendario(Y); pa2 = FE.pa(2, Y)
    aid = A.crear_alumno('Rita', 'Retro Lectura QA', Y, 3, A.CL(), pa2['fecha_inicio'])
    chk['asig'] = A.asignar(D.id_usuario('retro'), [(Y, [3])], 'retroactivo')
    cl_pa2 = FE.clases_habituales(3, pa2['fecha_inicio'], pa2['fecha_fin'], Y)
    F_pa2 = cl_pa2[-1] if cl_pa2 else None
    SPA2, mes_pa2, *_ = FE.semana_de(F_pa2, 3, Y) if F_pa2 else (None, None)
    # La semana del PR no tiene clases en el colegio Sur: su id (que es del año, no del colegio) se toma del colegio Norte.
    d_pr = A.hoy() - dt.timedelta(days=7) if A.hoy() - dt.timedelta(days=7) > A.fecha(pa2['fecha_fin']) else A.hoy()
    SPR, mes_pr, *_ = FE.semana_de(d_pr, 3, D.X())
    NY = D.nombre_colegio('sur')
    n = Nav(); ctx = n.ctx(); p = ctx.new_page()
    R.consola(ctx, 'Paso 1: colegio Sur con calendario particular (hoy en el PR2) y Docente Retro con asignación Retroactiva',
              [f'Calendario particular → HTTP {s}', f'Periodos: {[(x["tipo"] + str(x["numero"]), x["fecha_inicio"], x["fecha_fin"]) for x in cal["periodos"]]}',
               f'PATCH asignación retroactiva → {chk["asig"][0]} {str(chk["asig"][1])[:200]}'])
    con_actividad(p, CR); actr = act_de(CR)
    chk['asis_pa2'] = put_asis(CR, F_pa2, [(aid, 'presente', None)], actr, colegio=Y)
    abrir_lec(p, SPA2, mes_pa2, colegio=NY)
    b = boton(p, 'Crear la tabla'); chk['pa2_ui'] = (aviso_sup(p), textos(p, 'aún no tiene', 'Se creará'), b.count())
    if b.count():
        b.first.click(); p.wait_for_timeout(2500)
    tg = tabla_get(CR, SPA2, mes_pa2, colegio=Y)
    if tg[0] != 200:
        tabla_post(CR, actr, SPA2, mes_pa2, colegio=Y); tg = tabla_get(CR, SPA2, mes_pa2, colegio=Y)
    idt = (tg[1] or {}).get('id')
    try:
        escribir(p, 'Rita Retro Lectura QA', 'lsl', 2)
    except Exception as e:
        chk['lsl_ui'] = str(e)[:60]
    chk['pa2'] = (toasts_txt(p), filas_api(SPA2, mes_pa2, ['Rita'], colegio=Y))
    R.shot(p, f'Paso 2: durante el PR2, semana de la clase del {FE.legible(F_pa2)} (PA2): {chk["pa2_ui"]}; LSL 2 de Rita → {chk["pa2"]}', full=True)
    abrir_lec(p, SPR, mes_pr, colegio=NY, ir_=False)
    r = tabla_post(CR, actr, SPR, mes_pr, colegio=Y)
    chk['pr_ui'] = (aviso_sup(p), textos(p, 'aún no tiene', 'Sin clases', 'Se creará'), boton(p, 'Crear la tabla').count(), opciones(p, 'Semana'))
    chk['pr_api'] = (r[0], (r[1] or {}).get('motivo') if isinstance(r[1], dict) else r[1])
    R.shot(p, f'Paso 3: semana del PR2: {chk["pr_ui"]}; POST → {chk["pr_api"]}')
    chk['mover'] = FE.poner_calendario_en_pr(Y, False, A.calendario(Y))[0]
    A.cerrar_abiertas(CR); n.close(); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, CR); actr = act_de(CR)
    abrir_lec(p, SPA2, mes_pa2, colegio=NY)
    chk['fin_pr'] = (aviso_sup(p), filas_put(CR, idt, actr, [(aid, version_fila(CR, aid, SPA2, mes_pa2, colegio=Y), {'cantidad_lsl': 3})]) if idt else None)
    R.shot(p, f'Paso 4: PR2 terminado (PUT calendario → {chk["mover"]}): {chk["fin_pr"]}')
    pm = A.permiso(D.id_usuario('retro'), Y, 3, pa2['id_periodo_academico'], 'lectura', A.ahora() + dt.timedelta(days=30)); chk['permiso'] = pm[0]
    p.reload(); p.wait_for_timeout(2500); abrir_lec(p, SPA2, mes_pa2, colegio=NY)
    chk['con_permiso_ui'] = aviso_sup(p); chk['escritura_api'] = (tabla_get(CR, SPA2, mes_pa2, colegio=Y)[1] or {}).get('escritura')
    try:
        escribir(p, 'Rita Retro Lectura QA', 'lsl', 4)
    except Exception as e:
        chk['ui_bloqueada'] = str(e)[:60]
        chk['api_con_permiso'] = filas_put(CR, idt, actr, [(aid, version_fila(CR, aid, SPA2, mes_pa2, colegio=Y), {'cantidad_lsl': 4})]) if idt else None
    chk['fila'] = (toasts_txt(p), filas_api(SPA2, mes_pa2, ['Rita'], colegio=Y))
    R.shot(p, f'Paso 5: con permiso de Lectura para PA2 (HTTP {pm[0]}): {chk["con_permiso_ui"]}; escritura según la API {chk["escritura_api"]}; LSL 4 → {chk.get("api_con_permiso", "")} {chk["fila"]}')
    _fin(R, chk, n, CR)


@caso('CP-LEC-14')
def cp_lec14():
    R = Run('CP-LEC-14'); chk = {}; C = _c(); S = Semanas()
    if not _sem_req(R, S, 'ACT'):
        R.save(checks=chk); return
    _, act = nueva_act(C)
    preparar_asis(C, act, S.F, marcas=[('Ana Norte QA', 'presente'), ('Alumno03 Volumen QA', 'presente'), ('Alumno06 Volumen QA', 'tardanza')]); A.cerrar_abiertas(C)
    asis_antes = asis_api(S.F)
    n = Nav(); ctx = n.ctx(); p = ctx.new_page(); con_actividad(p, C)
    abrir_lec(p, S.ACT, S.mes_act, sub='Alfabetización'); boton(p, 'Crear la tabla').first.click(); p.wait_for_timeout(3000)
    nombres = [t.split('\n')[0] for t in p.locator('main tbody tr td:first-child').all_inner_texts()]
    chk['alfa'] = (len(nombres), sorted(set(n_.split(' ')[0] for n_ in nombres))[:15])
    R.shot(p, f'Paso 1: tabla de Alfabetización: {chk["alfa"]}', full=True)
    abrir_lec(p, S.ACT, S.mes_act, sub='Comprensión Lectora', ir_=False); boton(p, 'Crear la tabla').first.click(); p.wait_for_timeout(3000)
    nombres = [t.split('\n')[0] for t in p.locator('main tbody tr td:first-child').all_inner_texts()]
    chk['cl'] = (len(nombres), [x for x in nombres if 'Alumno03' in x or 'Alumno06' in x])
    R.shot(p, f'Paso 2: tabla de Comprensión Lectora: {chk["cl"][0]} alumnos; de Alfabetización en ella: {chk["cl"][1]}', full=True)
    chk['api'] = (lec_api(S.ACT, S.mes_act, prog=A.ALFA()), lec_api(S.ACT, S.mes_act), asis_antes == asis_api(S.F))
    R.consola(ctx, 'Paso 3: lo guardado (API)', [f'Tabla de Alfabetización: {chk["api"][0]}', f'Tabla de Comprensión Lectora: {chk["api"][1]}', f'Asistencias sin cambios: {chk["api"][2]}'])
    abrir_lec(p, S.ACT, S.mes_act, sub='Alfabetización', ir_=False); chk['otra'] = (textos(p, 'Clase de esta semana', 'aún no tiene', 'Ya existe'), boton(p, 'Crear la tabla').count())
    r = tabla_post(C, act_de(C), S.ACT, S.mes_act, prog=A.ALFA()); chk['otra_api'] = (r[0], (r[1] or {}).get('motivo'), (r[1] or {}).get('id'))
    R.shot(p, f'Paso 4: volver a Alfabetización: {chk["otra"]}; POST por la API → {chk["otra_api"]}')
    _fin(R, chk, n)
