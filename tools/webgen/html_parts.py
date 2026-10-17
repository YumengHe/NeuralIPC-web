"""页面骨架与通用 HTML 片段：整页模板（含 CSS 与 MathJax）、表格、视频卡片、设置小字。

每页开头是 doctype、charset、viewport，然后直接 <title> 和 <style>，省略 html / head / body 标签（HTML5 允许）；
颜色全是 CSS 变量（亮 / 暗两套）；公式由 MathJax（SVG 输出）渲染。
"""

from .common import MISSING, esc, pct

PAGE_CSS = """
:root {
  --bg: #fafaf8; --fg: #1f2328; --muted: #646b74; --border: #dcdfe3; --soft: #f1f3f5;
  --accent: #245f96; --good: #1f6b3a; --warn: #8a5a0b; --key: #b3261e;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial,
          "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #16191d; --fg: #e4e7eb; --muted: #9ba3ad; --border: #353b43; --soft: #20252b;
    --accent: #80b4e6; --good: #8fd3a5; --warn: #e6c27a; --key: #ff8a80;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #16191d; --fg: #e4e7eb; --muted: #9ba3ad; --border: #353b43; --soft: #20252b;
  --accent: #80b4e6; --good: #8fd3a5; --warn: #e6c27a; --key: #ff8a80;
  color-scheme: dark;
}
* { box-sizing: border-box; }
html, body { overflow-x: hidden; }
body { margin: 0; background: var(--bg); color: var(--fg); font-family: var(--font);
       font-size: 15px; line-height: 1.65; }
.wrap { max-width: 1200px; margin: 0 auto; padding: 0 16px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header.top { padding: 28px 0 8px; }
h1 { font-size: 1.85rem; margin: 0 0 8px; font-weight: 650; letter-spacing: 0.01em; }
.summary { margin: 8px 0 0; }
nav.toc { font-size: 0.9rem; margin: 14px 0 0; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
nav.toc { display: flex; flex-wrap: wrap; gap: 4px 18px; }
nav.weeks { display: grid; gap: 14px; margin: 18px 0 40px; }
a.weekcard { display: block; padding: 14px 16px; border-radius: 6px; background: var(--soft);
             border-left: 5px solid var(--accent); color: var(--fg); }
a.weekcard:hover { text-decoration: none; filter: brightness(0.97); }
a.weekcard b { font-size: 1.25rem; color: var(--accent); }
a.weekcard span { display: block; font-size: 0.86rem; color: var(--muted); margin: 2px 0 6px; }
h2 { font-size: 1.6rem; margin: 64px 0 14px; font-weight: 650; }
h3 { font-size: 1rem; margin: 22px 0 4px; font-weight: 600; }
h3.sub { font-size: 1.08rem; margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--border); }
h4 { font-size: 1.15rem; margin: 26px 0 8px; font-weight: 650; }
h5 { font-size: 1.05rem; margin: 20px 0 6px; font-weight: 650; }
section h4, section h5 { color: var(--accent); }
.kp { color: var(--key); font-weight: 600; margin: 10px 0 14px; }
pre.log { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.76rem;
          line-height: 1.45; background: var(--soft); border-radius: 4px; padding: 10px 12px; margin: 6px 0;
          max-width: 100%; white-space: pre-wrap; overflow-wrap: anywhere; }
details.repro { margin: 10px 0 26px; }
details.repro summary { cursor: pointer; color: var(--accent); font-size: 0.9rem; }
p.concl { font-size: 1.05rem; color: var(--good); }
p.expect { font-size: 1.08rem; color: var(--accent); }
p.setting { font-size: 0.8rem; color: var(--fg); }
section { scroll-margin-top: 12px; }
p { margin: 6px 0; }
.muted { color: var(--muted); }
code { font-size: 0.95em; word-break: break-all; }
.small { font-size: 0.86rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
        gap: 22px 18px; }
.demo { min-width: 0; }
.demo h3 { margin: 0 0 6px; font-size: 0.95rem; }
.demo h3 .key { color: var(--muted); font-weight: 400; font-size: 0.8rem; }
.demo p { font-size: 0.86rem; color: var(--muted); margin-top: 6px; }
video, img { display: block; width: 100%; height: auto; border-radius: 4px; background: var(--soft); }
img.plot { margin-top: 8px; }
.novideo { padding: 22px 12px; background: var(--soft); color: var(--muted); border-radius: 4px;
           font-size: 0.86rem; }
.tablewrap { max-width: 100%; margin: 6px 0 4px; }
table { border-collapse: collapse; font-size: 0.88rem; width: 100%; table-layout: auto; }
th, td { text-align: left; padding: 5px 14px 5px 0; border-bottom: 1px solid var(--border);
         white-space: normal; overflow-wrap: anywhere; vertical-align: top; }
th { font-weight: 600; color: var(--muted); font-size: 0.82rem; border-bottom-color: var(--fg); }
td { font-variant-numeric: tabular-nums; }
td.good { color: var(--good); }
td.warn { color: var(--warn); }
ul.obs { font-size: 1.02rem; font-weight: 600; margin: 8px 0; padding-left: 22px; } ul.obs li { margin: 3px 0; }
main.wrap { counter-reset: sec; } main.wrap section > h2 { counter-increment: sec; counter-reset: sub; } main.wrap section > h2::before { content: counter(sec) ". "; } main.wrap section > h3 { counter-increment: sub; } main.wrap section > h3::before { content: counter(sec) "." counter(sub) " "; }
main.wrap section > h3 { font-size: 1.3rem; margin: 56px 0 10px; padding-top: 20px; border-top: 1px solid var(--border); }
img.initframe { display: block; max-width: 640px; width: 100%; margin: 6px 0; }
mjx-container { max-width: 100%; } mjx-container svg { max-width: 100%; height: auto; }
ul.findings { padding-left: 20px; }
ul.findings li { margin: 8px 0; }
.next { }
footer.foot { color: var(--muted); font-size: 0.8rem; border-top: 1px solid var(--border);
              margin-top: 40px; padding: 12px 16px 28px; }
@media (max-width: 480px) {
  body { font-size: 14px; }
  th, td { padding-right: 10px; }
}
"""


def page(body, title):
    """整页 HTML：doctype + charset / viewport + <title> / <style> + MathJax 配置，body 放在 <main class="wrap"> 里。
    正文里的 d̂ 统一换成 MathJax 行内公式 \\(\\hat d\\)。"""
    body = body.replace("d̂", r"\(\hat d\)")
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{PAGE_CSS}</style>
<script>window.MathJax = {{tex: {{inlineMath: [["\\\\(", "\\\\)"]], displayMath: [["\\\\[", "\\\\]"]]}}, svg: {{fontCache: "global"}}}};</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js" async></script>
<main class="wrap">
{body}
</main>
"""


def table(heads, rows):
    """表格。heads：表头文字列表；rows：每行一个列表，格子是文本，或 (文本, css class) 给格子上色。全部转义。"""
    th = "".join(f"<th>{esc(h)}</th>" for h in heads)
    body = []
    for cells in rows:
        tds = []
        for c in cells:
            if isinstance(c, tuple):  # (文本, css class)
                tds.append(f'<td class="{c[1]}">{esc(c[0])}</td>')
            else:
                tds.append(f"<td>{esc(c)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<div class="tablewrap"><table><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def demo_card(r, facts):
    """一张视频卡片：标题 + 视频（或说明为什么没有）+ 一句说明。r 是 collect.py 的记录（需已过 media.plan_videos）；
    facts 提供说明里的占位数字（目前只有 {momentum}）。"""
    line = r["line"].replace("{momentum}", pct(facts.get("momentum_err", MISSING)))
    head = f'<h3>{esc(r["title"])}</h3>'
    if r["state"] != "ok":
        media = f'<div class="novideo">{esc(r["reason"])}</div>'
    elif r.get("video_web"):
        media = f'<video controls muted playsinline preload="metadata" src="{esc(r["video_web"])}"></video>'
    else:
        media = f'<div class="novideo">{esc(r["video_note"] or "没有视频")}</div>'
    return f'<div class="demo">{head}{media}<p>{esc(line)}</p></div>'


def setting(text):
    """实验设置：小号灰字，留给想看细节的人，组会上不读。"""
    return f'<p class="setting muted">设置：{esc(text)}</p>'
