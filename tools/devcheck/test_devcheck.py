"""设备核对页的本地验证：无头 Chromium 模拟 iPad（820×1180、1180×820，dpr 2，iPad UA）打开 devcheck/1，和服务器 indep_check 在同宽度下比。
GitHub API 用本地假仓库代替（Playwright 拦截 api.github.com，记下每次读写），不碰真笔记仓库。

--phase collect（开浏览器，结果存 --out-dir）：
  服务器参照：indep_check.run("snap", preview/3 | snap, [820, 1180])；
  每个视口：P  = ?mode=probe&page=preview/3&noupload=1（设备上原样跑 PROBE_JS，同时导出布局表，A/B 的对拍对象）；
            R1 = ?page=preview/3（默认 layout 模式，假 token、空仓库）：测基准页 + 待测页，上传基准页缓存与结果；
            R2 = ?page=snapshot/2（假仓库里有 R1 的基准页缓存）：应复用缓存、只测待测页；
            RA = ?page=preview/3&waits=fixed&noupload=1：固定等待，与 R1 比布局表与耗时。
--phase compare（不开浏览器，读 collect 的结果）：
  t1) P 的 PROBE_JS 原始采样（去掉 tm）与服务器 indep_check.probe_page 逐笔相同。
  t8) geom_probe 由 P 的布局表重算的每笔结果与 P 的 PROBE_JS 结果对拍：字符串 / 序号逐项相同，数值差 ≤ 0.01 px；
      两种滚动各比一次（P 记下的实际滚动 / 按 probe_page 推出的滚动），不一致的逐笔逐字段写进 ab_<宽>.json。
  t2) R1（布局表 → geom_probe → judge）与服务器 indep_check.run 的逐笔表相同（判定一致，偏移差相差 ≤ 0.01 px）。
  t3) R2（snapshot/2 对自己）0 笔失败。   t4) 设备页自报的有效性问题为空。
  t5) R2 用了 R1 上传的基准页缓存，只测了一页。   t6) RA 与 R1 布局表相同，打印两者耗时。
  t7) 所有写操作都是 PUT checks/devcheck_….json，没有别的写。
用法：/bin/python -B tools/devcheck/test_devcheck.py --out-dir <NAS 目录> --phase collect|compare|all
"""
import argparse
import base64
import functools
import http.server
import json
import pathlib
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_devcheck as B   # noqa: E402
import judge_devcheck as J   # noqa: E402

IPAD_UA = "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
VIEWS = ((820, 1180), (1180, 820))
NEW_SPEC = {"preview/3": "dir:_pv3/preview/3", "snapshot/2": "snap"}   # 服务器 indep_check 打开同一份页面的写法（_pv3 与 origin/main 逐字节相同）
PATH_RE = re.compile(r"checks/devcheck_[A-Za-z0-9_]+_\d{8}T\d{6}Z\.json")
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, PUT, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Accept, X-GitHub-Api-Version, Content-Type"}
NUM_TOL = 0.01


def serve_root():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
        type("Q", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None}), directory=str(B.ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", srv


class FakeRepo:
    """假的笔记仓库 contents API：files {路径: 文本}；log 记每次请求 (方法, 路径)；bad 记不该有的请求。"""
    PREFIX = f"https://api.github.com/repos/{J.NOTES_REPO}/contents/"

    def __init__(self, files=None):
        self.files, self.log, self.bad = dict(files or {}), [], []

    def handle(self, route, request):
        url, m = request.url, request.method
        if m == "OPTIONS":
            return route.fulfill(status=204, headers=CORS)
        if not url.startswith(self.PREFIX):
            self.bad.append((m, url))
            return route.fulfill(status=403, headers=CORS, body="")
        path = url[len(self.PREFIX):].split("?")[0]
        self.log.append((m, path))
        if m == "GET" and path == "checks":
            items = [{"path": p} for p in sorted(self.files) if p.startswith("checks/")]
            return route.fulfill(status=200 if items else 404, headers=CORS, content_type="application/json", body=json.dumps(items))
        if m == "GET":
            if path not in self.files:
                return route.fulfill(status=404, headers=CORS, body="{}")
            raw = "raw" in (request.headers.get("accept") or "")
            return route.fulfill(status=200, headers=CORS, content_type="application/json",
                                 body=self.files[path] if raw else json.dumps({"sha": "fake" + str(len(self.files[path]))}))
        if m == "PUT" and PATH_RE.fullmatch(path):
            self.files[path] = base64.b64decode(json.loads(request.post_data)["content"]).decode("utf-8")
            return route.fulfill(status=201, headers=CORS, content_type="application/json", body=json.dumps({"commit": {"sha": "f" * 40}}))
        self.bad.append((m, path))
        return route.fulfill(status=403, headers=CORS, body="")


def run_device(base, view, query, repo=None):
    """无头 Chromium 模拟 iPad 打开设备页，等跑完。repo 给了就放假 token、拦截 GitHub API。返回 {res, warns, done, wall_s}。"""
    from playwright.sync_api import sync_playwright
    tag = f"{view[0]}×{view[1]} {query}"
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": view[0], "height": view[1]}, device_scale_factor=2, user_agent=IPAD_UA, has_touch=True)
        if repo is not None:
            ctx.add_init_script("try { localStorage.setItem('nipc-notes-sync', JSON.stringify({ token: 'test-token' })); } catch (e) {}")
            ctx.route("https://api.github.com/**", repo.handle)
        pg = ctx.new_page()
        pg.on("console", lambda m: m.text.startswith("[devcheck]") and print(f"   [{tag}] {m.text}", flush=True))
        pg.on("pageerror", lambda e: print(f"   [{tag}] 页面报错：{e}", flush=True))
        pg.goto(f"{base}/devcheck/1/index.html?{query}", wait_until="load")
        pg.wait_for_function("window.__devcheck", timeout=60000)
        res = pg.evaluate("window.__devcheck.done.then(r => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v.data])))")
        warns = pg.evaluate("window.__devcheck.warns")
        done = pg.inner_text("#dc-done")
        browser.close()
    wall = round(time.time() - t0, 1)
    print(f"   [{tag}] 用时 {wall} s，页面最后显示：{done!r}", flush=True)
    return dict(res=res, warns=warns, done=done, wall_s=wall)


def collect(out, IC, gmaps, cal):
    base, srv = serve_root()
    widths = [v[0] for v in VIEWS]
    for pg in NEW_SPEC:
        (out / f"server_{pg.replace('/', '_')}").mkdir(exist_ok=True)
    repos = {v: FakeRepo() for v in VIEWS}
    with ThreadPoolExecutor(12) as ex:
        ref = {pg: ex.submit(IC.run, "snap", spec, widths, out / f"server_{pg.replace('/', '_')}", gmaps, None, (0, 0), cal)
               for pg, spec in NEW_SPEC.items()}
        pr = {v: ex.submit(run_device, base, v, "mode=probe&page=preview/3&noupload=1") for v in VIEWS}
        ra = {v: ex.submit(run_device, base, v, "page=preview/3&waits=fixed&noupload=1") for v in VIEWS}
        r1 = {v: ex.submit(run_device, base, v, "page=preview/3", repos[v]) for v in VIEWS}
        r1 = {v: f.result() for v, f in r1.items()}
        r2repo = {v: FakeRepo(repos[v].files) for v in VIEWS}
        r2 = {v: ex.submit(run_device, base, v, "page=snapshot/2", r2repo[v]) for v in VIEWS}
        r2 = {v: f.result() for v, f in r2.items()}
        ra = {v: f.result() for v, f in ra.items()}
        pr = {v: f.result() for v, f in pr.items()}
        ref = {pg: f.result() for pg, f in ref.items()}
    srv.shutdown()
    for v in VIEWS:
        w = v[0]
        for name, r in (("P", pr[v]), ("R1", r1[v]), ("R2", r2[v]), ("RA", ra[v])):
            (out / f"device_{w}_{name}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        for name, repo in (("R1", repos[v]), ("R2", r2repo[v])):
            (out / f"repo_{w}_{name}.json").write_text(json.dumps(dict(log=repo.log, bad=repo.bad, files=sorted(repo.files)), ensure_ascii=False), encoding="utf-8")


def num_eq(a, b):
    """两个 JSON 值相同：字符串 / 整数 / None 严格相同，浮点差 ≤ NUM_TOL，列表 / 字典逐项。"""
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= NUM_TOL
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(num_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(num_eq(a[k], b[k]) for k in a)
    return a == b


def field_diffs(js, py):
    """一笔的 PROBE_JS 结果与 geom_probe 结果不同的字段 {字段: [JS 值, 几何值]}（tm 不比）。"""
    keys = (set(js) | set(py)) - {"tm"}
    return {k: [js.get(k), py.get(k)] for k in sorted(keys) if not num_eq(js.get(k), py.get(k))}


def compare(out, IC, gmaps, cal):
    import geom_probe as G
    fails = []

    def check(ok, name, msg):
        print(f"{'PASS' if ok else 'FAIL'} {name} {msg}", flush=True)
        if not ok:
            fails.append(name)

    for v in VIEWS:
        w, tag = v[0], f"{v[0]}×{v[1]}"
        P, R1, R2, RA = (json.loads((out / f"device_{w}_{n}.json").read_text(encoding="utf-8")) for n in ("P", "R1", "R2", "RA"))
        dP, d1, d2, dA = P["res"]["preview/3"], R1["res"]["preview/3"], R2["res"]["snapshot/2"], RA["res"]["preview/3"]
        warns = P["warns"] + R1["warns"] + R2["warns"] + RA["warns"]
        check(not warns and all(d["valid"]["ok"] for d in (dP, d1, d2, dA)), f"t4@{tag}", f"设备页自报问题：{warns}")
        sdir = out / "server_preview_3"
        for side in ("old", "new"):
            sp = json.loads((sdir / f"probe_{w}_{side}.json").read_text(encoding="utf-8"))
            diff = sorted(i for i in set(sp) | set(dP[side]["probes"]) if field_diffs(sp.get(i, {}), dP[side]["probes"].get(i, {})))
            check(not diff, f"t1@{tag}:{side}", f"设备 PROBE_JS 与服务器 {dP[side]['page']}：{len(sp)} 笔，不同 {len(diff)} 笔 {diff[:5]}")
        ab = {}
        for side in ("old", "new"):
            run = dP[side]
            for how, kw in (("设备压住段+几何邻域", dict(pressed=run["pressed"])), ("全几何", dict(scrolls=run["scrolls"]))):
                t0 = time.time()
                geo = G.probe_all(run["layout"], IC.RP_GRID, IC.RP_SAMPLE, **kw)
                el = time.time() - t0
                bad = {i: field_diffs(run["probes"][i], geo.get(i, {})) for i in run["probes"]}
                bad = {i: d for i, d in bad.items() if d}
                ab[f"{side}:{how}"] = bad
                by = {}
                for d in bad.values():
                    for k in d:
                        by[k] = by.get(k, 0) + 1
                msg = f"{run['page']}：{how} 与 PROBE_JS 不同 {len(bad)}/{len(run['probes'])} 笔，按字段 {by}；几何重算 {el:.1f} s"
                if how == "全几何":   # 只作参考（插入点规则是近似），不算失败；交付走的是「设备压住段 + 几何邻域」
                    print(f"INFO t8@{tag}:{side}:{how} {msg}", flush=True)
                else:
                    check(not bad, f"t8@{tag}:{side}", msg)
        (out / f"ab_{w}.json").write_text(json.dumps(ab, ensure_ascii=False, indent=1), encoding="utf-8")
        srows = {r["id"]: r for r in json.loads((sdir / f"table_{w}.json").read_text(encoding="utf-8"))}
        rows = J.judge_rows(IC, d1["old"], d1["new"], gmaps, cal)
        J.write_table(rows, out, f"{w}_device_R1")
        bad = [r["id"] for r in rows if r["verdict"] != srows[r["id"]]["verdict"] or (r["off_diff"] is None) != (srows[r["id"]]["off_diff"] is None)
               or (r["off_diff"] is not None and abs(r["off_diff"] - srows[r["id"]]["off_diff"]) > NUM_TOL)]
        check(not bad, f"t2@{tag}", f"preview/3 布局表判定与服务器不同 {len(bad)} 笔 {bad[:5]}；设备判错 {sum(r['verdict'] == '错' for r in rows)}，"
              f"服务器判错 {sum(r['verdict'] == '错' for r in srows.values())}")
        rows2 = J.judge_rows(IC, d2["old"], d2["new"], gmaps, cal)
        f3 = [r["id"] for r in rows2 if r["verdict"] in IC.FAIL_VERDICTS]
        check(not f3, f"t3@{tag}", f"snapshot/2 对自己：失败 {len(f3)} 笔 {f3[:5]}")
        rp1 = json.loads((out / f"repo_{w}_R1.json").read_text(encoding="utf-8"))
        rp2 = json.loads((out / f"repo_{w}_R2.json").read_text(encoding="utf-8"))
        ok5 = d2["base_cached"] and d2["base_ref"] == d1["base_ref"] and d2["base_ref"] in rp1["files"] and d2["old"] == d1["old"]
        check(ok5, f"t5@{tag}", f"R2 复用基准页 {d2['base_ref']}；R1 用时 {R1['wall_s']} s（两页 {d1['old']['ms']} / {d1['new']['ms']}），"
              f"R2 用时 {R2['wall_s']} s（只测待测页 {d2['new']['ms']}）")
        same = dA["old"]["layout"] == d1["old"]["layout"] and dA["new"]["layout"] == d1["new"]["layout"]
        check(same, f"t6@{tag}", f"固定等待 vs 等布局稳定 布局表相同 {same}；用时 固定 {RA['wall_s']} s（{dA['old']['ms']} / {dA['new']['ms']}），"
              f"稳定 {R1['wall_s']} s；设备 PROBE_JS 模式 {P['wall_s']} s")
        puts = [p for m, p in rp1["log"] + rp2["log"] if m == "PUT"]
        check(not rp1["bad"] and not rp2["bad"] and puts and all(PATH_RE.fullmatch(p) for p in puts), f"t7@{tag}", f"写操作 {puts}，越界请求 {rp1['bad'] + rp2['bad']}")
    print(f"== 失败 {len(fails)} 项 {fails}")
    return fails


def quick(out, IC, every, run_browser):
    """几何对拍快速迭代：820 视口 P 模式每 every 笔跑一笔（run_browser 时开浏览器，存 device_820_Pq.json），然后只做 t8，逐笔列不一致字段。"""
    import geom_probe as G
    f = out / "device_820_Pq.json"
    if run_browser:
        base, srv = serve_root()
        f.write_text(json.dumps(run_device(base, VIEWS[0], f"mode=probe&every={every}&page=preview/3&noupload=1"), ensure_ascii=False), encoding="utf-8")
        srv.shutdown()
    P = json.loads(f.read_text(encoding="utf-8"))["res"]["preview/3"]
    for side in ("old", "new"):
        run = P[side]
        only = set(run["probes"])
        t0 = time.time()
        geo = G.probe_all(run["layout"], IC.RP_GRID, IC.RP_SAMPLE, pressed=run["pressed"], only=only)
        el = time.time() - t0
        geo2 = G.probe_all(run["layout"], IC.RP_GRID, IC.RP_SAMPLE, run["scrolls"], only=only)
        bad = {i: field_diffs(run["probes"][i], geo[i]) for i in run["probes"]}
        bad = {i: d for i, d in bad.items() if d}
        bad2 = sum(bool(field_diffs(run["probes"][i], geo2[i])) for i in run["probes"])
        prs = sum(run["pressed"][i].get("state") != run["probes"][i].get("state") or
                  "".join(p[0] for p in run["pressed"][i].get("pressed", [])) != (run["probes"][i].get("pressed") or "") for i in only)
        print(f"== {side} {run['page']}：{len(run['probes'])} 笔；设备压住段 + 几何邻域 与 PROBE_JS 不同 {len(bad)}（{el:.1f} s）；"
              f"全几何（实际滚动）不同 {bad2}；设备压住段（不等帧）与 PROBE_JS 压住串不同 {prs}", flush=True)
        for i, d in list(bad.items())[:12]:
            print(f"   {i}: " + "；".join(f"{k}: JS={str(a)[:160]} | 几何={str(b)[:160]}" for k, (a, b) in d.items()), flush=True)


def diag(out, IC):
    """几何对拍不一致的诊断：对 quick 结果里 JS 邻域有、几何没有的字形，报它的路径命令种类、外框内墨迹占比（0.5 px 点阵）、
    以及笔附近网格点（PROBE_JS 同口径）落在外框里却被几何判为不在墨迹里的个数与离墨迹边最近的距离。"""
    import numpy as np
    import geom_probe as G
    P = json.loads((out / "device_820_Pq.json").read_text(encoding="utf-8"))["res"]["preview/3"]
    for side in ("old", "new"):
        run = P[side]
        lay = G.Layout(run["layout"])
        geo = G.probe_all(run["layout"], IC.RP_GRID, IC.RP_SAMPLE, pressed=run["pressed"], only=set(run["probes"]))
        for sid, js in run["probes"].items():
            if js.get("state") != "ok" or js.get("nc") == geo[sid].get("nc"):
                continue
            jsid = {c[0] for c in js["cand"]}
            gid = {c[0] for c in geo[sid]["cand"]}
            for ident in sorted(jsid ^ gid):
                kind = "漏了" if ident in jsid else "多了"
                if ident[0] != "m":
                    p = int(ident[1:])
                    hit = [(ni, o, c) for ni, n in enumerate(run["layout"]["text"]) for (o, *c) in n["c"]
                           if n["p0"] + G.js_ws_strip_len(n["d"][:o]) == p]
                    ni, o, rect = hit[0]
                    n = run["layout"]["text"][ni]
                    over = [(k, [round(v, 1) for v in m["r"]]) for k, m in enumerate(run["layout"]["maths"])
                            if m["r"][0] < rect[2] and m["r"][2] > rect[0] and m["r"][1] < rect[3] and m["r"][3] > rect[1]]
                    print(f"   {side} {sid}：几何{kind}正文 {ident}「{n['d'][o]}」框 {[round(v, 1) for v in rect]} 节点 mb={n.get('mb')}，与之相交的公式容器 {over}")
                    st = next(s for s in run["layout"]["strokes"] if s["id"] == sid)
                    sx, sy = run["pressed"][sid]["scroll"]
                    fx, fy, s = lay.page_f[0] - sx, lay.page_f[1] - sy, lay.s
                    Pp = [(fx + q[0] * s, fy + q[1] * s) for q in st["abs"]]
                    lh = run["pressed"][sid]["lh"]
                    xs_, ys_ = [q[0] for q in Pp], [q[1] for q in Pp]
                    for y in G._axis(max(0, min(ys_) - lh), min(lay.inner[1] - 1, max(ys_) + lh), IC.RP_GRID):
                        for x in G._axis(max(0, min(xs_) - lh), min(lay.inner[0] - 1, max(xs_) + lh), IC.RP_GRID):
                            rx, ry = x - fx, y - fy
                            if lay._in(rect, rx, ry, 0):
                                near = [(lay.chars[k][0], lay.chars[k][1], [round(v, 2) for v in lay.chars[k][2:]]) for k in lay.char_grid.near(rx, ry)
                                        if lay._in(lay.chars[k][2:], rx, ry, 0.5)]
                                print(f"      网格点 ({rx:.2f}, {ry:.2f}) 在框内：几何 hit = {lay.hit(rx, ry, 0)}；附近字框 {near}")
                    continue
                m, k = map(int, ident[1:].split(":"))
                gi = next(i for i, g in enumerate(lay.glyphs) if g["m"] == m and g["k"] == k)
                g = lay.glyphs[gi]
                raw = run["layout"]["maths"][m]["g"][k]
                d = (run["layout"]["paths"].get(raw["href"][1:]) or {}).get("d") or raw.get("d") or ""
                cmds = "".join(sorted(set(c for c in d if c.isalpha())))
                l, t, r, b = g["r"]
                xs, ys = np.arange(l, r, 0.5), np.arange(t, b, 0.5)
                ink = sum(lay._glyph_hit(x, y) == gi for x in xs for y in ys)
                print(f"   {side} {sid}：几何{kind}字形 {ident} 「{g['c']}」 tag={raw['tag']} 命令 {cmds} 外框 {[round(v, 1) for v in g['r']]} "
                      f"墨迹占比 {ink / max(1, len(xs) * len(ys)):.2f} clip={g['clip'] is not None} x/y={raw['x']},{raw['y']} m={[round(v, 3) for v in raw['m']]}")
                # 这一笔的邻域网格点（第一层，1 行高）里落在该字形外框内的点：几何判不在墨迹里，离墨迹边多远（屏幕 px）
                st = next(s for s in run["layout"]["strokes"] if s["id"] == sid)
                sx, sy = run["scrolls"][sid]
                fx, fy, s = lay.page_f[0] - sx, lay.page_f[1] - sy, lay.s
                Pp = [(fx + p[0] * s, fy + p[1] * s) for p in st["abs"]]
                lh = js["tm"]["lh"]
                xs_, ys_ = [p[0] for p in Pp], [p[1] for p in Pp]
                gx = G._axis(max(0, min(xs_) - lh), min(lay.inner[0] - 1, max(xs_) + lh), IC.RP_GRID)
                gy = G._axis(max(0, min(ys_) - lh), min(lay.inner[1] - 1, max(ys_) + lh), IC.RP_GRID)
                ia, ib, ic, idd, e0, f0 = g["inv"]
                a, b_, c, dd, _, _ = raw["m"]
                for y in gy:
                    for x in gx:
                        rx, ry = x - fx, y - fy
                        if not lay._in(g["r"], rx, ry, 0):
                            continue
                        X, Y = rx - e0, ry - f0
                        ux, uy = ia * X + ic * Y, ib * X + idd * Y
                        ux, uy = ux - g["shift"][0], uy - g["shift"][1]
                        wn = G.winding(g["polys"], ux, uy)
                        ed = G.edge_dist(g["polys"], ux, uy)
                        print(f"      网格点 ({x:.2f}, {y:.2f}) 在外框内：绕数 {wn}，离路径边 {ed:.2f} 字形单位（≈ {ed * abs(a):.3f} px），"
                              f"半描边 {g['half']}，几何命中 {lay._glyph_hit(rx, ry) == gi}，clip {g['clip']}，ctm_fixed {lay.ctm_fixed}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--phase", choices=("collect", "compare", "all", "quick", "quick-offline", "diag"), default="all")
    ap.add_argument("--every", type=int, default=10, help="quick：每几笔跑一笔")
    ap.add_argument("--indep-check-dir", default=B.DEFAULT_IC_DIR)
    args = ap.parse_args()
    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    IC = B.load_ic(args.indep_check_dir)
    from webgen.annotate import DRAFTS
    gmaps = IC.RP.glyph_letter_maps(IC.RP.letter_maps(json.loads((DRAFTS / "notation_renames_week3_4.json").read_text(encoding="utf-8")).get("tex", {})))
    cal = json.loads((pathlib.Path(args.indep_check_dir) / "indep_check_cal" / "calibration.json").read_text(encoding="utf-8"))
    if args.phase == "diag":
        diag(out, IC)
        return
    if args.phase in ("quick", "quick-offline"):
        quick(out, IC, args.every, args.phase == "quick")
        return
    if args.phase in ("collect", "all"):
        collect(out, IC, gmaps, cal)
    if args.phase in ("compare", "all"):
        sys.exit(1 if compare(out, IC, gmaps, cal) else 0)


if __name__ == "__main__":
    main()
