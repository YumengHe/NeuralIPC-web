"""核对器自测：把预览页里一笔（压住多个字的荧光笔）右移 30 px，核对必须恰好报这一笔。"""
import json, os, sys, collections, migrate as M, build as BLD
from dump import dump
out_html = sys.argv[1]; work = sys.argv[2] if len(sys.argv) > 2 else 'build_tmp/notes_migrate'
tmp = os.path.join(work, os.path.splitext(os.path.basename(out_html))[0])
notes = json.load(open(tmp + '.notes.json'))
O = json.load(open(tmp + '.geom_old.json')); V0 = json.load(open(tmp + '.geom_out.json'))
victim = next(s for s in notes['strokes'] if s['mig']['status'] == 'same' and s['tool'] == 'hl' and len(s['mig']['cover']) >= 4)
for p in victim['pts']:
    p[0] = p[0] + (30 if victim['frame'] == 'px' else 30 / victim['orig']['w'])
test_html = os.path.join(os.path.dirname(out_html), '_selftest_' + os.path.basename(out_html))
BLD.write_page(out_html, notes['strokes'], notes['tombstones'], test_html, 'selftest')
V = dump(test_html, tmp + '.geom_selftest.json'); os.remove(test_html)
A, RA = M.stream(O); VA, VR = M.stream(V); gO, gV = M.Grid(RA), M.Grid(VR)
bad = []
for s in O['notes']:
    v = V['strokes'].get(s['id']); v0 = V0['strokes'].get(s['id'])
    if not (v and v['state'] == 'ok'): continue
    d = max(max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(v['abs'], v0['abs']))
    co, how = M.covered(O['strokes'][s['id']]['abs'], s['w'], s['tool'], gO); cn, _ = M.covered(v['abs'], s['w'], s['tool'], gV)
    so = ''.join(A[i][0] for i in co); sn = ''.join(VA[i][0] for i in cn)
    if d > 0.6 or (how == 'cover' and so != sn and s['id'] == victim['id']):
        bad.append((s['id'], round(d, 1), so, sn))
print('victim', victim['id'], victim['mig']['cover'])
print('flagged', bad)
sys.exit(0 if [b[0] for b in bad] == [victim['id']] else 1)
