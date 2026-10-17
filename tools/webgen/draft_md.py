"""讲稿 Markdown → HTML。支持的写法（完整示例见 README.md「讲稿标记」）：

- 普通 Markdown（Python-Markdown + tables 扩展）：段落、**粗体**、`代码`、列表（缩进不规则也行）、pipe 表格、链接
- 公式：$…$ 或 $`…`$ 行内，$$…$$（单行或多行）块级，交给 MathJax
- 独占一行的 [视频](assets/videos/x.mp4) 内嵌播放；独占一行的 ![说明](assets/images/x.png)，同一行多张则并排
- Notion 写法：<table><tr><td>…</td></tr></table>、<details><summary>…</summary>…</details>（可嵌套）、
  <image src="NAS 路径"></image>（复制进 assets/images/）、<mention-page url="…"/>
- 标题降两级（## → h4，### → h5），去掉讲稿自带的节号；--- 分隔线删掉
"""

import itertools
import re
from pathlib import Path

from .common import esc

NOTION_IMAGES = []   # 讲稿里 <image src=NAS 路径> 和实验示意图引用的图，build 时复制进 assets/images/
_STASH_IDS = itertools.count()


def normalize_list_indent(t):
    """把讲稿里 2 / 3 / 5 格等不规则缩进的嵌套列表改成 Python-Markdown 认的每级 4 格。
    按缩进维护一个「当前打开的列表项」栈：列表项的层级 = 栈里缩进更小的项数；缩进的续行（含公式行）挂在
    缩进比它小的最深一项下面；紧跟在列表里、顶格的 $$ 公式行也算该项的续行（否则列表被截断、编号重排）。"""
    out, stack, after_text = [], [], False   # after_text：上一行是列表项下的续行段落
    for line in t.split("\n"):
        body = line.lstrip(" ")
        ind = len(line) - len(body)
        if not body:
            out.append(line)
            after_text = False
            continue
        if re.match(r"(?:[-*]|\d+\.) ", body):
            while stack and stack[-1] >= ind:
                stack.pop()
            if after_text:
                out.append("")   # 续行段落后直接跟列表项会被当成段落的懒续行，补空行断开
            out.append("    " * len(stack) + body)
            stack.append(ind)
            after_text = False
        elif stack and (ind > 0 or body.startswith("$$")):
            out.append("    " * (sum(1 for s in stack if s < ind) if ind > 0 else len(stack)) + body)
            after_text = True
        else:
            stack = []
            out.append(line)
            after_text = False
    return "\n".join(out)


def notion_md_to_html(md):
    """讲稿 Markdown → HTML（支持的写法见模块说明）。公式、视频、图片、表格、折叠块先换成占位符存起来，
    普通 Markdown 部分交给 Python-Markdown 转换后再放回，避免它们被 Markdown 改写。"""
    import markdown
    stash, uid = [], next(_STASH_IDS)   # 占位符带本次调用编号：<details> 递归转换时内外层不串号

    def keep(html_text, block=False):
        """存一段已转换好的 HTML，返回占位符；block = 前后补空行使其独占一段。"""
        stash.append(html_text)
        return f"\n\n@@S{uid}x{len(stash) - 1}@@\n\n" if block else f"@@S{uid}x{len(stash) - 1}@@"

    def keep_indented(m, html_text):
        """块级占位符保留原行缩进（m.group(1)），留在所属列表项里。"""
        ind = m.group(1)
        return f"\n\n{ind}@@S{uid}x{len(stash)}@@\n\n" + ("" if stash.append(html_text) else "")

    def inline(s):
        """表格格子 / 折叠标题里的行内格式：**粗体**、`代码`。"""
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", s)

    t = normalize_list_indent(md.replace("\\<", "&lt;"))
    t = re.sub(r"(?ms)^[ \t]*\$\$\s*\n(.*?)\n[ \t]*\$\$[ \t]*$", lambda m: keep(f"<p>\\[{esc(m.group(1).strip())}\\]</p>", True), t)
    t = re.sub(r"(?m)^([ \t]*)\$\$(.+?)\$\$[ \t]*$", lambda m: keep_indented(m, f"<p>\\[{esc(m.group(2).strip())}\\]</p>"), t)
    t = re.sub(r"\$`(.+?)`\$", lambda m: keep(f"\\({esc(m.group(1))}\\)"), t)
    t = re.sub(r"(?<![\$\\])\$([^\$\n]+?)\$", lambda m: keep(f"\\({esc(m.group(1))}\\)"), t)
    t = re.sub(r"(?m)^([ \t]*)\[视频\]\((assets/videos/[^)\s]+\.mp4)\)[ \t]*$", lambda m: keep_indented(
        m, f'<figure><video controls muted playsinline preload="metadata" src="{esc(m.group(2))}"></video></figure>'), t)
    t = re.sub(r"(?m)^([ \t]*)((?:!\[[^\]]*\]\(assets/images/[^)\s]+\)[ \t]*)+)$", lambda m: keep_indented(
        m, (lambda imgs: imgs[0] if len(imgs) == 1 else '<div class="grid">' + "".join(imgs) + "</div>")(
            [f'<figure><img src="{esc(src)}" alt="{esc(alt)}" loading="lazy"></figure>'
             for alt, src in re.findall(r"!\[([^\]]*)\]\(([^)\s]+)\)", m.group(2))])), t)
    t = re.sub(r'<image src="([^"]+)"></image>(（[^）]*）)?', lambda m: keep(notion_image(m.group(1)), True), t)
    t = re.sub(r'<mention-page url="([^"]+)"\s*/>', r'[Notion 页面](\1)', t)

    def table_html(m):
        """Notion 的 <table>：第一行当表头，格子里只做行内格式。"""
        rows = re.findall(r"<tr>(.*?)</tr>", m.group(1), flags=re.S)
        cells = [re.findall(r"<td>(.*?)</td>", r, flags=re.S) for r in rows]
        head = "".join(f"<th>{inline(c.strip())}</th>" for c in cells[0])
        body = "".join("<tr>" + "".join(f"<td>{inline(c.strip())}</td>" for c in r) + "</tr>" for r in cells[1:])
        return keep(f'<div class="tablewrap"><table><tr>{head}</tr>{body}</table></div>', True)
    t = re.sub(r'(?s)<table[^>]*>(.*?)</table>', table_html, t)

    def details_html(m):
        """<details> 折叠块：标题做行内格式，内容（去掉一级 Tab 缩进）递归转换。"""
        inner = "\n".join(line[1:] if line.startswith("\t") else line for line in m.group(2).split("\n"))
        return keep(f"<details><summary>{inline(m.group(1).strip())}</summary>{notion_md_to_html(inner)}</details>", True)
    while "<details>" in t:   # 由内向外：先换掉不含嵌套的最内层
        t = re.sub(r"(?s)[ \t]*<details>\s*<summary>(.*?)</summary>((?:(?!<details>).)*?)[ \t]*</details>", details_html, t)

    t = re.sub(r"(?m)^---\s*$", "", t)
    t = re.sub(r"(?m)^(##+ )\d+(?:\.\d+)*\.? ", r"\1", t)   # 去掉讲稿自带的节号（页面只取部分节，原编号对不上）
    t = re.sub(r"(?m)^### ", "##### ", re.sub(r"(?m)^## ", "#### ", t))
    t = re.sub(r"(?m)^(\t+)", lambda m: "    " * len(m.group(1)), t)
    t = re.sub(r"(?m)^(?![-*] |\s|\||\d+\. )(.+)\n(?=\s*(?:[-*] |\d+\. ))", r"\1\n\n", t)   # 列表前补空行，否则不认（**粗体** 行也要补）
    # Notion 里每一行是一个独立块：相邻两行顶格正文各成一段，不并成一段（pipe 表格的行除外）
    t = re.sub(r"(?m)^(?![-*] |\s|\d+\. |\|)(.+)\n(?![-*] |\s|\d+\. |\|)", r"\1\n\n", t)
    # 列表后紧跟的顶格正文补空行，否则会被并进最后一条（Notion 里它是独立段落）
    t = re.sub(r"(?m)^(\s*(?:[-*]|\d+\.) .+)\n(?![-*] |\s|\d+\. )", r"\1\n\n", t)
    t = re.sub(r"(?m)^(?!\|)(.+)\n(?=\|)", r"\1\n\n", t)   # 表格前补空行
    out = markdown.markdown(t, extensions=["tables"])
    out = out.replace("<table>", '<div class="tablewrap"><table>').replace("</table>", "</table></div>")
    for i, s in reversed(list(enumerate(stash))):
        out = out.replace(f"<p>@@S{uid}x{i}@@</p>", s).replace(f"@@S{uid}x{i}@@", s)
    return out


def notion_image(src):
    """讲稿里的 NAS 图：登记到 NOTION_IMAGES（build 时复制进 assets/images/），返回 <img>。"""
    path = Path(src)
    if path not in NOTION_IMAGES:
        NOTION_IMAGES.append(path)
    return f'<figure><img src="assets/images/{path.name}" alt="{esc(path.stem)}"></figure>'
