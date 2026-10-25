"""用设备导出的布局表（build_devcheck.LAYOUT_JS）纯几何重算 indep_check.PROBE_JS 的逐笔结果，不在设备上做命中测试。

为什么：PROBE_JS 每笔做上千次 caretRangeFromPoint / elementsFromPoint，一页约 26 万次，iPad 上要十分钟级；布局表一页只导一遍。
口径与 PROBE_JS 逐条对应（采样点、视口裁剪、邻域网格与放大、排序、偏移参考、图、小节、内容身份），只把两种命中测试换成几何：
  - 正文字（caretRangeFromPoint 分支）：点落在公式容器或图里 → 浏览器给的不是文字位置，不命中；点落在某字框里 → 插入点按左右半边取
    该字或下一字（同一文字节点内的偏移），再照 PROBE_JS 依次试 [o, o−1]（跳过空白，字框外扩 e 包含点才算）；点不在任何字框、
    但在某行的行盒里（字框中心 ± 行高 / 2）且横向离某字 ≤ e → 插入点吸附到该行最近的字，同样试 [o, o−1]（e = 0 的网格点不可能这样命中）；
  - 公式字形（elementsFromPoint 分支）：点落在字形实际墨迹里（<use> 引用的字形路径按 getScreenCTM 变换后非零绕数填充；容器 overflow 非 visible 时
    先按容器框裁剪）才算命中，同一点多个字形取文档顺序最后一个（画在最上面）。
与 PROBE_JS 原结果的对拍见 tools/devcheck/test_devcheck.py（t8）。
"""
import bisect
import math
import re
import unicodedata

import numpy as np

JS_WS = set("\t\n\v\f\r       　﻿") | {chr(c) for c in range(0x2000, 0x200b)}
CELL = 32.0   # 空间索引格子（相对正文卡片原点的屏幕 px）


def js_round(v):
    """JS Math.round（.5 向 +∞）。"""
    return math.floor(v + 0.5)


def nfkc(hexcode):
    return unicodedata.normalize("NFKC", chr(int(hexcode, 16)))


def js_ws_strip_len(s):
    return sum(ch not in JS_WS for ch in s)


# ---------- SVG 路径：解析、压平成折线、非零绕数 ----------
_TOK = re.compile(r"[MmLlHhVvQqTtCcSsZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def flatten_path(d, nseg=48):
    """SVG path d → 若干闭合折线（[[x, y], ...]）。曲线按 nseg 段压平。"""
    toks = _TOK.findall(d or "")
    polys, cur, i, ctrl = [], [], 0, []
    x = y = sx = sy = 0.0
    cmd, last_ctrl, prev_cmd = None, None, None

    def nums(k):
        nonlocal i
        v = [float(t) for t in toks[i:i + k]]
        i += k
        return v
    while i < len(toks):
        t = toks[i]
        if re.fullmatch(r"[A-Za-z]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur:
                    polys.append(cur)
                cur, x, y = [], sx, sy
                prev_cmd, last_ctrl = cmd, None
                continue
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if c == "M":
            px, py = nums(2)
            if cur:
                polys.append(cur)
            x, y = px + ox, py + oy
            sx, sy = x, y
            cur = [[x, y]]
            cmd = "l" if rel else "L"
            last_ctrl = None
        elif c == "L":
            px, py = nums(2)
            x, y = px + ox, py + oy
            cur.append([x, y])
            last_ctrl = None
        elif c == "H":
            (px,) = nums(1)
            x = px + (x if rel else 0.0)
            cur.append([x, y])
            last_ctrl = None
        elif c == "V":
            (py,) = nums(1)
            y = py + (y if rel else 0.0)
            cur.append([x, y])
            last_ctrl = None
        elif c in "QT":
            if c == "Q":
                qx, qy, px, py = nums(4)
                qx, qy = qx + ox, qy + oy
            else:
                px, py = nums(2)
                qx, qy = (2 * x - last_ctrl[0], 2 * y - last_ctrl[1]) if last_ctrl and prev_cmd in "QqTt" else (x, y)
            px, py = px + ox, py + oy
            ctrl.append([qx, qy])
            for k in range(1, nseg + 1):
                u = k / nseg
                cur.append([(1 - u) ** 2 * x + 2 * (1 - u) * u * qx + u * u * px, (1 - u) ** 2 * y + 2 * (1 - u) * u * qy + u * u * py])
            last_ctrl, x, y = (qx, qy), px, py
        elif c in "CS":
            if c == "C":
                x1, y1, x2, y2, px, py = nums(6)
                x1, y1 = x1 + ox, y1 + oy
            else:
                x2, y2, px, py = nums(4)
                x1, y1 = (2 * x - last_ctrl[0], 2 * y - last_ctrl[1]) if last_ctrl and prev_cmd in "CcSs" else (x, y)
            x2, y2, px, py = x2 + ox, y2 + oy, px + ox, py + oy
            ctrl += [[x1, y1], [x2, y2]]
            for k in range(1, nseg + 1):
                u = k / nseg
                a, b, cc, dd = (1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u * u, u ** 3
                cur.append([a * x + b * x1 + cc * x2 + dd * px, a * y + b * y1 + cc * y2 + dd * py])
            last_ctrl, x, y = (x2, y2), px, py
        else:
            raise ValueError(f"不认识的路径命令 {cmd}")
        prev_cmd = cmd
    if cur:
        polys.append(cur)
    out = [np.array(p, dtype=float) for p in polys if len(p) >= 2]
    flatten_path.ctrl_bounds = None
    if out:   # 含控制点的外框（Skia getBounds 的口径）：核 CTM 时与压平外框各比一次
        allp = np.vstack(out + ([np.array(ctrl, dtype=float)] if ctrl else []))
        flatten_path.ctrl_bounds = (allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max())
    return out


def edge_dist(polys, x, y):
    """点到各折线（首尾相连）边的最短距离。"""
    best = math.inf
    for P in polys:
        a, b = P, np.roll(P, -1, axis=0)
        d = b - a
        L2 = (d ** 2).sum(1)
        t = np.where(L2 > 0, np.clip(((x - a[:, 0]) * d[:, 0] + (y - a[:, 1]) * d[:, 1]) / np.where(L2 > 0, L2, 1), 0, 1), 0)
        best = min(best, float(np.sqrt(((a[:, 0] + t * d[:, 0] - x) ** 2 + (a[:, 1] + t * d[:, 1] - y) ** 2).min())))
    return best


def winding(polys, x, y):
    """点 (x, y) 对折线集合的绕数（各折线首尾相连）。"""
    wn = 0
    for P in polys:
        x0, y0 = P[:, 0], P[:, 1]
        x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
        cr = (x1 - x0) * (y - y0) - (x - x0) * (y1 - y0)
        up = (y0 <= y) & (y1 > y) & (cr > 0)
        dn = (y0 > y) & (y1 <= y) & (cr < 0)
        wn += int(up.sum()) - int(dn.sum())
    return wn


class Grid:
    """矩形的空间索引：cell → 项序号列表。"""

    def __init__(self, rects, pad=0.0):
        self.cells = {}
        for k, (l, t, r, b) in enumerate(rects):
            for cx in range(int(math.floor((l - pad) / CELL)), int(math.floor((r + pad) / CELL)) + 1):
                for cy in range(int(math.floor((t - pad) / CELL)), int(math.floor((b + pad) / CELL)) + 1):
                    self.cells.setdefault((cx, cy), []).append(k)

    def near(self, x, y):
        return self.cells.get((int(math.floor(x / CELL)), int(math.floor(y / CELL))), ())


class Layout:
    """一页布局表的几何查询。坐标：相对正文卡片原点的屏幕 px（rx, ry）。"""

    MAX_E = 40.0   # 吸附 / 外扩查询半径上限（笔宽一半 + 1，荧光笔 16 px 宽 × 缩放 ≤ 2 远小于它）

    def __init__(self, L):
        self.L = L
        self.f = L["f"]
        self.s = L["f"][2]
        self.inner = L["inner"]
        self.max_scroll = L["max_scroll"]
        self.page_f = (L["f"][0] + L["scroll"][0], L["f"][1] + L["scroll"][1])
        self.rule = scroll_rule(L)
        self.overlays = [o["r"] for o in L.get("overlays") or []]
        self.cur_f = (0.0, 0.0)   # 当前这笔滚动下正文卡片原点的屏幕坐标（probe 里设）
        # 正文字
        self.chars = []          # [(节点序号, 偏移, l, t, r, b)]
        self.node_char = []      # 节点序号 → {偏移: 字序号}
        for ni, n in enumerate(L["text"]):
            m = {}
            for o, l, t, r, b in n["c"]:
                m[o] = len(self.chars)
                self.chars.append((ni, o, l, t, r, b))
            self.node_char.append(m)
        self.char_grid = Grid([c[2:] for c in self.chars])
        # 行盒（字框中心 ± 行高 / 2），横向外扩 MAX_E：吸附用
        self.line_rects = []
        for ni, o, l, t, r, b in self.chars:
            cy, h = (t + b) / 2, L["text"][ni]["lh"] / 2
            self.line_rects.append((l, cy - h, r, cy + h))
        self.line_grid = Grid(self.line_rects, pad=self.MAX_E)
        # 公式与字形
        self.glyphs = []         # [(公式序号, 公式内序号, 字, 外框, 命中函数所需)]
        self.cont_rects = [m["r"] for m in L["maths"]]
        self.cont_grid = Grid(self.cont_rects)
        poly_cache = {}
        self.ctm_fixed = 0
        for mi, m in enumerate(L["maths"]):
            clip = None if (m["ox"] == "visible" and m["oy"] == "visible") else m["r"]
            for k, g in enumerate(m["g"]):
                if g["tag"] == "use":
                    pid = g["href"][1:]
                    if pid not in poly_cache:
                        p = L["paths"].get(pid)
                        poly_cache[pid] = (flatten_path(p["d"]), flatten_path.ctrl_bounds) if p and p.get("d") else ([], None)
                    (polys, cb), shift = poly_cache[pid], (g["x"], g["y"])
                elif g["tag"] == "path":
                    polys, shift = flatten_path(g["d"]), (0.0, 0.0)
                    cb = flatten_path.ctrl_bounds
                else:
                    polys, cb, shift = None, None, (0.0, 0.0)   # <text> 等：按外框
                inv = None
                if g["m"] and polys:
                    a, b, c, d, e, f = g["m"]
                    # 核 CTM：路径外框（压平外框或含控制点外框，任一个）经 CTM 变换后应与浏览器给的字形外框重合
                    # （WebKit 在 CSS zoom 下 getScreenCTM 可能不含 zoom）；都差 > 0.5 px 就用「路径外框 → 字形外框」拟合的缩放 + 平移代替（计 ctm_fixed）
                    allp = np.vstack(polys) + np.array(shift)
                    l_, t_, r_, b2 = g["r"]

                    def off(bx):
                        cx = np.array([bx[0], bx[2], bx[0], bx[2]]) + shift[0]
                        cy = np.array([bx[1], bx[1], bx[3], bx[3]]) + shift[1]
                        X, Y = a * cx + c * cy + e, b * cx + d * cy + f
                        return max(abs(X.min() - l_), abs(X.max() - r_), abs(Y.min() - t_), abs(Y.max() - b2))
                    fb = (allp[:, 0].min() - shift[0], allp[:, 1].min() - shift[1], allp[:, 0].max() - shift[0], allp[:, 1].max() - shift[1])
                    if min(off(fb), off(cb) if cb else math.inf) > 0.5:
                        px0, px1, py0, py1 = allp[:, 0].min(), allp[:, 0].max(), allp[:, 1].min(), allp[:, 1].max()
                        if px1 > px0 and py1 > py0:
                            ka = (r_ - l_) / (px1 - px0)
                            kd = (b2 - t_) / (py1 - py0) * (1 if d > 0 else -1)
                            a, b, c, d = ka, 0.0, 0.0, kd
                            e = l_ - ka * (px0 + shift[0])
                            f = (t_ - kd * (py0 + shift[1])) if kd > 0 else (t_ - kd * (py1 + shift[1]))
                            self.ctm_fixed += 1
                    det = a * d - b * c
                    inv = (d / det, -b / det, -c / det, a / det, e, f) if det else None
                # 描边也算墨迹（浏览器命中测试含描边）：MathJax 字形 stroke = currentColor、stroke-width 3（字形单位，约 0.02 屏幕 px）
                half = (g.get("sw") or 0) / 2 if (g.get("stroke") or "none") != "none" else 0.0
                self.glyphs.append(dict(m=mi, k=k, c=nfkc(g["c"]), r=g["r"], polys=polys, shift=shift, inv=inv, clip=clip, half=half))
        self.glyph_grid = Grid([g["r"] for g in self.glyphs])
        self.media = L["media"]
        self.media_grid = Grid([q["r"] for q in self.media])

    # ---- 命中 ----
    @staticmethod
    def _in(q, x, y, e):
        return q[0] - e <= x <= q[2] + e and q[1] - e <= y <= q[3] + e

    def _blocked(self, rx, ry, ni=None):
        """点在（画在这个字上面的）公式容器或图里：caretRangeFromPoint 给的不是文字节点。同层内联内容按文档顺序画，
        后画的在上面：只有文档顺序在文字节点 ni 之后的公式（序号 ≥ 该节点的 mb）才挡住它；ni 为 None 时任何公式都挡。"""
        mb = self.L["text"][ni].get("mb", 0) if ni is not None else 0
        for k in self.cont_grid.near(rx, ry):
            if k >= mb and self._in(self.cont_rects[k], rx, ry, 0):
                return True
        for k in self.media_grid.near(rx, ry):
            q = self.media[k]["r"]
            if q[2] > q[0] and self._in(q, rx, ry, 0):
                return True
        return False

    def _caret(self, rx, ry, e):
        """插入点 (节点序号, 偏移) 或 None。"""
        inside = [k for k in self.char_grid.near(rx, ry) if self.chars[k][2] <= rx <= self.chars[k][4] and self.chars[k][3] <= ry <= self.chars[k][5]
                  and self.chars[k][4] > self.chars[k][2]]
        if inside:
            # 点在字框里：插入点就是这个字（不是按左右半边取整；quick#2 实测点在右半边 0.52–0.55 处浏览器仍给这个字）。
            # 相邻字框有亚像素重叠时取左边界最大（最靠后）的那个：quick#3 实测 x = 527.98 落在「6」[520.34, 527.98] 与「.」[527.97, 531.80] 的重叠里，浏览器给「.」
            k = max(inside, key=lambda k: (self.chars[k][2], k))
            return self.chars[k][0], self.chars[k][1]
        if e <= 0:
            return None
        best = None
        for k in self.line_grid.near(rx, ry):
            l, t, r, b = self.line_rects[k]
            if not (t <= ry <= b) or r <= l:
                continue
            dx = max(l - rx, 0.0, rx - r)
            if dx <= e and (best is None or dx < best[0]):
                best = (dx, k)
        if best is None:
            return None
        ni, o, l, t, r, b = self.chars[best[1]]
        return ni, (o + 1 if rx > r else o)

    def _glyph_hit(self, rx, ry):
        hit = None
        for k in self.glyph_grid.near(rx, ry):
            g = self.glyphs[k]
            if not self._in(g["r"], rx, ry, 0) or (g["clip"] and not self._in(g["clip"], rx, ry, 0)):
                continue
            if g["polys"] is None:
                ok = True
            elif g["inv"] is None:
                ok = False
            else:
                ia, ib, ic, idd, e, f = g["inv"]
                X, Y = rx - e, ry - f
                ux, uy = ia * X + ic * Y - g["shift"][0], ib * X + idd * Y - g["shift"][1]
                ok = winding(g["polys"], ux, uy) != 0 or (g["half"] > 0 and edge_dist(g["polys"], ux, uy) <= g["half"])
            if ok and (hit is None or k > hit):
                hit = k
        return hit

    def hit(self, rx, ry, e):
        """同 PROBE_JS hit(x, y, e)：返回 (key, 字, 外框 [l, t, r, b], where) 或 None。"""
        sx_, sy_ = rx + self.cur_f[0], ry + self.cur_f[1]   # 屏幕坐标：盖在正文上的固定 / 粘性元素按视口坐标挡字
        covered = any(q[0] <= sx_ <= q[2] and q[1] <= sy_ <= q[3] for q in self.overlays)
        cr = None if covered else self._caret(rx, ry, e)
        if cr and not self._blocked(rx, ry, cr[0]):
            if cr:
                ni, o0 = cr
                d = self.L["text"][ni]["d"]
                for o in (o0, o0 - 1):
                    if o < 0 or o >= len(d) or d[o] in JS_WS:
                        continue
                    k = self.node_char[ni].get(o)
                    if k is None:
                        continue
                    _, _, l, t, r, b = self.chars[k]
                    if r - l and self._in((l, t, r, b), rx, ry, e):
                        n = self.L["text"][ni]
                        p = n["p0"] + js_ws_strip_len(d[:o])
                        return ("t", ni, o), d[o], (l, t, r, b), ("p", p)
        g = self._glyph_hit(rx, ry)
        if g is not None:
            G = self.glyphs[g]
            return ("g", g), G["c"], tuple(G["r"]), ("m", G["m"], G["k"])
        return None

    def lh_of(self, h):
        if h is None:
            return self.L["art_lh"]
        if h[0][0] == "t":
            return self.L["text"][h[0][1]]["lh"]
        return self.L["maths"][self.glyphs[h[0][1]]["m"]]["lh"]


def _seg_d2(X, Y, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = np.clip(((X - ax) * dx + (Y - ay) * dy) / L2, 0, 1) if L2 else np.zeros_like(X)
    return (ax + t * dx - X) ** 2 + (ay + t * dy - Y) ** 2


def _within(X, Y, P, r):
    """每个网格点到折线的距离 ≤ r（同 PROBE_JS within）。"""
    if len(P) == 1:
        return _seg_d2(X, Y, P[0], P[0]) <= r * r
    ok = np.zeros(X.shape, dtype=bool)
    for i in range(1, len(P)):
        ok |= _seg_d2(X, Y, P[i - 1], P[i]) <= r * r
    return ok


def _axis(a0, a1, st):
    """for (v = a0; v <= a1; v += st) 的取值（逐次累加，与 JS 浮点一致）。"""
    out, v = [], a0
    while v <= a1:
        out.append(v)
        v += st
    return out


def _grid_hits(lay, P, x0, x1, y0, y1, st, r, fx, fy, neigh):
    xs, ys = _axis(x0, x1, st), _axis(y0, y1, st)
    if not xs or not ys:
        return
    X, Y = np.meshgrid(np.array(xs), np.array(ys))   # 行 = y，列 = x：先 y 后 x，与 JS 双重循环同序
    ok = _within(X, Y, P, r)
    for yi, xi in zip(*np.nonzero(ok)):
        h = lay.hit(xs[xi] - fx, ys[yi] - fy, 0)
        if h and h[0] not in neigh:
            neigh[h[0]] = h


SCROLL_RULES = {
    "round": lambda v, dpr: math.floor(v + 0.5),
    "floor": lambda v, dpr: math.floor(v),
    "ceil": lambda v, dpr: math.ceil(v),
    "device_px": lambda v, dpr: math.floor(v * dpr + 0.5) / dpr,
    "none": lambda v, dpr: v,
}


def scroll_rule(L):
    """设备页实测的 [目标, 实际 scrollY] 对上哪种取整（按 SCROLL_RULES 顺序第一个全对上的）；没有实测或都对不上返回 None。"""
    obs, dpr = L.get("scroll_rule") or [], L.get("dpr", 1)
    for name, fn in SCROLL_RULES.items():
        if obs and all(abs(fn(t, dpr) - a) < 1e-9 for t, a in obs):
            return name
    return None


def scroll_for(lay, abs0):
    """probe_page 的滚动：scrollTo(max(0, 起点页面 y − innerHeight / 2))，按这台设备的取整规则取整，再夹到 [0, 最大滚动]。返回 (scrollX, scrollY)。"""
    y = lay.page_f[1] + abs0[1] * lay.s
    v = max(0.0, y - lay.inner[1] / 2)
    rule = SCROLL_RULES[lay.rule or "none"]
    return lay.L["scroll"][0], min(rule(v, lay.L.get("dpr", 1)), lay.max_scroll[1])


def pressed_hits(pre):
    """设备上原样跑的压住段（build_devcheck.PRESSED_JS）结果 → 与 Layout.hit 同形的命中项列表。"""
    out = []
    for c, ident, l, t, r, b in pre["pressed"]:
        where = ("p", int(ident[1:])) if ident[0] == "p" else ("m", *map(int, ident[1:].split(":")))
        out.append((("dev", ident), c, (l, t, r, b), where))
    return out


def probe(lay, sid, grid_px, sample_px, scroll=None, pre=None):
    """一笔的 PROBE_JS 结果（state / pressed / neigh / sec / pos / mids / ref / off / box / media / nc / noff / nd / cand），无 tm。
    pre 给了（设备上原样跑的压住段结果）：压住串、行高、滚动都用它，只有邻域网格用几何。"""
    st = next((s for s in lay.L["strokes"] if s["id"] == sid), None)
    if pre is not None and pre.get("state") != "ok":
        return {"state": pre.get("state")}
    if st is None or st["state"] != "ok" or not st["abs"]:
        return {"state": st["state"] if st else "none"}
    if pre is not None:
        scroll = tuple(pre["scroll"])
    sx, sy = scroll or scroll_for(lay, st["abs"][0])
    fx, fy, s = lay.page_f[0] - sx, lay.page_f[1] - sy, lay.s
    lay.cur_f = (fx, fy)
    W, H = lay.inner
    pad = (st["w"] or 2.4) / 2 * s + 1
    P = [(fx + p[0] * s + 0, fy + p[1] * s + 0) for p in st["abs"]]
    S = []
    for i in range(len(P)):
        if i == 0:
            S.append(P[0])
            continue
        (x0, y0), (x1, y1) = P[i - 1], P[i]
        n = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / sample_px))
        for k in range(1, n + 1):
            S.append((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n))
    in_view = sum(1 for x, y in S if x >= 0 and y >= 0 and x < W and y < H)
    if in_view < len(S) and (S[0][1] < 0 or S[0][1] >= H):
        return {"state": "offscreen"}
    if pre is not None:
        pressed, lh = pressed_hits(pre), pre["lh"]
    else:
        pressed, seen = [], set()
        for x, y in S:
            h = lay.hit(x - fx, y - fy, pad)
            if h and h[0] not in seen:
                seen.add(h[0])
                pressed.append(h)
        lh = lay.lh_of(pressed[0] if pressed else None)
    xs, ys = [p[0] for p in P], [p[1] for p in P]
    B = dict(l=min(xs), t=min(ys), r=max(xs), b=max(ys))
    Pa = np.array(P)
    neigh = {}
    _grid_hits(lay, Pa, max(0, B["l"] - lh), min(W - 1, B["r"] + lh), max(0, B["t"] - lh), min(H - 1, B["b"] + lh), grid_px, lh, fx, fy, neigh)
    k = 1
    while not neigh and k <= 6:
        r = lh * 2 ** k
        stp = max(grid_px, r / 16)
        _grid_hits(lay, Pa, max(0, B["l"] - r), min(W - 1, B["r"] + r), max(0, B["t"] - r), min(H - 1, B["b"] + r), stp, r, fx, fy, neigh)
        k += 1
    scr = lambda h: (h[2][0] + fx, h[2][1] + fy, h[2][2] + fx, h[2][3] + fy)   # 屏幕框 l, t, r, b
    order = sorted(neigh.values(), key=lambda h: (js_round(scr(h)[1] / 4), scr(h)[0]))
    x0, y0 = P[0]
    dist = lambda q: math.hypot(max(q[0] - x0, 0, x0 - q[2]), max(q[1] - y0, 0, y0 - q[3]))
    ref = pressed[0] if pressed else (sorted(order, key=lambda h: dist(scr(h)))[0] if order else None)
    media = None
    for m in lay.media:
        q = (m["r"][0] + fx, m["r"][1] + fy, m["r"][2] + fx, m["r"][3] + fy)
        qw, qh = q[2] - q[0], q[3] - q[1]
        if qw and 2 * sum(1 for x, y in S if q[0] <= x <= q[2] and q[1] <= y <= q[3]) > len(S):
            media = {"src": m["src"], "rel": [(B["l"] - q[0]) / qw, (B["t"] - q[1]) / qh], "size": [qw / s, qh / s]}
            break
    sec = None
    for h in lay.L["heads"]:
        if h["t"] + fy <= B["t"]:
            sec = h["s"]
        else:
            break
    ident = lambda h: (f"p{h[3][1]}" if h[3][0] == "p" else f"m{h[3][1]}:{h[3][2]}")
    allh = pressed + order
    cand, cs = [], set()
    for h in allh:
        i = ident(h)
        if i in cs:
            continue
        cs.add(i)
        q = scr(h)
        cand.append([i, h[1], (x0 - q[0]) / s, (y0 - q[1]) / s, dist(q)])
    cand.sort(key=lambda c: c[4])
    rq = scr(ref) if ref else None
    return {"state": "ok", "pressed": "".join(h[1] for h in pressed), "neigh": "".join(h[1] for h in order), "sec": sec,
            "pos": sorted({h[3][1] for h in allh if h[3][0] == "p"}), "mids": sorted({h[3][1] for h in allh if h[3][0] == "m"}),
            "ref": ref[1] if ref else None, "off": [(x0 - rq[0]) / s, (y0 - rq[1]) / s] if ref else None,
            "box": [B["l"] + sx, B["t"] + sy, B["r"] - B["l"], B["b"] - B["t"]], "media": media,
            "nc": [h[1] for h in order], "noff": [[(x0 - scr(h)[0]) / s, (y0 - scr(h)[1]) / s] for h in order],
            "nd": [dist(scr(h)) for h in order], "cand": cand}


def probe_all(L, grid_px, sample_px, scrolls=None, pressed=None, only=None):
    """一页全部笔（only 给了只算这些）：{笔 id: 结果}。pressed 给了（设备上原样跑的压住段，layout 模式默认有）就用它的压住串、行高、滚动；
    否则 scrolls（设备 probe 模式记下的实际滚动）或按 scroll_for 推滚动，压住串也用几何（插入点规则是近似）。"""
    lay = Layout(L)
    return {s["id"]: probe(lay, s["id"], grid_px, sample_px, (scrolls or {}).get(s["id"]), (pressed or {}).get(s["id"]))
            for s in L["strokes"] if only is None or s["id"] in only}


def layout_stats(L):
    """布局表的自检数：滚动取整规则、CTM 与字形外框不符而改用拟合的字形数、字 / 字形 / 笔数。"""
    lay = Layout(L)
    return dict(scroll_rule=lay.rule, ctm_fixed=lay.ctm_fixed, chars=len(lay.chars), glyphs=len(lay.glyphs), strokes=len(L["strokes"]))


def dump_from_layout(L):
    """第二遍偏移用的内容项坐标（同 build_devcheck.DUMP_JS 的口径：正文卡片 px）：{f, p, m, a0}。"""
    s = L["f"][2]
    p = [[c[1] / s, c[2] / s] for n in L["text"] for c in n["c"]]
    m = [[[g["r"][0] / s, g["r"][1] / s] for g in mc["g"]] for mc in L["maths"]]
    a0 = {st["id"]: (st["abs"][0] if st["abs"] else None) for st in L["strokes"]}
    return {"f": L["f"], "p": p, "m": m, "a0": a0}


__all__ = ["Layout", "probe", "probe_all", "dump_from_layout", "bisect"]
