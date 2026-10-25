"""把迁移结论写成笔记层运行时能「只靠精确匹配」还原的笔：
- 原锚点还在且整组内容原样平移（same）：存储坐标 pts 一个字节不改，锚点前后文换成新版原文。
  这样在用户自己的设备（iPad 字体、排版）上与快照完全一致，不受服务器字体影响。
- 其余（改写、挪位置、图重画）：锚到新版里对应的那个字 / 那条陈列公式 / 那张图，坐标按服务器上量的平移量换算。
- 内容没了：anchor.gone = true（运行时不画、不显示灰色笔），原锚点原样留着备查。
每笔另存 mig = {status, cover, why}（迁移说明）和 drawn（快照里的原样，第一次迁移时记下，之后不改）。"""
import copy, json, re, time

QUOTE = 30


def r2(v):
    return round(v * 100) / 100


def r4(v):
    return round(v * 10000) / 10000


def text_anchor(N, p):
    t = N['text']
    return {'type': 'text', 'exact': t[p], 'prefix': t[max(0, p - QUOTE): p], 'suffix': t[p + 1: p + 1 + QUOTE]}


def char_with_rect(N, p, step):
    while 0 <= p < len(N['text']):
        if N['rects'][p]:
            return p
        p += step
    return None


def orig_anchor_ref(O, s, absp):
    """快照里这笔的锚点在旧页上实际落在哪：('text', 位置) / ('math', 公式序号) / ('media', 序号) / ('page', None)。"""
    a, p0 = s['anchor'], s['pts'][0]
    if s['frame'] == 'px' and a['type'] == 'text':
        x, y = absp[0][0] - p0[0], absp[0][1] - p0[1]
        for p, r in enumerate(O['rects']):
            if r and abs(r[0] - x) < 0.05 and abs(r[1] - y) < 0.05 and O['text'][p] == a['exact']:
                return 'text', p
    if s['frame'] == 'norm' and a['type'] == 'math':
        for k, m in enumerate(O['maths']):
            b = m['box']
            if b and m['display'] and abs(b[0] + p0[0] * b[2] - absp[0][0]) < 0.05 and abs(b[1] + p0[1] * b[3] - absp[0][1]) < 0.05:
                return 'math', k
    if a['type'] == 'page':
        return 'page', None
    return a['type'], None


def build(O, N, result, maps):
    A, B, RA, RB, mp, solid = maps
    tokA = {(t[1], t[2] if t[1] == 't' else tuple(t[2])): i for i, t in enumerate(A)}
    out, expect = [], {}
    now = int(time.time() * 1000)   # 同步按 updatedAt 合并：迁移后的笔要比仓库里旧的那版新，才不会被旧锚点盖回去
    for s in O['notes']:
        r = result.get(s['id'])
        absp = O['strokes'][s['id']]['abs']
        ns = {k: copy.deepcopy(v) for k, v in s.items() if k not in ('drawn', 'mig', 'coverOn')}
        ns['drawn'] = copy.deepcopy(s.get('drawn') or {k: s[k] for k in ('pts', 'frame', 'anchor', 'orig')})
        ns['updatedAt'] = now
        ns['mig'] = {'status': r['status'], 'cover': r.get('cover', ''), **({'why': r['why']} if r.get('why') else {})}
        if r['kind'] == 'gone':
            ns['anchor'] = dict(s['anchor'], gone=True)
            out.append(ns); expect[s['id']] = None; continue
        if r['kind'] == 'media':
            m = N['media'][r['new_media']]; b = m['box']
            ns['anchor'] = {'type': 'media', 'src': m['src'], 'ctx': N['text'][max(0, m['pos'] - QUOTE): m['pos']]}
            ns['frame'] = 'norm'
            ns['orig'] = {'x': r2(b[0]), 'y': r2(b[1]), 'w': r2(b[2]), 'h': r2(b[3])}
            ns['pts'] = s['pts'] if r['status'] == 'same' and s['frame'] == 'norm' else [[r4(x), r4(y), pr] for x, y, pr in r['norm']]
            expect[s['id']] = [(b[0] + x * b[2], b[1] + y * b[3]) for x, y, _ in ns['pts']]
            out.append(ns); continue
        dx, dy = r['delta']
        new_abs = [(p[0] + dx, p[1] + dy) for p in absp]
        expect[s['id']] = new_abs
        kind, ref = orig_anchor_ref(O, s, absp)
        kept = False
        if r['status'] == 'same' and ref is not None:
            if kind == 'text':
                i = tokA.get(('t', ref))
                if i is not None and solid[i] and mp[i] >= 0 and RA[i] and RB[mp[i]] \
                        and abs(RB[mp[i]][0] - RA[i][0] - dx) < 0.5 and abs(RB[mp[i]][1] - RA[i][1] - dy) < 0.5:
                    p = B[mp[i]][2]
                    ns['anchor'] = text_anchor(N, p); ns['frame'] = 'px'
                    q = N['rects'][p]; ns['orig'] = {'x': r2(q[0]), 'y': r2(q[1]), 'w': r2(q[2]), 'h': r2(q[3])}
                    ns['pts'] = s['pts']; kept = True
            elif kind == 'math':
                # 公式原样（TeX 相同、全部符号原样对上同一条新公式、平移量一致）：整条公式的比例坐标不变
                om = O['maths'][ref]
                js = [mp[tokA[('g', (ref, gi))]] for gi in range(len(om['ch']))]
                ks = {B[j][2][0] for j in js if j >= 0 and B[j][1] == 'g'}
                if len(ks) == 1 and all(j >= 0 for j in js):
                    k = ks.pop(); nm = N['maths'][k]
                    if nm['tex'] == om['tex'] and nm['display'] and len(nm['ch']) == len(om['ch']) \
                            and abs(nm['box'][2] - om['box'][2]) < 0.5 and abs(nm['box'][0] - om['box'][0] - dx) < 0.5 \
                            and abs(nm['box'][1] - om['box'][1] - dy) < 0.5:
                        ns['anchor'] = {'type': 'math', 'tex': nm['tex'], 'ctx': N['text'][max(0, nm['pos'] - QUOTE): nm['pos']]}
                        ns['frame'] = 'norm'; b = nm['box']
                        ns['orig'] = {'x': r2(b[0]), 'y': r2(b[1]), 'w': r2(b[2]), 'h': r2(b[3])}
                        ns['pts'] = s['pts']; kept = True
        if not kept:
            j = r['new_tok']; t = B[j]
            if t[1] == 'g' and N['maths'][t[2][0]]['display']:
                nm = N['maths'][t[2][0]]; b = nm['box']
                ns['anchor'] = {'type': 'math', 'tex': nm['tex'], 'ctx': N['text'][max(0, nm['pos'] - QUOTE): nm['pos']]}
                ns['frame'] = 'norm'
                ns['orig'] = {'x': r2(b[0]), 'y': r2(b[1]), 'w': r2(b[2]), 'h': r2(b[3])}
                ns['pts'] = [[r4((x - b[0]) / b[2]), r4((y - b[1]) / b[3]), p[2]] for (x, y), p in zip(new_abs, absp)]
            else:
                if t[1] == 't':
                    p = t[2]
                else:   # 行内公式里的符号：运行时只认正文字，锚到公式后面第一个字（没有就前面那个字）
                    pos = N['maths'][t[2][0]]['pos']
                    p = char_with_rect(N, pos, 1)
                    if p is None or p - pos > 3:
                        p = char_with_rect(N, pos - 1, -1)
                q = N['rects'][p]
                ns['anchor'] = text_anchor(N, p); ns['frame'] = 'px'
                ns['orig'] = {'x': r2(q[0]), 'y': r2(q[1]), 'w': r2(q[2]), 'h': r2(q[3])}
                ns['pts'] = [[r2(x - q[0]), r2(y - q[1]), p_[2]] for (x, y), p_ in zip(new_abs, absp)]
            # 用存下的（取整后的）坐标重算期望位置
            b = ns['orig']
            expect[s['id']] = ([(b['x'] + x * b['w'], b['y'] + y * b['h']) for x, y, _ in ns['pts']] if ns['frame'] == 'norm'
                               else [(q[0] + x, q[1] + y) for x, y, _ in ns['pts']])
        ns['mig']['kept'] = kept
        out.append(ns)
    return out, expect


def write_page(new_html, strokes, tombstones, out_html, saved, assets_prefix=None):
    """新版页面（含笔记层 JS）里嵌着的笔记换成迁移后的笔；页面其余字节不动。
    assets_prefix：输出页和新版页不在同一目录时，图片 / 视频路径前面加的相对路径（如 '../2/'）。"""
    s = open(new_html, encoding='utf-8').read()
    if assets_prefix:
        s = re.sub(r'((?:src|href|poster)=")assets/', lambda m: m.group(1) + assets_prefix + 'assets/', s)
    k = s.index('window.NIPC_SNAPSHOT = ') + len('window.NIPC_SNAPSHOT = ')
    d, e = json.JSONDecoder().raw_decode(s, k)
    d['strokes'] = strokes; d['tombstones'] = tombstones; d['saved'] = saved
    body = json.dumps(d, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    open(out_html, 'w', encoding='utf-8').write(s[:k] + body + s[e:])
