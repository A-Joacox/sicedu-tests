"""Cliente de la API de SICEDU (la misma que usa el frontend, en <URL de QA>/api).

Importante: el sistema cierra la sesión anterior de un usuario cuando ese usuario vuelve a
iniciar sesión. Por eso las cuentas se manejan con la clase Cuenta, que guarda su token y
lo renueva solo si la API responde 401. Si una prueba abre el navegador con una cuenta,
conviene pedir antes los tokens de API que necesite, o tomar el token del navegador con
ui.token_navegador(page).
"""
import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import config

LIMA = dt.timezone(dt.timedelta(hours=-5))


class ErrorApi(Exception):
    pass


def _pedir(metodo, ruta, token=None, body=None, timeout=40):
    datos = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(config.API + ruta, data=datos, method=metodo)
    req.add_header('Content-Type', 'application/json')
    req.add_header('Accept', 'application/json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt else None)
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors='replace')
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, txt[:500]
    except urllib.error.URLError as e:
        raise ErrorApi(f'No se pudo conectar con {config.API}{ruta}: {e.reason}')


class Cuenta:
    """Una cuenta con su token de API (se renueva si la sesión se cerró)."""

    def __init__(self, correo, clave, nombre=''):
        self.correo = correo.lower()
        self.clave = clave
        self.nombre = nombre or correo
        self._tk = None

    def __repr__(self):
        return f'Cuenta({self.nombre})'

    def login(self):
        s, r = _pedir('POST', '/login', body={'correo': self.correo, 'password': self.clave})
        if s != 200:
            raise ErrorApi(f'No se pudo iniciar sesión por API con {self.nombre}: {s} {r}')
        self._tk = r['access_token']
        return self._tk

    def tk(self):
        return self._tk or self.login()

    def olvidar(self):
        """Tras iniciar sesión en el navegador con esta cuenta, su token de API ya no vale."""
        self._tk = None

    def usar_token(self, token):
        self._tk = token


def api(metodo, ruta, quien=None, body=None, timeout=40):
    """quien: una Cuenta, un token (str) o None. Con una Cuenta, reintenta una vez si su sesión se cerró."""
    if isinstance(quien, Cuenta):
        s, r = _pedir(metodo, ruta, quien.tk(), body, timeout)
        if s == 401:
            quien.login()
            s, r = _pedir(metodo, ruta, quien.tk(), body, timeout)
        return s, r
    return _pedir(metodo, ruta, quien, body, timeout)


def ok(res, que=''):
    s, r = res
    if s >= 300:
        raise ErrorApi(f'{que}: HTTP {s} {json.dumps(r, ensure_ascii=False)[:400] if not isinstance(r, str) else r[:400]}')
    return r


def todas_las_paginas(ruta, quien, clave='items'):
    out, pagina = [], 1
    sep = '&' if '?' in ruta else '?'
    while True:
        r = ok(api('GET', f'{ruta}{sep}page={pagina}', quien), ruta)
        out += r.get(clave, [])
        if pagina >= (r.get('total_pages') or 1):
            return out
        pagina += 1


def q(**kw):
    return urllib.parse.urlencode({k: v for k, v in kw.items() if v is not None})


def uid():
    return str(uuid.uuid4())


# ── Fechas ──────────────────────────────────────────────────────────────────────────

def ahora():
    return dt.datetime.now(LIMA)


def hoy():
    return ahora().date()


def iso(d):
    return d.isoformat() if isinstance(d, (dt.date, dt.datetime)) else d


def fecha(s):
    return dt.date.fromisoformat(s[:10]) if isinstance(s, str) else s


# ── Supervisora y catálogos ─────────────────────────────────────────────────────────

_SUP = None


def sup():
    global _SUP
    if _SUP is None:
        config.exigir_credenciales()
        _SUP = Cuenta(config.SUP_CORREO, config.SUP_CLAVE, 'Supervisora E2E')
    return _SUP


_CACHE = {}


def _cat(ruta):
    if ruta not in _CACHE:
        _CACHE[ruta] = ok(api('GET', ruta, sup()), ruta)
    return _CACHE[ruta]


def grados():
    return {g['nombre']: g['id'] for g in _cat('/grados')}


def id_grado(n):
    """n: 3 o '3.º'."""
    nombre = n if isinstance(n, str) else f'{n}.º'
    return grados()[nombre]


def programas():
    return {p['nombre']: p['id'] for p in _cat('/programas')}


def ALFA():
    return programas()['Alfabetización']


def CL():
    return programas()['Comprensión Lectora']


def anio():
    for a in _cat('/anios-escolares'):
        if a.get('vigente'):
            return a['id']
    return _cat('/anios-escolares')[-1]['id']


def niveles_rk():
    return {n['letra']: n['id'] for n in _cat('/niveles-razkids')}


# ── Colegios, calendario y clases ───────────────────────────────────────────────────

def colegios(activo=True):
    return todas_las_paginas('/colegios?' + q(activo=str(activo).lower()), sup())


def colegio_por_nombre(nombre, activo=None):
    estados = [True, False] if activo is None else [activo]
    for a in estados:
        for c in colegios(a):
            if c['nombre'].strip().lower() == nombre.strip().lower():
                return c
    return None


def colegio(id_colegio, quien=None):
    return ok(api('GET', f'/colegios/{id_colegio}', quien or sup()), 'colegio')


def seccion(id_colegio, grado):
    g = id_grado(grado)
    for gr in colegio(id_colegio)['grados']:
        if gr['id'] == g:
            return gr['secciones'][0]['id']
    raise ErrorApi(f'El colegio {id_colegio} no ofrece el grado {grado}')


def calendario(id_colegio, quien=None):
    return ok(api('GET', '/calendarios?' + q(id_colegio=id_colegio), quien or sup()), 'calendario')


def periodo_de(id_colegio, d, quien=None):
    return ok(api('GET', '/calendarios/periodo?' + q(id_colegio=id_colegio, fecha=iso(d)), quien or sup()), 'periodo')


def periodo_actual(id_colegio):
    return calendario(id_colegio)['periodo_actual']


def periodos(id_colegio, tipo='PA'):
    return [p for p in calendario(id_colegio)['periodos'] if p['tipo'] == tipo]


def clases(id_colegio, grado, desde=None, hasta=None, quien=None):
    return ok(api('GET', f'/colegios/{id_colegio}/clases?' + q(id_grado=id_grado(grado), id_seccion=seccion(id_colegio, grado),
                                                              desde=iso(desde), hasta=iso(hasta)), quien or sup()), 'clases')


def es_lectivo(id_colegio, d):
    return periodo_de(id_colegio, d).get('es_lectivo')


# ── Alumnos ─────────────────────────────────────────────────────────────────────────

def alumnos(id_colegio, grado=None, programa=None, activo=True):
    return todas_las_paginas('/alumnos?' + q(id_colegio=id_colegio, id_grado=id_grado(grado) if grado else None,
                                             id_programa=programa, activo=str(activo).lower()), sup())


def crear_alumno(nombres, apellidos, id_colegio, grado, programa, desde):
    r = ok(api('POST', '/alumnos', sup(), {'nombres': nombres, 'apellidos': apellidos, 'id_colegio': id_colegio,
                                           'id_grado': id_grado(grado), 'id_programa': programa,
                                           'pertenece_desde': iso(desde)}), f'crear alumno {nombres} {apellidos}')
    return r.get('id') or r.get('id_alumno')


def desactivar_alumno(id_alumno, desde):
    return api('PATCH', f'/alumnos/{id_alumno}/desactivar', sup(), {'aplicar_desde': iso(desde)})


# ── Usuarios, asignaciones y permisos ───────────────────────────────────────────────

def usuario_por_correo(correo):
    for activo in ('true', 'false'):
        s, r = api('GET', '/usuarios?' + q(q=correo, activo=activo), sup())
        if s == 200:
            for u in r.get('items', []):
                if u['correo'].lower() == correo.lower():
                    return u
    return None


def asignacion(colegios_grados, inicio=None):
    """colegios_grados: [(id_colegio, [grados])]. inicio: None, 'retroactivo' o 'proximo'."""
    cols = []
    for c, gs in colegios_grados:
        b = {'id_colegio': c, 'grados': [id_grado(g) for g in gs]}
        if inicio:
            b['inicio_asignacion'] = inicio
        cols.append(b)
    return {'id_anio_escolar': anio(), 'colegios': cols}


def asignar(id_usuario, colegios_grados, inicio=None):
    return api('PATCH', f'/usuarios/{id_usuario}', sup(), {'asignacion': asignacion(colegios_grados, inicio)})


def permiso(id_usuario, id_colegio, grado, id_pa, modulo, fin, inicio=None, motivo='Prueba QA automatizada'):
    b = {'id_anio_escolar': anio(), 'id_colegio': id_colegio, 'id_grado': id_grado(grado), 'id_periodo_academico': id_pa,
         'modulo': modulo, 'fin': iso(fin), 'motivo': motivo}
    if inicio:
        b['inicio'] = iso(inicio)
        b['desde_ahora'] = False
    else:
        b['desde_ahora'] = True
    return api('POST', f'/usuarios/{id_usuario}/permisos', sup(), b)


# ── Actividades ─────────────────────────────────────────────────────────────────────

def iniciar_actividad(cuenta):
    s, r = api('POST', '/actividades', cuenta, {'id_actividad': uid()})
    if s == 409 and isinstance(r, dict) and r.get('motivo') == 'actividad_activa_existente':
        cerrar_abiertas(cuenta)
        s, r = api('POST', '/actividades', cuenta, {'id_actividad': uid()})
    return ok((s, r), f'iniciar actividad de {cuenta}')['actividad']['id']


def actividad_en_curso(cuenta):
    s, r = api('GET', '/actividades?' + q(estado='en_curso'), cuenta)
    items = r.get('items', []) if s == 200 else []
    return items[0]['id'] if items else None


def finalizar_actividad(cuenta, id_actividad):
    return api('POST', f'/actividades/{id_actividad}/finalizar', cuenta, {})


def cerrar_abiertas(cuenta):
    """Finaliza las actividades en curso de la cuenta (equivale a la precondición "sin actividad")."""
    for _ in range(3):
        a = actividad_en_curso(cuenta)
        if not a:
            return
        finalizar_actividad(cuenta, a)


def cerrar_sesion(cuenta):
    if cuenta._tk:
        api('POST', '/logout', cuenta._tk)
        cuenta.olvidar()
