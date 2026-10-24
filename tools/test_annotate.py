"""手写标注层的浏览器测试（playwright + chromium）：iPad 上写、导出，Mac 上导入，检查笔迹是否落在同样的内容上。

检查项（每项打印 PASS / FAIL 和实测数字，全部通过退出码 0）：
  a) 1180×820（iPad 横屏）视口：手指滑动只滚屏不出笔画；用模拟 Apple Pencil（CDP pointerType=pen，带压感）
     在 week3_4.html 的一张图和一段文字上各画一笔；橡皮擦 + 撤销；导出 JSON。
  b) 1440×900（Mac）视口导入该 JSON（替换），两笔包围盒相对目标（图 / 起笔那个字）的坐标与 iPad 上相差 ≤ 2px；
     再「合并」导入同一文件不重复；820×1180（iPad 竖屏，正文被 zoom 缩小）同样 ≤ 2px；打印 media 下同样 ≤ 2px。
  c) week2.html：折叠框后面的一笔在展开 / 收起后仍对齐；折叠框里的一笔收起时隐藏、展开后对齐。
  d) 标注关闭时：点击落在视频上（能解码时还检查真的在播放）；点击折叠框标题能展开。
  e) 内容改动：在两个目标之前插入一个新段落和一张图，并改掉起笔段落开头几个字，导入后两笔仍落在原来的图 / 字上（≤ 2px）。
  f) 删掉目标图、整段改写目标段落：两笔标灰显示（不丢），工具栏提示「有 2 笔对应的内容已变」。
截图与导出的 JSON 写到 --out（默认 /nas/xiaoyingwang/Neural-IPC/outputs/web_annotate_test/，每次原路覆盖）。

用法：
    /bin/python tools/test_annotate.py [--out DIR]
页面用仓库根目录下已生成的 week3_4.html、week2.html（先跑 tools/build_site.py --execute）。不改任何仓库文件。
"""
import argparse
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = pathlib.Path("/nas/xiaoyingwang/Neural-IPC/outputs/web_annotate_test")
TOL = 2.0   # 允许的偏差（未缩放 CSS px）

# 页面内测量：某一笔的包围盒相对目标（图按 src、字按一段唯一的文字 needle 的第一个字）的坐标，单位未缩放 CSS px
MEASURE_JS = """(spec) => {
  const N = window.__nipcNotes, f = N.frame();
  const article = document.querySelector('article');
  let T = null;
  if (spec.kind === 'img') {
    const img = [...article.querySelectorAll('img')].find(i => i.getAttribute('src').split('/').pop() === spec.src);
    T = img && img.getBoundingClientRect();
  } else {
    const w = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const i = n.data.indexOf(spec.needle);
      if (i >= 0) { const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1); T = r.getClientRects()[0]; break; }
    }
  }
  const sel = spec.print ? `svg.annot-print path[data-id="${spec.id}"]` : `#annot-layer path[data-id="${spec.id}"]`;
  const path = document.querySelector(sel);
  if (!T) return {error: 'target not found'};
  if (!path) return {error: 'path not found'};
  const pr = path.getBoundingClientRect(), shown = getComputedStyle(path).display !== 'none' && pr.width > 0;
  return {shown, cls: path.getAttribute('class'), s: f.s,
          x: (pr.left - T.left) / f.s, y: (pr.top - T.top) / f.s, w: pr.width / f.s, h: pr.height / f.s,
          targetTop: (T.top - main().top) / f.s};
  function main() { return document.querySelector('main').getBoundingClientRect(); }
}"""

# 选测试目标：第一张配图；一段没有公式、第一个文本节点够长的正文段落（取第 25 个字起的 16 个字作 needle）
PICK_JS = """() => {
  const article = document.querySelector('article');
  const img = article.querySelector('figure img');
  const ps = [...article.querySelectorAll('section > p')].filter(p =>
      !p.querySelector('mjx-container') && p.firstChild && p.firstChild.nodeType === 3 && p.firstChild.data.trim().length > 80);
  const p = ps[Math.min(4, ps.length - 1)];
  const t = p.firstChild.data, k = 25;
  return {src: img.getAttribute('src').split('/').pop(), needle: t.slice(k, k + 16)};
}"""

# 截获导出：a[download].click() 时读出 Blob 内容（不真的下载到磁盘）
CATCH_DOWNLOAD_JS = """() => {
  window.__dl = null;
  const orig = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (!this.download) return orig.call(this);
    const name = this.download;
    fetch(this.href).then(r => r.text()).then(text => { window.__dl = {name, text}; });
  };
}"""


class Report:
    """收集每项检查的结果并打印。"""

    def __init__(self):
        self.fails = 0

    def check(self, name, ok, detail):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}：{detail}", flush=True)
        self.fails += 0 if ok else 1


def open_page(ctx, rel):
    page = ctx.new_page()
    page.on("pageerror", lambda err: print(f"      [页面 JS 报错] {rel}: {err}", flush=True))
    page.goto((ROOT / rel).as_uri())
    page.wait_for_function("window.__nipcNotes")
    return page


def toolbar_pen(page, color="red"):
    """展开工具栏、选笔（会自动打开标注）。"""
    if page.is_visible("#annot-fab"):
        page.click("#annot-fab")
    page.click(f'[data-tool="pen"][data-color="{color}"]')


def set_annotation(page, on):
    if page.is_visible("#annot-fab"):
        page.click("#annot-fab")
    if (page.get_attribute("#annot-toggle", "aria-pressed") == "true") != on:
        page.click("#annot-toggle")


def pen_stroke(cdp, pts, forces):
    """用 CDP 发一笔 Apple Pencil 输入（pointerType=pen，force 即压感）。"""
    base = {"pointerType": "pen", "button": "left"}
    (x, y), f = pts[0], forces[0]
    cdp.send("Input.dispatchMouseEvent", {**base, "type": "mousePressed", "x": x, "y": y, "buttons": 1, "clickCount": 1, "force": f})
    for (x, y), f in zip(pts[1:], forces[1:]):
        cdp.send("Input.dispatchMouseEvent", {**base, "type": "mouseMoved", "x": x, "y": y, "buttons": 1, "force": f})
    cdp.send("Input.dispatchMouseEvent", {**base, "type": "mouseReleased", "x": x, "y": y, "buttons": 0, "force": 0})


def scroll_to(page, js_target):
    page.evaluate(f"() => ({js_target}).scrollIntoView({{block: 'center', behavior: 'instant'}})")
    page.wait_for_timeout(300)


def img_js(src):
    return f"[...document.querySelectorAll('article img')].find(i => i.getAttribute('src').endsWith('/{src}'))"


def char_rect(page, needle):
    return page.evaluate("""(needle) => {
      const w = document.createTreeWalker(document.querySelector('article'), NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        const i = n.data.indexOf(needle);
        if (i >= 0) { const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1);
                      const q = r.getClientRects()[0]; return {x: q.left, y: q.top, w: q.width, h: q.height}; }
      }
      return null;
    }""", needle)


def needle_parent_js(needle):
    return ("(() => { const w = document.createTreeWalker(document.querySelector('article'), NodeFilter.SHOW_TEXT);"
            f" for (let n = w.nextNode(); n; n = w.nextNode()) if (n.data.includes({json.dumps(needle)})) return n.parentElement; }})()")


def zigzag(x, y, n=12, dx=10, dy=14):
    return [(x + i * dx, y + (dy if i % 2 else 0)) for i in range(n)]


def strokes(page):
    return page.evaluate("window.__nipcNotes.strokes()")


def close_enough(a, b):
    return all(abs(a[k] - b[k]) <= TOL for k in ("x", "y", "w", "h"))


def fmt(m):
    return "{" + ", ".join(f"{k}={m[k]:.2f}" for k in ("x", "y", "w", "h")) + "}"


def compare(rep, name, ref, got):
    if "error" in got:
        rep.check(name, False, got["error"])
        return
    diff = max(abs(ref[k] - got[k]) for k in ("x", "y", "w", "h"))
    rep.check(name, got["shown"] and close_enough(ref, got),
              f"参考 {fmt(ref)} 实测 {fmt(got)} 最大差 {diff:.2f}px 显示={got['shown']}")


def import_notes(page, text, mode="replace"):
    if page.is_visible("#annot-fab"):
        page.click("#annot-fab")
    page.set_input_files("#annot-file", files=[{"name": "notes.json", "mimeType": "application/json",
                                                "buffer": text.encode()}])
    page.click(f'[data-import="{mode}"]')
    page.wait_for_timeout(400)


def shot_around(page, out, name, js_target):
    scroll_to(page, js_target)
    page.screenshot(path=str(out / name))


def test_ipad_draw(browser, rep, out):
    """a) iPad 横屏：手指滚屏、两笔、橡皮擦 + 撤销、导出。返回 (导出文本, 目标, 两笔 id, 参考测量)。"""
    ctx = browser.new_context(viewport={"width": 1180, "height": 820}, has_touch=True)
    page = open_page(ctx, "week3_4.html")
    cdp = ctx.new_cdp_session(page)
    tgt = page.evaluate(PICK_JS)
    toolbar_pen(page)
    lay = page.evaluate("({w: document.querySelector('main').offsetWidth, cls: document.documentElement.className})")
    rep.check("a0 iPad 横屏版式", lay["w"] == 920 and "annot-noaside" in lay["cls"], f"main 宽 {lay['w']}px，html class={lay['cls']}")

    y0 = page.evaluate("scrollY")
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": 600, "y": 600}]})
    for k in range(1, 9):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": 600, "y": 600 - 30 * k}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    page.wait_for_timeout(200)
    y1 = page.evaluate("scrollY")
    rep.check("a1 手指滑动滚屏、不出笔画", y1 - y0 > 200 and len(strokes(page)) == 0, f"scrollY {y0} → {y1}，笔画数 {len(strokes(page))}")

    scroll_to(page, img_js(tgt["src"]))
    r = page.evaluate(f"(() => {{ const q = ({img_js(tgt['src'])}).getBoundingClientRect(); return {{x: q.left, y: q.top, w: q.width, h: q.height}}; }})()")
    pts = zigzag(r["x"] + 0.3 * r["w"], r["y"] + 0.4 * r["h"])
    pen_stroke(cdp, pts, [0.2 + 0.06 * i for i in range(len(pts))])
    scroll_to(page, needle_parent_js(tgt["needle"]))
    c = char_rect(page, tgt["needle"])
    sx, sy = c["x"] + c["w"] / 2, c["y"] + c["h"] / 2
    pts = [(sx + 8 * i, sy + (6 if i else 0)) for i in range(16)]
    pen_stroke(cdp, pts, [0.9 - 0.04 * i for i in range(len(pts))])
    page.wait_for_timeout(300)
    st = strokes(page)
    kinds = [s["anchor"]["type"] for s in st]
    rep.check("a2 两笔已存、锚点类型", kinds == ["media", "text"],
              f"锚点 {kinds}；文字锚点 exact={st[1]['anchor'].get('exact')!r}" if len(st) == 2
              else f"笔画数 {len(st)}，锚点 {[s['anchor'] for s in st]}，点数 {[len(s['pts']) for s in st]}")
    if len(st) != 2:
        raise SystemExit("a2 没画出两笔，后面的检查无法进行")
    pres = sorted({p[2] for p in st[0]["pts"]})
    widths = page.evaluate(f"""() => [...document.querySelectorAll('#annot-layer path')].map(p => p.getBBox().height)""")
    rep.check("a3 压感进了笔画", len(pres) > 3 and min(pres) >= 0, f"第一笔压感取值 {pres[:3]}…{pres[-2:]}（共 {len(pres)} 种）")
    ids = [s["id"] for s in st]
    ref = [page.evaluate(MEASURE_JS, {"id": ids[0], "kind": "img", "src": tgt["src"]}),
           page.evaluate(MEASURE_JS, {"id": ids[1], "kind": "char", "needle": tgt["needle"]})]
    print(f"      iPad 参考：图 {fmt(ref[0])}，字 {fmt(ref[1])}（path 高度 {widths}）")
    stored = page.evaluate("(k) => localStorage.getItem(k) !== null", "nipc-notes:" + page.evaluate("location.pathname"))
    rep.check("a4 自动存进本机 localStorage", stored, f"键存在={stored}")

    page.click('[data-tool="eraser"]')
    pen_stroke(cdp, [(sx + 40, sy - 10 + 3 * k) for k in range(10)], [0.5] * 10)
    page.wait_for_timeout(200)
    n_erased = len(strokes(page))
    page.click("#annot-undo")
    page.wait_for_timeout(200)
    rep.check("a5 橡皮擦按笔擦、撤销恢复", n_erased == 1 and len(strokes(page)) == 2, f"擦后 {n_erased} 笔，撤销后 {len(strokes(page))} 笔")

    shot_around(page, out, "a_ipad_text.png", needle_parent_js(tgt["needle"]))
    shot_around(page, out, "a_ipad_image.png", img_js(tgt["src"]))
    page.evaluate(CATCH_DOWNLOAD_JS)
    page.click("#annot-export")
    page.wait_for_function("window.__dl")
    dl = page.evaluate("window.__dl")
    data = json.loads(dl["text"])
    (out / dl["name"]).write_text(dl["text"], encoding="utf-8")
    rep.check("a6 导出", dl["name"].startswith("week3_4_notes_") and data["version"] == 1 and data["colWidth"] == 920
              and len(data["strokes"]) == 2, f"文件名 {dl['name']}，page={data['page']}，{len(data['strokes'])} 笔，{len(dl['text'])} 字节")
    ctx.close()
    return dl["text"], tgt, ids, ref


def test_mac_import(browser, rep, out, text, tgt, ids, ref):
    """b) Mac 宽屏导入、合并不重复、打印 media；iPad 竖屏（zoom）导入。"""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = open_page(ctx, "week3_4.html")
    import_notes(page, text)
    lay = page.evaluate("({w: document.querySelector('main').offsetWidth, aside: getComputedStyle(document.querySelector('aside')).display})")
    rep.check("b0 Mac 版式", lay["w"] == 920 and lay["aside"] != "none", f"main 宽 {lay['w']}px，目录 display={lay['aside']}")
    specs = [{"id": ids[0], "kind": "img", "src": tgt["src"]}, {"id": ids[1], "kind": "char", "needle": tgt["needle"]}]
    for k, (spec, name) in enumerate(zip(specs, ["图", "字"])):
        compare(rep, f"b1 Mac 1440 导入后{name}上的笔对齐", ref[k], page.evaluate(MEASURE_JS, spec))
    shot_around(page, out, "b_mac_text.png", needle_parent_js(tgt["needle"]))
    shot_around(page, out, "b_mac_image.png", img_js(tgt["src"]))
    import_notes(page, text, "merge")
    rep.check("b2 合并同一文件不重复", len(strokes(page)) == 2, f"合并后 {len(strokes(page))} 笔")

    page.emulate_media(media="print")
    page.wait_for_timeout(400)
    for k, (spec, name) in enumerate(zip(specs, ["图", "字"])):
        compare(rep, f"b3 打印 media 下{name}上的笔对齐", ref[k], page.evaluate(MEASURE_JS, {**spec, "print": True}))
    scroll_to(page, needle_parent_js(tgt["needle"]))
    page.screenshot(path=str(out / "b_print_text.png"))
    page.emulate_media(media="screen")
    page.wait_for_timeout(300)
    left = page.evaluate("document.querySelectorAll('svg.annot-print').length")
    rep.check("b4 退出打印后清理", left == 0, f"残留打印 svg {left} 个")
    ctx.close()

    ctx = browser.new_context(viewport={"width": 820, "height": 1180}, has_touch=True)
    page = open_page(ctx, "week3_4.html")
    import_notes(page, text)
    z = page.evaluate("document.querySelector('main').style.zoom")
    for k, (spec, name) in enumerate(zip(specs, ["图", "字"])):
        compare(rep, f"b5 iPad 竖屏 820（zoom={z}）{name}上的笔对齐", ref[k], page.evaluate(MEASURE_JS, spec))
    shot_around(page, out, "b_ipad_portrait_text.png", needle_parent_js(tgt["needle"]))
    ctx.close()


def test_week2_details(browser, rep, out):
    """c) 折叠框展开 / 收起后对齐；d) 关标注时折叠框可点。"""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = open_page(ctx, "week2.html")
    cdp = ctx.new_cdp_session(page)
    pick = page.evaluate("""() => {
      const ds = [...document.querySelectorAll('article details')].filter(d => !d.open);
      for (const d of ds) {
        let n = d.nextElementSibling;
        while (n && !(n.tagName === 'P' && n.firstChild && n.firstChild.nodeType === 3 && n.firstChild.data.trim().length > 40)) n = n.nextElementSibling;
        const inner = [...d.querySelectorAll('p')].find(p => p.firstChild && p.firstChild.nodeType === 3 && p.firstChild.data.trim().length > 40);
        if (n && inner) {
          d.dataset.testPick = '1';
          const t = n.firstChild.data.trim(), u = inner.firstChild.data.trim();
          return {after: t.slice(10, 26), inside: u.slice(10, 26)};
        }
      }
      return null;
    }""")
    if not pick:
        rep.check("c0 week2 找到折叠框", False, "没有合适的折叠框")
        return
    det = "document.querySelector('details[data-test-pick]')"
    toolbar_pen(page, "blue")
    scroll_to(page, needle_parent_js(pick["after"]))
    c = char_rect(page, pick["after"])
    pen_stroke(cdp, [(c["x"] + c["w"] / 2 + 7 * i, c["y"] + c["h"] / 2) for i in range(12)], [0.5] * 12)
    page.wait_for_timeout(200)
    sid = strokes(page)[-1]["id"]
    spec = {"id": sid, "kind": "char", "needle": pick["after"]}
    ref = page.evaluate(MEASURE_JS, spec)

    set_annotation(page, False)
    page.evaluate(f"{det}.scrollIntoView({{block: 'center', behavior: 'instant'}})")
    page.click("details[data-test-pick] > summary")
    page.wait_for_timeout(400)
    opened = page.evaluate(f"{det}.open")
    rep.check("d1 关标注时点折叠框标题能展开", opened, f"open={opened}")
    got = page.evaluate(MEASURE_JS, spec)
    compare(rep, "c1 折叠框展开后，框后面的笔仍对齐", ref, got)
    rep.check("c2 框后面的笔跟着内容下移", got.get("targetTop", 0) - ref["targetTop"] > 20,
              f"目标字在卡片内 y {ref['targetTop']:.1f} → {got.get('targetTop', 0):.1f}")

    toolbar_pen(page, "black")
    scroll_to(page, needle_parent_js(pick["inside"]))
    c = char_rect(page, pick["inside"])
    pen_stroke(cdp, [(c["x"] + c["w"] / 2 + 7 * i, c["y"] + c["h"] / 2 + 3) for i in range(12)], [0.6] * 12)
    page.wait_for_timeout(200)
    iid = strokes(page)[-1]["id"]
    ispec = {"id": iid, "kind": "char", "needle": pick["inside"]}
    iref = page.evaluate(MEASURE_JS, ispec)
    page.screenshot(path=str(out / "c_week2_details_open.png"))
    set_annotation(page, False)
    page.click("details[data-test-pick] > summary")
    page.wait_for_timeout(400)
    hidden = page.evaluate(f"""() => getComputedStyle(document.querySelector('#annot-layer path[data-id="{iid}"]')).display""")
    rep.check("c3 收起后框里的笔隐藏", hidden == "none", f"display={hidden}")
    compare(rep, "c4 收起后框后面的笔仍对齐", ref, page.evaluate(MEASURE_JS, spec))
    page.click("details[data-test-pick] > summary")
    page.wait_for_timeout(400)
    compare(rep, "c5 再展开后框里的笔对齐", iref, page.evaluate(MEASURE_JS, ispec))
    ctx.close()


def test_video_click(browser, rep):
    """d) 关标注时视频照常可点。"""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = open_page(ctx, "week3_4.html")
    toolbar_pen(page)
    set_annotation(page, False)
    page.evaluate("""() => { const v = document.querySelector('article video'); window.__vclick = false;
                    v.addEventListener('click', () => { window.__vclick = true; }); v.scrollIntoView({block: 'center', behavior: 'instant'}); }""")
    page.wait_for_timeout(300)
    box = page.evaluate("(() => { const r = document.querySelector('article video').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()")
    top = page.evaluate("([x, y]) => document.elementFromPoint(x, y).tagName", [box["x"], box["y"]])
    can = page.evaluate("document.querySelector('article video').canPlayType('video/mp4; codecs=\"avc1.42E01E\"')")
    page.mouse.click(box["x"], box["y"])
    page.wait_for_timeout(800)
    clicked = page.evaluate("window.__vclick")
    paused = page.evaluate("document.querySelector('article video').paused")
    rep.check("d2 关标注时点击落在视频上", top == "VIDEO" and clicked, f"该点最上层元素 {top}，video 收到 click={clicked}")
    if can:
        rep.check("d3 视频开始播放", not paused, f"canPlayType={can!r}，paused={paused}")
    else:
        print(f"[SKIP] d3 视频开始播放：本测试浏览器不能解码 H.264（canPlayType 为空），只核点击是否到达视频；paused={paused}")
    ctx.close()


def test_drift(browser, rep, out, text, tgt, ids, ref):
    """e) 目标之前插段落和图、改起笔段落开头几个字后导入；f) 删掉目标后导入，笔标灰不丢。"""
    specs = [{"id": ids[0], "kind": "img", "src": tgt["src"]}, {"id": ids[1], "kind": "char", "needle": tgt["needle"]}]
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = open_page(ctx, "week3_4.html")
    tops0 = page.evaluate(   # 改动前两个目标在卡片内的 y，用来证明改动确实把它们推下去了
"""([src, needle]) => {
      const m = document.querySelector('main').getBoundingClientRect();
      const img = [...document.querySelectorAll('article img')].find(i => i.getAttribute('src').endsWith('/' + src));
      const w = document.createTreeWalker(document.querySelector('article'), NodeFilter.SHOW_TEXT);
      let t = null; for (let n = w.nextNode(); n; n = w.nextNode()) if (n.data.includes(needle)) { t = n.parentElement; break; }
      return [img.getBoundingClientRect().top - m.top, t.getBoundingClientRect().top - m.top];
    }""", [tgt["src"], tgt["needle"]])
    edit = page.evaluate("""([src, needle]) => {
      const article = document.querySelector('article');
      const img = [...article.querySelectorAll('img')].find(i => i.getAttribute('src').endsWith('/' + src));
      const w = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
      let tn = null; for (let n = w.nextNode(); n; n = w.nextNode()) if (n.data.includes(needle)) { tn = n; break; }
      const para = tn.parentElement.closest('p');
      const other = [...article.querySelectorAll('figure img')].find(i => !i.getAttribute('src').endsWith('/' + src));
      const first = (img.compareDocumentPosition(para) & Node.DOCUMENT_POSITION_FOLLOWING) ? img.closest('figure') : para;
      const p = document.createElement('p');
      p.textContent = '（测试插入的新段落）这一段是测试时临时插进来的，用来把后面的内容往下推，检查笔迹是否跟着原来的内容走。';
      const fig = document.createElement('figure');
      const im = document.createElement('img'); im.src = other.getAttribute('src'); im.style.width = '400px';
      fig.appendChild(im);
      first.before(p, fig);
      const lead = para.firstChild;
      const old = lead.data.slice(0, 4);
      lead.data = '改过的字' + lead.data.slice(4);
      return {inserted_before: first.tagName, old_head: old, new_img: other.getAttribute('src')};
    }""", [tgt["src"], tgt["needle"]])
    page.wait_for_function("[...document.querySelectorAll('article img')].every(i => i.complete)")
    page.wait_for_timeout(300)
    import_notes(page, text)
    for k, (spec, name) in enumerate(zip(specs, ["图", "字"])):
        got = page.evaluate(MEASURE_JS, spec)
        compare(rep, f"e{k + 1} 插入段落+图、改段首 {edit['old_head']!r}→'改过的字' 后{name}上的笔对齐", ref[k], got)
        if "targetTop" in got:
            rep.check(f"e{k + 3} 目标{name}确实被推下去了", got["targetTop"] - tops0[k] > 50,
                      f"目标在卡片内 y {tops0[k]:.1f} → {got['targetTop']:.1f}")
    st = page.evaluate("window.__nipcNotes.status()")
    rep.check("e5 没有误判为内容已变", st["orphans"] == 0, f"orphans={st['orphans']}")
    shot_around(page, out, "e_drift_text.png", needle_parent_js(tgt["needle"]))
    shot_around(page, out, "e_drift_image.png", img_js(tgt["src"]))
    ctx.close()

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = open_page(ctx, "week3_4.html")
    page.evaluate("""([src, needle]) => {
      const article = document.querySelector('article');
      [...article.querySelectorAll('img')].filter(i => i.getAttribute('src').endsWith('/' + src)).forEach(i => i.closest('figure').remove());
      const w = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) if (n.data.includes(needle)) {
        n.parentElement.closest('p').textContent = '这一段整段改写成了完全不同的内容，原来的字一个都不剩，用来测试找不到对应内容时笔迹不丢、标灰显示。';
        break;
      }
    }""", [tgt["src"], tgt["needle"]])
    page.wait_for_timeout(300)
    import_notes(page, text)
    st = page.evaluate("window.__nipcNotes.status()")
    cls = page.evaluate("[...document.querySelectorAll('#annot-layer path')].map(p => [p.getAttribute('class'), getComputedStyle(p).display])")
    status_text = page.inner_text("#annot-status")
    rep.check("f1 目标删掉后两笔标灰、不丢", st["orphans"] == 2 and all("orphan" in c and d != "none" for c, d in cls),
              f"orphans={st['orphans']}，path={cls}，提示「{status_text.strip()}」")
    page.evaluate(f"document.querySelector('#annot-layer path[data-id=\"{ids[1]}\"]').scrollIntoView({{block: 'center', behavior: 'instant'}})")
    page.wait_for_timeout(300)
    page.screenshot(path=str(out / "f_orphan.png"))
    ctx.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rep = Report()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        print("chromium", browser.version)
        text, tgt, ids, ref = test_ipad_draw(browser, rep, args.out)
        print(f"      目标：图 {tgt['src']}，字 needle={tgt['needle']!r}")
        test_mac_import(browser, rep, args.out, text, tgt, ids, ref)
        test_week2_details(browser, rep, args.out)
        test_video_click(browser, rep)
        test_drift(browser, rep, args.out, text, tgt, ids, ref)
        browser.close()
    print(f"== 失败 {rep.fails} 项；截图与 JSON 在 {args.out}")
    sys.exit(1 if rep.fails else 0)


if __name__ == "__main__":
    main()
