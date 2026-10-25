"""共用：无头 Chromium 打开页面，MathJax 从本地 npm 包提供，等笔记层就绪。"""
import os
from playwright.sync_api import sync_playwright
MJ = os.environ.get('NIPC_MATHJAX_DIR') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mj', 'package')

def route_mathjax(page):
    """MathJax 从本地 npm 包提供（机器上连不了 CDN 时用；没有本地包就照常联网）。"""
    if not os.path.isdir(MJ):
        page.route('**/api.github.com/**', lambda r: r.abort()); return
    def handle(route):
        u = route.request.url
        i = u.find('/mathjax@3.2.2/')
        path = os.path.join(MJ, u[i + len('/mathjax@3.2.2/'):].split('?')[0])
        if os.path.exists(path):
            route.fulfill(path=path, content_type='application/javascript')
        else:
            route.abort()
    page.route('**/cdn.jsdelivr.net/**', handle)
    page.route('**/api.github.com/**', lambda r: r.abort())

def open_page(pw, html_path, width=1180, open_details=True):
    b = pw.chromium.launch()
    pg = b.new_page(viewport={'width': width, 'height': 1000})
    route_mathjax(pg)
    pg.goto('file://' + os.path.abspath(html_path))
    pg.wait_for_function('window.__nipcNotes && window.MathJax && MathJax.startup && MathJax.startup.document '
                         '&& [...MathJax.startup.document.math].length > 0', timeout=120000)
    pg.wait_for_timeout(500)
    if open_details:
        pg.evaluate("document.querySelectorAll('article details').forEach(d => d.open = true)")
    pg.evaluate("document.fonts.ready")
    pg.wait_for_timeout(800)
    pg.evaluate("__nipcNotes.render()")
    return b, pg
