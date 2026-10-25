"""设备核对页的本地验证：无头 Chromium 模拟 iPad（820×1180、1180×820，dpr 2，iPad UA）打开 devcheck/1，和服务器 indep_check 在同宽度下比。
  t1) 设备页采到的每笔原始采样（PROBE_JS 结果，去掉耗时 tm）与 indep_check.probe_page 逐笔相同；全文、公式字形串相同。
  t2) 用设备页数据走 judge_devcheck 的判定，与 indep_check.run 的逐笔表相同（判定一致，偏移差相差 ≤ 0.01 px）。
  t3) 待测页 = snapshot/2（对自己）：0 笔失败。
  t4) 设备页自报的有效性问题为空（无头浏览器里 iframe 视口 = 设定视口）。
不上传（noupload=1），结果只写 --out-dir。用法：/bin/python tools/devcheck/test_devcheck.py --out-dir <NAS 目录>（全部通过退出码 0）
"""
import argparse
import functools
import http.server
import json
import pathlib
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_devcheck as B   # noqa: E402
import judge_devcheck as J   # noqa: E402

IPAD_UA = ("Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
VIEWS = ((820, 1180), (1180, 820))
NEW_SPEC = {"preview/3": "dir:_pv3/preview/3", "snapshot/2": "snap"}   # 服务器 indep_check 打开同一份页面的写法（_pv3 与 origin/main 逐字节相同）


def serve_root():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
        type("Q", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None}), directory=str(B.ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", srv


def run_device(base, view, pages):
    """无头 Chromium 模拟 iPad 打开设备页，等跑完，返回 {页: devcheck 数据}。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": view[0], "height": view[1]}, device_scale_factor=2, user_agent=IPAD_UA, has_touch=True)
        pg = ctx.new_page()
        pg.on("console", lambda m: m.text.startswith("[devcheck]") and print(f"   [{view[0]}×{view[1]} {pages}] {m.text}", flush=True))
        pg.on("pageerror", lambda e: print(f"   [{view[0]}×{view[1]} {pages}] 页面报错：{e}", flush=True))
        pg.goto(f"{base}/devcheck/1/index.html?page={','.join(pages)}&noupload=1", wait_until="load")
        pg.wait_for_function("window.__devcheck", timeout=60000)
        res = pg.evaluate("window.__devcheck.done.then(r => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v.data])))")
        warns = pg.evaluate("window.__devcheck.warns")
        browser.close()
    return res, warns


def strip_tm(pr):
    return {k: v for k, v in pr.items() if k != "tm"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--indep-check-dir", default=B.DEFAULT_IC_DIR)
    args = ap.parse_args()
    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    IC = B.load_ic(args.indep_check_dir)
    from webgen.annotate import DRAFTS
    gmaps = IC.RP.glyph_letter_maps(IC.RP.letter_maps(json.loads((DRAFTS / "notation_renames_week3_4.json").read_text(encoding="utf-8")).get("tex", {})))
    cal = json.loads((pathlib.Path(args.indep_check_dir) / "indep_check_cal" / "calibration.json").read_text(encoding="utf-8"))
    base, srv = serve_root()
    widths = [v[0] for v in VIEWS]
    for pg in NEW_SPEC:
        (out / f"server_{pg.replace('/', '_')}").mkdir(exist_ok=True)
    with ThreadPoolExecutor(len(NEW_SPEC) * (1 + len(VIEWS))) as ex:
        ref = {pg: ex.submit(IC.run, "snap", spec, widths, out / f"server_{pg.replace('/', '_')}", gmaps, None, (0, 0), cal)
               for pg, spec in NEW_SPEC.items()}
        # 每个（视口, 待测页）一个设备页实例并行跑（每个实例 = 基准页 + 这一个待测页）
        devf = {(v, pg): ex.submit(run_device, base, v, [pg]) for v in VIEWS for pg in NEW_SPEC}
        ref = {pg: f.result() for pg, f in ref.items()}
        dev = {}
        for (v, pg), f in devf.items():
            r, w = f.result()
            dev.setdefault(v, ({}, []))
            dev[v][0].update(r)
            dev[v][1].extend(w)
    srv.shutdown()
    fails = []
    for v in VIEWS:
        w = v[0]
        res, warns = dev[v]
        for pg, d in res.items():
            (out / f"device_{w}_{pg.replace('/', '_')}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tag = f"{v[0]}×{v[1]}"
        ok4 = not warns and all(d["valid"]["ok"] for d in res.values())
        print(f"{'PASS' if ok4 else 'FAIL'} t4 {tag} 设备页自报问题：{warns}")
        fails += [] if ok4 else [f"t4@{tag}"]
        for pg, d in res.items():
            sdir = out / f"server_{pg.replace('/', '_')}"
            for side, run in (("old", d["old"]), ("new", d["new"])):
                sp = json.loads((sdir / f"probe_{w}_{side}.json").read_text(encoding="utf-8"))
                diff = [i for i in set(sp) | set(run["probes"]) if strip_tm(sp.get(i, {})) != strip_tm(run["probes"].get(i, {}))]
                print(f"{'PASS' if not diff else 'FAIL'} t1 {tag} {pg} {side}：{len(sp)} 笔，原始采样不同 {len(diff)} 笔 {sorted(diff)[:5]}")
                fails += [f"t1@{tag}:{pg}:{side}"] if diff else []
            rows = J.judge_rows(IC, d["old"], d["new"], gmaps, cal)
            J.write_table(rows, out, f"{w}_device_{pg.replace('/', '_')}")
            srows = {r["id"]: r for r in ref[pg][w]}
            bad = [r["id"] for r in rows if r["verdict"] != srows[r["id"]]["verdict"] or
                   (r["off_diff"] is None) != (srows[r["id"]]["off_diff"] is None) or
                   (r["off_diff"] is not None and abs(r["off_diff"] - srows[r["id"]]["off_diff"]) > 0.01)]
            print(f"{'PASS' if not bad else 'FAIL'} t2 {tag} {pg}：判定 / 偏移差与服务器不同 {len(bad)} 笔 {bad[:5]}；"
                  f"设备判错 {sum(r['verdict'] == '错' for r in rows)}，服务器判错 {sum(r['verdict'] == '错' for r in ref[pg][w])}")
            fails += [f"t2@{tag}:{pg}"] if bad else []
            if pg == "snapshot/2":
                f3 = [r["id"] for r in rows if r["verdict"] in IC.FAIL_VERDICTS]
                print(f"{'PASS' if not f3 else 'FAIL'} t3 {tag} snapshot/2 对自己：失败 {len(f3)} 笔 {f3[:5]}")
                fails += [f"t3@{tag}"] if f3 else []
    print(f"== 失败 {len(fails)} 项 {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
