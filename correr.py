"""Corre los casos de prueba automatizados contra QA y deja la evidencia en resultados/.

Ejemplos:
  correr.bat --listar                      lista los 139 casos y cuáles están automatizados
  correr.bat --modulo Asistencias          un módulo (nombre o sigla: ASI, LEC, RUB, RV…)
  correr.bat --caso CP-ASI-04 CP-RUB-01    casos sueltos
  correr.bat --rechazados                  los casos rechazados en la ronda 6 que estén automatizados
  correr.bat --todo                        todos los automatizados
  correr.bat --ver ...                     muestra el navegador mientras corre
"""
import argparse
import csv
import datetime as dt
import importlib
import json
import os
import pkgutil
import shutil
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config  # noqa: E402


def cargar_casos():
    import casos
    for m in pkgutil.iter_modules(casos.__path__):
        importlib.import_module(f'casos.{m.name}')


def listar(cat):
    filas = []
    for cp, mod, titulo, v in cat.CASOS_PLAN:
        e = cat.estado_de(cp)
        nota = cat.REGISTRO.get(cp, {}).get('notas') or cat.SOLO_LOCAL.get(cp, '')
        filas.append((cp, cat.MODULOS[mod], titulo, v, e, nota))
    with open(config.RAIZ / 'catalogo.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Caso', 'Módulo', 'Título', 'Ronda 6', 'En QA', 'Notas'])
        w.writerows(filas)
    cuenta = {}
    for f in filas:
        cuenta[f[4]] = cuenta.get(f[4], 0) + 1
    for cp, mod, titulo, v, e, nota in filas:
        print(f'{cp:<10} {mod:<24} {e:<11} {v:<27} {titulo[:60]}')
    print('\nResumen:', ', '.join(f'{k}: {n}' for k, n in sorted(cuenta.items())))
    print('Se guardó catalogo.csv (ábrelo con Excel).')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--modulo', nargs='*', default=[])
    ap.add_argument('--caso', nargs='*', default=[])
    ap.add_argument('--todo', action='store_true')
    ap.add_argument('--rechazados', action='store_true')
    ap.add_argument('--listar', action='store_true')
    ap.add_argument('--ver', action='store_true', help='mostrar el navegador')
    a = ap.parse_args()
    if a.ver:
        os.environ['QA_HEADLESS'] = 'false'
        config.HEADLESS = False

    from lib import catalogo as cat
    cargar_casos()
    if a.listar or not (a.modulo or a.caso or a.todo or a.rechazados):
        listar(cat)
        return

    sel = []
    for cp, mod, titulo, v in cat.CASOS_PLAN:
        quiere = a.todo or cp in [c.upper() for c in a.caso] or mod in [cat.modulo_desde_texto(m) for m in a.modulo] \
            or (a.rechazados and v == 'Rechazado')
        if quiere:
            sel.append(cp)
    corre = [cp for cp in sel if cp in cat.REGISTRO]
    fuera = [cp for cp in sel if cp not in cat.REGISTRO]
    if fuera:
        print('Sin automatizar en QA (se omiten):', ', '.join(f'{cp} ({cat.estado_de(cp)})' for cp in fuera))
    if not corre:
        print('No hay casos automatizados en la selección.')
        return

    from lib import api as A
    from lib import datos as D
    from lib import ui
    try:
        A.sup().login()
    except Exception as ex:
        sys.exit(f'No se pudo entrar como la Supervisora E2E en {config.BASE}: {ex}')
    marca = dt.datetime.now().strftime('%Y%m%d-%H%M')
    salida = config.RESULTADOS / marca
    salida.mkdir(parents=True, exist_ok=True)
    ui.SALIDA = str(salida)
    print(f'URL: {config.BASE}   resultados: {salida}')
    resumen = []
    for i, cp in enumerate(corre, 1):
        inf = cat.info(cp)
        print(f'\n=== [{i}/{len(corre)}] {cp} · {inf["nombre_modulo"]} · {inf["titulo"]}', flush=True)
        t0 = time.time()
        try:
            e = D.preparar_caso(cp)
            print(f'  datos nuevos: {", ".join(c["nombre"] for c in e["colegios"].values())} ({round(time.time() - t0)} s)', flush=True)
            cat.REGISTRO[cp]['fn']()
            estado, error = 'ejecutado', None
        except KeyboardInterrupt:
            print('Interrumpido por el usuario.')
            break
        except Exception as ex:
            estado, error = 'error', f'{type(ex).__name__}: {ex}'
            traceback.print_exc()
            os.makedirs(salida / cp, exist_ok=True)
            (salida / cp / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        finally:
            ui.cerrar_todo()
            D.cerrar_caso()
        resumen.append({'cp': cp, 'modulo': inf['nombre_modulo'], 'titulo': inf['titulo'], 'ronda6': inf['ronda6'],
                        'modo': cat.REGISTRO[cp]['modo'], 'estado': estado, 'error': error, 'seg': round(time.time() - t0)})
        print(f'--- {cp}: {estado}{" · " + error if error else ""}', flush=True)
    info = {'url': config.BASE, 'inicio': marca, 'fin': dt.datetime.now().isoformat(),
            'casos': resumen}
    (salida / 'resumen.json').write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
    lineas = [f'# Corrida {marca} contra {config.BASE}', '', '| Caso | Módulo | Estado | Notas |', '| --- | --- | --- | --- |']
    for r in resumen:
        lineas.append(f'| {r["cp"]} | {r["modulo"]} | {r["estado"]} | {r["error"] or ""} |')
    (salida / 'resumen.md').write_text('\n'.join(lineas), encoding='utf-8')
    zipf = shutil.make_archive(str(salida), 'zip', str(salida))
    print(f'\nListo. {sum(r["estado"] == "ejecutado" for r in resumen)} ejecutados, {sum(r["estado"] == "error" for r in resumen)} con error.')
    print(f'Envía este archivo para el análisis: {zipf}')


if __name__ == '__main__':
    main()
