"""Fechas de prueba calculadas con el calendario real del colegio (no hay fechas fijas).

En local los casos usaban fechas fijas (el lunes 26/10, el receso del 17/10…). En QA se
calculan a partir del calendario y de las clases del colegio de la corrida.
"""
import datetime as dt

from . import api as A
from . import datos as D

UN_DIA = dt.timedelta(days=1)


def pa_actual(cid=None):
    p = A.periodo_actual(cid or D.X())
    return p if p and p['tipo'] == 'PA' else None


def pa(numero, cid=None):
    return next(p for p in A.periodos(cid or D.X()) if p['numero'] == numero)


def pa_anterior(cid=None):
    """El último PA culminado antes de hoy."""
    hoy = A.hoy()
    pas = [p for p in A.periodos(cid or D.X()) if A.fecha(p['fecha_fin']) < hoy]
    return pas[-1] if pas else None


def clases_habituales(grado, desde, hasta, cid=None):
    cid = cid or D.X()
    out = []
    for c in A.clases(cid, grado, desde, hasta):
        if c.get('tipo') == 'habitual' and not c.get('reprogramada'):
            out.append(A.fecha(c['fecha']))
    return sorted(set(out))


def ultima_clase(grado=3, cid=None, hasta=None, incluir_hoy=True):
    """La clase habitual más reciente del grado dentro del PA vigente (hasta hoy)."""
    p = pa_actual(cid)
    if not p:
        return None
    tope = hasta or (A.hoy() if incluir_hoy else A.hoy() - UN_DIA)
    fs = [f for f in clases_habituales(grado, p['fecha_inicio'], tope, cid) if f <= tope]
    return fs[-1] if fs else None


def clases_del_pa(grado, numero_pa, cid=None):
    p = pa(numero_pa, cid)
    return clases_habituales(grado, p['fecha_inicio'], min(A.fecha(p['fecha_fin']), A.hoy()), cid)


def receso_pasado(cid=None):
    hoy = A.hoy()
    prs = [p for p in A.periodos(cid or D.X(), 'PR') if A.fecha(p['fecha_inicio']) <= hoy]
    if not prs:
        return None
    pr = prs[-1]
    return A.fecha(pr['fecha_inicio'])


def no_lectivo_pasado(cid=None, en_pa=None):
    """Un día no lectivo (feriado) ya pasado dentro de un PA, que caiga de lunes a viernes."""
    cal = A.calendario(cid or D.X())
    hoy = A.hoy()
    pas = [p for p in cal['periodos'] if p['tipo'] == 'PA' and (en_pa is None or p['numero'] == en_pa)]
    for d in sorted(cal.get('dias_no_lectivos', []), key=lambda x: x['fecha_inicio'], reverse=True):
        f = A.fecha(d['fecha_inicio'])
        if f < hoy and f.isoweekday() <= 5 and any(A.fecha(p['fecha_inicio']) <= f <= A.fecha(p['fecha_fin']) for p in pas):
            return f, d['motivo']
    return None, None


def antes_del_anio(cid=None):
    """Un día de semana anterior al PA1 (fuera de todo periodo académico)."""
    f = A.fecha(pa(1, cid)['fecha_inicio']) - dt.timedelta(days=10)
    while f.isoweekday() > 5:
        f -= UN_DIA
    return f


def lectivo_sin_clase(grado=3, cid=None, desde=None, hasta=None):
    """Un día lectivo (lunes a viernes) del PA vigente, ya pasado, en que el grado no tiene clase."""
    cid = cid or D.X()
    p = pa_actual(cid)
    ini = A.fecha(desde or p['fecha_inicio'])
    fin = A.fecha(hasta or A.hoy())
    clases = set(clases_habituales(grado, ini, fin, cid))
    f = fin
    while f >= ini:
        if f.isoweekday() <= 5 and f not in clases and A.es_lectivo(cid, f):
            return f
        f -= UN_DIA
    return None


def lectivo_sin_clase_en(grado, numero_pa, cid=None):
    p = pa(numero_pa, cid)
    return lectivo_sin_clase(grado, cid, p['fecha_inicio'], min(A.fecha(p['fecha_fin']), A.hoy()))


def mes_anterior(d=None):
    d = d or A.hoy()
    return (d.replace(day=1) - UN_DIA).month


def legible(d):
    return d.strftime('%d/%m/%Y') if d else '—'


MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


def mes_nombre(m):
    return MESES[(m.month if hasattr(m, 'month') else m) - 1]


def semana_de(d, grado=3, cid=None, programa=None):
    """(id_semana, mes, fecha_inicio, fecha_fin) de la semana que contiene la fecha d."""
    cid = cid or D.X()
    d = A.fecha(d)
    for m in [d.month, (d - dt.timedelta(days=7)).month, (d + dt.timedelta(days=7)).month]:
        s, r = A.api('GET', '/semanas?' + A.q(id_anio_escolar=A.anio(), mes=m, id_colegio=cid, id_grado=A.id_grado(grado),
                                              id_seccion=A.seccion(cid, grado), id_programa=programa), A.sup())
        if s != 200:
            continue
        for w in r:
            if A.fecha(w['fecha_inicio']) <= d <= A.fecha(w['fecha_fin']) + dt.timedelta(days=2):
                return w['id_semana'], m, A.fecha(w['fecha_inicio']), A.fecha(w['fecha_fin'])
    return None, d.month, None, None


def calendario_particular_en_pr(cid, en_pr=True):
    """Periodos de un calendario particular en que hoy cae en el PR2 (en_pr=True) o en que el PR2
    terminó ayer (en_pr=False). Así el PA2 queda recién culminado para probar la regularización."""
    hoy = A.hoy()
    gen = {(p['tipo'], p['numero']): (A.fecha(p['fecha_inicio']), A.fecha(p['fecha_fin'])) for p in A.calendario(cid)['periodos']}
    pa2_ini = gen[('PA', 2)][0]
    pa2_fin = hoy - dt.timedelta(days=13)
    pr2_fin = hoy + dt.timedelta(days=2) if en_pr else hoy - dt.timedelta(days=1)
    pa4_fin = gen[('PA', 4)][1]
    resto = (pa4_fin - pr2_fin).days
    pa3_fin = pr2_fin + dt.timedelta(days=max(5, resto // 2))
    per = [('PA', 1, *gen[('PA', 1)]), ('PR', 1, *gen[('PR', 1)]), ('PA', 2, pa2_ini, pa2_fin), ('PR', 2, pa2_fin + UN_DIA, pr2_fin),
           ('PA', 3, pr2_fin + UN_DIA, pa3_fin), ('PR', 3, pa3_fin + UN_DIA, pa3_fin + 2 * UN_DIA),
           ('PA', 4, pa3_fin + 3 * UN_DIA, pa4_fin), ('PR', 4, *gen[('PR', 4)])]
    return [{'tipo': t, 'numero': n, 'fecha_inicio': a.isoformat(), 'fecha_fin': b.isoformat()} for t, n, a, b in per]


def poner_calendario_en_pr(cid, en_pr=True, existente=None):
    """Crea (o actualiza) el calendario particular del colegio. Devuelve (HTTP, respuesta)."""
    body = {'periodos': calendario_particular_en_pr(cid, en_pr), 'dias_no_lectivos': []}
    if existente:
        return A.api('PUT', f'/calendarios/{existente["id_calendario"]}', A.sup(), {'version': existente['version'], **body})
    return A.api('POST', '/calendarios/particulares', A.sup(), {'id_colegio': cid, 'id_anio_escolar': A.anio(), **body})


DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']


def dia_semana(d):
    return DIAS[d.weekday()] if d else '—'
