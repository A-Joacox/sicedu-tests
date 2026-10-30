"""Colegio de demostración con volumen real (preparar.bat --demo).

Crea (o completa) "I.E. Demo QA Huascarán": 6 grados, cada uno con su día de clase y entre 30 y
40 alumnos con nombres y apellidos peruanos. En 1.º todos son de Alfabetización; en los demás grados
se reparten entre Alfabetización y Comprensión Lectora. Lo atiende la cuenta Docente Demo de la
suite. Este colegio NO se inactiva al terminar los casos: queda activo para revisar las pantallas a
mano con un volumen real o medir tiempos de carga.
"""
import json
import random

from . import api as A
from . import config
from . import datos as D

NOMBRE = 'I.E. Demo QA Huascarán'
UBICACION = {'departamento': 'Áncash', 'provincia': 'Huaraz', 'distrito': 'Independencia', 'nivel_educativo': 'Primaria'}
DIAS = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 1}            # lunes = 1 … viernes = 5
PROPORCION_CL = {1: 0.0, 2: 0.3, 3: 0.6, 4: 0.8, 5: 0.8, 6: 0.85}   # parte de Comprensión Lectora por grado

NOMBRES_F = ['María', 'Rosa', 'Luz', 'Carmen', 'Ana', 'Flor', 'Yesenia', 'Milagros', 'Ruth', 'Gladys', 'Nayeli', 'Kiara', 'Sofía',
             'Valeria', 'Camila', 'Luciana', 'Mía', 'Ximena', 'Fiorella', 'Daniela', 'Alexandra', 'Brigitte', 'Yanela', 'Rocío',
             'Mariela', 'Esther', 'Nélida', 'Sheyla', 'Dayana', 'Jimena', 'Thalía', 'Lizbeth', 'Abigail', 'Cielo', 'Maricielo']
NOMBRES_M = ['José', 'Luis', 'Juan', 'Carlos', 'Jorge', 'Miguel', 'Edwin', 'Wilmer', 'Fredy', 'Elmer', 'Rubén', 'Jhon', 'Brayan',
             'Santiago', 'Mateo', 'Thiago', 'Sebastián', 'Gael', 'Adrián', 'Anderson', 'Kevin', 'Yordi', 'Fabricio', 'Rodrigo',
             'Alexis', 'Renzo', 'Piero', 'Jhair', 'Dylan', 'Josué', 'Erick', 'Franco', 'Aarón', 'Joel', 'Iker']
APELLIDOS = ['Quispe', 'Huamán', 'Mamani', 'Flores', 'Rojas', 'Sánchez', 'Ramírez', 'Torres', 'Mendoza', 'Chávez', 'Vásquez',
             'Castillo', 'Espinoza', 'Cruz', 'Ríos', 'Gutiérrez', 'Salazar', 'Vega', 'Paredes', 'Cáceres', 'Huaranga', 'Minaya',
             'Colonia', 'Jamanca', 'Sotelo', 'Tarazona', 'Vargas', 'Obregón', 'Rosales', 'Maguiña', 'Cochachin', 'Yanac', 'Depaz',
             'Alvarado', 'Villanueva', 'Henostroza', 'Aguirre', 'Bernardo', 'Caushi', 'Julca', 'León', 'Moreno', 'Palacios']

_ESTADO = config.ESTADO / 'demo.json'


def _alumnos_generados(seed=2026):
    """Lista estable de (nombres, apellidos, grado, subprograma) para los 6 grados."""
    rnd = random.Random(seed)
    usados = set()
    out = []
    for g in range(1, 7):
        cantidad = rnd.randint(30, 40)
        n_cl = round(cantidad * PROPORCION_CL[g])
        for i in range(cantidad):
            while True:
                nom = rnd.choice(NOMBRES_F if rnd.random() < 0.5 else NOMBRES_M)
                if rnd.random() < 0.3:
                    nom += ' ' + rnd.choice(NOMBRES_F + NOMBRES_M)
                ape = f'{rnd.choice(APELLIDOS)} {rnd.choice(APELLIDOS)}'
                if (nom, ape) not in usados:
                    usados.add((nom, ape))
                    break
            out.append((nom, ape, g, 'CL' if i < n_cl else 'ALFA'))
    return out


def crear_demo(log=print):
    config.exigir_credenciales()
    col = A.colegio_por_nombre(NOMBRE)
    if col is None:
        body = {'nombre': NOMBRE, **UBICACION, 'grados': [{'id_grado': A.id_grado(g), 'dia_clase': d} for g, d in DIAS.items()],
                'programas': [A.ALFA(), A.CL()]}
        col = A.ok(A.api('POST', '/colegios', A.sup(), body), 'crear el colegio de demostración')
        log(f'  ✓ Colegio creado: {NOMBRE} (id {col["id"]}), {UBICACION["distrito"]} - {UBICACION["provincia"]}')
    else:
        if not col.get('activo', True):
            A.api('PATCH', f'/colegios/{col["id"]}/activar', A.sup())
        log(f'  · El colegio ya existe (id {col["id"]}); se completan los alumnos que falten.')
    cid = col['id']
    desde = [p for p in A.periodos(cid) if p['numero'] == 1][0]['fecha_inicio']
    existentes = {(a['nombres'], a['apellidos']) for a in A.alumnos(cid)}
    prog = {'CL': A.CL(), 'ALFA': A.ALFA()}
    nuevos = 0
    por_grado = {}
    for nom, ape, g, p in _alumnos_generados():
        por_grado[g] = por_grado.get(g, 0) + 1
        if (nom, ape) in existentes:
            continue
        A.crear_alumno(nom, ape, cid, g, prog[p], desde)
        nuevos += 1
    log(f'  ✓ Alumnos: {sum(por_grado.values())} en total ({nuevos} nuevos). Por grado: '
        + ', '.join(f'{g}.º {n}' for g, n in sorted(por_grado.items())))
    asg = A.asignacion([(cid, list(range(1, 7)))])
    uid = D.asegurar_cuenta('docente-demo', asg, log)
    if uid:
        s, r = A.asignar(uid, [(cid, list(range(1, 7)))])
        log(f'  {"✓" if s == 200 else "✗"} Docente Demo ({config.correo_de("docente-demo")}) asignado a los 6 grados'
            + ('' if s == 200 else f': {s} {str(r)[:200]}'))
    config.ESTADO.mkdir(exist_ok=True)
    _ESTADO.write_text(json.dumps({'id': cid, 'nombre': NOMBRE, 'alumnos': sum(por_grado.values()), 'por_grado': por_grado},
                                  ensure_ascii=False, indent=1), encoding='utf-8')
    log(f'\nPara verlo: entra a {config.BASE} con {config.correo_de("docente-demo")} (clave QA_CLAVE_CUENTAS)'
        ' o con tu Supervisor y elige el colegio en los filtros.')
    return cid
