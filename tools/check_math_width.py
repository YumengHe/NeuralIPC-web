"""列出页面里放不下的陈列公式：在给定窗口宽度下打开生成好的页面，等 MathJax 排完，逐个比较陈列公式的
实际宽度与正文列宽，打印超宽的公式（超出的像素和 TeX 源码），供讲稿里手动断行。

用法：
    /bin/python tools/check_math_width.py week3_4.html week2.html [--width 1440]
    /bin/python tools/check_math_width.py week3_4.html --shot "第一步：平底的解" <输出 png>
页面按仓库根目录的相对路径给。不给 --shot 时只读、不写文件；--shot 展开全部折叠，把含这段文字的最小折叠块
（没有就取所在段落）整块截成一张长图，写到给的路径，供自查实际版式。依赖 playwright（用户目录安装的 chromium）。
"""
import argparse
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 每个陈列公式：容器可用宽度 vs 公式 svg 的自然宽度；TeX 源码从 MathJax 的 math 列表取
JS = """() => {
  const out = [];
  for (const m of MathJax.startup.document.math) {
    if (!m.display) continue;
    const c = m.typesetRoot;
    if (!c) continue;
    const svg = c.querySelector('svg');
    const need = svg ? svg.getBoundingClientRect().width : c.scrollWidth;
    const have = c.parentElement.getBoundingClientRect().width;
    if (need > have + 0.5) out.push({over: Math.round(need - have), tex: m.math});
  }
  return out;
}"""


def check(page, rel):
    """打开一页、等公式排完，返回超宽公式列表。"""
    page.goto((ROOT / rel).as_uri(), wait_until="domcontentloaded", timeout=120000)   # 只等公式，不等图片视频（共享机负载高时 load 会超时）
    page.wait_for_function("window.MathJax && MathJax.startup && MathJax.startup.promise", timeout=120000)
    page.evaluate("MathJax.startup.promise")
    return page.evaluate(JS)


def shot(page, text, out):
    """展开全部 <details>，等图片加载完，把含 text 的最小折叠块（没有就取所在段落）截成一张长图。"""
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    page.evaluate("Promise.all([...document.images].map(i => (i.loading = 'eager', i.complete ? 0 : "
                  "new Promise(r => { i.onload = i.onerror = r; }))))")
    target = page.locator("details", has_text=text).last
    if target.count() == 0:
        target = page.locator("p", has_text=text).first
    target.scroll_into_view_if_needed()
    box = page.evaluate("e => { const r = e.getBoundingClientRect(); return {x: r.x + scrollX, y: r.y + scrollY, "
                        "w: r.width, h: r.height}; }", target.element_handle())
    stem, seg = out[:-4] if out.endswith(".png") else out, 1800      # 长块按 1800 px 一段切开，便于逐段看清
    for k, y0 in enumerate(range(0, int(box["h"]) + 1, seg), 1):
        path = f"{stem}_{k:02d}.png"
        page.screenshot(path=path, full_page=True,
                        clip=dict(x=box["x"], y=box["y"] + y0, width=box["w"], height=min(seg, box["h"] - y0)))
        print(f"wrote {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--shot", nargs=2, metavar=("TEXT", "OUT_PNG"), help="把含 TEXT 的折叠块截图到 OUT_PNG（只用第一个页面）")
    args = ap.parse_args()
    total = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": 900})
        if args.shot:
            check(page, args.pages[0])
            shot(page, *args.shot)
            browser.close()
            return
        for rel in args.pages:
            bad = check(page, rel)
            total += len(bad)
            print(f"== {rel}（窗口 {args.width}px）：超宽陈列公式 {len(bad)} 个")
            for b in bad:
                print(f"   超出 {b['over']} px：{b['tex'].strip()}")
        browser.close()
    sys.exit(0 if total == 0 else 1)


if __name__ == "__main__":
    main()
