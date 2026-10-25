"""一条命令：量旧版 → 量新版 → 迁移 → 写预览页 → 打开预览页独立核对，0 错才算过（非零退出码 = 有错）。

  python3 run.py <快照页.html> <新版页.html> <输出页.html> [--width 1180]

--work 目录里另写 <页>.notes.json（迁移后的笔记，可直接作为笔记仓库的 notes/<页>.json）和 <页>.report.txt（每组笔的结论）。"""
import argparse, collections, json, os, sys, time
import migrate as M, build as BLD
from dump import dump

ap = argparse.ArgumentParser()
ap.add_argument('old_html'); ap.add_argument('new_html'); ap.add_argument('out_html')
ap.add_argument('--width', type=int, default=1180)
ap.add_argument('--work', default='build_tmp/notes_migrate', help='中间文件、迁移后的笔记 JSON、报告写在这里')
ap.add_argument('--assets-prefix', default=None, help="输出页找图片用的相对路径前缀，如 '../2/'")
ap.add_argument('--also', type=int, nargs='*', default=[820, 2048], help='另用这些窗口宽度再打开一遍，每笔位置要与主宽度一致')
args = ap.parse_args()
os.makedirs(args.work, exist_ok=True)
tmp = os.path.join(args.work, os.path.splitext(os.path.basename(args.out_html))[0])

O = dump(args.old_html, tmp + '.geom_old.json', args.width)
N = dump(args.new_html, tmp + '.geom_new.json', args.width)
result, report, maps = M.plan(O, N)
strokes, expect = BLD.build(O, N, result, maps)
snap = json.load(open(tmp + '.geom_old.json'))  # 旧版删除记录照搬
old_src = open(args.old_html, encoding='utf-8').read()
k = old_src.index('window.NIPC_SNAPSHOT = ') + len('window.NIPC_SNAPSHOT = ')
tombs = json.JSONDecoder().raw_decode(old_src, k)[0].get('tombstones', {})
BLD.write_page(args.new_html, strokes, tombs, args.out_html, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), args.assets_prefix)
json.dump({'format': 'nipc-notes', 'version': 1, 'page': os.path.basename(args.new_html), 'colWidth': 920,
           'strokes': strokes, 'tombstones': tombs}, open(tmp + '.notes.json', 'w'), ensure_ascii=False)

# ---------- 核对：打开写出的预览页，笔记层自己把笔画出来，量每一笔实际画在哪、压住了什么 ----------
V = dump(args.out_html, tmp + '.geom_out.json', args.width)
A, B, RA, RB, mp, solid = maps
VA, VR = M.stream(V)
gV = M.Grid(VR); gO = M.Grid(RA)
errs, lines = [], []


def still_there(vals, absp, s, T, R_, grid, slack=3.0):
    """旧页上压住的每个记号，在新页上这笔外框（外扩 slack px）里都还能找到同一个记号。"""
    pad = (s['w'] / 2 if s['tool'] == 'hl' else max(1.5, s['w'] / 2)) + slack
    x0, y0, x1, y1 = M.bbox(absp, pad)
    near = [T[i][0] for i in grid.query(x0, y0, x1, y1) if x0 <= M.center(R_[i])[0] <= x1 and y0 <= M.center(R_[i])[1] <= y1]
    pool = collections.Counter(near)
    need = collections.Counter(vals)
    return all(pool[c] >= n for c, n in need.items())

cnt = collections.Counter()
for s in O['notes']:
    sid = s['id']; r = result[sid]; e = expect[sid]; v = V['strokes'].get(sid)
    shown = bool(v and v['state'] == 'ok' and v['abs'])
    if e is None:
        cnt['hidden'] += 1
        if shown:
            errs.append((sid, 'should be hidden but is drawn'))
        continue
    if not shown:
        errs.append((sid, f'should be drawn but is {v and v["state"]}')); continue
    # 1. 运行时画的位置 = 迁移算出的位置
    d = max(max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(e, v['abs']))
    if d > 0.6:
        errs.append((sid, f'runtime drew it {d:.1f}px away from the computed place'))
    # 2. 独立核对（不用迁移的任何结论）：新页上这笔压住的内容 与 旧页上它压住的内容（字母按换名表）一样
    if r['kind'] == 'move':
        co, _ = M.covered(O['strokes'][sid]['abs'], s['w'], s['tool'], gO)
        cn, _ = M.covered(v['abs'], s['w'], s['tool'], gV)
        so = ''.join(M.RENAME.get(A[i][0], A[i][0]) for i in co); sn = ''.join(VA[i][0] for i in cn)
        def subseq(x, y):   # x 的每个记号按先后都在 y 里
            it = iter(y); return all(c in it for c in x)
        if so != sn:
            if r['status'] == 'same' and not still_there(so, v['abs'], s, VA, VR, gV) and M.covered(O['strokes'][sid]['abs'], s['w'], s['tool'], gO)[1] == 'cover':
                errs.append((sid, f'unchanged content but covers {sn!r} instead of {so!r}'))
            else:
                lines.append(f'  note {sid} [{r["status"]}] covered {so!r} → now {sn!r}')
    cnt['shown'] += 1

# 3. 换窗口宽度（iPad 竖屏 820、宽屏 2048）：窄屏时正文整体缩放，绝对位置会有亚像素取整，所以这里比的是
#    「每笔压住的内容」：快照页和预览页都在这个宽度下打开，同一笔压住的内容要和主宽度下的结论一致
def covers(G, sid, s):
    st = G['strokes'].get(sid)
    if not (st and st['state'] == 'ok' and st['abs']):
        return None
    T, R_ = M.stream(G)
    c, _ = M.covered(st['abs'], s['w'], s['tool'], M.Grid(R_))
    return ''.join(T[i][0] for i in c)
for w in args.also:
    Ow = dump(args.old_html, tmp + f'.geom_old_{w}.json', w); Vw = dump(args.out_html, tmp + f'.geom_out_{w}.json', w)
    To, Ro = M.stream(Ow); Tv, Rv = M.stream(Vw); go, gv = M.Grid(Ro), M.Grid(Rv)
    for s in O['notes']:
        sid = s['id']; r = result[sid]
        a, b = Ow['strokes'].get(sid), Vw['strokes'].get(sid)
        shown = bool(b and b['state'] == 'ok')
        if (expect[sid] is None) == shown:
            errs.append((sid, f'width {w}: shown={shown} but expected {"hidden" if expect[sid] is None else "shown"}')); continue
        if r['kind'] != 'move' or r['status'] != 'same' or not shown:
            continue
        co, _ = M.covered(a['abs'], s['w'], s['tool'], go); cn, _ = M.covered(b['abs'], s['w'], s['tool'], gv)
        so = ''.join(M.RENAME.get(To[i][0], To[i][0]) for i in co); sn = ''.join(Tv[i][0] for i in cn)
        if so != sn and not still_there(so, b['abs'], s, Tv, Rv, gv) and M.covered(a['abs'], s['w'], s['tool'], go)[1] == 'cover':
            errs.append((sid, f'width {w}: covers {sn!r} instead of {so!r}'))

with open(tmp + '.report.txt', 'w') as f:
    c = collections.Counter(x[3] for x in report)
    f.write(f'groups {len(report)} {dict(c)}\n')
    for x in report:
        f.write('\t'.join(map(str, x)) + '\n')
    f.write('\n'.join(lines) + '\n')
    for x in errs:
        f.write('ERROR ' + ' '.join(x) + '\n')
print('groups:', dict(collections.Counter(x[3] for x in report)))
print('strokes:', dict(cnt), ' errors:', len(errs))
for x in errs[:30]:
    print('  ERROR', *x)
print('\n'.join(lines[:60]))
sys.exit(1 if errs else 0)
