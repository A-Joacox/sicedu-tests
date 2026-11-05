"""Lectura de los correos que envía SICEDU (contraseña temporal, PIN).

En QA los correos llegan a la bandeja del probador (alias +sicedu-...). La suite no entra a
esa bandeja: se detiene y pide pegar el dato. Con QA_MODO_CORREO=buzon:<carpeta> lee los .eml
de una carpeta (lo usa el entorno local del probador para validar la suite).
"""
import email
import glob
import os
import re
import time
from email import policy

from . import config

_TEMPORAL = [re.compile(r'[Cc]ontraseña temporal[^\n]*?:\s*(\S+)'),
             re.compile(r'\n\s*([A-Za-z0-9!#$%&*+\-.=?@^_]{10,})\s*\n')]
_PIN = re.compile(r'\b(\d{6})\b')


def _buzon():
    return config.MODO_CORREO.split(':', 1)[1] if config.MODO_CORREO.startswith('buzon:') else None


def _correos_buzon(desde_ts, para):
    out = []
    for f in sorted(glob.glob(os.path.join(_buzon(), '*.eml'))):
        try:
            ts = float(os.path.basename(f)[:-4])
        except ValueError:
            continue
        if ts < desde_ts:
            continue
        m = email.message_from_bytes(open(f, 'rb').read(), policy=policy.default)
        if para and para.lower() not in (m['To'] or '').lower():
            continue
        cuerpo = m.get_body(preferencelist=('plain', 'html'))
        out.append({'asunto': m['Subject'], 'texto': cuerpo.get_content() if cuerpo else ''})
    return out


def _esperar_buzon(para, desde_ts, patrones, espera=20):
    fin = time.time() + espera
    while time.time() < fin:
        for m in reversed(_correos_buzon(desde_ts, para)):
            for p in patrones:
                x = p.search(m['texto'])
                if x:
                    return x.group(1).strip()
        time.sleep(0.5)
    return None


ESPERA_MIN = float(config.env('QA_ESPERA_CORREO', '10') or 10)   # minutos que espera un dato antes de seguir sin él


def _leer(segundos):
    """input() con tiempo límite (Windows y Linux). None si se acabó el tiempo o no hay consola."""
    import sys
    if not sys.stdin or not sys.stdin.isatty():
        return None
    fin = time.time() + segundos
    if os.name == 'nt':
        import msvcrt
        buf = ''
        while time.time() < fin:
            if msvcrt.kbhit():
                ch = msvcrt.getwche()
                if ch in ('\r', '\n'):
                    print(); return buf
                if ch == '\b':
                    buf = buf[:-1]
                elif ch == '\x16':
                    pass
                else:
                    buf += ch
            else:
                time.sleep(0.05)
        print(); return None
    import select
    r, _, _ = select.select([sys.stdin], [], [], segundos)
    return sys.stdin.readline() if r else None


def _preguntar(texto, validar):
    print()
    print('=' * 78)
    print(texto)
    print(f'(Si en {ESPERA_MIN:g} minutos no se pega nada, la suite sigue sin este dato.)')
    print('=' * 78)
    while True:
        print('> ', end='', flush=True)
        v = _leer(ESPERA_MIN * 60)
        if v is None:
            print('Sin respuesta: se sigue sin este dato.')
            return None
        v = v.strip()
        if not v:
            return None
        if validar(v):
            return v
        print('El valor no tiene el formato esperado. Vuelve a pegarlo (o Enter para omitir).')


def contrasena_temporal(correo, desde_ts):
    if _buzon():
        return _esperar_buzon(correo, desde_ts, _TEMPORAL)
    return _preguntar(f'Revisa el correo enviado a {correo} (asunto de bienvenida de SICEDU)\n'
                      'y pega aquí la CONTRASEÑA TEMPORAL. Enter para omitir esta cuenta.',
                      lambda v: len(v) >= 8 and ' ' not in v)


def pin(correo, desde_ts):
    if _buzon():
        return _esperar_buzon(correo, desde_ts, [_PIN])
    return _preguntar(f'Revisa el correo enviado a {correo} y pega aquí el PIN de 6 dígitos.\n'
                      'Enter si no llegó ningún correo.', lambda v: bool(re.fullmatch(r'\d{6}', v)))


def llego_correo(correo, desde_ts, que='un correo'):
    """True/False si llegó un correo; en modo manual se le pregunta al probador."""
    if _buzon():
        time.sleep(3)
        return bool(_correos_buzon(desde_ts, correo))
    v = _preguntar(f'¿Llegó {que} a {correo}? Escribe s (sí) o n (no).', lambda x: x.lower() in ('s', 'n', 'si', 'sí', 'no'))
    return None if v is None else v.lower().startswith('s')
