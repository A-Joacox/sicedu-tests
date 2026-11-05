"""Navegador, evidencia y ayudas de interfaz (Playwright)."""
import html
import json
import os
import re
import shutil
import time

from playwright.sync_api import sync_playwright

from . import config
from .api import Cuenta

BASE = config.BASE
SALIDA = None  # carpeta de la corrida de resultados; la fija correr.py


# ── Evidencia ───────────────────────────────────────────────────────────────────────

def _enmascarar(texto):
    texto = re.sub(r'(contraseña temporal[^:\n]*:\s*)\S+', r'\1••••••', texto, flags=re.I)
    texto = re.sub(r'(PIN[^0-9\n]{0,20})\d{6}\b', r'\1••••••', texto)
    return texto


class Run:
    """Evidencia de un caso: capturas numeradas con su descripción y un steps.json."""

    def __init__(self, cp):
        self.cp = cp
        self.dir = os.path.join(SALIDA or str(config.RESULTADOS / 'sueltos'), cp)
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir)
        self.n = 0
        self.steps = []
        self.t0 = time.time()
        self.notas = []

    def shot(self, page, caption, full=False):
        self.n += 1
        fn = os.path.join(self.dir, f'{self.n:02d}.png')
        try:
            page.screenshot(path=fn, full_page=full)
        except Exception as e:  # una captura fallida no debe cortar el caso
            fn = None
            caption += f' [sin captura: {str(e)[:80]}]'
        caption = _enmascarar(caption)
        self.steps.append({'n': self.n, 'file': os.path.basename(fn) if fn else None, 'caption': caption})
        print(f'  [{self.cp}] {self.n:02d} {caption[:300]}', flush=True)

    def consola(self, ctx, titulo, lineas, caption=None):
        """Evidencia de pasos sin interfaz (respuestas de la API): se renderiza como una consola."""
        pg = ctx.new_page()
        cuerpo = html.escape(_enmascarar('\n'.join(str(x) for x in lineas)))
        pg.set_content(f"""<html><body style='margin:0;background:#0f172a;font-family:Consolas,monospace'>
<div style='padding:10px 16px;background:#1e293b;color:#e2e8f0;font:600 14px Segoe UI,sans-serif'>{html.escape(titulo)}</div>
<pre style='margin:0;padding:16px;color:#e2e8f0;font-size:13px;line-height:1.45;white-space:pre-wrap;word-break:break-all'>{cuerpo}</pre></body></html>""")
        pg.set_viewport_size({'width': 1100, 'height': 200})
        h = pg.evaluate('document.body.scrollHeight')
        pg.set_viewport_size({'width': 1100, 'height': max(120, min(h, 900))})
        self.shot(pg, caption or (titulo + ': ' + ' | '.join(str(x) for x in lineas))[:900])
        pg.close()

    def nota(self, texto):
        """Algo que en QA no se pudo verificar o se hizo distinto que en el plan."""
        self.notas.append(texto)
        print(f'  [{self.cp}] NOTA: {texto}', flush=True)

    def save(self, **extra):
        data = {'cp': self.cp, 'steps': self.steps, 'notas': self.notas, 'dur_s': round(time.time() - self.t0),
                'url': BASE, **extra}
        txt = _enmascarar(json.dumps(data, ensure_ascii=False, indent=1, default=str))
        open(os.path.join(self.dir, 'steps.json'), 'w', encoding='utf-8').write(txt)


_ABIERTOS = []


def cerrar_todo():
    """Cierra los navegadores que un caso dejó abiertos (por ejemplo, si falló a la mitad)."""
    while _ABIERTOS:
        n = _ABIERTOS.pop()
        try:
            n.close()
        except Exception:
            pass


class Nav:
    def __init__(self):
        cerrar_todo()
        self.pw = sync_playwright().start()
        self._cerrado = False
        _ABIERTOS.append(self)
        args = ['--disable-background-networking', '--disable-component-update', '--disable-sync',
                '--disable-features=AutofillServerCommunication,OptimizationHints']
        exe = os.environ.get('QA_CHROMIUM')
        self.b = self.pw.chromium.launch(headless=config.HEADLESS, slow_mo=config.LENTO_MS or None,
                                         args=args, **({'executable_path': exe} if exe else {}))

    def ctx(self, **kw):
        o = dict(viewport={'width': 1280, 'height': 800}, locale='es-PE', timezone_id=config.ZONA)
        o.update(kw)
        return self.b.new_context(**o)

    def close(self):
        if self._cerrado:
            return
        self._cerrado = True
        try:
            self.b.close()
        except Exception:
            pass
        finally:
            try:
                self.pw.stop()
            except Exception:
                pass
            if self in _ABIERTOS:
                _ABIERTOS.remove(self)


# ── Sesión ──────────────────────────────────────────────────────────────────────────

def ir_login(page):
    page.goto(BASE + '/login')
    page.wait_for_load_state('networkidle')


def llenar_login(page, correo, clave):
    page.fill('input[name=correo]', correo)
    page.fill('input[name=password]', clave)


def login(page, cuenta: Cuenta, esperar=True):
    """Inicia sesión en el navegador. La sesión de API de esa cuenta deja de valer."""
    ir_login(page)
    llenar_login(page, cuenta.correo, cuenta.clave)
    page.click('button[type=submit]')
    cuenta.olvidar()
    if esperar:
        page.wait_for_url(lambda u: '/login' not in u, timeout=20000)
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(800)
        tk = token_navegador(page)
        if tk:
            cuenta.usar_token(tk)


def token_navegador(page):
    try:
        return page.evaluate("sessionStorage.getItem('sicedu.token') || localStorage.getItem('sicedu.token')")
    except Exception:
        return None


def con_actividad(page, cuenta):
    """Inicia sesión y pulsa "Iniciar actividad" (la precondición de los módulos de registro)."""
    from .api import cerrar_abiertas
    try:
        cerrar_abiertas(cuenta)
    except Exception:
        pass
    login(page, cuenta)
    b = page.get_by_role('button', name='Iniciar actividad')
    if b.count():
        b.first.click()
        page.wait_for_timeout(1800)


def logout(page):
    page.locator('button[aria-haspopup=menu]').click()
    page.wait_for_timeout(300)
    page.get_by_role('menuitem', name='Cerrar sesión').click()
    page.wait_for_timeout(800)
    dlg = page.locator('[role=dialog]')
    if dlg.count() and '/login' not in page.url:
        dlg.get_by_role('button').last.click()
        page.wait_for_timeout(800)


# ── Navegación y formularios ────────────────────────────────────────────────────────

def ir(page, nombre):
    page.locator('aside nav a').filter(has_text=re.compile('^' + re.escape(nombre) + '$')).first.click()
    page.wait_for_timeout(1800)


def main_txt(page):
    return page.locator('main').inner_text()


def textos(page, *pal):
    return [l for l in main_txt(page).split('\n') if any(w.lower() in l.lower() for w in pal)][:4]


_ETIQUETA = "e=>{const l=e.closest('label')||document.querySelector('label[for=\"'+e.id+'\"]');return (l?l.innerText:(e.getAttribute('aria-label')||'')).split('\\n')[0]}"


def sel_txt(s):
    return s.evaluate("s=>s.selectedIndex>=0?s.options[s.selectedIndex].text:''")


def filtros_ui(page):
    out = []
    for s in page.locator('main select').all():
        lab = s.evaluate(_ETIQUETA)
        if lab.startswith(('Fluidez', 'Comprensión de', 'Nivel colocado', 'Proyección')):
            continue
        out.append((lab.strip(), sel_txt(s)))
    return out


def poner(page, etiqueta, valor):
    """Elige `valor` en el desplegable de `etiqueta`. Acepta un texto que empiece igual (colegios con sufijo)."""
    for x in page.locator('main select').all():
        lab = x.evaluate(_ETIQUETA)
        if lab.strip().upper() == etiqueta.upper():
            opciones = [o.strip() for o in x.locator('option').all_inner_texts()]
            elegido = valor if valor in opciones else next((o for o in opciones if o.startswith(valor)), None)
            if not elegido:
                return False
            x.select_option(label=elegido)
            page.wait_for_timeout(1500)
            return True
    return False


def opciones(page, etiqueta):
    for x in page.locator('main select').all():
        if x.evaluate(_ETIQUETA).strip().upper() == etiqueta.upper():
            return [o.strip() for o in x.locator('option').all_inner_texts()]
    return None


def fila(page, nombre):
    return page.locator('main tbody tr').filter(has_text=nombre).first


def toasts_txt(page):
    try:
        return [t.strip().replace('\n', ' ') for t in page.locator('[role=status], [role=alert], [aria-live]').all_inner_texts() if t.strip()][-4:]
    except Exception:
        return []


def dlg(page):
    return page.locator('[role=dialog]:visible').last


def cerrar_dialogos(page):
    for _ in range(3):
        if not page.locator('[role=dialog]:visible').count():
            break
        b = dlg(page).get_by_role('button', name=re.compile('Cancelar|Descartar|Cerrar'))
        (b.last if b.count() else dlg(page).get_by_role('button').last).click()
        page.wait_for_timeout(400)


def pie(page):
    m = re.search(r'Página (\d+) de (\d+)', main_txt(page))
    return m.groups() if m else None


def idb_todo(page):
    return page.evaluate("""(async()=>{const out={};for(const d of await indexedDB.databases()){const db=await new Promise(r=>{const o=indexedDB.open(d.name);o.onsuccess=()=>r(o.result)});
      for(const s of db.objectStoreNames){const tx=db.transaction(s,'readonly');const st=tx.objectStore(s);
        const ks=await new Promise(r=>{const q=st.getAllKeys();q.onsuccess=()=>r(q.result)});const vs=await new Promise(r=>{const q=st.getAll();q.onsuccess=()=>r(q.result)});
        out[d.name+'/'+s]=ks.map((k,i)=>[String(k),vs[i]]);}}return JSON.stringify(out)})()""")


def cola_idb(page):
    raw = idb_todo(page)
    return [raw[max(0, m.start() - 20): m.start() + 420] for m in re.finditer(r'"(id_operacion|idOperacion)"', raw)][:6]


def respuesta_de(page, accion, url_parte, metodo='PUT', timeout=8000):
    """Ejecuta accion() y devuelve (status, cuerpo, cuerpo_enviado) de la petición que dispara."""
    try:
        with page.expect_response(lambda r: url_parte in r.url and r.request.method == metodo, timeout=timeout) as ri:
            accion()
        r = ri.value
        page.wait_for_timeout(800)
        try:
            cuerpo = r.json()
        except Exception:
            cuerpo = r.text()[:300]
        try:
            enviado = json.loads(r.request.post_data or 'null')
        except Exception:
            enviado = None
        return r.status, cuerpo, enviado
    except Exception as e:
        return 'sin petición', str(e)[:100], None


def backend_caido(ctx, caido=True):
    """Simula que el backend no responde: las llamadas a /api fallan desde el navegador."""
    patron = re.compile(re.escape(BASE) + r'/api/.*')
    if caido:
        ctx.route(patron, lambda route: route.abort('connectionrefused'))
    else:
        ctx.unroute(patron)
