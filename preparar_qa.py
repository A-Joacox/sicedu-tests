"""Prepara QA para una corrida de la suite.

  preparar.bat            crea los datos de una corrida nueva (colegios, alumnos, permisos),
                          crea las cuentas que falten y reasigna a los Docentes de la suite.
  preparar.bat --estado   muestra la corrida vigente y las cuentas.
  preparar.bat --demo     crea (o completa) el colegio de demostración "I.E. Demo QA Huascarán":
                          6 grados con 30 a 40 alumnos cada uno y la cuenta Docente Demo. Queda activo.

La primera vez se crean 7 cuentas con alias de tu correo (joaquin.mercado+sicedu-…). Por cada
una llega un correo de bienvenida con una contraseña temporal: la suite se detiene y te pide
pegarla. Después las cuentas quedan listas con la clave QA_CLAVE_CUENTAS del .env.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import api as A  # noqa: E402
from lib import config  # noqa: E402
from lib import datos as D  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--estado', action='store_true')
    ap.add_argument('--demo', action='store_true')
    a = ap.parse_args()
    config.exigir_credenciales()
    print(f'QA: {config.BASE}')
    s, r = A.api('GET', '/')
    if s != 200:
        sys.exit(f'La API no responde en {config.API}: {s} {r}')
    A.sup().login()
    print(f'Supervisora E2E: sesión iniciada ({config.SUP_CORREO}).')
    if a.demo:
        from lib import demo
        print(f'\nColegio de demostración: {demo.NOMBRE}')
        demo.crear_demo()
        return
    if a.estado:
        try:
            e = D.estado()
            print('Corrida vigente:', e['sufijo'], {k: v['nombre'] for k, v in e['colegios'].items()}, 'alumnos:', len(e['alumnos']))
        except SystemExit as ex:
            print(ex)
        for et in list(D.CUENTAS) + list(D.CUENTAS_EXTRA):
            u = A.usuario_por_correo(config.correo_de(et))
            print(f'  {et:<13} {config.correo_de(et):<48} {"no existe" if not u else ("falta primer ingreso" if u.get("debe_cambiar_contrasena") else "lista")}')
        return

    print('\n1) Colegios temporales para crear las cuentas Docente')
    D.crear_corrida()
    print('\n2) Cuentas de la suite')
    plan = {'docente-a': [(D.X(), [3])], 'rv-uno': [(D.X(), [1, 2])], 'docente-b': [(D.X(), [4])],
            'sin-grupos': [(D.Y(), [6])], 'retro': [(D.Y(), [5])]}
    faltan = []
    for et, (rol, *_ ) in D.CUENTAS.items():
        asg = A.asignacion(plan[et]) if rol == 'Docente' else None
        if not D.asegurar_cuenta(et, asg):
            faltan.append(et)
    print('\n3) Asignaciones de los Docentes a los colegios de la corrida')
    D.asignar_docentes()
    # Los colegios de la preparación solo sirven para crear las cuentas Docente (exigen una asignación).
    # Cada caso crea los suyos, así que estos se inactivan para que no aparezcan en los filtros.
    D.cerrar_caso()
    print('\nListo.' if not faltan else f'\nListo, pero faltan cuentas: {", ".join(faltan)}. Vuelve a ejecutar preparar.bat cuando tengas sus contraseñas temporales.')
    print('Ahora puedes correr la suite, por ejemplo: correr.bat --modulo Asistencias')


if __name__ == '__main__':
    main()
