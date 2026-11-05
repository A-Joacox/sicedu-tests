"""Ayudas compartidas por los casos de la tanda 2 (pantallas de administración y rutas)."""
import re

from lib import api as A
from lib import datos as D
from lib.ui import BASE, dlg, main_txt


def sup_ui():
    """Supervisora para la interfaz: la cuenta supervisor-2 de la suite (la E2E queda para la API)."""
    return D.cuenta('supervisor-2')


def menu(p):
    return [t.strip() for t in p.locator('aside nav a').all_inner_texts()]


def visitar(p, ruta):
    p.goto(BASE + ruta)
    p.wait_for_load_state('networkidle')
    p.wait_for_timeout(1500)
    return p.url.replace(BASE, '')


def estado_pantalla(p):
    t = p.locator('main').inner_text() if p.locator('main').count() else p.locator('body').inner_text()
    if 'No se pudo mostrar esta pantalla' in t:
        return 'ERROR DE PANTALLA'
    if '403' in p.url or 'Acceso denegado' in t or 'no tiene permiso' in t.lower():
        return 'acceso denegado'
    if '/login' in p.url:
        return 'pide iniciar sesión'
    return 'carga'


def abrir_menu(p, nombre):
    p.locator('aside nav a').filter(has_text=re.compile('^' + re.escape(nombre) + '$')).first.click()
    p.wait_for_timeout(1500)


def fin(R, chk, n, *cuentas):
    for c in cuentas:
        try:
            A.cerrar_abiertas(c)
        except Exception:
            pass
    R.save(checks=chk)
    n.close()


def hay_dialogo(p):
    return p.locator('[role=dialog]:visible').count() > 0


def errores_dlg(p, extra=''):
    if not hay_dialogo(p):
        return ['(el modal se cerró)']
    pat = r'Ingresa|Selecciona|debe|posterior|Ya existe|ya existe|todavía|inactiv|calendario|Sin conexión|No se pudo|ya fue|ya venció|obligatori|descartar|inválid|registrad|máximo|mínimo|caracteres' + (('|' + extra) if extra else '')
    return [l.strip() for l in dlg(p).inner_text().split('\n') if l.strip() and re.search(pat, l)]


def avisos(p):
    t = main_txt(p) if p.locator('main').count() else ''
    return [l for l in t.split('\n') if re.search(r'conexión|No se pudo|Reintentar|sin conexión|servidor', l, re.I)][:4]


def tabla(p):
    return [r.replace('\t', ' | ') for r in p.locator('main tbody tr').all_inner_texts()]


def sufijo():
    """Parte única de los datos del caso (la hora del colegio del caso, p. ej. 'USR-02 101530')."""
    return D.estado()['sufijo']


def hhmmss():
    return D.estado()['sufijo'].split(' ')[-1]


def dni_unico(semilla):
    """DNI de 8 dígitos que no se repite entre corridas (deriva de la hora y una semilla)."""
    import time
    return '7' + str((int(time.time() * 10) + semilla * 7919) % 10_000_000).zfill(7)


def registrar_colegio(cid, nombre):
    """Anota un colegio creado por el caso para que se inactive al terminar (como los de la corrida)."""
    e = D.estado()
    e['colegios'][f'extra-{cid}'] = {'id': cid, 'nombre': nombre}
    D.guardar_estado(e)


def crear_colegio(nombre, grados_dias, programas=None, departamento='Áncash', provincia='Huaraz', distrito='Independencia'):
    """grados_dias: {grado: día (1 = lunes)}. Se inactiva al terminar el caso."""
    body = {'nombre': nombre, 'departamento': departamento, 'provincia': provincia, 'distrito': distrito, 'nivel_educativo': 'Primaria',
            'grados': [{'id_grado': A.id_grado(g), 'dia_clase': d} for g, d in grados_dias.items()],
            'programas': programas or [A.ALFA(), A.CL()]}
    r = A.ok(A.api('POST', '/colegios', A.sup(), body), 'crear colegio ' + nombre)
    registrar_colegio(r['id'], nombre)
    return r['id']


def nombre_unico(base):
    return f'{base} {hhmmss()}'
