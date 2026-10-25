"""用设备核对页（devcheck/1）在用户设备上采到的数据，按独立核对器 indep_check 的判定逐笔判迁移对不对。

输入：笔记仓库 checks/devcheck_<页>_<时间>.json（gh api 只读拉取；--local 可给本地文件）。里面有基准页 snapshot/2 与待测页在设备上
原样跑 PROBE_JS 的逐笔采样、page_texts_js 的全文与公式字形串、待测页全部内容项的正文卡片坐标（第二遍偏移用）和设备环境。
判定完全复用 indep_check：IdentityMap → pick_refs → 偏移（= 待测页笔起点 − 参考内容项左上角，与 REF_JS 同式）→ judge（噪声底校准同服务器）；
写 table_<宽>.json / .md，再用 indep_check 的 summarize / breakdown 出与服务器核对器相同格式的按类计数表；
另给「TeX 原样公式」单项：snapshot/2 嵌入笔记里 anchor.type == "math" 且 anchor.tex 与待测页某个 MathJax 源 TeX（\\(…\\) / \\[…\\]，
html.unescape 后 strip）逐字相等的笔，各判定多少笔。

有效性（任一条不过，结果判「无效」，退出码 2）：设备页自己报的问题（iframe 视口 ≠ 设备视口、iframe 被撑高、运行中视口变了、
text-size-adjust 不是 100%）；页面里嵌的 PROBE_JS 与当前 indep_check.PROBE_JS 不同；服务器在同一视口的无头浏览器里打开同一页，
CSS 决定的量（main zoom、正文字号、行高、根字号）与设备 iframe 里量到的不同（说明 iframe 里的排版不等于直接打开）。

用法：
    /bin/python tools/devcheck/judge_devcheck.py --list
    /bin/python tools/devcheck/judge_devcheck.py --file checks/devcheck_preview_3_20261025T183012Z.json
    /bin/python tools/devcheck/judge_devcheck.py --local <本地 json>
结果目录默认 /nas/xiaoyingwang/Neural-IPC/outputs/web_annotate_test/devcheck/<文件名去 .json>/。
"""
import argparse
import hashlib
import html as htmlmod
import json
import pathlib
import re
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_devcheck as B   # noqa: E402  ENV_JS、默认 indep_check 目录

NOTES_REPO = "delluluwxy/neural-ipc-notes"
OUT_ROOT = pathlib.Path("/nas/xiaoyingwang/Neural-IPC/outputs/web_annotate_test/devcheck")
WEB_ROOT = B.ROOT
ENV_KEYS = ("zoom", "p_font", "p_lh", "root_font")   # CSS / 页面 JS 按视口决定、与字体无关的量：设备 iframe 与服务器同视口必须相同


def check_path(p):
    """只读 checks/ 下的 devcheck 文件。"""
    if not re.fullmatch(r"checks/devcheck_[A-Za-z0-9_]+_\d{8}T\d{6}Z\.json", p):
        raise SystemExit(f"路径必须是 checks/devcheck_<页>_<时间>.json：{p}")
    return p


def gh_list():
    r = subprocess.run(["gh", "api", f"repos/{NOTES_REPO}/contents/checks", "--jq", ".[] | [.path, .size] | @tsv"],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"列 checks/ 失败：{r.stderr.strip()}")
    return r.stdout


def gh_fetch(path):
    r = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw", f"repos/{NOTES_REPO}/contents/{check_path(path)}"],
                       capture_output=True)
    if r.returncode:
        raise SystemExit(f"拉取 {path} 失败：{r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def git_text(spec):
    """部署仓库 git 对象里的文件（如 origin/main:snapshot/2/week3_4.html）。"""
    r = subprocess.run(["git", "-C", str(WEB_ROOT), "show", spec], capture_output=True)
    if r.returncode:
        raise SystemExit(f"git show {spec} 失败：{r.stderr.decode(errors='replace').strip()}")
    return r.stdout.decode("utf-8")


def snapshot_notes(html):
    m = re.search(r"<script>window\.NIPC_SNAPSHOT = (.*?);</script>", html, flags=re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def page_tex(html):
    """页面 MathJax 源 TeX：去掉 <script>/<style> 后 \\(…\\) 与 \\[…\\] 里的原文，html.unescape 后 strip。"""
    body = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S | re.I)
    return [htmlmod.unescape(a or b).strip() for a, b in re.findall(r"\\\((.*?)\\\)|\\\[(.*?)\\\]", body, flags=re.S)]


def new_offsets(refs, dump):
    """第二遍偏移：{笔 id: 待测页上笔起点相对参考内容项左上角的偏移（正文卡片 px）}，对不上的 None。"""
    out = {}
    for sid, (_, _, ident) in refs.items():
        a0 = dump["a0"].get(sid)
        if ident[0] == "p":
            k = int(ident[1:])
            q = dump["p"][k] if k < len(dump["p"]) else None
        else:
            m, g = map(int, ident[1:].split(":"))
            q = dump["m"][m][g] if m < len(dump["m"]) and g < len(dump["m"][m]) else None
        out[sid] = None if (a0 is None or q is None) else [a0[0] - q[0], a0[1] - q[1]]
    return out


def probes_of(IC, run):
    """一次运行的逐笔采样：设备 probe 模式直接用 PROBE_JS 结果；默认 layout 模式由布局表纯几何重算（geom_probe，与 PROBE_JS 对拍过）。"""
    if run.get("probes") is not None:
        return run["probes"]
    import geom_probe as G
    return G.probe_all(run["layout"], IC.RP_GRID, IC.RP_SAMPLE)


def judge_rows(IC, old, new, gmaps, cal):
    """逐笔判定行（与 indep_check.run 的行同字段）。old / new 是设备页的一次运行（probes 或 layout、texts、dump）。"""
    import geom_probe as G
    old = dict(old, probes=probes_of(IC, old))
    new = dict(new, probes=probes_of(IC, new))
    if new.get("dump") is None:
        new["dump"] = G.dump_from_layout(new["layout"])
    imap = IC.IdentityMap(old["texts"], new["texts"])
    refs = IC.pick_refs(old["probes"], new["probes"], imap)
    noff = new_offsets(refs, new["dump"])
    rows = []
    for i, o in old["probes"].items():
        ref = None
        if i in refs and noff.get(i):
            c, (ox, oy), _ = refs[i]
            ref = (c, max(abs(ox - noff[i][0]), abs(oy - noff[i][1])))
        n = new["probes"].get(i, {"state": "none"})
        verdict, why = IC.judge(o, n, new["texts"], gmaps, ref, cal)
        rows.append(dict(id=i, verdict=verdict, why=why, old_pressed=o.get("pressed"), new_pressed=n.get("pressed"),
                         ref=ref[0] if ref else None, off_diff=ref[1] if ref else None))
    return rows


def write_table(rows, out_dir, w):
    (out_dir / f"table_{w}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["| id | 旧压住 | 新压住 | 偏移参考字 | 偏移差 px | 判定 | 说明 |", "|---|---|---|---|---|---|---|"]
    md += [f"| `{r['id']}` | {r['old_pressed'] or ''} | {r['new_pressed'] or ''} | {r['ref'] or ''} | "
           f"{'' if r['off_diff'] is None else round(r['off_diff'], 1)} | {r['verdict']} | {r['why']} |" for r in rows]
    (out_dir / f"table_{w}.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def env_server(IC, page, viewport):
    """服务器无头浏览器在设备同一视口里打开 origin/main 的这一页（同 indep_check 的打开方式），跑 ENV_JS。"""
    from playwright.sync_api import sync_playwright
    RP = IC.RP
    src = IC.load_spec(f"git:origin/main:{page}")
    RP.VIEW = {"width": viewport[0], "height": viewport[1]}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        base, srv = RP.serve()
        pg = RP.open_served(browser, base, src["path"], src["html"], git_prefix=src["git"])
        env = pg.evaluate(B.ENV_JS)
        browser.close()
        srv.shutdown()
    return env


def validity(IC, d, env_check):
    probs = list(d.get("valid", {}).get("problems") or [])
    if d.get("probe_src_sha256") != hashlib.sha256(IC.PROBE_JS.encode("utf-8")).hexdigest():
        probs.append("页面里嵌的 PROBE_JS 与当前 indep_check.PROBE_JS 不同")
    if d.get("cfg", {}).get("layout_sha256") != hashlib.sha256(B.LAYOUT_JS.encode("utf-8")).hexdigest():
        probs.append("页面里的 LAYOUT_JS 与当前 build_devcheck.LAYOUT_JS 不同（geom_probe 口径可能对不上）")
    import geom_probe as G
    for run in (d["old"], d["new"]):
        if run.get("probes") is None and G.scroll_rule(run["layout"]) is None:
            probs.append(f"{run['page']} 的滚动取整规则认不出：{run['layout'].get('scroll_rule')}")
        if run.get("layout"):
            print(f"   {run['page']} 布局表自检：{G.layout_stats(run['layout'])}", flush=True)
    envs = {}
    if env_check:
        for key, run in (("old", d["old"]), ("new", d["new"])):
            srv = env_server(IC, run["page"], d["device"]["viewport"])
            envs[run["page"]] = dict(device=run["env_start"], server=srv)
            for k in ENV_KEYS:
                if run["env_start"].get(k) != srv.get(k):
                    probs.append(f"{run['page']} 的 {k}：设备 iframe {run['env_start'].get(k)!r} ≠ 服务器同视口 {srv.get(k)!r}")
    return probs, envs


def tex_same_stat(d, rows):
    """「TeX 原样公式」单项：快照笔记里 anchor.type == math 且 anchor.tex 与待测页某个源 TeX 逐字相等的笔，按判定计数。"""
    notes = snapshot_notes(git_text(f"origin/main:{d['base']}/week3_4.html"))
    texs = set(page_tex(git_text(f"origin/main:{d['page']}/week3_4.html")))
    math = [s for s in notes["strokes"] if (s.get("anchor") or {}).get("type") == "math"]
    same = [s["id"] for s in math if s["anchor"].get("tex") in texs]
    by = {r["id"]: r for r in rows}
    cnt = {}
    for sid in same:
        v = by.get(sid, {}).get("verdict", "（无此笔）")
        cnt[v] = cnt.get(v, 0) + 1
    bad = [by[s] for s in same if s in by and by[s]["verdict"] in ("错", "超时", "无法核")]
    return dict(math_strokes=len(math), tex_same=len(same), counts=cnt, bad=[(r["id"], r["verdict"], r["why"]) for r in bad])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="列出笔记仓库 checks/ 下的文件")
    ap.add_argument("--file", help="笔记仓库里的路径 checks/devcheck_….json")
    ap.add_argument("--local", help="本地 devcheck json（下载的或本地测试的）")
    ap.add_argument("--out-dir", help="结果目录（默认 OUT_ROOT/<文件名>）")
    ap.add_argument("--indep-check-dir", default=B.DEFAULT_IC_DIR)
    ap.add_argument("--no-env-check", action="store_true", help="不在服务器上同视口复量环境（只看设备页自报的问题）")
    ap.add_argument("--n", type=int, default=20, help="breakdown 每类列前几笔")
    args = ap.parse_args()
    if args.list:
        print(gh_list())
        return
    if bool(args.file) == bool(args.local):
        raise SystemExit("--file 与 --local 二选一")
    raw = gh_fetch(args.file) if args.file else pathlib.Path(args.local).read_bytes()
    name = pathlib.Path(args.file or args.local).stem
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else OUT_ROOT / name
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.file:
        (out_dir / pathlib.Path(args.file).name).write_bytes(raw)   # 原样存一份
    d = json.loads(raw)
    assert d.get("format") == "nipc-devcheck" and d.get("version") == 1, "不是 devcheck 文件"

    IC = B.load_ic(args.indep_check_dir)
    from webgen.annotate import DRAFTS
    table = json.loads((DRAFTS / "notation_renames_week3_4.json").read_text(encoding="utf-8")).get("tex", {})
    gmaps = IC.RP.glyph_letter_maps(IC.RP.letter_maps(table))   # 同 indep_check.main
    cal = json.loads((pathlib.Path(args.indep_check_dir) / "indep_check_cal" / "calibration.json").read_text(encoding="utf-8"))

    probs, envs = validity(IC, d, not args.no_env_check)
    w = d["device"]["viewport"][0]
    rows = judge_rows(IC, d["old"], d["new"], gmaps, cal)
    write_table(rows, out_dir, w)
    print(f"== {d['page']}（设备 {d['device']['viewport'][0]}×{d['device']['viewport'][1]}，dpr {d['device']['dpr']}，{d['at']}）")
    print(f"   UA：{d['device']['ua']}")
    print(f"   有效性：{'有效' if not probs else '无效'}" + "".join(f"\n     - {p}" for p in probs))
    tally = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print(f"   {len(rows)} 笔：" + "，".join(f"{k} {v}" for k, v in sorted(tally.items())))
    IC.summarize(SimpleNamespace(summarize=[f"{d['page']}(设备)={out_dir}"], out_dir=str(out_dir)))
    IC.breakdown(SimpleNamespace(breakdown=str(out_dir), out_dir=str(out_dir), n=args.n))
    ts = tex_same_stat(d, rows)
    print(f"\n== TeX 原样公式：快照公式笔 {ts['math_strokes']} 笔，anchor.tex 在新页原样 {ts['tex_same']} 笔；判定 "
          + "，".join(f"{k} {v}" for k, v in sorted(ts["counts"].items())))
    for b in ts["bad"]:
        print(f"   {b[1]} {b[0]}：{b[2]}")
    summary = dict(file=args.file or args.local, page=d["page"], device=d["device"], valid=not probs, problems=probs, envs=envs,
                   tally=tally, tex_same=ts)
    (out_dir / "devcheck_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果目录：{out_dir}")
    sys.exit(2 if probs else (1 if any(r["verdict"] in IC.FAIL_VERDICTS for r in rows) else 0))


if __name__ == "__main__":
    main()
