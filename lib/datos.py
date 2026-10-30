"""Datos de prueba en QA: cuentas fijas de la suite y datos nuevos para cada caso.

- Las cuentas se crean una sola vez (preparar_qa.py --cuentas) con alias del correo del
  probador. El primer ingreso pide pegar la contraseña temporal que llega por correo.
- Antes de cada caso, correr.py crea colegios, alumnos y permisos nuevos con el código del caso
  ("QA AUTO ASI-04 1912 Norte") y reasigna a los Docentes de la suite a esos colegios: cada caso
  empieza con datos limpios, como en local con la base restaurada. Al terminar, esos colegios se
  inactivan. El estado del caso en curso queda en estado/corrida.json.
"""
import datetime as dt
import json
import time
import zlib

from . import api as A
from . import config, correo

ROL = {'Docente': 1, 'Supervisor': 2, 'Directivo': 3}

# etiqueta: (rol, nombres, apellidos)
CUENTAS = {
    'docente-a': ('Docente', 'Docente A', 'QA Auto'),
    'docente-b': ('Docente', 'Docente B', 'QA Auto'),
    'rv-uno': ('Docente', 'Docente RV', 'QA Auto'),
    'retro': ('Docente', 'Docente Retro', 'QA Auto'),
    'sin-grupos': ('Docente', 'Docente Sin Grupos', 'QA Auto'),
    'directivo': ('Directivo', 'Directivo', 'QA Auto'),
    'supervisor-2': ('Supervisor', 'Supervisora Dos', 'QA Auto'),
}

# Cuentas que no se reasignan en cada caso (preparar.bat --demo).
CUENTAS_EXTRA = {
    'docente-demo': ('Docente', 'Docente Demo', 'QA Auto'),
}


def _def(etiqueta):
    return CUENTAS.get(etiqueta) or CUENTAS_EXTRA[etiqueta]


_ESTADO = config.ESTADO / 'corrida.json'
_CUENTAS_JSON = config.ESTADO / 'cuentas.json'


def _dni(correo):
    return '9' + str(zlib.crc32(correo.encode()) % 10_000_000).zfill(7)


def cuenta(etiqueta):
    return A.Cuenta(config.correo_de(etiqueta), config.CLAVE_CUENTAS, _def(etiqueta)[1])


def directivo():
    return cuenta('directivo')


# ── Estado de la corrida ────────────────────────────────────────────────────────────

def estado():
    if not _ESTADO.exists():
        raise SystemExit('No hay datos de corrida. Ejecuta primero: preparar.bat')
    return json.loads(_ESTADO.read_text(encoding='utf-8'))


def guardar_estado(e):
    config.ESTADO.mkdir(exist_ok=True)
    _ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding='utf-8')


def X():
    """Id del colegio "Norte" de la corrida (el de Docente A)."""
    return estado()['colegios']['norte']['id']


def Y():
    return estado()['colegios']['sur']['id']


def nombre_colegio(clave='norte'):
    return estado()['colegios'][clave]['nombre']


def alumno(nombre):
    """Id de un alumno de la corrida por su nombre completo ('Ana Norte QA') o su primer nombre ('Extra12')."""
    al = estado()['alumnos']
    if nombre in al:
        return al[nombre]
    for k, v in al.items():
        if k.split(' ')[0] == nombre:
            return v
    return None


def fecha_estado(clave):
    return A.fecha(estado()['fechas'][clave])


# ── Cuentas ─────────────────────────────────────────────────────────────────────────

def _cuentas_creadas():
    return json.loads(_CUENTAS_JSON.read_text(encoding='utf-8')) if _CUENTAS_JSON.exists() else {}


def asegurar_cuenta(etiqueta, asignacion=None, log=print):
    """Crea la cuenta si no existe y hace su primer ingreso. Devuelve el id de usuario o None."""
    rol, nombres, apellidos = _def(etiqueta)
    correo_c = config.correo_de(etiqueta)
    u = A.usuario_por_correo(correo_c)
    creadas = _cuentas_creadas()
    if u is None:
        body = {'nombres': nombres, 'apellidos': apellidos, 'dni': _dni(correo_c), 'correo': correo_c, 'id_rol': ROL[rol]}
        if rol == 'Docente':
            body['asignacion'] = asignacion
        t0 = time.time() - 2
        s, r = A.api('POST', '/usuarios', A.sup(), body)
        if s != 201:
            log(f'  ✗ No se pudo crear {correo_c}: {s} {r}')
            return None
        u = r['usuario']
        log(f'  ✓ Cuenta creada: {correo_c} ({rol}). Correo enviado: {r.get("correo_enviado")}')
        temporal = r.get('contraseña_temporal')
    else:
        temporal = None
        if not u.get('debe_cambiar_contrasena'):
            log(f'  · Ya existe y está lista: {correo_c}')
            creadas[etiqueta] = u['id']
            config.ESTADO.mkdir(exist_ok=True)
            _CUENTAS_JSON.write_text(json.dumps(creadas, indent=1), encoding='utf-8')
            return u['id']
        log(f'  · {correo_c} existe pero falta su primer ingreso.')
        t0 = 0
    if not temporal:
        temporal = correo.contrasena_temporal(correo_c, t0)
    if not temporal:
        log(f'  ✗ Sin contraseña temporal para {correo_c}: vuelve a ejecutar preparar.bat cuando la tengas.')
        return None
    s, r = A.api('POST', '/password/primer-ingreso', body={'correo': correo_c, 'contraseña_temporal': temporal,
                                                         'contraseña_nueva': config.CLAVE_CUENTAS,
                                                         'confirmar_contraseña_nueva': config.CLAVE_CUENTAS})
    if s != 200:
        log(f'  ✗ Primer ingreso de {correo_c} rechazado: {s} {r.get("detail") if isinstance(r, dict) else r}')
        return None
    A.api('POST', '/logout', r['access_token'])
    log(f'  ✓ Primer ingreso hecho: {correo_c}')
    creadas[etiqueta] = u['id']
    config.ESTADO.mkdir(exist_ok=True)
    _CUENTAS_JSON.write_text(json.dumps(creadas, indent=1), encoding='utf-8')
    return u['id']


def id_usuario(etiqueta):
    c = _cuentas_creadas()
    if etiqueta in c:
        return c[etiqueta]
    u = A.usuario_por_correo(config.correo_de(etiqueta))
    return u['id'] if u else None


# ── Datos por corrida ───────────────────────────────────────────────────────────────

ALUMNOS_NORTE = (
    [(n, 'Norte QA', 3, 'CL') for n in ['Ana', 'Beto', 'Carla', 'Dante', 'Elsa']]
    + [(f'Extra{i:02d}', 'Rubrica QA', 3, 'CL') for i in range(1, 13)]
    + [(f'Alumno{i:02d}', 'Volumen QA', 3, 'CL' if i % 3 else 'ALFA') for i in range(1, 39)]
    + [('Grado1P1', 'Entrada QA', 1, 'ALFA'), ('Grado2P2', 'Entrada QA', 2, 'CL'), ('Grado4P2', 'Entrada QA', 4, 'CL'),
       ('Grado4P1', 'Entrada QA', 4, 'ALFA'), ('Grado5P2', 'Entrada QA', 5, 'CL'), ('Grado6P2', 'Entrada QA', 6, 'CL')]
)
ALUMNOS_SUR = [('Kira', 'Sur QA', 3, 'CL'), ('Lalo', 'Sur QA', 4, 'CL'), ('Mia', 'Sur QA', 5, 'CL')]


def dia_de_clase(hoy):
    """Día de clase (1 = lunes … 5 = viernes) para que hoy sea día de clase; en fin de semana, el viernes."""
    return min(hoy.isoweekday(), 5)


def crear_corrida(sufijo=None, log=print):
    config.exigir_credenciales()
    hoy = A.hoy()
    sufijo = sufijo or A.ahora().strftime('%m%d-%H%M')
    e = {'sufijo': sufijo, 'creada': A.ahora().isoformat(), 'url': config.BASE, 'colegios': {}, 'alumnos': {}, 'fechas': {}}
    dia = dia_de_clase(hoy)
    for clave, nombre in [('norte', f'QA AUTO {sufijo} Norte'), ('sur', f'QA AUTO {sufijo} Sur')]:
        body = {'nombre': nombre, 'departamento': 'Áncash', 'provincia': 'Carhuaz', 'distrito': 'Shilla', 'nivel_educativo': 'Primaria',
                'grados': [{'id_grado': A.id_grado(g), 'dia_clase': dia} for g in range(1, 7)],
                'programas': [A.ALFA(), A.CL()]}
        r = A.ok(A.api('POST', '/colegios', A.sup(), body), 'crear colegio ' + nombre)
        e['colegios'][clave] = {'id': r['id'], 'nombre': nombre}
        log(f'  ✓ Colegio {nombre} (id {r["id"]}), clase todos los grados el día {dia} de la semana')
    guardar_estado(e)
    cal = A.calendario(e['colegios']['norte']['id'])
    pas = [p for p in cal['periodos'] if p['tipo'] == 'PA']
    e['fechas']['inicio_anio'] = pas[0]['fecha_inicio']
    e['periodo_actual'] = cal['periodo_actual']
    if not cal['periodo_actual'] or cal['periodo_actual']['tipo'] != 'PA':
        log(f'  ⚠ Hoy no es un día de PA en el calendario general ({cal["periodo_actual"]}). Muchos casos no aplican.')
    desde = pas[0]['fecha_inicio']
    prog = {'CL': A.CL(), 'ALFA': A.ALFA()}
    for clave, lista in [('norte', ALUMNOS_NORTE), ('sur', ALUMNOS_SUR)]:
        cid = e['colegios'][clave]['id']
        for nom, ape, g, p in lista:
            e['alumnos'][f'{nom} {ape}'] = A.crear_alumno(nom, ape, cid, g, prog[p], desde)
        log(f'  ✓ {len(lista)} alumnos en {e["colegios"][clave]["nombre"]}')
    # Extra12: inactivo desde hoy (perteneció al grupo hasta ayer).
    A.desactivar_alumno(e['alumnos']['Extra12 Rubrica QA'], hoy)
    e['fechas']['extra12_inactivo_desde'] = hoy.isoformat()
    guardar_estado(e)
    return e


def asignar_docentes(log=print):
    """Reasigna a los Docentes de la suite a los colegios de la corrida (la asignación anterior se libera)."""
    X_, Y_ = X(), Y()
    plan = {'docente-a': [(X_, [3])], 'rv-uno': [(X_, [1, 2])], 'docente-b': [(X_, [4])],
            'sin-grupos': [(Y_, [6])], 'retro': [(Y_, [5])]}
    for et, cg in plan.items():
        uid = id_usuario(et)
        if not uid:
            log(f'  ✗ Falta la cuenta {et}: ejecuta preparar.bat --cuentas')
            continue
        s, r = A.asignar(uid, cg)
        log(f'  {"✓" if s == 200 else "✗"} {et} → {cg} ({s}{"" if s == 200 else " " + str(r)[:200]})')


def permisos_base(log=print):
    """Permisos de Rúbrica y Registro de Vuelo de Docente A para los PA ya culminados (como en la ronda 6)."""
    hoy = A.hoy()
    uid = id_usuario('docente-a')
    fin = (A.ahora() + dt.timedelta(days=30)).replace(hour=23, minute=0, second=0, microsecond=0)
    for p in A.periodos(X()):
        if A.fecha(p['fecha_fin']) < hoy:
            for mod in ('rubrica', 'registro_vuelo'):
                s, r = A.permiso(uid, X(), 3, p['id_periodo_academico'], mod, fin)
                log(f'  {"✓" if s == 201 else "·"} permiso {mod} PA{p["numero"]} para Docente A ({s})')


def _quiet(*a, **k):
    pass


def preparar_caso(cp, log=_quiet):
    """Datos nuevos para un caso: colegios, alumnos, asignaciones y permisos base."""
    suf = f'{cp.replace("CP-", "").replace("CP", "AUT-")} {A.ahora().strftime("%H%M%S")}'
    e = crear_corrida(suf, log)
    asignar_docentes(log)
    permisos_base(log)
    return e


def cerrar_caso():
    """Cierra actividades abiertas de los Docentes y desactiva los colegios del caso."""
    for et, (rol, *_) in CUENTAS.items():
        if rol == 'Docente':
            try:
                A.cerrar_abiertas(cuenta(et))
            except Exception:
                pass
    try:
        for c in estado()['colegios'].values():
            A.api('PATCH', f'/colegios/{c["id"]}/desactivar', A.sup())
    except Exception:
        pass


def id_docente(etiqueta):
    """id_docente de una cuenta Docente (para las rutas de Seguimiento)."""
    nombre = _def(etiqueta)[1]
    for cid in [X(), Y()]:
        for d in A.todas_las_paginas('/seguimiento/docentes?' + A.q(id_colegio=cid), A.sup()):
            if d['nombres'] == nombre:
                return d['id_docente']
    for d in A.todas_las_paginas('/seguimiento/docentes', A.sup()):
        if d['nombres'] == nombre and d['apellidos'] == _def(etiqueta)[2]:
            return d['id_docente']
    return None
