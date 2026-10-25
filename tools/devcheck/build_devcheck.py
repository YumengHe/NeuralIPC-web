"""生成设备核对页 devcheck/1/index.html：在用户自己的设备上，用独立核对器（indep_check）的采样代码原样采集两页笔记的几何数据并上传。

为什么要它：服务器无头 Chromium 的字体 / 排版和用户的 iPad 不一样，同一份迁移结果在服务器上判几乎全对、她在 iPad 上看到一堆错。
所以采样必须在她的设备上做，判定仍用服务器上现成的 indep_check.judge（tools/devcheck/judge_devcheck.py）。

页面做的事（用户打开一次，不用操作）：
  1. 同源 iframe（宽高 = 设备视口）依次加载基准页 snapshot/2 和每个待测页（?page=preview/3,preview/2，默认这两个）；
  2. 每页照 repair_notes_positions.open_served + indep_check.probe_page 的顺序：等标注层和 MathJax startup.promise、图片 eager 加载完、
     展开全部 details、等 1.5 s、注入「标注层不接收命中」样式、再等 0.8 s；逐笔 instant 滚动后在 iframe 文档里原样执行 PROBE_JS；
     最后原样执行 page_texts_js（全文 + 每个公式的字形串）；
  3. 待测页另导出全部内容项（正文字、公式字形）的正文卡片坐标和每笔起点（与 REF_JS 的 rectOf 同口径），服务器据此算第二遍偏移；
  4. 记录设备与 iframe 环境（UA、视口、article 宽、main zoom、字号、行高、text-size-adjust），iframe 与顶层视口不一致或运行中视口变了就在页上写明并标无效；
  5. 有同步 token（localStorage nipc-notes-sync，与标注层同步 / covers 页同一读法）就上传到笔记仓库 checks/devcheck_<页>_<时间>.json，否则给下载链接。

用法（在部署 worktree 根目录）：
    /bin/python tools/devcheck/build_devcheck.py --indep-check-dir /nas/xiaoyingwang/Neural-IPC/outputs/web_annotate_test/diag_wt/tools
"""
import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "devcheck" / "1" / "index.html"
DEFAULT_IC_DIR = "/nas/xiaoyingwang/Neural-IPC/outputs/web_annotate_test/diag_wt/tools"
BASE_PAGE = "snapshot/2"
TARGET_PAGES = ("preview/3", "preview/2", "snapshot/2")   # snapshot/2 也可当待测页：对自己应 0 错（自测）
DEFAULT_TARGETS = ("preview/3", "preview/2")

# iframe 里的环境：判 iframe 排版是否等于直接打开（服务器在同一视口的无头浏览器里跑同一段，见 judge_devcheck.env_check）
ENV_JS = r"""() => {
  const de = document.documentElement, art = document.querySelector('main article'), main = document.querySelector('main');
  const p = art && art.querySelector('p'), cp = p ? getComputedStyle(p) : null, cr = getComputedStyle(de), vv = window.visualViewport;
  const r1 = v => Math.round(v * 100) / 100;
  return { inner: [innerWidth, innerHeight], client: [de.clientWidth, de.clientHeight], scroll_h: de.scrollHeight,
           zoom: (main && main.style.zoom) || '', art_w: art ? r1(art.getBoundingClientRect().width) : null,
           art_offset_w: art ? art.offsetWidth : null, p_font: cp ? cp.fontSize : null, p_lh: cp ? cp.lineHeight : null,
           root_font: cr.fontSize, tsa: cr.webkitTextSizeAdjust || cr.textSizeAdjust || '',
           vv: vv ? [r1(vv.width), r1(vv.height), vv.scale] : null, dpr: devicePixelRatio,
           frame: window.__nipcNotes ? (f => [r1(f.x), r1(f.y), f.s])(window.__nipcNotes.frame()) : null };
}"""

# 第二遍偏移的数据：REF_JS 对给定 [笔, 内容身份] 量「笔起点 − 内容项左上角」（正文卡片 px）。设备上不知道服务器会选哪个内容身份
# （要两页全文 diff），所以导出全部内容项左上角的正文卡片坐标 ((q.left − f.x) / f.s, (q.top − f.y) / f.s) 和每笔起点 abs[0]，
# 服务器上 偏移 = abs[0] − 坐标，与 REF_JS 的 (f.x + abs0·f.s − q.left) / f.s 代数相同。文字遍历、空白规则、公式字形枚举与 REF_JS 一致。
DUMP_JS = r"""() => {
  const art = document.querySelector('main article'), N = window.__nipcNotes, f = N.frame();
  const k = v => Math.round(v * 1000) / 1000, c = q => [k((q.left - f.x) / f.s), k((q.top - f.y) / f.s)];
  const p = [], rg = document.createRange();
  const w = document.createTreeWalker(art, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) { const par = n.parentElement;
    if (!(par && !par.closest('mjx-container, script, style, .annot-ui'))) continue;
    for (let o = 0; o < n.data.length; o++) { if (/\s/.test(n.data[o])) continue;
      rg.setStart(n, o); rg.setEnd(n, o + 1); p.push(c(rg.getBoundingClientRect())); } }
  const m = [...art.querySelectorAll('mjx-container')].map(mc => [...mc.querySelectorAll('[data-c]')].map(el => c(el.getBoundingClientRect())));
  const a0 = {};
  for (const s of N.strokes()) { const d = N.placed(s.id); a0[s.id] = d && d.abs ? [d.abs[0][0], d.abs[0][1]] : null; }
  return { f: [f.x, f.y, f.s], p, m, a0 };
}"""


# 布局表（默认模式）：每页只导出一遍几何，不做命中测试；服务器用 geom_probe.py 按 PROBE_JS 的口径纯几何重算每笔。
# 坐标一律是「屏幕 px 相对正文卡片原点 (f.x, f.y)」，与滚动无关；另给导出时的滚动、f、视口与可滚动高度，服务器据此重放 probe_page 的滚动。
#  text：过滤规则同 PROBE_JS（父元素不在 mjx-container / script / style / .annot-ui 里）的每个文字节点：节点原文 d、
#        去空白前缀长度 p0（= PROBE_JS tOff）、父元素行高 lh、每个非空白字 [节点内偏移, l, t, r, b]（Range.getBoundingClientRect）。
#  maths：每个 mjx-container：外框、父元素行高、overflow-x 与可见裁剪框；每个 [data-c]：字符、标签、href、x/y、getScreenCTM、外框。
#  paths：被引用的字形路径 {id: d}；media：img / video 外框与 src；heads：h2 / h3 上沿与文字；strokes：每笔 placed 状态、abs、笔宽。
LAYOUT_JS = r"""() => {
  const art = document.querySelector('main article'), N = window.__nipcNotes, f = N.frame(), de = document.documentElement;
  const R = q => [q.left - f.x, q.top - f.y, q.right - f.x, q.bottom - f.y];
  const lhOf = el => { const cs = getComputedStyle(el), v = parseFloat(cs.lineHeight); return Number.isFinite(v) ? v : 1.7 * parseFloat(cs.fontSize); };
  const text = [], rg = document.createRange(); let co = 0;
  const w = document.createTreeWalker(art, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) { const par = n.parentElement;
    if (!(par && !par.closest('mjx-container, script, style, .annot-ui'))) continue;
    const cs = [];
    for (let o = 0; o < n.data.length; o++) { if (/\s/.test(n.data[o])) continue;
      rg.setStart(n, o); rg.setEnd(n, o + 1); const q = rg.getBoundingClientRect(); cs.push([o, ...R(q)]); }
    text.push({ d: n.data, p0: co, lh: lhOf(par), c: cs }); co += n.data.replace(/\s+/g, '').length; }
  const paths = {}, need = new Set();
  const maths = [...art.querySelectorAll('mjx-container')].map(mc => {
    const cs = getComputedStyle(mc), q = mc.getBoundingClientRect();
    const g = [...mc.querySelectorAll('[data-c]')].map(el => { const m = el.getScreenCTM && el.getScreenCTM();
      const href = el.getAttribute('href') || el.getAttribute('xlink:href') || '';
      if (href) need.add(href.slice(1));
      return { c: el.getAttribute('data-c'), tag: el.tagName.toLowerCase(), href, x: +(el.getAttribute('x') || 0), y: +(el.getAttribute('y') || 0),
               d: el.tagName.toLowerCase() === 'path' ? el.getAttribute('d') : null,
               m: m ? [m.a, m.b, m.c, m.d, m.e - f.x, m.f - f.y] : null, r: R(el.getBoundingClientRect()) }; });
    return { r: R(q), lh: lhOf(mc.parentElement || mc), ox: cs.overflowX, oy: cs.overflowY, g }; });
  for (const id of need) { const el = document.getElementById(id); if (el) paths[id] = { tag: el.tagName.toLowerCase(), d: el.getAttribute('d') }; }
  const media = [...art.querySelectorAll('img, video')].map(e => ({ src: (e.getAttribute('src') || '').split('/').pop(), r: R(e.getBoundingClientRect()) }));
  const heads = [...art.querySelectorAll('h2, h3')].map(h => ({ t: h.getBoundingClientRect().top - f.y, s: h.textContent.trim() }));
  const strokes = N.strokes().map(s => { const d = N.placed(s.id);
    return { id: s.id, w: s.w, state: d ? d.state : 'none', abs: d && d.abs ? d.abs.map(p => [p[0], p[1]]) : null }; });
  return { f: [f.x, f.y, f.s], scroll: [scrollX, scrollY], inner: [innerWidth, innerHeight], max_scroll: [de.scrollWidth - de.clientWidth, de.scrollHeight - de.clientHeight],
           art_lh: lhOf(art), text, maths, paths, media, heads, strokes };
}"""


def load_ic(ic_dir):
    """import indep_check（不改它）：它在 diag_wt 分支的 tools/ 下，靠 sys.path 引入。"""
    sys.path.insert(0, str(ic_dir))
    import indep_check as IC
    return IC


def js_str(s):
    """嵌进 <script> 的 JS 字符串字面量（JSON 编码；</ 转义，防提前结束 script）。"""
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")


def sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def build(IC):
    """返回页面 HTML。采样常数取 indep_check 的 GRID_PX / SAMPLE_PX / BUDGET_MS，与服务器 probe_one 的参数一致。"""
    cfg = dict(base=BASE_PAGE, targets=list(TARGET_PAGES), default_targets=list(DEFAULT_TARGETS),
               grid=IC.RP_GRID, sample=IC.RP_SAMPLE, budget=IC.BUDGET_MS,
               probe_sha256=sha256(IC.PROBE_JS), texts_sha256=sha256(IC.page_texts_js()),
               env_sha256=sha256(ENV_JS), dump_sha256=sha256(DUMP_JS), layout_sha256=sha256(LAYOUT_JS))
    tpl = (pathlib.Path(__file__).with_name("devcheck_template.html")).read_text(encoding="utf-8")
    return (tpl.replace("/*@CFG@*/null", js_str(json.dumps(cfg, ensure_ascii=False)))
               .replace("/*@PROBE_JS@*/''", js_str(IC.PROBE_JS))
               .replace("/*@TEXTS_JS@*/''", js_str(IC.page_texts_js()))
               .replace("/*@ENV_JS@*/''", js_str(ENV_JS))
               .replace("/*@DUMP_JS@*/''", js_str(DUMP_JS))
               .replace("/*@LAYOUT_JS@*/''", js_str(LAYOUT_JS)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--indep-check-dir", default=DEFAULT_IC_DIR)
    args = ap.parse_args()
    html = build(load_ic(args.indep_check_dir))
    for k in ("/*@CFG@*/", "/*@PROBE_JS@*/", "/*@TEXTS_JS@*/", "/*@ENV_JS@*/", "/*@DUMP_JS@*/", "/*@LAYOUT_JS@*/"):
        assert k not in html, f"模板占位 {k} 没替换"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"写出 {OUT}（{len(html.encode('utf-8'))} 字节）")


if __name__ == "__main__":
    main()
