"""笔记迁移：把「笔画在旧版页面上的样子」原样搬到新版页面（不依赖笔记层运行时的模糊匹配）。

思路（一条规则，没有可调门槛的规则叠加）：
  1. 两版页面在同一个无头 Chromium、同一宽度下打开，展开全部折叠，量出每个正文字、每个公式符号的矩形；
     旧版上每一笔实际画在哪（笔记层自己画出来的位置，即用户确认过的样子）。
  2. 把整页内容排成一条记号流：正文字 + 公式符号（按文档先后，公式插在它所在的位置），旧版、新版各一条，
     做一次全局 diff（difflib，最长公共块递归）。diff 里原样保留的记号 = 「同一个内容」；
     一对一的短替换（d → δ、t → q 这种只换字母）也算同一个内容。
  3. 一笔（或连着写的一组笔）压住 / 挨着的内容记号 = 中心落在笔画外框里的记号；一个都没有（下划线、旁注）
     就取外框附近最近的那一行 / 那一个。
  4. 这些记号在新版里还在 → 整组笔刚性平移 Δ = 新矩形 − 旧矩形（取组里的「锚记号」）。
     原笔的锚字本身还在、且压住的内容平移量一致 → 笔的存储坐标一个字节不改，只把锚点前后文换成新版原文
     （这样在用户 iPad 上与原来完全一致，和服务器字体无关）。
     压住的内容在 diff 里删了 → 在新版里找同一串内容（只在新增的那些地方找），用前后文挑；找不到 → 内容没了，隐藏。
  5. 输出的锚点都是新版原文里一字不差、能唯一定位的 TextQuote / 公式 TeX / 图片 src，
     运行时只走「精确匹配」分支，不会再被运行时的模糊匹配挪走。
"""
import json, sys, math, difflib, collections
import figmatch

QUOTE = 30


def load(p):
    return json.load(open(p, encoding='utf-8'))


def stream(G):
    """记号流：[(值, 类型, 定位)]，类型 't'（正文字，定位 = 文字索引位置）或 'g'（公式符号，定位 = (公式序号, 符号序号)）。"""
    by_pos = collections.defaultdict(list)
    for k, m in enumerate(G['maths']):
        by_pos[m['pos']].append(k)
    toks, rects = [], []
    text = G['text']
    for p in range(len(text) + 1):
        for k in by_pos.get(p, []):
            m = G['maths'][k]
            for i, c in enumerate(m['ch']):
                toks.append((c, 'g', (k, i))); rects.append(m['q'][i])
        if p < len(text):
            c = text[p]
            if c == ' ':
                continue  # 空白不参与内容比对（行内公式删掉后留下的空格不算改动）
            toks.append((c, 't', p)); rects.append(G['rects'][p])
    return toks, rects


def align(A, B):
    """旧记号序号 → 新记号序号（-1 = 新版里没有）。等长短替换（≤ 3 个记号，前后都是原样的内容）按位置一一对应。"""
    a = [t[0] for t in A]; b = [t[0] for t in B]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    mp = [-1] * len(a); kind = [''] * len(a)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            for k in range(i2 - i1):
                mp[i1 + k] = j1 + k; kind[i1 + k] = 'eq'
        elif op == 'replace' and i2 - i1 == j2 - j1 and i2 - i1 <= 3:
            for k in range(i2 - i1):
                mp[i1 + k] = j1 + k; kind[i1 + k] = 'sub'
    inv = [-1] * len(b)
    for i, j in enumerate(mp):
        if j >= 0:
            inv[j] = i
    return mp, kind, inv


def bbox(abs_pts, pad):
    xs = [p[0] for p in abs_pts]; ys = [p[1] for p in abs_pts]
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def center(r):
    return r[0] + r[2] / 2, r[1] + r[3] / 2


def rdist(r, x, y):
    dx = max(r[0] - x, 0, x - r[0] - r[2]); dy = max(r[1] - y, 0, y - r[1] - r[3])
    return math.hypot(dx, dy)


class Grid:
    """记号矩形的空间索引（按 64px 格子）。"""
    def __init__(self, rects):
        self.rects = rects; self.cells = collections.defaultdict(list)
        for i, r in enumerate(rects):
            if not r or (r[2] <= 0 and r[3] <= 0):
                continue
            for gx in range(int(r[0] // 64), int((r[0] + r[2]) // 64) + 1):
                for gy in range(int(r[1] // 64), int((r[1] + r[3]) // 64) + 1):
                    self.cells[(gx, gy)].append(i)

    def query(self, x0, y0, x1, y1):
        out = set()
        for gx in range(int(x0 // 64), int(x1 // 64) + 1):
            for gy in range(int(y0 // 64), int(y1 // 64) + 1):
                out.update(self.cells.get((gx, gy), ()))
        return out


def covered(abs_pts, w, tool, grid, slack=0.0):
    """一笔压住的记号；没有就取挨着的（下划线：横向在笔画范围内、竖直最近的那一行；旁注：最近的那一个）。
    返回 (记号序号列表, 方式)。"""
    pad = (w / 2 if tool == 'hl' else max(1.5, w / 2)) + slack
    x0, y0, x1, y1 = bbox(abs_pts, pad)
    near = grid.query(x0 - 40, y0 - 40, x1 + 40, y1 + 40)
    R = grid.rects
    inside = [i for i in near if x0 <= center(R[i])[0] <= x1 and y0 <= center(R[i])[1] <= y1]
    if inside:
        return sorted(inside), 'cover'
    pts = [(p[0], p[1]) for p in abs_pts[:: max(1, len(abs_pts) // 40)]] + [(abs_pts[-1][0], abs_pts[-1][1])]
    d = {i: min(rdist(R[i], x, y) for x, y in pts) for i in near}
    over = [i for i in d if x0 <= center(R[i])[0] <= x1 and d[i] <= 30]
    if over:
        dmin = min(d[i] for i in over)
        return sorted(i for i in over if d[i] <= dmin + 0.5 * R[i][3]), 'under'
    for rad in (30, 120, 480, 2000):
        cand = grid.query(x0 - rad, y0 - rad, x1 + rad, y1 + rad)
        dd = [(min(rdist(R[i], x, y) for x, y in pts), i) for i in cand]
        dd = [t for t in dd if t[0] <= rad]
        if dd:
            dd.sort(); return [dd[0][1]], 'near'
    return [], 'none'


def stroke_time(sid):
    try:
        return int(sid[:-6], 36)
    except ValueError:
        return 0


def group_strokes(items):
    """连着写的几笔归为一组，整组用同一个平移、一起显示或隐藏：
    时间间隔 ≤ 1.5 s 且外框相距 ≤ 25 px（一口气写下的一个记号），或者钢笔笔画外框相距 ≤ 6 px 且时间相隔 ≤ 60 s
    （停顿后接着写的同一处手写，如 ½v^(−½) 分几次写完）。可传递（并查集）。图上的笔不与正文笔并组。"""
    n = len(items)
    par = list(range(n))
    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    order = sorted(range(n), key=lambda k: stroke_time(items[k]['id']))
    for x in range(n):
        for y in range(x + 1, n):
            a, b = items[order[x]], items[order[y]]
            gap = stroke_time(b['id']) - stroke_time(a['id'])
            if gap > 60000:
                break
            if a['media'] != b['media']:
                continue
            A_, B_ = a['box'], b['box']
            d = math.hypot(max(A_[0] - B_[2], B_[0] - A_[2], 0), max(A_[1] - B_[3], B_[1] - A_[3], 0))
            if (gap <= 1500 and d <= 25) or (d <= 6 and a['s']['tool'] == b['s']['tool'] == 'pen'):
                par[find(order[x])] = find(order[y])
    groups = collections.defaultdict(list)
    for k in order:
        groups[find(k)].append(items[k])
    return sorted(groups.values(), key=lambda g: stroke_time(g[0]['id']))


def bigram_sim(a, b):
    A = {a[i:i + 2] for i in range(len(a) - 1)}; B = {b[i:i + 2] for i in range(len(b) - 1)}
    return len(A & B) / len(A | B) if A | B else 1.0


PUNCT = set('，。、；：,.;:！？!?（）()「」 ')
RENAME = {}   # 旧记号 → 新记号的字母换名（t → q 等），main 里由 diff 的短替换统计出来
SOLID = 4   # diff 里原样保留的一段至少这么多个记号，才算「这里的内容没变」（1–3 个字的零碎匹配在改写过的段落里到处都是）


def solidity(A, mp, kind):
    """旧记号 i 的对应是否可信：所在原样段 ≥ SOLID 个记号；短替换（d → δ）要前后紧挨着可信的原样段。"""
    n = len(A); run = [0] * n
    i = 0
    while i < n:
        if kind[i] == 'eq':
            j = i
            while j + 1 < n and kind[j + 1] == 'eq' and mp[j + 1] == mp[j] + 1:
                j += 1
            for k in range(i, j + 1):
                run[k] = j - i + 1
            i = j + 1
        else:
            i += 1
    solid = [kind[i] == 'eq' and run[i] >= SOLID for i in range(n)]
    i = 0
    while i < n:
        if kind[i] == 'sub':
            j = i
            while j + 1 < n and kind[j + 1] == 'sub':
                j += 1
            ok = i > 0 and j + 1 < n and solid[i - 1] and solid[j + 1]
            for k in range(i, j + 1):
                solid[k] = ok
            i = j + 1
        else:
            i += 1
    return solid


def edge_match(a, i0, i1, b, j0, j1, cap=12):
    """旧版 a[i0..i1] 与新版 b[j0..j1] 两侧紧挨着的记号（按字母换名后）原样相同的个数：左边往前数 + 右边往后数。"""
    n = 0
    for k in range(1, cap + 1):
        if i0 - k < 0 or j0 - k < 0 or RENAME.get(a[i0 - k], a[i0 - k]) != b[j0 - k]:
            break
        n += 1
    for k in range(1, cap + 1):
        if i1 + k >= len(a) or j1 + k >= len(b) or RENAME.get(a[i1 + k], a[i1 + k]) != b[j1 + k]:
            break
        n += 1
    return n


def occurrences(s, key, lo=0, hi=None):
    hi = len(s) if hi is None else hi
    out, st = [], lo
    while True:
        j = s.find(key, st, hi)
        if j < 0:
            return out
        out.append(j); st = j + 1


def learn_renames(A, B, mp, kind, solid):
    """全页统计：前后都是原样内容的一对一替换（旧字母 → 新字母），出现 ≥ 2 次且从没换成别的字母，就当作记号改名。"""
    cnt = collections.defaultdict(collections.Counter)
    for i, k in enumerate(kind):
        if k == 'sub' and solid[i]:
            cnt[A[i][0]][B[mp[i]][0]] += 1
    RENAME.clear()
    for o, c in cnt.items():
        (n, m), = [(n, m) for n, m in c.most_common(1)]
        if m >= 2 and m == sum(c.values()) and o.isalpha() and n.isalpha():
            RENAME[o] = n
    print('letter renames', RENAME)


def decide(cov, how, A, B, RA, RB, mp, inv, solid, a_vals, b_vals, gA, g):
    """一组笔 → {'kind': 'move', delta, old_tok, new_tok, status} 或 {'kind': 'gone', why}。

    1. 压住的记号大多（≥ 一半）在 diff 里可信地原样保留，且平移量一致 → 刚性平移（same / partial）。
       旁注、下划线（没压住内容）用笔画周围一行以内的记号一起投票，规则同上。
    2. 否则在新版对应的那一段里（前后最近的可信原样记号之间）找同一串内容：找到 → 平移到那里（rephrased）。
    3. 那一段里没有：在新版新增的内容里全页找，前后文相似才认（moved）。
    4. 都没有 → 内容没了，隐藏（gone）。"""
    def shift(i, j):
        ra, rb = RA[i], RB[j]
        return (rb[0] - ra[0], rb[1] - ra[1]) if ra and rb else None

    voters = list(cov)
    if how <= {'near', 'under'}:
        # 旁注 / 下划线：取笔画外框外扩一行（24 px）内的全部记号投票，最近的那个记号排第一
        xs = [it['box'] for it in g]
        x0 = min(b[0] for b in xs) - 24; y0 = min(b[1] for b in xs) - 24
        x1 = max(b[2] for b in xs) + 24; y1 = max(b[3] for b in xs) + 24
        hood = sorted(i for i in gA.query(x0, y0, x1, y1)
                      if x0 <= center(RA[i])[0] <= x1 and y0 <= center(RA[i])[1] <= y1)
        voters = list(cov) + [i for i in hood if i not in cov]
    good = [i for i in voters if solid[i] and mp[i] >= 0 and shift(i, mp[i])]
    base = len(voters)
    if good and 2 * len(good) >= base:
        cnt = collections.Counter()
        for i in good:
            d = shift(i, mp[i]); cnt[(round(d[0]), round(d[1]))] += 1
        best, _ = cnt.most_common(1)[0]
        inl = [i for i in good if abs(shift(i, mp[i])[0] - best[0]) <= 1.5 and abs(shift(i, mp[i])[1] - best[1]) <= 1.5]
        # 锚记号：优先压住的记号里第一个可信的
        pick = next((i for i in cov if i in inl), inl[0])
        status = 'same' if len(inl) == len(good) == len(voters) else 'partial'
        if 2 * len(inl) < base:
            status = 'reflow'   # 内容都在，但换行变了（各记号平移量不一）：按多数平移
        return {'kind': 'move', 'old_tok': pick, 'new_tok': mp[pick], 'delta': shift(pick, mp[pick]), 'status': status}

    # 要找的内容 = 压住的第一个到最后一个记号之间的整段（下划线下的上下标也算），去掉首尾标点
    i0, i1 = cov[0], cov[-1]
    while i0 < i1 and A[i0][0] in PUNCT:
        i0 += 1
    while i1 > i0 and A[i1][0] in PUNCT:
        i1 -= 1
    key = a_vals[i0:i1 + 1]
    keys = [key]
    rk = ''.join(RENAME.get(c, c) for c in key)
    if rk != key:
        keys.append(rk)
    # 新版对应段：前后最近的可信原样记号之间（core）；再各外扩 200 个记号（改写常把关键词挪到相邻句），外扩处要前后文像才认
    lo = i0 - 1
    while lo >= 0 and not (solid[lo] and mp[lo] >= 0):
        lo -= 1
    hi = i1 + 1
    while hi < len(A) and not (solid[hi] and mp[hi] >= 0):
        hi += 1
    L = mp[lo] + 1 if lo >= 0 else 0
    R = mp[hi] if hi < len(A) else len(B)
    L2, R2 = max(0, L - 200), min(len(B), R + 200)
    ctx_a = a_vals[max(0, i0 - 20): i0] + '|' + a_vals[i1 + 1: i1 + 21]
    span_a = max(1, hi - lo); rel = (i0 - lo) / span_a; span_b = max(1, R - L + 1)
    k = lo
    while k >= 0 and not (solid[k] and mp[k] >= 0 and shift(k, mp[k])):
        k -= 1
    dy_lo = shift(k, mp[k])[1] if k >= 0 else None
    return {'kind': 'search', 'i0': i0, 'i1': i1, 'keys': keys, 'L': L, 'R': R, 'ctx_a': ctx_a, 'span_a': hi - lo, 'dy_lo': dy_lo}


def search_moved(q, A, B, RA, RB, inv, solid, a_vals, b_vals):
    """内容在原段里找不到：在新版新增（没对上旧版）的内容里全页找，前后文要像。"""
    i0, i1, keys, ctx_a, key = q['i0'], q['i1'], q['keys'], q['ctx_a'], q['keys'][0]
    def shift(i, j):
        ra, rb = RA[i], RB[j]
        return (rb[0] - ra[0], rb[1] - ra[1]) if ra and rb else None
    scored = []
    for kk in keys:
        for j in occurrences(b_vals, kk):
            if any(inv[j + k] >= 0 and solid[inv[j + k]] for k in range(len(kk))):
                continue
            scored.append((bigram_sim(ctx_a, b_vals[max(0, j - 20): j] + '|' + b_vals[j + len(kk): j + len(kk) + 20]), j))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= 0.3 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.1) \
            and (len(key) >= 2 or scored[0][0] >= 0.5):
        j0 = scored[0][1]
        k = next((k for k in range(i1 - i0 + 1) if RA[i0 + k] and RB[j0 + k]), None)
        if k is not None:
            i = i0 + k
            return {'kind': 'move', 'old_tok': i, 'new_tok': j0 + k, 'delta': shift(i, j0 + k), 'status': 'moved',
                    'sim': round(scored[0][0], 2)}
    return {'kind': 'gone', 'status': 'gone', 'why': f'content gone: {key!r}'}


def local_overlap(a, i0, i1, b, j0, j1, n=10):
    """旧版关键词前后各 n 个记号里的字二元组，有多大比例也出现在新版候选前后各 n 个记号里（按字母换名）。"""
    ra = lambda s: ''.join(RENAME.get(c, c) for c in s)
    oa = ra(a[max(0, i0 - n): i0]) + '\x00' + ra(a[i1 + 1: i1 + 1 + n])
    ob = b[max(0, j0 - n): j0] + '\x00' + b[j1 + 1: j1 + 1 + n]
    A_ = {oa[k:k + 2] for k in range(len(oa) - 1) if '\x00' not in oa[k:k + 2]}
    B_ = {ob[k:k + 2] for k in range(len(ob) - 1)}
    return len(A_ & B_) / len(A_) if A_ else 0.0


def resolve_cluster(qs, A, B, RA, RB, a_vals, b_vals):
    """同一段旧文字里要重新找位置的几组笔（改写过的段落）：各组的关键词在新版对应段里找位置。候选打分 = 紧挨着的前后记号
    原样相同的个数 + 前后 10 个记号的字二元组重合 − 竖直平移量与附近没变内容不一致的程度；整段一起按叙述先后做单调对齐
    （动态规划，放进去的关键词越多越好）。返回 {组序号: (新记号位置, 分)}。"""
    coreL = min(q['L'] for q in qs); coreR = max(q['R'] for q in qs)
    # 外扩：至少 200 个记号，且不少于旧段长度（整段挪到了公式后面这类情况，核心窗口会缩成几乎为零）
    ext = max(200, max(q['span_a'] for q in qs))
    L = max(0, coreL - ext); R = min(len(B), coreR + ext)
    opts = []
    for q in qs:
        o = []
        for kk in q['keys']:
            for j in occurrences(b_vals, kk, L, R):
                if j + len(kk) > R:
                    continue
                lo_ = local_overlap(a_vals, q['i0'], q['i1'], b_vals, j, j + len(kk) - 1)
                em = edge_match(a_vals, q['i0'], q['i1'], b_vals, j, j + len(kk) - 1)
                # 多字关键词：对应段里出现就是候选；单个字 / 符号：紧挨着的前后至少有 1 个记号对得上，或前后文明显像
                if len(kk) == 1 and em < 1 and lo_ < 0.3:
                    continue
                k0 = next((t for t in range(len(kk)) if RA[q['i0'] + t] and RB[j + t]), None)
                dy = abs((RB[j + k0][1] - RA[q['i0'] + k0][1]) - q['dy_lo']) if k0 is not None and q['dy_lo'] is not None else 0
                o.append((0.1 * min(em, 10) + lo_ - 0.3 * min(1.0, dy / 600), j, len(kk)))
        o.sort(reverse=True)
        opts.append(o)
    # 动态规划：关键词按旧版先后排好，新位置也按先后（改写一般保持叙述顺序），每放进一个关键词得 1 分 + 前后文分，
    # 跳过得 0 分；求总分最大。放不进去的关键词留给下面的「夹住」和全页找
    order = sorted(range(len(qs)), key=lambda k: qs[k]['i0'])
    states = [(-1, 0.0, [])]
    for k in order:
        nxt = list(states)
        for last, sc, path in states:
            for s_, j, n in opts[k]:
                if j > last:
                    nxt.append((j + n - 1, sc + 1.0 + 0.5 * s_, path + [(k, j, round(s_, 3))]))
        keep = {}
        for last, sc, path in nxt:
            if last not in keep or sc > keep[last][1]:
                keep[last] = (last, sc, path)
        states = sorted(keep.values(), key=lambda t: -t[1])[:400]
    _, _, path = max(states, key=lambda t: t[1])
    got = {k: (j, s_) for k, j, s_ in path}
    taken = {t: k for k, (j, _) in got.items() for t in range(j, j + len(qs[k]['keys'][0]))}
    # 第二轮「夹住」：没放进去的关键词，若旧版里它前后的关键词都放好了，且它在新版这两者之间恰好出现一次（间隔 ≤ 80 个记号），就是它
    for _ in range(3):
        changed = False
        for x, k in enumerate(order):
            if k in got:
                continue
            prev = next((got[order[y]][0] for y in range(x - 1, -1, -1) if order[y] in got), None)
            nxt = next((got[order[y]][0] for y in range(x + 1, len(order)) if order[y] in got), None)
            if prev is None or nxt is None or nxt - prev > 80:
                continue
            hits = [(j, kk) for kk in qs[k]['keys'] for j in occurrences(b_vals, kk, prev + 1, nxt) if j + len(kk) <= nxt]
            if len({j for j, _ in hits}) == 1:
                if not any(t in taken for t in range(hits[0][0], hits[0][0] + len(hits[0][1]))):
                    got[k] = (hits[0][0], -1.0); changed = True
        if not changed:
            break
    return got


def plan(O, N):
    """O / N：旧版、新版页面的几何（dump.py 量出的）。返回 ({笔 id: 结论}, 每组一行的报告, 旧→新记号对应)。"""
    A, RA = stream(O); B, RB = stream(N)
    mp, kind, inv = align(A, B)
    solid = solidity(A, mp, kind)
    learn_renames(A, B, mp, kind, solid)
    gA = Grid(RA)
    a_vals = ''.join(t[0] for t in A); b_vals = ''.join(t[0] for t in B)
    text_tok_A = {t[2]: i for i, t in enumerate(A) if t[1] == 't'}
    text_tok_B = {t[2]: i for i, t in enumerate(B) if t[1] == 't'}

    notes = O['notes']
    items = []
    for s in notes:
        pl = O['strokes'].get(s['id'])
        if not pl or pl['state'] != 'ok' or not pl['abs']:
            items.append({'id': s['id'], 's': s, 'abs': None, 'box': (0, 0, 0, 0), 'media': None}); continue
        absp = pl['abs']
        media = None
        for mi, m in enumerate(O['media']):
            bx = m['box']
            if bx and 2 * sum(1 for p in absp if bx[0] <= p[0] <= bx[0] + bx[2] and bx[1] <= p[1] <= bx[1] + bx[3]) > len(absp):
                media = mi; break
        cov, how = ([], 'media') if media is not None else covered(absp, s['w'], s['tool'], gA)
        items.append({'id': s['id'], 's': s, 'abs': absp, 'box': bbox(absp, 0), 'media': media, 'cov': cov, 'how': how})

    groups = group_strokes([it for it in items if it['abs']])
    report, pending = [], []
    result = {}

    for g in groups:
        gid = g[0]['id']
        if g[0]['media'] is not None:
            m = O['media'][g[0]['media']]
            # 同名图在新版里第几张：按旧版里它前面的同名图个数
            nth = sum(1 for x in O['media'][:g[0]['media']] if x['src'] == m['src'])
            news = [k for k, x in enumerate(N['media']) if x['src'] == m['src']]
            if len(news) <= nth:
                for it in g:
                    result[it['id']] = {'kind': 'gone', 'status': 'gone', 'why': 'image removed: ' + m['src'], 'cover': m['src']}
                report.append((gid, len(g), 'media', 'gone', m['src'])); continue
            nm = N['media'][news[nth]]
            same = figmatch.same_file(m['file'], nm['file'])
            # 图没变：整组原样；图重画了：每笔单独跟它下面那块图走（标签放大、挪位置时一组里的几笔各自挪）
            for sub in ([g] if same else [[it] for it in g]):
                st, out, why = figmatch.transfer(m['file'], nm['file'], m['box'], nm['box'], [it['abs'] for it in sub])
                for it, pts in zip(sub, out or [None] * len(sub)):
                    if st == 'gone':
                        result[it['id']] = {'kind': 'gone', 'status': 'gone', 'why': f'figure {m["src"]}: {why}', 'cover': m['src']}
                    else:
                        result[it['id']] = {'kind': 'media', 'status': 'same' if st == 'same' else 'figure',
                                            'new_media': news[nth], 'old_media': g[0]['media'], 'norm': pts,
                                            'why': why, 'cover': m['src']}
                report.append((sub[0]['id'], len(sub), 'media', 'same' if st == 'same' else ('figure' if st != 'gone' else 'gone'),
                               m['src'] + ('' if st == 'same' else ' ' + why)))
            continue

        cov = sorted({i for it in g for i in it['cov']})
        how = {it['how'] for it in g}
        if not cov:
            for it in g:
                result[it['id']] = {'kind': 'gone', 'status': 'gone', 'why': 'nothing nearby', 'cover': ''}
            report.append((gid, len(g), 'none', 'gone', '')); continue
        cov_str = ''.join(A[i][0] for i in cov)
        res = decide(cov, how, A, B, RA, RB, mp, inv, solid, a_vals, b_vals, gA, g)
        res['cover'] = cov_str
        pending.append((g, res))

    # 改写过的段落：同一个旧文字块里要重找位置的组一起做单调对齐
    def blk_of(i):   # 行内公式里的符号算它所在那段文字
        p = A[i][2] if A[i][1] == 't' else O['maths'][A[i][2][0]]['pos']
        return O['blk'][min(p, len(O['blk']) - 1)]
    clusters = collections.defaultdict(list)
    for n, (g, res) in enumerate(pending):
        if res['kind'] == 'search':
            clusters[blk_of(res['i0'])].append(n)
    for key, members in clusters.items():
        got = resolve_cluster([pending[n][1] for n in members], A, B, RA, RB, a_vals, b_vals)
        for k, n in enumerate(members):
            q = pending[n][1]
            if k in got:
                j0, sim = got[k]
                kk = next(i for i in range(q['i1'] - q['i0'] + 1) if RA[q['i0'] + i] and RB[j0 + i])
                i = q['i0'] + kk
                pending[n] = (pending[n][0], {'kind': 'move', 'old_tok': i, 'new_tok': j0 + kk,
                                              'delta': (RB[j0 + kk][0] - RA[i][0], RB[j0 + kk][1] - RA[i][1]),
                                              'status': 'rephrased', 'sim': round(sim, 2), 'cover': q['cover']})
            else:
                r = search_moved(q, A, B, RA, RB, inv, solid, a_vals, b_vals)
                r['cover'] = q['cover']
                pending[n] = (pending[n][0], r)
    for g, res in pending:
        for it in g:
            result[it['id']] = dict(res)
        report.append((g[0]['id'], len(g), '/'.join(sorted({it['how'] for it in g})), res['status'], res['cover']))

    return result, report, (A, B, RA, RB, mp, solid)


def main(old_path, new_path, out_path):
    result, report, _ = plan(load(old_path), load(new_path))
    json.dump({'result': result, 'report': report}, open(out_path, 'w'), ensure_ascii=False, indent=0)
    c = collections.Counter(r[3] for r in report)
    print('groups', len(report), dict(c), 'strokes', collections.Counter(v['kind'] for v in result.values()))


if __name__ == '__main__':
    main(*sys.argv[1:4])
