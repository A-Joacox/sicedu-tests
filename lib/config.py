"""Configuración de la suite: se lee del archivo .env de la carpeta de la suite.

Ninguna contraseña está escrita en el código: todas salen del .env (que no se comparte)
o de variables de entorno del sistema, que tienen prioridad.
"""
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ESTADO = RAIZ / 'estado'
RESULTADOS = RAIZ / 'resultados'


def _leer_env(ruta):
    valores = {}
    if not ruta.exists():
        return valores
    for linea in ruta.read_text(encoding='utf-8').splitlines():
        linea = linea.strip()
        if not linea or linea.startswith('#') or '=' not in linea:
            continue
        clave, valor = linea.split('=', 1)
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in '"\'':
            valor = valor[1:-1]
        valores[clave.strip()] = valor
    return valores


_ENV = _leer_env(Path(os.environ.get('QA_ENV_FILE', RAIZ / '.env')))


def env(clave, defecto=None, obligatorio=False):
    valor = os.environ.get(clave, _ENV.get(clave, defecto))
    if obligatorio and not valor:
        sys.exit(f'Falta {clave} en el archivo .env (copia .env.example como .env y complétalo).')
    return valor


def _base(url):
    url = (url or '').strip().rstrip('/')
    url = re.sub(r'/login$', '', url)
    if url and not url.startswith('http'):
        url = 'https://' + url
    return url


BASE = _base(env('QA_BASE_URL', 'https://qa-huascaran.ingsoftware.lat'))
API = BASE + '/api'

# Cuenta de la Supervisora E2E de QA (la misma del seed sembrar-e2e).
SUP_CORREO = env('QA_SUPERVISOR_CORREO')
SUP_CLAVE = env('QA_SUPERVISOR_CLAVE')

# Cuentas propias de la suite: alias del correo del probador (usuario+sicedu-<etiqueta>@dominio).
ALIAS_USUARIO = env('QA_CORREO_USUARIO', 'joaquin.mercado')
ALIAS_DOMINIO = env('QA_CORREO_DOMINIO', 'utec.edu.pe')
CLAVE_CUENTAS = env('QA_CLAVE_CUENTAS')

# manual: la suite pide pegar la contraseña temporal o el PIN que llegó al correo.
# buzon:<carpeta>: lee los .eml de una carpeta (solo para el entorno local del probador).
MODO_CORREO = env('QA_MODO_CORREO', 'manual')

HEADLESS = env('QA_HEADLESS', 'true').lower() not in ('0', 'false', 'no')
LENTO_MS = int(env('QA_LENTO_MS', '0') or 0)
ZONA = 'America/Lima'


def correo_de(etiqueta):
    """Correo de una cuenta de la suite: joaquin.mercado+sicedu-docente-a@utec.edu.pe."""
    return f'{ALIAS_USUARIO}+sicedu-{etiqueta}@{ALIAS_DOMINIO}'.lower()


def exigir_credenciales():
    faltan = [k for k, v in [('QA_SUPERVISOR_CORREO', SUP_CORREO), ('QA_SUPERVISOR_CLAVE', SUP_CLAVE),
                             ('QA_CLAVE_CUENTAS', CLAVE_CUENTAS)] if not v]
    if faltan:
        sys.exit('Faltan en el .env: ' + ', '.join(faltan))
