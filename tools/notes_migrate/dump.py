import os, sys, json
from playwright.sync_api import sync_playwright
from browser import open_page
PROBE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'probe.js'), encoding='utf-8').read()
def dump(src, out, width=1180):
    with sync_playwright() as p:
        b, pg = open_page(p, src, width)
        d = pg.evaluate(PROBE); d['notes'] = pg.evaluate('__nipcNotes.strokes()')
        json.dump(d, open(out, 'w'), ensure_ascii=False); b.close()
        return d
if __name__ == '__main__':
    for src, out in zip(sys.argv[1::2], sys.argv[2::2]):
        d = dump(src, out); print(out, len(d['text']), len(d['maths']), len(d['media']), sum(1 for v in d['strokes'].values() if v and v['state']=='ok'))
