"""逐笔核对用户的手写笔记还落不落在原来的内容上（只读，只打印，不写任何文件）。

从笔记仓库（gh api，默认 delluluwxy/neural-ipc-notes 的 notes/<页名>.json）取出全部笔，在本地生成好的页面上
按 annotate.py 同样的规则找每一笔的锚点，分四类：
  exact    原样找到（公式 TeX、图 src、标题/表格文字、正文前后文都一字不差）；
  renamed  原样找不到，按页面里嵌的记号改名表（notation_renames_<页>.json）换写法后找到；
  fuzzy    上面都不行，只能靠模糊匹配（标注层会挂到「最像」的地方，可能挂错）；
  orphan   页面上找不到（标注层显示为灰色）。
fuzzy / orphan 就是「笔记没跟着内容走」，逐条打印锚点内容，供补改名表。

用法：
    /bin/python tools/check_notes_anchors.py week3_4.html [--notes <本地 json>]
依赖 playwright（用户目录安装的 chromium）与已登录的 gh。
"""
import argparse
import json
import pathlib
import subprocess
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = "delluluwxy/neural-ipc-notes"

# 与 annotate.py 第 5–7 节同样的正文索引（空白合并、跳过公式/脚本/标注层）、陈列公式 TeX、标题与表格文字
PAGE_JS = """() => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const article = document.querySelector('main article');
  const skip = n => !n.parentElement || !!n.parentElement.closest('mjx-container, script, style, svg, .annot-ui');
  const plain = el => { const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let s = '';
    for (let n = w.nextNode(); n; n = w.nextNode()) if (!skip(n)) s += n.data; return norm(s); };
  const w = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
  let chars = [], last = true;
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    if (skip(n)) continue;
    for (const c of n.data) { const sp = /\\s/.test(c); if (sp && last) continue; chars.push(sp ? ' ' : c); last = sp; }
  }
  const math = [];
  for (const m of MathJax.startup.document.math)
    if (m.display && m.typesetRoot && article.contains(m.typesetRoot)) math.push(norm(m.math));
  const src = [...article.querySelectorAll('img, video')].map(e =>
    (e.getAttribute('src') || '').split('#')[0].split('?')[0].split('/').pop());
  const el = document.getElementById('annot-renames');
  return { text: chars.join(''), math, src,
           heads: [...article.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(plain),
           cells: [...article.querySelectorAll('td,th')].map(plain),
           renames: el ? JSON.parse(el.textContent || '{}') : {} };
}"""


def load_notes(page_file, path):
    """本地 json 或笔记仓库里的 notes/<页名>.json。"""
    if path:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    out = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw",
                          f"repos/{REPO}/contents/notes/{pathlib.Path(page_file).stem}.json"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def page_data(rel):
    """打开生成好的页面，等 MathJax 排完，取出锚点要用的全部内容。"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto((ROOT / rel).as_uri(), wait_until="domcontentloaded", timeout=120000)
        page.wait_for_function("window.MathJax && MathJax.startup && MathJax.startup.promise", timeout=120000)
        page.evaluate("MathJax.startup.promise")
        data = page.evaluate(PAGE_JS)
        browser.close()
    return data


def norm(s):
    return " ".join((s or "").split())


def follow(table, key):
    """沿改名表走到底（同 annotate.py renamedTex，有环就停）；没改名返回 None。"""
    seen, k = {key}, key
    while k in table and table[k] not in seen:
        k = table[k]
        seen.add(k)
    return None if k == key else k


def rename_text(table, s):
    """文字按改名表逐个替换到不再变化（同 annotate.py renamedText，最多 20 轮）；没替换返回 None。"""
    changed = False
    for _ in range(20):
        hit = False
        for o, n in table.items():
            if o != n and o in s:
                s, hit, changed = s.replace(o, n), True, True
        if not hit:
            break
    return s if changed else None


def classify(a, d):
    """一笔的锚点在当前页上的去向：(类别, 给人看的锚点内容)。"""
    tex = {norm(k): norm(v) for k, v in d["renames"].get("tex", {}).items()}
    txt = {norm(k): norm(v) for k, v in d["renames"].get("text", {}).items()}
    t = a.get("type")
    if t == "page":
        return "exact", "（整页）"
    if t == "media":
        return ("exact" if a["src"] in d["src"] else "orphan"), f"图 {a['src']}"
    if t == "math":
        if a["tex"] in d["math"]:
            return "exact", a["tex"]
        t2 = follow(tex, a["tex"])
        return ("renamed" if t2 in d["math"] else "orphan"), a["tex"]
    if t in ("heading", "cell"):
        key, pool = (a["text"], d["heads"]) if t == "heading" else (a["cell"], d["cells"])
        if key in pool:
            return "exact", key
        r = rename_text(txt, key)
        return ("renamed" if r in pool else "orphan"), key
    quote = a["prefix"] + a["exact"] + a["suffix"]
    if quote in d["text"]:
        return "exact", quote
    r = rename_text(txt, quote)
    if r and r in d["text"]:
        return "renamed", quote
    seed_p, seed_s = a["prefix"][-4:] + a["exact"], a["exact"] + a["suffix"][:4]
    return ("fuzzy" if seed_p in d["text"] or seed_s in d["text"] else "orphan"), quote


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("page")
    ap.add_argument("--notes", help="本地笔记 json（默认从笔记仓库取）")
    args = ap.parse_args()
    notes = load_notes(args.page, args.notes)
    d = page_data(args.page)
    groups = {}
    for s in notes.get("strokes", []):
        cat, what = classify(s["anchor"], d)
        groups.setdefault(cat, []).append((s["anchor"].get("type"), what))
    total = sum(len(v) for v in groups.values())
    print(f"== {args.page}：笔记 {total} 笔（保存于 {notes.get('saved')}）；" +
          "，".join(f"{k} {len(groups.get(k, []))}" for k in ("exact", "renamed", "fuzzy", "orphan")))
    for cat in ("fuzzy", "orphan"):
        seen = set()
        for typ, what in groups.get(cat, []):
            if (typ, what) in seen:
                continue
            seen.add((typ, what))
            n = sum(1 for x in groups[cat] if x == (typ, what))
            print(f"  {cat:6s} {typ:7s} ×{n}  {what[:120]}")
    sys.exit(0 if not groups.get("fuzzy") and not groups.get("orphan") else 1)


if __name__ == "__main__":
    main()
