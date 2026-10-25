"""设备核对页的本地验证：无头 Chromium 模拟 iPad（820×1180、1180×820，dpr 2，iPad UA）打开 devcheck/1，和服务器 indep_check 在同宽度下比。
GitHub API 用本地假仓库代替（Playwright 拦截 api.github.com，记下每次读写），不碰真笔记仓库。
每个视口：
  R1 = ?page=preview/3（假 token、空仓库）：测基准页 + 待测页，上传基准页缓存与待测页结果；
  R2 = ?page=snapshot/2（假仓库里有 R1 的基准页缓存）：应复用缓存、只测待测页；
  RA = ?page=preview/3&waits=fixed&noupload=1（只在 820 跑）：服务器 indep_check 的固定等待，A/B 比耗时与结果。
  t1) R1 / R2 的原始采样（PROBE_JS 结果，去掉耗时 tm）与 indep_check.probe_page 逐笔相同；全文、公式字形串相同。
  t2) 用设备页数据走 judge_devcheck 的判定，与 indep_check.run 的逐笔表相同（判定一致，偏移差相差 ≤ 0.01 px）。
  t3) R2（snapshot/2 对自己）0 笔失败。
  t4) 设备页自报的有效性问题为空。
  t5) R2 用了 R1 上传的基准页缓存（base_cached、base_ref、old 与 R1 相同），只测了一页。
  t6) A/B：RA（固定等待）与 R1（等布局稳定）逐笔采样相同；打印两者每页耗时。
  t7) 所有写操作都是 PUT checks/devcheck_….json，没有别的写。
结果只写 --out-dir。用法：/bin/python -B tools/devcheck/test_devcheck.py --out-dir <NAS 目录>（全部通过退出码 0）
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
    """无头 Chromium 模拟 iPad 打开设备页，等跑完。repo 给了就放假 token、拦截 GitHub API。返回 ({页: 数据}, 警告)。"""
    from playwright.sync_api import sync_playwright
    tag = f"{view[0]}×{view[1]} {query}"
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
    print(f"   [{tag}] 页面最后显示：{done!r}", flush=True)
    return res, warns


def strip_tm(pr):
    return {k: v for k, v in pr.items() if k != "tm"}


def probe_diff(a, b):
    return sorted(i for i in set(a) | set(b) if strip_tm(a.get(i, {})) != strip_tm(b.get(i, {})))


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
    repos = {v: FakeRepo() for v in VIEWS}
    with ThreadPoolExecutor(8) as ex:
        ref = {pg: ex.submit(IC.run, "snap", spec, widths, out / f"server_{pg.replace('/', '_')}", gmaps, None, (0, 0), cal)
               for pg, spec in NEW_SPEC.items()}
        r1 = {v: ex.submit(run_device, base, v, "page=preview/3", repos[v]) for v in VIEWS}
        ra = ex.submit(run_device, base, VIEWS[0], "page=preview/3&waits=fixed&noupload=1")
        r1 = {v: f.result() for v, f in r1.items()}
        r2 = {v: ex.submit(run_device, base, v, "page=snapshot/2", FakeRepo(repos[v].files)) for v in VIEWS}
        r2 = {v: f.result() for v, f in r2.items()}
        ra = ra.result()
        ref = {pg: f.result() for pg, f in ref.items()}
    srv.shutdown()
    fails = []

    def check(ok, name, msg):
        print(f"{'PASS' if ok else 'FAIL'} {name} {msg}", flush=True)
        if not ok:
            fails.append(name)

    for v in VIEWS:
        w, tag = v[0], f"{v[0]}×{v[1]}"
        d1, d2 = r1[v][0]["preview/3"], r2[v][0]["snapshot/2"]
        for name, d in (("R1", d1), ("R2", d2)):
            (out / f"device_{w}_{name}_{d['page'].replace('/', '_')}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        check(not r1[v][1] and not r2[v][1] and d1["valid"]["ok"] and d2["valid"]["ok"], f"t4@{tag}", f"设备页自报问题：{r1[v][1] + r2[v][1]}")
        for name, d in (("R1", d1), ("R2", d2)):
            sdir = out / f"server_{d['page'].replace('/', '_')}"
            for side in ("old", "new"):
                sp = json.loads((sdir / f"probe_{w}_{side}.json").read_text(encoding="utf-8"))
                diff = probe_diff(sp, d[side]["probes"])
                check(not diff, f"t1@{tag}:{name}:{side}", f"{d[side]['page']}：{len(sp)} 笔，原始采样与服务器不同 {len(diff)} 笔 {diff[:5]}")
            rows = J.judge_rows(IC, d["old"], d["new"], gmaps, cal)
            J.write_table(rows, out, f"{w}_device_{name}")
            srows = {r["id"]: r for r in ref[d["page"]][w]}
            bad = [r["id"] for r in rows if r["verdict"] != srows[r["id"]]["verdict"] or
                   (r["off_diff"] is None) != (srows[r["id"]]["off_diff"] is None) or
                   (r["off_diff"] is not None and abs(r["off_diff"] - srows[r["id"]]["off_diff"]) > 0.01)]
            worst = max((abs(r["off_diff"] - srows[r["id"]]["off_diff"]) for r in rows
                         if r["off_diff"] is not None and srows[r["id"]]["off_diff"] is not None), default=0)
            check(not bad, f"t2@{tag}:{name}", f"{d['page']}：判定 / 偏移差与服务器不同 {len(bad)} 笔 {bad[:5]}；偏移差最大相差 {worst:.4f} px；"
                  f"设备判错 {sum(r['verdict'] == '错' for r in rows)}，服务器判错 {sum(r['verdict'] == '错' for r in ref[d['page']][w])}")
            if name == "R2":
                f3 = [r["id"] for r in rows if r["verdict"] in IC.FAIL_VERDICTS]
                check(not f3, f"t3@{tag}", f"snapshot/2 对自己：失败 {len(f3)} 笔 {f3[:5]}")
        base_files = [p for p in repos[v].files if p.startswith("checks/devcheck_base_")]
        ok5 = (d2["base_cached"] and d2["base_ref"] == d1["base_ref"] and d2["base_ref"] in base_files and d2["old"] == d1["old"])
        check(ok5, f"t5@{tag}", f"R2 复用基准页缓存 {d2['base_ref']}（R1 上传 {base_files}）；耗时 R1 {d1['old']['ms']} + {d1['new']['ms']}，R2 只测待测页 {d2['new']['ms']}")
        puts = [p for m, p in repos[v].log if m == "PUT"]
        check(not repos[v].bad and puts and all(PATH_RE.fullmatch(p) for p in puts), f"t7@{tag}", f"写操作 {puts}，越界请求 {repos[v].bad}")
    da = ra[0]["preview/3"]
    d1 = r1[VIEWS[0]][0]["preview/3"]
    diff = probe_diff(da["old"]["probes"], d1["old"]["probes"]) + probe_diff(da["new"]["probes"], d1["new"]["probes"])
    check(not diff, "t6", f"A/B 820：固定等待 vs 等布局稳定 逐笔采样不同 {len(diff)} 笔 {diff[:5]}；耗时（ms）固定 {da['old']['ms']} / {da['new']['ms']}，"
          f"稳定 {d1['old']['ms']} / {d1['new']['ms']}")
    print(f"== 失败 {len(fails)} 项 {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
