"""Inicio (CU009 a CU012): CP-INI-01 a CP-INI-29, adaptados a QA.

- En QA no se mueve el reloj del servidor ni el calendario general (lo comparte todo el equipo): los
  recesos y los cambios de periodo se hacen con fechas particulares de los colegios del caso.
- Los indicadores de la Supervisora y del Directivo son globales y en QA hay datos de otros probadores:
  se verifica la diferencia (delta) que produce cada acción, no el valor absoluto.
- Lo que en local se leía en la base de datos se lee por la API (actividades, asistencias, rúbricas) o queda como NOTA.
"""
import datetime as dt
import json
import re
import time

from lib import api as A
from lib import datos as D
from lib import fechas as FE
from lib.catalogo import SOLO_LOCAL, caso
from lib.ui import (BASE, Nav, Run, backend_caido, cola_idb, con_actividad, idb_todo, ir, login, logout, main_txt, textos,
                    toasts_txt, token_navegador)

from casos._comun import crear_colegio, fin, hhmmss, sup_ui
from casos.asi import abrir_asis, controles, de_alumno, marcar_asis, put_asis
from casos.lec import Semanas, abrir_lec, escribir, filas_api, tabla_post
from casos.rub import abrir_rubrica, elegir, rub_de
from casos.rv import abrir_rv, elegir_rv
from casos.ses import acts

SOLO_LOCAL['CP-INI-20'] = ('Necesita fijar en la base de datos el último inicio de sesión de varios Docentes (hace 2, 4 y 10 días); '
                           'en QA no se puede cambiar esa fecha.')
SOLO_LOCAL['CP-INI-24'] = ('Necesita Docentes con su última actividad hace varios días hábiles (fechas de actividad en la base de datos); '
                           'en QA las actividades solo se pueden crear con la hora actual.')
SOLO_LOCAL['CP-INI-29'] = 'Necesita mover la hora del servidor (viernes 23:59, último día del mes).'

MSG_SIN = 'No puedes iniciar una actividad porque no tienes asignaciones habilitadas ni permisos excepcionales vigentes.'
AVISO_ACT = 'Inicia una actividad de trabajo para habilitar el registro de datos.'
DEBES = 'Debes iniciar una actividad de trabajo para registrar o modificar información.'
RECESO = 'La fecha seleccionada corresponde a un periodo de receso.'
TXT_ACT = re.compile(r'Actividad iniciada a las (\d\d:\d\d)\. La sesión finaliza (?:el (\d\d/\d\d) )?a las (\d\d:\d\d)\.')
PEND = re.compile(r'Tienes (\d+) registros? offline pendientes? de sincronizar\.?')


# ── Ayudas ──────────────────────────────────────────────────────────────────────────

def cuerpo_lineas(p, *pal):
    """Como textos(), pero lee todo el body y no espera a que exista <main> (la página puede quedar en un error)."""
    try:
        t = p.locator('body').inner_text(timeout=5000)
    except Exception as e:
        return ['(sin página: ' + str(e).split(chr(10))[0][:60] + ')']
    return [l for l in t.split('\n') if any(w.lower() in l.lower() for w in pal)][:4]


def texto_act(p):
    m = TXT_ACT.search(main_txt(p))
    return m.group(0) if m else None


def pendientes(p):
    m = PEND.search(main_txt(p))
    return int(m.group(1)) if m else None


def boton(p, nombre='Iniciar actividad'):
    b = p.get_by_role('button', name=nombre)
    return {'visible': b.count() > 0, 'habilitado': b.first.is_enabled() if b.count() else None}


def iniciar_ui(p):
    p.get_by_role('button', name='Iniciar actividad').first.click(); p.wait_for_timeout(2200)


def finalizar_ui(p):
    p.get_by_role('button', name='Finalizar actividad').first.click(); p.wait_for_timeout(2200)


def sup_res():
    r = A.api('GET', '/inicio/supervisor', A.sup())[1]
    return {k: r.get(k) for k in ('colegios_registrados', 'docentes_activos', 'docentes_con_actividad_activa', 'registros_vencidos',
                                  'registros_incompletos', 'vencidos_por_modulo', 'incompletos_por_modulo')} if isinstance(r, dict) else r


def dir_res():
    r = A.api('GET', '/inicio/directivo', D.cuenta('directivo'))[1]
    return r if isinstance(r, dict) else {'error': r}


def delta(a, b, k):
    try:
        return b[k] - a[k]
    except Exception:
        return None


def act_api(cuenta, id_act):
    a = next((x for x in acts(cuenta) if x['id'] == id_act), None)
    return {k: a.get(k) for k in ('inicio', 'fin', 'tipo_cierre', 'sincronizacion', 'creada_sin_conexion', 'sincronizado_en', 'id_sesion') if k in a} if a else None


def red(p):
    lst = []
    p.on('request', lambda rq: lst.append(f'{A.ahora():%H:%M:%S} {rq.method} {rq.url.split("/api")[-1][:70]}')
         if '/api/' in rq.url and rq.method != 'GET' else None)
    return lst


def asignar_bloques(uid, bloques):
    """bloques: [(id_colegio, [grados], inicio)] con inicio None, 'retroactivo' o 'proximo' por colegio."""
    cols = []
    for c, gs, ini in bloques:
        b = {'id_colegio': c, 'grados': [A.id_grado(g) for g in gs]}
        if ini:
            b['inicio_asignacion'] = ini
        cols.append(b)
    return A.api('PATCH', f'/usuarios/{uid}', A.sup(), {'asignacion': {'id_anio_escolar': A.anio(), 'colegios': cols}})


def colegio_pr(R, ctx, etiqueta, grados=(3,), alumnos=True):
    """Colegio del caso con fechas particulares en que hoy cae en el receso posterior a PA2."""
    cid = crear_colegio(f'QA AUTO {hhmmss()} {etiqueta}', {g: min(A.hoy().isoweekday(), 5) for g in grados})
    s, r = FE.poner_calendario_en_pr(cid, True)
    if alumnos:
        for g in grados:
            A.crear_alumno('Alumno', f'{etiqueta} QA {g}', cid, g, A.CL(), FE.pa(1, cid)['fecha_inicio'])
    R.consola(ctx, f'Precondición: colegio {etiqueta} (API)', [f'{A.colegio(cid)["nombre"]}: fechas particulares con hoy en el receso posterior a PA2 → HTTP {s}'
                                                               f'{"" if s < 300 else " " + str(r)[:200]}', f'Periodo de hoy: {A.periodo_actual(cid)}'])
    return cid


def perm(uid, cid, grado, id_pa, modulo, fin_, inicio=None):
    b = {'id_anio_escolar': A.anio(), 'id_colegio': cid, 'id_grado': A.id_grado(grado), 'id_periodo_academico': id_pa, 'modulo': modulo,
         'fin': A.iso(fin_), 'motivo': 'Prueba QA automatizada'}
    if inicio:
        b['inicio'] = A.iso(inicio); b['desde_ahora'] = False
    else:
        b['desde_ahora'] = True
    return A.api('POST', f'/usuarios/{uid}/permisos', A.sup(), b)


def pid_de(r):
    return (r or {}).get('id') or (r or {}).get('id_permiso') if isinstance(r, dict) else None


# ── CP-INI-01 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-01')
def cp_ini01():
    R = Run('CP-INI-01'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a'); X = D.X()
    A.cerrar_abiertas(C); uid = D.id_usuario('docente-a'); pa = FE.pa_anterior(X)
    s, r = perm(uid, X, 4, pa['id_periodo_academico'], 'asistencias', A.ahora() + dt.timedelta(days=3))
    n3 = len(A.alumnos(X, 3)); n4 = len(A.alumnos(X, 4))
    R.consola(ctx, 'Precondición: asignaciones y permiso de Docente A (API)', [f'Asignación habilitada: {D.nombre_colegio()} 3.º ({n3} alumnos activos)',
                                                                              f'Permiso vigente para {D.nombre_colegio()} 4.º, PA{pa["numero"]}, Asistencias → HTTP {s}',
                                                                              f'Alumnos activos del 4.º (no deben sumarse): {n4}'])
    login(p, C); p.wait_for_timeout(2500); t = main_txt(p)
    chk['inicio'] = t[:1200]; chk['colegio'] = D.nombre_colegio() in t
    chk['alumnos_mostrados'] = re.findall(r'(\d+)\s*alumnos?', t, re.I)[:6]
    R.shot(p, f'Pasos 1-2: Inicio de Docente A: colegio visible {chk["colegio"]}; cantidades de alumnos {chk["alumnos_mostrados"]} (se espera {n3})', full=True)
    chk['apartado'] = 'Permisos de corrección vigentes' in t
    bloque = t.split('Permisos de corrección vigentes', 1)[1][:400] if chk['apartado'] else ''
    chk['permiso_txt'] = bloque.replace('\n', ' | ')
    chk['hora_peru'] = bool(re.search(r'\d\d:\d\d', bloque))
    R.shot(p, f'Pasos 3-4: apartado "Permisos de corrección vigentes" {chk["apartado"]}: {chk["permiso_txt"][:250]}')
    chk['pendientes'] = (pendientes(p), len(cola_idb(p)))
    chk['iniciar'] = boton(p); chk['cronometro'] = bool(re.search(r'\b\d\d:\d\d:\d\d\b', t))
    R.shot(p, f'Pasos 5-6: Resumen de Acción {chk["pendientes"][0]} pendientes (IndexedDB {chk["pendientes"][1]}); "Iniciar actividad" {chk["iniciar"]}; '
              f'cronómetro {chk["cronometro"]}')
    fin(R, chk, n, C)


# ── CP-INI-02 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-02', notas='La espera del paso 2 se acorta a 2 minutos.')
def cp_ini02():
    R = Run('CP-INI-02'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a')
    A.cerrar_abiertas(C); login(p, C); t0 = A.ahora(); tk = token_navegador(p)
    from casos.aut import jwt
    exp = dt.datetime.fromtimestamp(jwt(tk)['exp'], A.LIMA)
    R.shot(p, f'Paso 1: sesión iniciada a las {t0:%H:%M:%S} (T0); el token expira a las {exp:%H:%M}')
    time.sleep(120)
    t1 = A.ahora(); iniciar_ui(p)
    chk['boton'] = boton(p, 'Finalizar actividad'); chk['texto'] = texto_act(p)
    m = TXT_ACT.search(chk['texto'] or '')
    chk['horas'] = {'inicio': m.group(1) if m else None, 'esperado_inicio': f'{t1:%H:%M}', 'fin': m.group(3) if m else None,
                    'esperado_fin': f'{(t0 + dt.timedelta(hours=8)):%H:%M}'}
    R.shot(p, f'Pasos 2-4: "Iniciar actividad" a las {t1:%H:%M:%S} (T1): {chk["texto"]}; esperado {chk["horas"]}')
    time.sleep(60); chk['un_minuto_despues'] = texto_act(p)
    R.shot(p, f'Paso 5: un minuto después: {chk["un_minuto_despues"]} (igual: {chk["un_minuto_despues"] == chk["texto"]})')
    act = A.actividad_en_curso(token_navegador(p)); chk['api'] = act_api(token_navegador(p), act)
    R.consola(ctx, 'Paso 6: la actividad según la API (GET /api/actividades)', [json.dumps(chk['api'], ensure_ascii=False)])
    mods = {}
    abrir_rubrica(p); mods['Rúbrica'] = p.locator('main select:enabled').count()
    S = Semanas(); abrir_lec(p, S.ACT, S.mes_act); mods['Lectura'] = textos(p, 'Crear la tabla', 'Debes iniciar')[:2]
    abrir_rv(p); mods['Registro de Vuelo'] = p.locator('main select:enabled').count()
    ir(p, 'Alumnos'); ag = p.get_by_role('button', name='Agregar'); mods['Alumnos (Agregar habilitado)'] = ag.first.is_enabled() if ag.count() else None
    chk['modulos'] = mods
    R.shot(p, f'Paso 7: módulos con la actividad iniciada: {mods}')
    fin(R, chk, n, C)


# ── CP-INI-04 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-04')
def cp_ini04():
    R = Run('CP-INI-04'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a'); X = D.X()
    A.cerrar_abiertas(C); login(p, C); F = FE.ultima_clase(3)
    R.shot(p, 'Paso 1: Docente A en Inicio sin "Iniciar actividad"')
    abrir_asis(p, F)
    chk['asistencias'] = {'controles': controles(p), 'marcar_todos': 'Marcar todos como presentes' in main_txt(p), 'aviso': AVISO_ACT in main_txt(p)}
    R.shot(p, f'Paso 2: Asistencias del {FE.legible(F)} sin actividad: {chk["asistencias"]}')
    S = Semanas(); abrir_lec(p, S.ACT, S.mes_act); t = main_txt(p)
    chk['lectura'] = {'aviso': DEBES in t or AVISO_ACT in t, 'crear_tabla': 'Crear la tabla' in t or 'Crear tabla' in t, 'textos': textos(p, 'actividad de trabajo')[:2]}
    R.shot(p, f'Paso 3: Seguimiento de Lectura sin actividad: {chk["lectura"]}')
    abrir_rubrica(p); t = main_txt(p)
    chk['rubrica'] = {'selects_habilitados': p.locator('main tbody select:enabled').count(), 'aviso': textos(p, 'actividad de trabajo')[:2],
                      'registrar': [b.is_enabled() for b in p.get_by_role('button', name=re.compile('Registrar evaluaciones')).all()]}
    R.shot(p, f'Paso 4: Rúbrica sin actividad: {chk["rubrica"]}')
    abrir_rv(p)
    chk['rv'] = {'selects_habilitados': p.locator('main tbody select:enabled').count(), 'aviso': textos(p, 'actividad de trabajo')[:2],
                 'registrar': [b.is_enabled() for b in p.get_by_role('button', name=re.compile('Registrar niveles')).all()]}
    R.shot(p, f'Paso 4: Registro de Vuelo sin actividad: {chk["rv"]}')
    ir(p, 'Alumnos'); ag = p.get_by_role('button', name='Agregar')
    chk['alumnos'] = {'agregar_habilitado': ag.first.is_enabled() if ag.count() else None, 'filas': p.locator('main tbody tr').count(),
                      'lapices_habilitados': p.locator('main tbody').get_by_role('button', name=re.compile('^Editar')).evaluate_all('els=>els.filter(e=>!e.disabled).length'),
                      'switches_habilitados': p.locator('main tbody [role=switch]:enabled, main tbody input[type=checkbox]:enabled').count()}
    R.shot(p, f'Paso 5: Alumnos en consulta: {chk["alumnos"]}')
    tk = token_navegador(p)
    s1, r1 = A.api('POST', '/alumnos', tk, {'nombres': 'Sin', 'apellidos': f'Actividad {hhmmss()}', 'id_colegio': X, 'id_grado': A.id_grado(3),
                                             'id_programa': A.CL(), 'pertenece_desde': A.iso(A.hoy())})
    s2, r2 = put_asis(tk, F, [(D.alumno('Ana Norte QA'), 'presente', None)], None)
    chk['api'] = {'alumno': (s1, str(r1)[:200]), 'asistencia': (s2, str(r2)[:200])}
    R.consola(ctx, 'Paso 6: escrituras por la API sin actividad (con el token de la sesión)', [f'POST /api/alumnos → HTTP {s1} {json.dumps(r1, ensure_ascii=False)[:250]}',
                                                                                              f'PUT /api/asistencias → HTTP {s2} {r2}'])
    ir(p, 'Inicio'); iniciar_ui(p)
    ir(p, 'Alumnos'); ag = p.get_by_role('button', name='Agregar'); chk['alumnos_con_act'] = ag.first.is_enabled() if ag.count() else None
    abrir_asis(p, F); chk['asis_con_act'] = controles(p)
    R.shot(p, f'Paso 7: con actividad: "Agregar" habilitado {chk["alumnos_con_act"]}; controles de Asistencias {chk["asis_con_act"]}')
    fin(R, chk, n, C)


# ── CP-INI-05 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-05')
def cp_ini05():
    R = Run('CP-INI-05'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a')
    con_actividad(p, C); chk['texto1'] = texto_act(p); tk = token_navegador(p); act = A.actividad_en_curso(tk)
    abrir_rubrica(p); chk['evaluacion'] = elegir(p, 'Ana Norte QA', 'Fluidez', 'Logrado')[:2]
    R.shot(p, f'Paso 1: actividad en curso ({chk["texto1"]}); evaluación de Ana en Rúbrica: {chk["evaluacion"]}; token copiado')
    ir(p, 'Inicio'); peticiones = []
    p.on('request', lambda rq: peticiones.append(rq.url) if '/finalizar' in rq.url else None)
    b = p.get_by_role('button', name='Finalizar actividad'); b.first.click()
    chk['deshabilitado_procesando'] = (b.first.is_enabled() is False) if b.count() else 'el botón cambió enseguida'
    try:
        b.first.click(timeout=400)
    except Exception:
        pass
    p.wait_for_timeout(2500); chk['peticiones_finalizar'] = len(peticiones)
    chk['tras'] = {'url': p.url.replace(BASE, ''), 'iniciar': boton(p), 'pendientes': pendientes(p)}
    R.shot(p, f'Pasos 2-3: "Finalizar actividad": deshabilitado mientras procesa {chk["deshabilitado_procesando"]}; peticiones {len(peticiones)}; {chk["tras"]}')
    chk['me'] = A.api('GET', '/me', tk)[0]; chk['actividad1'] = act_api(tk, act); chk['rubrica'] = rub_de('Ana Norte QA')
    R.consola(ctx, 'Pasos 4-5: la sesión y la actividad por la API', [f'GET /api/me → HTTP {chk["me"]}', f'Actividad: {chk["actividad1"]}', f'Rúbrica de Ana: {chk["rubrica"]}'])
    iniciar_ui(p); chk['texto2'] = texto_act(p)
    m1, m2 = TXT_ACT.search(chk['texto1'] or ''), TXT_ACT.search(chk['texto2'] or '')
    chk['misma_expiracion'] = (m1.group(3) if m1 else None) == (m2.group(3) if m2 else None)
    R.shot(p, f'Paso 6: segunda actividad: {chk["texto2"]} (misma hora de expiración: {chk["misma_expiracion"]})')
    lista = acts(tk); chk['actividades'] = [(a['id'][:8], a.get('inicio'), a.get('fin'), a.get('tipo_cierre')) for a in lista[:3]]
    chk['activas'] = len(acts(tk, estado='en_curso'))
    R.consola(ctx, 'Paso 7: actividades de Docente A (API)', [str(x) for x in chk['actividades']] + [f'Actividades en curso: {chk["activas"]}',
              'Que las dos estén vinculadas a la misma sesión está en la base de datos.'])
    p2 = ctx.new_page(); p2.add_init_script(f"if(!sessionStorage.getItem('sicedu.token'))sessionStorage.setItem('sicedu.token','{tk}')")
    p2.goto(BASE + '/inicio'); p2.wait_for_timeout(3000)
    b2 = p2.get_by_role('button', name='Iniciar actividad')
    if b2.count():
        b2.first.click(); p2.wait_for_timeout(2000)
    chk['otra_pestana'] = (b2.count(), toasts_txt(p2) + textos(p2, 'Debes finalizar'), len(acts(tk, estado='en_curso')))
    R.shot(p2, f'Paso 8: otra pestaña con la misma sesión, "Iniciar actividad": {chk["otra_pestana"][1]}; actividades en curso {chk["otra_pestana"][2]}')
    fin(R, chk, n, C)


# ── CP-INI-06 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-06', notas='El tipo de cierre "Manual" de la sesión (paso 5) queda como NOTA.')
def cp_ini06():
    R = Run('CP-INI-06'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a')
    con_actividad(p, C); tk = token_navegador(p); act = A.actividad_en_curso(tk)
    abrir_rubrica(p); chk['evaluacion'] = elegir(p, 'Beto Norte QA', 'Comprensión', 'En proceso')[:2]
    R.shot(p, f'Paso 1: actividad en curso; evaluación de Beto: {chk["evaluacion"]}; token copiado')
    p.locator('button[aria-haspopup=menu]').click(); p.wait_for_timeout(300)
    t2 = A.ahora(); p.get_by_role('menuitem', name='Cerrar sesión').click(); p.wait_for_timeout(200)
    chk['indicador'] = p.locator('[aria-busy=true], [role=progressbar], .animate-spin').count()
    R.shot(p, f'Paso 2: inmediatamente después de "Cerrar sesión" ({t2:%H:%M:%S}): indicadores de carga {chk["indicador"]}')
    dl = p.locator('[role=dialog]')
    if dl.count() and '/login' not in p.url:
        chk['dialogo'] = dl.inner_text()[:300]; dl.get_by_role('button').last.click()
    p.wait_for_timeout(2500); chk['url'] = p.url.replace(BASE, '')
    R.shot(p, f'Paso 3: {chk["url"]}')
    chk['me'] = A.api('GET', '/me', tk)[0]; chk['actividad'] = act_api(C, act); chk['rubrica'] = rub_de('Beto Norte QA')
    R.consola(ctx, f'Pasos 4-5: API (cierre a las {t2:%H:%M:%S})', [f'GET /api/me con el token copiado → HTTP {chk["me"]}', f'Actividad: {chk["actividad"]}',
                                                                  f'Rúbrica de Beto: {chk["rubrica"]}'])
    R.nota('Paso 5: el cierre de la sesión con tipo "Manual" está en la base de datos; en QA no hay una consulta para verlo.')
    login(p, C); chk['iniciar'] = boton(p)
    R.shot(p, f'Paso 6: al volver a entrar: "Iniciar actividad" {chk["iniciar"]}')
    fin(R, chk, n, C)


# ── CP-INI-07 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-07')
def cp_ini07():
    R = Run('CP-INI-07'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a')
    S = Semanas(); F = S.F
    con_actividad(p, C); act = A.actividad_en_curso(token_navegador(p))
    tabla_post(token_navegador(p), act, S.ACT, S.mes_act)
    abrir_lec(p, S.ACT, S.mes_act); abrir_rv(p); abrir_asis(p, F)
    abrir_rubrica(p); chk['filtros'] = [x.input_value() for x in p.locator('main select').all()[:6]]
    R.shot(p, f'Paso 1: Rúbrica con sus filtros: {chk["filtros"]} (se abrieron antes Lectura, Registro de Vuelo y Asistencias para tener su copia local)')
    ctx.set_offline(True); p.wait_for_timeout(600)
    reg = {'rubrica': elegir(p, 'Carla Norte QA', 'Fluidez', 'Logrado')[:2]}
    abrir_lec(p, S.ACT, S.mes_act)
    try:
        escribir(p, 'Carla Norte QA', 'lsl', 2); reg['lectura'] = 'escrito'
    except Exception as e:
        reg['lectura'] = 'no se pudo escribir: ' + str(e).split(chr(10))[0][:60]
        R.shot(p, 'Paso 3: Seguimiento de Lectura sin conexión, abierta desde el menú: la fila de Carla no está disponible para escribir', full=True)
    abrir_rv(p); reg['registro_vuelo'] = elegir_rv(p, 'Carla Norte QA', 'Nivel colocado', 'K')
    abrir_asis(p, F); reg['asistencia'] = marcar_asis(p, 'Carla Norte QA', 'Presente', esperar=False)
    chk['registros'] = reg; chk['cola'] = cola_idb(p)
    R.shot(p, f'Paso 3: registros sin conexión: {reg}')
    R.consola(ctx, f'Paso 3: IndexedDB: {len(chk["cola"])} operaciones pendientes', [c[:300] for c in chk['cola']] or ['(vacía)'])
    ir(p, 'Alumnos'); ag = p.get_by_role('button', name='Agregar')
    chk['alumnos'] = {'agregar_habilitado': ag.first.is_enabled() if ag.count() else None, 'filas': p.locator('main tbody tr').count()}
    R.shot(p, f'Paso 4: Alumnos sin conexión: {chk["alumnos"]}')
    ir(p, 'Inicio'); chk['pendientes'] = pendientes(p)
    R.shot(p, f'Paso 5: Inicio: "Tienes {chk["pendientes"]} registros offline pendientes de sincronizar." (se esperan 4)')
    ir(p, 'Rúbrica'); p.wait_for_timeout(1500); chk['filtros_vuelta'] = [x.input_value() for x in p.locator('main select').all()[:6]]
    R.shot(p, f'Paso 6: Rúbrica otra vez: filtros {chk["filtros_vuelta"]} (iguales: {chk["filtros_vuelta"] == chk["filtros"]})')
    ls = json.loads(p.evaluate('JSON.stringify(localStorage)')); chk['local_storage'] = list(ls.keys())
    R.consola(ctx, 'Paso 7: Local Storage', [f'{k}: {str(v)[:150]}' for k, v in ls.items()] or ['(vacío)'])
    ctx.set_offline(False); p.wait_for_timeout(60000); ir(p, 'Inicio')
    chk['tras'] = {'pendientes_inicio': pendientes(p), 'cola': len(cola_idb(p)), 'rubrica': rub_de('Carla Norte QA'), 'lectura': filas_api(S.ACT, S.mes_act, ['Carla']),
                   'asistencia': de_alumno(F, 'Carla Norte QA')}
    R.shot(p, f'Paso 8: 60 s después de reconectar: Inicio muestra {chk["tras"]["pendientes_inicio"]} pendientes; cola {chk["tras"]["cola"]}')
    R.consola(ctx, 'Paso 8: los 4 registros por la API', [f'Rúbrica de Carla: {chk["tras"]["rubrica"]}', f'Lectura de Carla: {chk["tras"]["lectura"]}',
                                                        f'Asistencia de Carla: {chk["tras"]["asistencia"]}', 'Registro de Vuelo: ver la pantalla (se verifica en CP-RV).'])
    fin(R, chk, n, C)


# ── CP-INI-09 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-09', notas='Usa a Docente B, reasignado durante el caso a un colegio en receso con "Próximo".')
def cp_ini09():
    R = Run('CP-INI-09'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; B = D.cuenta('docente-b'); uid = D.id_usuario('docente-b'); X = D.X()
    A.cerrar_abiertas(B); cid = colegio_pr(R, ctx, 'Receso INI09')
    chk['asignacion'] = asignar_bloques(uid, [(cid, [3], 'proximo')])[0]
    pa = FE.pa_anterior(X)['id_periodo_academico']; t = A.ahora()
    pr = perm(uid, X, 4, pa, 'asistencias', t + dt.timedelta(days=5), inicio=t + dt.timedelta(days=2))
    ve = perm(uid, X, 4, pa, 'rubrica', t + dt.timedelta(minutes=2))
    rv = perm(uid, X, 4, pa, 'registro_vuelo', t + dt.timedelta(days=3))
    rev = A.api('POST', f'/usuarios/{uid}/permisos/{pid_de(rv[1])}/revocar', A.sup(), {'motivo': 'Prueba QA'})[0]
    R.consola(ctx, 'Precondición: Docente B solo con "Próximo" en el colegio en receso y tres permisos que no habilitan',
              [f'Asignación → HTTP {chk["asignacion"]}', f'Programado: HTTP {pr[0]} · por vencer en 2 minutos: HTTP {ve[0]} · revocado: HTTP {rv[0]} → {rev}',
               'Se espera a que el permiso de 2 minutos venza.'])
    time.sleep(150)
    login(p, B); p.wait_for_timeout(2500); t_ = p.locator('body').inner_text()
    chk['boton'] = boton(p); chk['mensaje'] = MSG_SIN in t_; chk['apartado'] = 'Permisos de corrección vigentes' in t_
    R.shot(p, f'Pasos 1-3: "Iniciar actividad" {chk["boton"]}; mensaje de CU010 {chk["mensaje"]}; apartado de permisos {chk["apartado"]}')
    tk = token_navegador(p); s, r = A.api('POST', '/actividades', tk, {'id_actividad': A.uid()}); chk['api'] = (s, str(r)[:250])
    R.consola(ctx, 'Paso 4: inicio de actividad por la API', [f'POST /api/actividades → HTTP {s} {json.dumps(r, ensure_ascii=False)[:300]}'])
    mods = {}
    for nm in ['Asistencias', 'Rúbrica', 'Seguimiento de Lectura', 'Registro de Vuelo']:
        ir(p, nm); mods[nm] = {'selects_habilitados': p.locator('main tbody select:enabled').count(), 'avisos': textos(p, 'actividad', 'No puedes', 'asignaciones')[:2]}
    chk['modulos'] = mods
    R.shot(p, f'Paso 5: módulos de registro: {json.dumps(mods, ensure_ascii=False)[:500]}')
    s, r = A.api('GET', '/alumnos', tk); items = (r.get('items') if isinstance(r, dict) else r) or []
    ajenos = [a for a in items if a.get('id_colegio') != cid]
    chk['alumnos'] = (s, len(items), len(ajenos))
    R.consola(ctx, 'Paso 6: GET /api/alumnos con el token', [f'HTTP {s}: {len(items)} alumnos; de otros colegios: {len(ajenos)}'])
    fin(R, chk, n, B)


# ── CP-INI-10 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-10', modo='parcial', notas='Los indicadores son globales: se verifican las diferencias que produce cada acción.')
def cp_ini10():
    R = Run('CP-INI-10'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; S = sup_ui(); C = D.cuenta('docente-a')
    A.cerrar_abiertas(C)
    r0 = sup_res(); chk['inicial'] = r0
    R.consola(ctx, 'Paso 1: indicadores actuales (GET /api/inicio/supervisor)', [json.dumps(r0, ensure_ascii=False)])
    login(p, S); chk['pantalla'] = main_txt(p)[:900]
    R.shot(p, 'Pasos 2-3: Inicio de la Supervisora', full=True)
    # Colegio inactivo: el colegio Sur del caso deja de contar
    s = A.api('PATCH', f'/colegios/{D.Y()}/desactivar', A.sup())[0]; r1 = sup_res()
    chk['colegio_inactivo'] = {'HTTP': s, 'colegios': delta(r0, r1, 'colegios_registrados'), 'docentes_activos': delta(r0, r1, 'docentes_activos')}
    A.api('PATCH', f'/colegios/{D.Y()}/activar', A.sup())
    # Docente inactivo con asignaciones
    ub = D.id_usuario('docente-b'); r2a = sup_res(); A.api('PATCH', f'/usuarios/{ub}/desactivar', A.sup(), {}); r2 = sup_res()
    chk['docente_inactivo'] = delta(r2a, r2, 'docentes_activos')
    A.api('PATCH', f'/usuarios/{ub}/activar', A.sup(), {})
    R.consola(ctx, 'Paso 3: diferencias al inactivar', [f'Colegio Sur del caso inactivo → colegios {chk["colegio_inactivo"]["colegios"]} (se espera -1), '
                                                      f'Docentes activos {chk["colegio_inactivo"]["docentes_activos"]}',
                                                      f'Docente B inactivo → Docentes activos {chk["docente_inactivo"]} (se espera -1)'])
    c2 = n.ctx(); p2 = c2.new_page(); login(p2, C); a0 = sup_res(); iniciar_ui(p2); a1 = sup_res()
    p.reload(); p.wait_for_timeout(2500); R.shot(p, f'Pasos 5-6: con Docente A en actividad: "Docentes con actividad activa" {delta(a0, a1, "docentes_con_actividad_activa")} (se espera +1)')
    finalizar_ui(p2); a2 = sup_res(); p.reload(); p.wait_for_timeout(2500)
    chk['actividad'] = (delta(a0, a1, 'docentes_con_actividad_activa'), delta(a1, a2, 'docentes_con_actividad_activa'))
    R.shot(p, f'Paso 7: tras finalizar: diferencia {chk["actividad"][1]} (se espera -1)')
    ls = p.evaluate('JSON.stringify(localStorage)'); chk['local_storage'] = {'claves': list(json.loads(ls).keys()), 'token': 'eyJ' in ls, 'clave': 'password' in ls.lower()}
    R.consola(ctx, 'Paso 8: Local Storage', [ls[:900]])
    # Paso 9: un Docente con solo un permiso vigente en un colegio en PR cuenta como activo
    cid = colegio_pr(R, ctx, 'Receso INI10'); asignar_bloques(ub, [(cid, [4], 'proximo')]); b0 = sup_res()
    pa1 = FE.pa(1, cid)['id_periodo_academico']
    s9, r9 = perm(ub, cid, 3, pa1, 'asistencias', A.ahora() + dt.timedelta(days=2)); b1 = sup_res()
    A.api('POST', f'/usuarios/{ub}/permisos/{pid_de(r9)}/revocar', A.sup(), {'motivo': 'Prueba QA'}); b2 = sup_res()
    chk['permiso_pr'] = {'otorgar': (s9, delta(b0, b1, 'docentes_activos')), 'revocar': delta(b1, b2, 'docentes_activos')}
    R.consola(ctx, 'Paso 9: Docente B con un permiso vigente en un colegio en receso', [
        'Docente B queda asignado con "Próximo" al colegio en receso; por CU011 ya cuenta como activo, así que el permiso no debería cambiar el total.',
        f'Otorgar el permiso (HTTP {s9}) → Docentes activos {chk["permiso_pr"]["otorgar"][1]}; revocarlo → {chk["permiso_pr"]["revocar"]}'])
    R.nota('Pasos 1 y 4: el conteo completo de referencia y los registros que solo están en IndexedDB de otro dispositivo necesitan la base de datos; '
           'se verifican las diferencias de cada acción.')
    fin(R, chk, n, C)


# ── CP-INI-11 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-11', modo='parcial', notas='Las tarjetas son globales: se verifican las diferencias que produce cada acción.')
def cp_ini11():
    R = Run('CP-INI-11'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; Dr = D.cuenta('directivo'); C = D.cuenta('docente-a')
    r0 = dir_res(); chk['inicial'] = r0
    sin_doc = crear_colegio(f'QA AUTO {hhmmss()} Sin Docente', {3: min(A.hoy().isoweekday(), 5)}); r1 = dir_res()
    A.crear_alumno('Alumno', 'Sin Docente QA', sin_doc, 3, A.CL(), A.iso(A.hoy())); r1b = dir_res()
    ny = len(A.alumnos(D.Y())); A.api('PATCH', f'/colegios/{D.Y()}/desactivar', A.sup()); r2 = dir_res()
    chk['deltas'] = {'colegio_sin_docente': delta(r0, r1, 'colegios_operando'), 'alumno_sin_docente': delta(r1, r1b, 'beneficiarios_activos'),
                     'colegio_inactivo': {'beneficiarios': delta(r1b, r2, 'beneficiarios_activos'), 'alumnos_del_colegio': ny, 'operando': delta(r1b, r2, 'colegios_operando')}}
    R.consola(ctx, 'Paso 1: diferencias en las tarjetas (GET /api/inicio/directivo)', [f'Inicial: {r0}',
              f'Colegio activo nuevo sin Docente → Operando {chk["deltas"]["colegio_sin_docente"]} (se espera 0)',
              f'Un alumno activo en ese colegio → Beneficiarios {chk["deltas"]["alumno_sin_docente"]} (se espera +1)',
              f'Colegio Sur del caso inactivo ({ny} alumnos activos, Docentes asignados) → Beneficiarios {chk["deltas"]["colegio_inactivo"]["beneficiarios"]} (se espera -{ny}); '
              f'Operando {chk["deltas"]["colegio_inactivo"]["operando"]} (se espera -1)'])
    login(p, Dr); p.wait_for_timeout(2500); t = main_txt(p)
    chk['tarjetas'] = [x for x in ['Total de Beneficiarios Activos', 'Total de Colegios Operando', 'Salud del Sistema'] if x.lower() in t.lower()]
    chk['graficos'] = p.locator('main svg, main canvas').count(); chk['texto'] = t[:500]
    R.shot(p, f'Pasos 2-3: tarjetas {chk["tarjetas"]}; gráficos {chk["graficos"]}', full=True)
    # Paso 5: tres avisos del mismo registro cuentan como un pendiente
    RV = D.cuenta('rv-uno'); A.cerrar_abiertas(RV); act = A.iniciar_actividad(RV); X = D.X(); F = FE.ultima_clase(1)
    h0 = dir_res(); reg = {'id_colegio': X, 'id_grado': A.id_grado(1), 'id_seccion': A.seccion(X, 1), 'fecha': A.iso(F), 'id_alumno': D.alumno('Grado1P1 Entrada QA')}
    for _ in range(3):
        A.api('POST', '/sincronizacion/pendientes', RV, [{'id_operacion': A.uid(), 'id_dispositivo': 'tablet-qa', 'id_actividad': act, 'modulo': 'asistencias',
                                                          'realizado_en': A.ahora().replace(microsecond=0).isoformat(), 'registro': reg}])
    h1 = dir_res()
    s, r = put_asis(RV, F, [(reg['id_alumno'], 'presente', None)], act, grado=1); h2 = dir_res(); A.finalizar_actividad(RV, act)
    chk['salud'] = {'antes': h0.get('salud_sistema'), 'tres_avisos': h1.get('salud_sistema'), 'tras_sincronizar': h2.get('salud_sistema'), 'asistencia': s}
    R.consola(ctx, 'Paso 5: Salud del Sistema con tres avisos de pendiente del mismo registro', [json.dumps(chk['salud'], ensure_ascii=False),
              'La salud es global: con muchos registros, un pendiente puede no mover el entero redondeado.'])
    # Paso 6: el Docente inactiva a un alumno
    A.cerrar_abiertas(C); act = A.iniciar_actividad(C); aid = D.alumno('Elsa Norte QA'); b0 = dir_res()
    s6 = A.api('PATCH', f'/alumnos/{aid}/desactivar', C, {'aplicar_desde': A.iso(A.hoy())})[0]; b1 = dir_res(); A.finalizar_actividad(C, act)
    p.reload(); p.wait_for_timeout(2500); chk['inactivar'] = (s6, delta(b0, b1, 'beneficiarios_activos'))
    R.shot(p, f'Paso 6: Docente A inactiva a Elsa (HTTP {s6}): Beneficiarios {chk["inactivar"][1]} (se espera -1)')
    nombres = list(D.estado()['alumnos']); body = p.locator('body').inner_text(); ls = p.evaluate('JSON.stringify(localStorage)')
    chk['privacidad'] = {'nombres': [x for x in nombres if x in body], 'botones_main': p.locator('main').get_by_role('button').count(),
                         'iniciar': p.get_by_role('button', name='Iniciar actividad').count(), 'token_en_ls': 'eyJ' in ls,
                         'nombres_en_ls': [x for x in nombres if x.split(' ')[0] in ls]}
    R.consola(ctx, 'Paso 7: nombres, botones y Local Storage', [json.dumps(chk['privacidad'], ensure_ascii=False), ls[:600]])
    R.nota('Paso 1: los conteos completos de referencia necesitan la base de datos; se verifican las diferencias de cada acción.')
    fin(R, chk, n, C)


# ── CP-INI-12 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-12', notas='El backend "detenido" se simula cortando las llamadas a /api desde el navegador.')
def cp_ini12():
    R = Run('CP-INI-12'); n = Nav(); chk = {}
    casos_ = [('Supervisora', sup_ui(), 'No existe información operativa disponible sin conexión.',
               'No hay conexión con el servidor ni un resumen local guardado. Intente más tarde.'),
              ('Directivo', D.cuenta('directivo'), 'No existe información institucional disponible sin conexión.',
               'No se pudieron cargar los indicadores y no hay datos locales. Intente más tarde.')]
    borrar = "Object.keys(localStorage).filter(k=>/resumen|inicio|indicador/i.test(k)).forEach(k=>localStorage.removeItem(k))"
    for rol, cuenta, sin_txt, err_txt in casos_:
        ctx = n.ctx(); p = ctx.new_page(); c = {}
        login(p, cuenta); p.wait_for_timeout(2500); c['ls'] = list(json.loads(p.evaluate('JSON.stringify(localStorage)')).keys())
        R.shot(p, f'Paso 1 ({rol}): Inicio con conexión; Local Storage {c["ls"]}')
        ctx.set_offline(True)
        try:
            p.reload(); p.wait_for_timeout(3000); c['recarga'] = p.locator('body').inner_text()[:300]
        except Exception as e:
            c['recarga'] = 'error del navegador: ' + str(e).split('\n')[0][:80]
        c['desactualizado'] = cuerpo_lineas(p, 'desactualiz', 'sin conexión', 'No se pudo contactar')[:3]
        R.shot(p, f'Paso 2 ({rol}): recarga sin conexión: {c["desactualizado"] or c["recarga"][:150]}')
        try:
            p.evaluate(borrar); p.reload(); p.wait_for_timeout(3000)
            c['sin_resumen'] = (sin_txt in p.locator('body').inner_text(), p.url.replace(BASE, ''))
        except Exception as e:
            c['sin_resumen'] = ('error', str(e)[:80])
        R.shot(p, f'Paso 3 ({rol}): sin resumen y sin conexión: mensaje de CU {c["sin_resumen"]}')
        ctx.set_offline(False); p.wait_for_timeout(1000)
        p.goto(BASE + '/inicio'); p.wait_for_timeout(2500)
        if '/login' in p.url:
            login(p, cuenta)
        ir(p, 'Inicio'); p.wait_for_timeout(1500)
        backend_caido(ctx, True)
        menu = [t.strip() for t in p.locator('aside nav a').all_inner_texts()]
        otro = next((m for m in menu if m != 'Inicio'), None)
        if otro:
            ir(p, otro)
        ir(p, 'Inicio'); p.wait_for_timeout(2500); c['caido'] = cuerpo_lineas(p, 'desactualiz', 'conexión', 'Intente')[:3]
        R.shot(p, f'Paso 4 ({rol}): backend sin responder, con resumen guardado: {c["caido"]}')
        p.evaluate(borrar)
        if otro:
            ir(p, otro)
        ir(p, 'Inicio'); p.wait_for_timeout(2500)
        c['caido_sin'] = (err_txt in p.locator('body').inner_text(), cuerpo_lineas(p, 'Intente', 'conexión')[:3])
        R.shot(p, f'Paso 5 ({rol}): backend sin responder y sin resumen: mensaje de CU {c["caido_sin"][0]}')
        backend_caido(ctx, False)
        if otro:
            ir(p, otro)
        ir(p, 'Inicio'); p.wait_for_timeout(2500); c['restaurado'] = cuerpo_lineas(p, 'Docentes', 'Colegios', 'Beneficiarios')
        R.shot(p, f'Paso 6 ({rol}): backend respondiendo otra vez: los datos se actualizan')
        chk[rol] = c; ctx.close()
    ctx = n.ctx(); p = ctx.new_page(); p.goto(BASE + '/login'); p.wait_for_timeout(1500)
    p.evaluate('localStorage.clear(); sessionStorage.clear()'); ctx.clear_cookies(); ctx.set_offline(True)
    try:
        p.reload(); p.wait_for_timeout(2500); chk['sin_datos'] = p.locator('body').inner_text()[:200]
        R.shot(p, f'Paso 7: datos del sitio borrados y sin conexión: {chk["sin_datos"][:120]}')
    except Exception as e:
        chk['sin_datos'] = str(e).split('\n')[0][:100]
        R.consola(ctx, 'Paso 7: datos del sitio borrados y sin conexión', [chk['sin_datos'], 'La aplicación no carga.'])
    R.nota('Paso 7: Playwright borra Local Storage, Session Storage y cookies; la caché del Service Worker se borra al cerrar el contexto del navegador.')
    fin(R, chk, n)


# ── CP-INI-14 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-14', notas='La espera sin conexión del paso 4 se acorta a 2 minutos.')
def cp_ini14():
    R = Run('CP-INI-14'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a')
    con_actividad(p, C); tk = token_navegador(p); act = A.actividad_en_curso(tk)
    ctx.set_offline(True); p.wait_for_timeout(600); R.shot(p, 'Paso 1: actividad en curso; "Offline" activado')
    t2 = A.ahora(); finalizar_ui(p)
    chk['tras'] = {'iniciar': boton(p), 'url': p.url.replace(BASE, ''), 'token': bool(token_navegador(p))}
    R.shot(p, f'Pasos 2-3: "Finalizar actividad" sin conexión a las {t2:%H:%M:%S}: {chk["tras"]}')
    time.sleep(120); ctx.set_offline(False); p.wait_for_timeout(60000)
    chk['api'] = act_api(C, act)
    R.consola(ctx, f'Paso 5: la actividad según la API (fin esperado {t2:%H:%M:%S})', [json.dumps(chk['api'], ensure_ascii=False)])
    fin(R, chk, n, C)


# ── CP-INI-15 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-15')
def cp_ini15():
    from casos.aut import jwt
    R = Run('CP-INI-15'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a'); peticiones = red(p)
    A.cerrar_abiertas(C); login(p, C); exp = dt.datetime.fromtimestamp(jwt(token_navegador(p))['exp'], A.LIMA)
    abrir_rubrica(p); ir(p, 'Inicio')
    R.shot(p, f'Paso 1: sesión con conexión; expira a las {exp:%H:%M}')
    ctx.set_offline(True); t2 = A.ahora(); iniciar_ui(p)
    chk['texto'] = texto_act(p); chk['boton'] = boton(p, 'Finalizar actividad')
    R.shot(p, f'Paso 2: sin conexión, "Iniciar actividad" a las {t2:%H:%M:%S}: {chk["texto"]}; {chk["boton"]}')
    chk['cola'] = cola_idb(p); R.consola(ctx, 'Paso 3: IndexedDB', [c[:300] for c in chk['cola']] or ['(vacía)'])
    abrir_rubrica(p); chk['evaluacion'] = elegir(p, 'Dante Norte QA', 'Fluidez', 'Logrado')[:2]; chk['cola2'] = len(cola_idb(p))
    R.shot(p, f'Paso 4: evaluación de Dante sin conexión: {chk["evaluacion"]}; operaciones en la cola {chk["cola2"]}')
    ctx.set_offline(False); p.wait_for_timeout(60000)
    lista = [a for a in acts(C) if a.get('inicio', '') >= (t2 - dt.timedelta(minutes=2)).isoformat()[:16]]
    chk['actividades'] = [{k: a.get(k) for k in ('id', 'inicio', 'fin', 'tipo_cierre', 'creada_sin_conexion', 'sincronizacion')} for a in lista]
    chk['rubrica'] = rub_de('Dante Norte QA')
    R.consola(ctx, f'Paso 5: tras reconectar (inicio esperado {t2:%H:%M:%S})', [json.dumps(x, ensure_ascii=False) for x in chk['actividades']] +
              [f'Rúbrica de Dante: {chk["rubrica"]}', 'Peticiones de escritura:'] + peticiones)
    ir(p, 'Inicio')
    if p.get_by_role('button', name='Finalizar actividad').count():
        finalizar_ui(p)
    borrado = p.evaluate("""(async()=>{let n=0;for(const d of await indexedDB.databases()){const db=await new Promise(r=>{const o=indexedDB.open(d.name);o.onsuccess=()=>r(o.result)});
      for(const s of db.objectStoreNames){const tx=db.transaction(s,'readwrite');const st=tx.objectStore(s);
        const ks=await new Promise(r=>{const q=st.getAllKeys();q.onsuccess=()=>r(q.result)});
        for(const k of ks){if(/calendar/i.test(String(k))){st.delete(k);n++}else{const v=await new Promise(r=>{const q=st.get(k);q.onsuccess=()=>r(q.result)});
          if(v&&typeof v==='object'&&v.datos&&('calendarios' in v.datos||'calendario' in v.datos)){delete v.datos.calendarios;delete v.datos.calendario;st.put(v,k);n++}}}}}return n})()""")
    ctx.set_offline(True); iniciar_ui(p)
    chk['sin_calendario'] = {'borrados': borrado, 'avisos': toasts_txt(p) + textos(p, 'No se puede verificar'), 'texto': texto_act(p)}
    R.shot(p, f'Pasos 6-7: calendario borrado de IndexedDB ({borrado} entradas) y sin conexión: {chk["sin_calendario"]}')
    ctx.set_offline(False); p.wait_for_timeout(10000)
    fin(R, chk, n, C)


# ── CP-INI-16 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-16')
def cp_ini16():
    R = Run('CP-INI-16'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a'); F = FE.ultima_clase(3)
    peticiones = red(p)
    con_actividad(p, C); act1 = A.actividad_en_curso(token_navegador(p)); abrir_asis(p, F); abrir_rubrica(p)
    ctx.set_offline(True); p.wait_for_timeout(500)
    reg = {'rubrica': elegir(p, 'Elsa Norte QA', 'Fluidez', 'En proceso')[:2]}
    abrir_asis(p, F); reg['asistencia'] = marcar_asis(p, 'Elsa Norte QA', 'Tardanza', esperar=False)
    R.shot(p, f'Paso 1: sin conexión: evaluación y asistencia de Elsa {reg}')
    ir(p, 'Inicio'); t1 = A.ahora(); finalizar_ui(p); chk['tras_fin'] = boton(p)
    R.shot(p, f'Paso 2: "Finalizar actividad" sin conexión a las {t1:%H:%M:%S} (T1): {chk["tras_fin"]}')
    t2 = A.ahora(); iniciar_ui(p); chk['texto2'] = texto_act(p)
    abrir_rubrica(p); reg['rubrica2'] = elegir(p, 'Elsa Norte QA', 'Comprensión', 'Logrado')[:2]
    R.shot(p, f'Paso 3: "Iniciar actividad" sin conexión a las {t2:%H:%M:%S} (T2) y otra evaluación: {chk["texto2"]}')
    chk['registros'] = reg; del peticiones[:]
    ctx.set_offline(False); p.wait_for_timeout(45000); chk['orden'] = list(peticiones)
    R.consola(ctx, 'Paso 4: orden de las peticiones al reconectar', peticiones or ['(ninguna)'])
    lista = acts(C)[:3]; chk['actividades'] = [{k: a.get(k) for k in ('id', 'inicio', 'fin', 'tipo_cierre')} for a in lista]
    chk['datos'] = {'rubrica': rub_de('Elsa Norte QA'), 'asistencia': de_alumno(F, 'Elsa Norte QA'), 'actividad1': act_api(C, act1)}
    R.consola(ctx, f'Paso 5: actividades y registros (T1 = {t1:%H:%M:%S}, T2 = {t2:%H:%M:%S})', [json.dumps(x, ensure_ascii=False) for x in chk['actividades']] +
              [f'Rúbrica de Elsa: {chk["datos"]["rubrica"]}', f'Asistencia de Elsa: {chk["datos"]["asistencia"]}',
               f'Actividades en curso: {len(acts(C, estado="en_curso"))}'])
    # Variante
    ir(p, 'Inicio'); ctx.set_offline(True); p.wait_for_timeout(400); finalizar_ui(p); iniciar_ui(p)
    abrir_rubrica(p); elegir(p, 'Ana Norte QA', 'Comprensión', 'Logrado'); ir(p, 'Inicio')
    try:
        logout(p)
    except Exception as e:
        chk['logout_offline'] = str(e)[:80]
    del peticiones[:]; ctx.set_offline(False); p.wait_for_timeout(1000); login(p, C); p.wait_for_timeout(15000)
    chk['orden_variante'] = list(peticiones)
    R.consola(ctx, 'Paso 6: variante con cierre de sesión sin conexión: peticiones al volver a entrar', peticiones or ['(ninguna)'])
    fin(R, chk, n, C)


# ── CP-INI-19 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-19', notas='Usa a Docente B (un solo colegio) y el reloj del navegador para el paso 5.')
def cp_ini19():
    R = Run('CP-INI-19'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; B = D.cuenta('docente-b'); uid = D.id_usuario('docente-b'); X = D.X()
    A.cerrar_abiertas(B)
    # Registro pendiente: un aviso de pendiente informado por el dispositivo, antes de cambiar el calendario
    act = A.iniciar_actividad(B); F = FE.ultima_clase(4)
    A.api('POST', '/sincronizacion/pendientes', B, [{'id_operacion': A.uid(), 'id_dispositivo': 'tablet-qa', 'id_actividad': act, 'modulo': 'asistencias',
                                                     'realizado_en': A.ahora().replace(microsecond=0).isoformat(),
                                                     'registro': {'id_colegio': X, 'id_grado': A.id_grado(4), 'id_seccion': A.seccion(X, 4), 'fecha': A.iso(F),
                                                                  'id_alumno': (A.alumnos(X, 4) or [{}])[0].get('id')}}])
    A.finalizar_actividad(B, act)
    hoy = A.hoy(); gen = {(q['tipo'], q['numero']): q for q in A.calendario(X)['periodos']}
    pa4_ini = max(hoy + dt.timedelta(days=3), A.fecha(gen[('PA', 3)]['fecha_fin']) + dt.timedelta(days=3))
    pr3_fin = hoy - dt.timedelta(days=2)
    per = []
    for (t, k), q_ in sorted(gen.items(), key=lambda x: x[1]['fecha_inicio']):
        a, b = A.fecha(q_['fecha_inicio']), A.fecha(q_['fecha_fin'])
        if (t, k) == ('PA', 3):
            b = min(b, pr3_fin - dt.timedelta(days=2))
        if (t, k) == ('PR', 3):
            a, b = pr3_fin - dt.timedelta(days=1), pr3_fin
        if (t, k) == ('PA', 4):
            a = pa4_ini
        per.append({'tipo': t, 'numero': k, 'fecha_inicio': a.isoformat(), 'fecha_fin': b.isoformat()})
    s, r = A.api('POST', '/calendarios/particulares', A.sup(), {'id_colegio': X, 'id_anio_escolar': A.anio(), 'periodos': per, 'dias_no_lectivos': []})
    chk['config'] = (s, str(r)[:200] if s >= 300 else 'ok')
    R.consola(ctx, 'Paso 1: fechas particulares del colegio Norte con hoy fuera de PA y PR', [f'POST /api/calendarios/particulares → HTTP {s} {chk["config"][1]}',
              f'PR3 termina el {FE.legible(pr3_fin)} y PA4 empieza el {FE.legible(pa4_ini)}', f'Periodo de hoy: {A.periodo_actual(X)}'])
    if s >= 300:
        fin(R, chk, n, B); return
    calid = r.get('id_calendario') or r.get('id')
    p.clock.install(); login(p, B); p.wait_for_timeout(2500)
    chk['boton'] = boton(p); chk['mensaje'] = MSG_SIN in p.locator('body').inner_text()
    R.shot(p, f'Pasos 2-3: "Iniciar actividad" {chk["boton"]}; mensaje de CU010 {chk["mensaje"]}')
    s2, r2 = A.api('POST', '/actividades', token_navegador(p), {'id_actividad': A.uid()}); chk['api'] = (s2, str(r2)[:250])
    R.consola(ctx, 'Paso 4: inicio de actividad por la API', [f'POST /api/actividades → HTTP {s2} {json.dumps(r2, ensure_ascii=False)[:300]}'])
    dentro = dt.datetime.combine(pa4_ini + dt.timedelta(days=1), dt.time(10, 0))
    p.clock.set_system_time(dentro); p.reload(); p.wait_for_timeout(3000)
    chk['reloj'] = (p.url.replace(BASE, ''), boton(p))
    R.shot(p, f'Paso 5: reloj del equipo en el {dentro:%d/%m} (dentro de PA4) y recarga: {chk["reloj"]}')
    chk['pendiente'] = textos(p, 'pendiente', 'sincroniz')[:3]
    R.consola(ctx, 'Paso 6: registro pendiente', [f'Textos en Inicio: {chk["pendiente"]}',
                                                 'El pendiente se informó por la API; que se sincronice se verifica en Seguimiento (columna "Sincronización").'])
    s3, _ = A.api('POST', f'/calendarios/{calid}/usar-general', A.sup(), {})
    p.clock.set_system_time(dt.datetime.now()); p.reload(); p.wait_for_timeout(3000)
    if '/login' in p.url:
        login(p, B)
    chk['general'] = (s3, boton(p))
    R.shot(p, f'Paso 7: "Usar calendario general" (HTTP {s3}) y reloj restaurado: {chk["general"][1]}')
    fin(R, chk, n, B)


# ── CP-INI-21 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-21', modo='parcial', notas='El receso se hace con fechas particulares de los colegios del caso; el cierre del año (pasos 4-5) no se prueba.')
def cp_ini21():
    R = Run('CP-INI-21'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    r0 = dir_res()
    ca = colegio_pr(R, ctx, 'Operando A', alumnos=False); cb = colegio_pr(R, ctx, 'Operando B', alumnos=False); cc = colegio_pr(R, ctx, 'Operando C', alumnos=False)
    r1 = dir_res()
    ua, ub = D.id_usuario('sin-grupos'), D.id_usuario('docente-b')
    sa = asignar_bloques(ua, [(ca, [3], 'proximo')])[0]; r2 = dir_res()
    sb = asignar_bloques(ub, [(cb, [3], 'retroactivo')])[0]; r3 = dir_res()
    chk['deltas'] = {'tres_colegios_sin_docente': delta(r0, r1, 'colegios_operando'), 'A_proximo': (sa, delta(r1, r2, 'colegios_operando')),
                     'B_retroactivo': (sb, delta(r2, r3, 'colegios_operando'))}
    sb2 = asignar_bloques(ub, [(cb, [3, 4], 'retroactivo')])[0]; r4 = dir_res()
    chk['deltas']['B_dos_grados'] = (sb2, delta(r3, r4, 'colegios_operando'))
    R.consola(ctx, 'Pasos 1-3: Total de Colegios Operando (GET /api/inicio/directivo) con los tres colegios en el receso posterior a PA2', [
        f'Inicial: {r0}', f'Colegios A, B y C sin Docente → {chk["deltas"]["tres_colegios_sin_docente"]} (se espera 0)',
        f'A con un Docente "Próximo" (HTTP {sa}) → {chk["deltas"]["A_proximo"][1]} (se espera +1)',
        f'B con un Docente "Retroactivo" (HTTP {sb}) → {chk["deltas"]["B_retroactivo"][1]} (se espera +1)',
        f'B con un segundo grado del mismo Docente (HTTP {sb2}) → {chk["deltas"]["B_dos_grados"][1]} (se espera 0: B cuenta una sola vez)'])
    login(p, D.cuenta('directivo')); p.wait_for_timeout(2500)
    R.shot(p, f'Paso 3: Inicio del Directivo: {dir_res()}', full=True)
    R.nota('Pasos 4-6: el cierre del año (todos los periodos terminados) necesita mover el calendario general o la fecha del servidor; no se prueba en QA.')
    fin(R, chk, n)


# ── CP-INI-23 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-23', modo='parcial', notas='El receso se hace con fechas particulares; los pasos 7-8 (mover la fecha del servidor) no se prueban.')
def cp_ini23():
    from casos.usr import cerrar_receso
    R = Run('CP-INI-23'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}
    Rr, Pp = D.cuenta('retro'), D.cuenta('sin-grupos'); ur, up = D.id_usuario('retro'), D.id_usuario('sin-grupos')
    for c in (Rr, Pp):
        A.cerrar_abiertas(c)
    cid = colegio_pr(R, ctx, 'Receso INI23', grados=(3,))
    s0 = sup_res()
    chk['asignaciones'] = (asignar_bloques(ur, [(cid, [3], 'retroactivo')])[0], asignar_bloques(up, [(cid, [3], 'proximo')])[0])
    s1 = sup_res()
    login(p, Rr); chk['R_inicio'] = {'boton': boton(p), 'colegio': A.colegio(cid)['nombre'] in main_txt(p)}
    R.shot(p, f'Pasos 1-2: Docente R (Retroactivo): {chk["R_inicio"]}')
    iniciar_ui(p); tk = token_navegador(p); act = A.actividad_en_curso(tk)
    f_pa2 = FE.clases_del_pa(3, 2, cid); f_pa2 = f_pa2[-1] if f_pa2 else None
    al = A.alumnos(cid, 3)[0]['id']
    chk['asistencia_pa2'] = put_asis(tk, f_pa2, [(al, 'presente', None)], act, colegio=cid) if f_pa2 else 'sin clases en PA2'
    R.consola(ctx, 'Paso 3: registros del Docente R en el receso (por la API, con el token de la sesión)', [
        f'Asistencia del {FE.legible(f_pa2)} (PA2) → {chk["asistencia_pa2"]}',
        f'Clase guardada: {[(c["fecha"], c.get("id_periodo_academico")) for c in A.clases(cid, 3, f_pa2, f_pa2)] if f_pa2 else None}; '
        f'PA2 = {FE.pa(2, cid)["id_periodo_academico"]}'])
    abrir_asis(p, A.hoy(), colegio=A.colegio(cid)['nombre']); chk['receso'] = RECESO in main_txt(p)
    R.shot(p, f'Paso 4: Asistencias con una fecha del receso: mensaje de CU {chk["receso"]}')
    A.finalizar_actividad(tk, act); logout(p)
    login(p, Pp); chk['P'] = {'boton': boton(p), 'mensaje': MSG_SIN in p.locator('body').inner_text()}
    R.shot(p, f'Paso 5: Docente P (Próximo): {chk["P"]}')
    chk['docentes_activos'] = delta(s0, s1, 'docentes_activos')
    R.consola(ctx, 'Paso 6: "Docentes activos" de la Supervisora', [f'Al asignar R (Retroactivo) y P (Próximo) en el colegio en receso: {chk["docentes_activos"]} '
                                                                  '(los dos ya tenían asignación habilitada en el colegio Sur; se espera 0, cada Docente cuenta una vez)'])
    s2, _ = cerrar_receso(cid); A.cerrar_abiertas(Rr); act2 = A.iniciar_actividad(Rr)
    f2 = FE.clases_del_pa(3, 2, cid)
    chk['tras_receso'] = (s2, put_asis(Rr, f2[-2] if len(f2) > 1 else f2[-1], [(al, 'tardanza', None)], act2, colegio=cid) if f2 else None)
    A.finalizar_actividad(Rr, act2)
    R.consola(ctx, 'Paso 7: receso terminado (fechas particulares: PR2 hasta ayer)', [f'PUT calendario → HTTP {s2}',
              f'Asistencia nueva de PA2 sin permiso → {chk["tras_receso"][1]} (se espera rechazo: necesita un permiso de CU028)'])
    R.nota('Paso 3: la evaluación de Rúbrica de un mes de PA2 se verifica en CP-RUB. Paso 7 (operación hecha durante el PR y sincronizada después) y '
           'paso 8 (PR posterior a PA1) necesitan mover la fecha del servidor.')
    fin(R, chk, n, Rr, Pp)


# ── CP-INI-25 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-25', modo='parcial', notas='Los indicadores son globales: se verifican las diferencias en las clases ya pasadas del colegio del caso.')
def cp_ini25():
    R = Run('CP-INI-25'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; C = D.cuenta('docente-a'); X = D.X()
    pasadas = [f for f in FE.clases_habituales(3, FE.pa_actual(X)['fecha_inicio'], A.hoy() - dt.timedelta(days=1), X)]
    if len(pasadas) < 2:
        R.nota('El PA vigente todavía no tiene dos clases pasadas del 3.º.'); fin(R, chk, n, C); return
    f_lunes, f_reprog = pasadas[-1], pasadas[-2]
    v0 = sup_res(); chk['inicial'] = {k: v0[k] for k in ('registros_vencidos', 'registros_incompletos')}
    R.consola(ctx, 'Paso 1: indicadores actuales', [json.dumps(v0, ensure_ascii=False)])
    # La clase f_reprog se reprograma a una fecha futura: su fecha original deja de contar
    nueva = A.hoy() + dt.timedelta(days=1)
    while nueva.isoweekday() > 5 or not A.es_lectivo(X, nueva):
        nueva += dt.timedelta(days=1)
    s, r = A.api('POST', f'/colegios/{X}/clases/reprogramaciones', A.sup(), {'id_grado': A.id_grado(3), 'id_seccion': A.seccion(X, 3),
                                                                           'fecha_original': A.iso(f_reprog), 'fecha_nueva': A.iso(nueva), 'motivo': 'Prueba QA'})
    v1 = sup_res(); chk['reprogramada'] = (s, delta(v0, v1, 'registros_vencidos'))
    R.consola(ctx, f'Paso 3: la clase del {FE.legible(f_reprog)} se reprograma al {FE.legible(nueva)}', [f'POST /api/clases/reprogramaciones → HTTP {s} {"" if s < 300 else str(r)[:200]}',
              f'Vencidos: {chk["reprogramada"][1]} (se espera -1: la fecha original no vence, la nueva todavía no llega)'])
    A.cerrar_abiertas(C); act = A.iniciar_actividad(C)
    adic = A.hoy()
    sa = put_asis(C, adic, [(D.alumno('Ana Norte QA'), 'presente', None)], act, adicional=True) if adic not in FE.clases_habituales(3, adic, adic, X) else 'hoy hay clase habitual'
    v2 = sup_res(); chk['adicional'] = (sa, delta(v1, v2, 'registros_vencidos'))
    nombres = [k for k in D.estado()['alumnos'] if k.endswith('Norte QA') or k.endswith('Rubrica QA')]
    ids = [D.alumno(x) for x in nombres if x != 'Extra12 Rubrica QA']
    s4 = put_asis(C, f_lunes, [(i, 'presente', None) for i in ids[:-1]], act)[0]; v3 = sup_res()
    chk['incompleta'] = (s4, delta(v2, v3, 'registros_vencidos'), delta(v2, v3, 'registros_incompletos'))
    s5 = put_asis(C, f_lunes, [(ids[-1], 'ausente', None)], act)[0]; v4 = sup_res()
    chk['completa'] = (s5, delta(v3, v4, 'registros_incompletos'))
    A.finalizar_actividad(C, act)
    p.goto(BASE + '/login'); login(p, sup_ui()); R.shot(p, 'Inicio de la Supervisora al terminar el caso', full=True)
    R.consola(ctx, f'Pasos 4-6: asistencias del 3.º (clase del {FE.legible(f_lunes)})', [
        f'Clase adicional de hoy → {chk["adicional"][0]}; vencidos {chk["adicional"][1]} (se espera 0: la clase pasada sigue vencida)',
        f'Lista con un alumno sin marcar (HTTP {s4}) → vencidos {chk["incompleta"][1]} (se espera -1), incompletos {chk["incompleta"][2]} (se espera +1)',
        f'Se marca al alumno faltante (HTTP {s5}) → incompletos {chk["completa"][1]} (se espera -1)'])
    R.nota('Pasos 2, 3 (día no lectivo) y 7 necesitan esperar a que termine el día de clase; se verifican con clases ya pasadas.')
    fin(R, chk, n, C)


# ── CP-INI-26 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-26', notas='D2 es Docente B, reasignado durante el caso con "Próximo" a un colegio en receso.')
def cp_ini26():
    R = Run('CP-INI-26'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; B = D.cuenta('docente-b'); uid = D.id_usuario('docente-b'); X = D.X()
    A.cerrar_abiertas(B); cid = colegio_pr(R, ctx, 'Receso INI26')
    asignar_bloques(uid, [(cid, [3], 'proximo')])
    pa = FE.pa_anterior(X); s, r = perm(uid, X, 3, pa['id_periodo_academico'], 'asistencias', A.ahora() + dt.timedelta(days=2)); pid = pid_de(r)
    R.consola(ctx, f'Precondición: D2 sin asignaciones habilitadas, con permiso vigente para Asistencias de PA{pa["numero"]}, {D.nombre_colegio()} 3.º',
              [f'POST permiso → HTTP {s} {json.dumps(r, ensure_ascii=False)[:250]}'])
    login(p, B); p.wait_for_timeout(2500); t = main_txt(p)
    chk['apartado'] = ('Permisos de corrección vigentes' in t, t.split('Permisos de corrección vigentes', 1)[-1][:300].replace('\n', ' | ') if 'Permisos de corrección vigentes' in t else '')
    R.shot(p, f'Paso 1: apartado "Permisos de corrección vigentes": {chk["apartado"]}')
    chk['boton'] = boton(p)
    if chk['boton']['habilitado']:
        iniciar_ui(p)
    R.shot(p, f'Paso 2: "Iniciar actividad" {chk["boton"]}')
    act = A.actividad_en_curso(token_navegador(p))
    if not act:
        sa, ra = A.api('POST', '/actividades', token_navegador(p), {'id_actividad': A.uid()}); chk['inicio_api'] = sa
        act = A.actividad_en_curso(token_navegador(p))
        R.consola(ctx, 'Paso 2: inicio por la API con el permiso vigente', [f'POST /api/actividades → HTTP {sa}'])
    f_pa = FE.clases_del_pa(3, pa['numero'], X)[-1]
    abrir_asis(p, f_pa, colegio=D.nombre_colegio()); chk['aviso'] = textos(p, 'Corrección excepcional')
    chk['marcar'] = marcar_asis(p, 'Ana Norte QA', 'Presente')
    R.shot(p, f'Paso 3: Asistencias del {FE.legible(f_pa)}: aviso {chk["aviso"]}; registro {chk["marcar"]}')
    abrir_rubrica(p, colegio=D.nombre_colegio()); chk['rubrica'] = p.locator('main tbody select:enabled').count()
    f4 = FE.clases_del_pa(4, pa['numero'], X); abrir_asis(p, f4[-1], grado='4.º', colegio=D.nombre_colegio()); chk['asis_4'] = controles(p)
    R.shot(p, f'Paso 4: Rúbrica del mismo grupo (selects habilitados {chk["rubrica"]}); Asistencias de 4.º: {chk["asis_4"]}')
    g = A.api('GET', '/asistencias?' + A.q(id_colegio=X, id_grado=A.id_grado(3), id_seccion=A.seccion(X, 3), fecha=A.iso(f_pa)), A.sup())[1]
    ana = next((a for a in (g or {}).get('alumnos', []) if a['nombre'].startswith('Ana ')), {})
    chk['registro'] = {k: ana.get(k) for k in ('estado', 'id_permiso', 'id_docente', 'registrado_por') if k in ana} or ana
    R.consola(ctx, 'Paso 5: la asistencia guardada (API)', [json.dumps(chk['registro'], ensure_ascii=False)[:400],
                                                          'Si la API no devuelve el permiso ni el Docente, el dato está en la base de datos.'])
    rv = A.api('POST', f'/usuarios/{uid}/permisos/{pid}/revocar', A.sup(), {'motivo': 'Prueba QA'})[0]
    chk['revocado'] = (rv, put_asis(token_navegador(p), f_pa, [(D.alumno('Beto Norte QA'), 'presente', None)], act))
    R.consola(ctx, 'Paso 6: la Supervisora revoca el permiso con la actividad de D2 abierta', [f'Revocar → HTTP {rv}', f'Nueva asistencia → {chk["revocado"][1]}'])
    fin(R, chk, n, B)


# ── CP-INI-27 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-27', notas='El Docente M es Docente B; el colegio Y es un colegio del caso con fechas particulares.')
def cp_ini27():
    R = Run('CP-INI-27'); n = Nav(); ctx = n.ctx(); p = ctx.new_page(); chk = {}; B = D.cuenta('docente-b'); uid = D.id_usuario('docente-b'); X = D.X()
    A.cerrar_abiertas(B); Yc = colegio_pr(R, ctx, 'Colegio Y', grados=(4,))
    s = asignar_bloques(uid, [(X, [4], None), (Yc, [4], 'proximo')])[0]
    R.consola(ctx, 'Precondición: M con 4.º del colegio Norte (calendario general, hoy en PA) y 4.º del colegio Y (fechas particulares, hoy en PR, "Próximo")',
              [f'PATCH asignación → HTTP {s}', f'Periodo de hoy en Norte: {A.periodo_actual(X)}', f'Periodo de hoy en Y: {A.periodo_actual(Yc)}'])
    login(p, B); p.wait_for_timeout(2500); chk['inicio'] = {'boton': boton(p), 'texto': main_txt(p)[:500]}
    R.shot(p, f'Paso 1: Inicio de M: "Iniciar actividad" {chk["inicio"]["boton"]}', full=True)
    iniciar_ui(p); F = FE.ultima_clase(4, X)
    abrir_asis(p, F, grado='4.º', colegio=D.nombre_colegio())
    al4 = A.alumnos(X, 4)
    chk['norte'] = marcar_asis(p, al4[0]['nombres'] + ' ' + al4[0]['apellidos'], 'Presente') if al4 else 'el 4.º del colegio Norte no tiene alumnos'
    R.shot(p, f'Paso 2: asistencia del colegio Norte del {FE.legible(F)}: {chk["norte"]}')
    ny = A.colegio(Yc)['nombre']; fy = FE.clases_del_pa(4, 2, Yc); fy = fy[-1] if fy else None
    if fy:
        abrir_asis(p, fy, grado='4.º', colegio=ny); chk['y_pa2'] = {'controles': controles(p), 'avisos': textos(p, 'periodo', 'habilit', 'receso')[:3]}
        R.shot(p, f'Paso 3: colegio Y con una fecha de PA2 ({FE.legible(fy)}): {chk["y_pa2"]}')
    abrir_asis(p, A.hoy(), grado='4.º', colegio=ny); chk['y_pr'] = RECESO in main_txt(p)
    R.shot(p, f'Paso 4: colegio Y con la fecha de hoy (receso): mensaje de CU {chk["y_pr"]}')
    cl = A.clases(X, 4, F, F); chk['clase'] = [(c['fecha'], c.get('id_periodo_academico')) for c in cl]
    R.consola(ctx, 'Paso 5: la clase del colegio Norte (API)', [f'{chk["clase"]}; PA vigente de Norte: {FE.pa_actual(X)["id_periodo_academico"]} (PA{FE.pa_actual(X)["numero"]})'])
    fin(R, chk, n, B)


# ── CP-INI-28 ───────────────────────────────────────────────────────────────────────

@caso('CP-INI-28')
def cp_ini28():
    R = Run('CP-INI-28'); n = Nav(); chk = {}; C = D.cuenta('docente-a'); F = FE.ultima_clase(3)
    ctx = n.ctx(); p = ctx.new_page()
    con_actividad(p, C); abrir_asis(p, F); abrir_rubrica(p); abrir_asis(p, F)
    ctx.set_offline(True); p.wait_for_timeout(500)
    chk['marcar'] = marcar_asis(p, 'Beto Norte QA', 'Ausente', esperar=False); chk['cola'] = len(cola_idb(p))
    R.shot(p, f'Paso 1: asistencia de Beto sin conexión: cola {chk["cola"]}')
    estado = ctx.storage_state()
    tk = token_navegador(p)
    p.close()
    p = ctx.new_page()
    p.add_init_script(f"if(!sessionStorage.getItem('sicedu.token'))sessionStorage.setItem('sicedu.token','{tk}')")
    try:
        p.goto(BASE + '/inicio'); p.wait_for_timeout(3500); chk['reabrir'] = (p.url.replace(BASE, ''), p.locator('body').inner_text()[:250])
    except Exception as e:
        chk['reabrir'] = ('error del navegador', str(e).split('\n')[0][:100])
    R.shot(p, f'Paso 2: sin conexión, pestaña cerrada y SICEDU abierto otra vez: {chk["reabrir"][0]} {chk["reabrir"][1][:150]}')
    chk['storage'] = {'origenes': len(estado.get('origins', []))}
    try:
        abrir_asis(p, F); chk['asis'] = {'controles': controles(p), 'aviso': textos(p, 'No se puede verificar', 'habilitación')[:2]}
        abrir_rubrica(p); chk['rubrica'] = p.locator('main tbody select:enabled').count()
    except Exception as e:
        chk['asis'] = 'no se pudo abrir: ' + str(e)[:80]
    R.shot(p, f'Paso 3: controles tras reabrir sin conexión: {chk.get("asis")}; selects de Rúbrica habilitados {chk.get("rubrica")}')
    try:
        ir(p, 'Inicio')
        if p.get_by_role('button', name='Finalizar actividad').count():
            finalizar_ui(p)
        iniciar_ui(p); chk['iniciar'] = (texto_act(p), toasts_txt(p) + textos(p, 'No se puede verificar'))
    except Exception as e:
        chk['iniciar'] = str(e)[:80]
    R.shot(p, f'Paso 4: finalizar e iniciar otra actividad: {chk["iniciar"]}')
    try:
        chk['cola_tras'] = len(cola_idb(p))
    except Exception:
        chk['cola_tras'] = None
    R.consola(ctx, 'Paso 5: IndexedDB', [f'Operaciones pendientes: {chk["cola_tras"]}'])
    ctx.set_offline(False); p.wait_for_timeout(2000)
    if '/login' in p.url:
        login(p, C)
    p.wait_for_timeout(30000); chk['sincronizada'] = de_alumno(F, 'Beto Norte QA')
    R.shot(p, f'Paso 6: con conexión: asistencia de Beto según la API {chk["sincronizada"]}')
    R.nota('Paso 2: Playwright no puede reiniciar el navegador conservando Session Storage; se cierra la pestaña y se abre otra con el mismo token.')
    fin(R, chk, n, C)
