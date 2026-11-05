"""Registro de casos: cada caso automatizado se declara con @caso(...).

modo:
  'qa'       → corre completo en QA.
  'parcial'  → corre en QA, pero algún paso del plan no se puede hacer allí (queda como NOTA en la evidencia).
Los casos sin función son 'pendiente' (llegan en una tanda posterior) o 'solo_local' (necesitan
la base de datos, mover el reloj del servidor u otra cosa que en QA no se puede).
"""
from ._plan import CASOS_PLAN

MODULOS = {
    'AUT': 'Autenticación', 'ROL': 'Roles y permisos', 'INI': 'Inicio', 'COL': 'Colegios',
    'CAL': 'Calendario académico', 'PER': 'Permisos de corrección', 'ALU': 'Alumnos', 'USR': 'Usuarios',
    'SES': 'Sesiones', 'SEG': 'Seguimiento', 'LEC': 'Seguimiento de Lectura', 'ASI': 'Asistencias',
    'RUB': 'Rúbrica', 'RV': 'Registro de Vuelo',
}

REGISTRO = {}

# Casos que no se automatizan contra QA y por qué (se completan tanda a tanda).
SOLO_LOCAL = {}


def caso(cp, modo='qa', notas=''):
    def deco(fn):
        REGISTRO[cp] = {'fn': fn, 'modo': modo, 'notas': notas}
        return fn
    return deco


def info(cp):
    for c, m, t, v in CASOS_PLAN:
        if c == cp:
            return {'cp': c, 'modulo': m, 'nombre_modulo': MODULOS[m], 'titulo': t, 'ronda6': v}
    return None


def estado_de(cp):
    if cp in REGISTRO:
        return REGISTRO[cp]['modo']
    if cp in SOLO_LOCAL:
        return 'solo_local'
    return 'pendiente'


def modulo_desde_texto(txt):
    t = txt.strip().lower()
    for k, v in MODULOS.items():
        if t in (k.lower(), v.lower()) or v.lower().startswith(t):
            return k
    return None
