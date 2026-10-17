"""生成 Neural-IPC 组会网页（index.html + 每周一页 weekN.html），发布在 GitHub Pages。

读者是课题组同学：懂 IPC，但没亲手跑过这些东西。页面文字来自每周讲稿（Neural-IPC-sandbox docs/drafts/web_<周>.md），
视频卡片、数据表里的数字全部从 NAS 上的结果文件读，缺失或失败的如实写成人话。

    # 默认只演练：打印每项结果的状态、将写哪些文件、压哪些视频，什么都不写
    python tools/build_site.py

    # 真正写文件、压视频
    python tools/build_site.py --execute [--crf 26] [--force-videos]

    # 回归：只把三个 html 写到指定目录（不压视频、不复制图片、不写仓库），用来和改动前逐字节比较
    python tools/build_site.py --html-only --out-dir <目录>

必须用 Neural-IPC 的 genesis 环境跑（要用它自带的 imageio-ffmpeg 二进制和 numpy、markdown）：
    /data/xiaoyingwang/projects/Neural-IPC-sandbox/.conda/genesis/bin/python tools/build_site.py

每个压好的视频超过 10 MB、或页面引用的视频加起来超过 60 MB，就报错停止，不写页面。代码分工见 README.md。
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # 不往本仓库和 Neural-IPC 仓库（加载 configs.py 时）写 __pycache__

from webgen import week1_box as box  # noqa: E402  （必须在 dont_write_bytecode 之后导入）
from webgen.catalog import E0_FIG, HYDRO, HYDRO_MORE, LABEL_VIDEOS  # noqa: E402
from webgen.collect import collect_demos, collect_official_test, genesis_commit  # noqa: E402
from webgen.common import file_size_str  # noqa: E402
from webgen.config import (DEMO_ROOT, IMAGE_DIR, MAX_IMAGE_BYTES, MAX_TOTAL_VIDEO_BYTES,  # noqa: E402
                           MAX_VIDEO_BYTES, OUT_ROOT, VIDEO_DIR)
from webgen.draft_md import NOTION_IMAGES  # noqa: E402
from webgen.media import encode_video, get_ffmpeg_exe, plan_videos  # noqa: E402
from webgen.pages import build_pages  # noqa: E402
from webgen.week2_hydro import collect_hydro_sweeps  # noqa: E402

STATE_LABEL = {"ok": "完成", "failed": "失败", "not_run": "尚未运行", "unfinished": "未结束", "stale": "旧配置的结果，重跑中",
               "rejected": "被拒绝（预期内）"}


def parse_args():
    """命令行参数；--html-only 必须配 --out-dir，且不能和 --execute 同用。"""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--execute", action="store_true", help="真正写文件、压视频（默认只打印计划）")
    ap.add_argument("--crf", type=int, default=26, help="libx264 CRF（默认 26；数字越大文件越小）")
    ap.add_argument("--force-videos", action="store_true", help="忽略 encode_manifest.json，全部重新压缩")
    ap.add_argument("--variant", choices=sorted(box.VARIANTS), default="stiffball",
                    help="盒子实验主结果用哪一套（VARIANTS；run_sweep_queue.sh 的 TAG）")
    ap.add_argument("--html-only", action="store_true",
                    help="回归用：只把 html 写到 --out-dir，不压视频、不复制图片、不写仓库")
    ap.add_argument("--out-dir", type=Path, help="--html-only 的输出目录")
    args = ap.parse_args()
    if args.html_only and (args.execute or args.out_dir is None):
        ap.error("--html-only 必须配 --out-dir，且不能和 --execute 同用")
    return args


def collect_all(args):
    """收集页面要用的全部记录并排好视频 / 图片任务。返回 dict：demos、tests、hydro、hydro_more、gsweeps、cfg、
    videos（盒子每档视频）、hy（hydro 扫描）、vjobs、manifest、ijobs、commit、unlisted。"""
    box.set_variant(args.variant)
    demos, tests, unlisted = collect_demos()
    cfg, gsweeps = box.collect_sweeps()
    hydro = collect_official_test(HYDRO["key"], HYDRO["nodeid"], HYDRO["title"], "")
    hydro_more = [collect_official_test(key, nodeid, title, "") for key, nodeid, title, _ in HYDRO_MORE]
    all_demos = demos + tests + [hydro] + hydro_more
    videos = box.gen_level_videos(gsweeps)   # 盒子扫描每档自己的视频（和 demo 视频一起压缩、一起上传）
    bypass = [x for x in (box.bypass_video_record(r["level"]) for r in box.rows_of(gsweeps, "init_penetration")) if x]
    hy = collect_hydro_sweeps(cfg)   # Genesis hydro 参数扫描（week2 [[HYDRO_SWEEP]]）
    vjobs, manifest = plan_videos(all_demos + list(videos.values()) + bypass + [dict(v) for v in LABEL_VIDEOS.values()]
                                  + list(hy["videos"].values()) + hy["official"], args.crf, args.force_videos)
    ijobs = [{"src": src, "dst": IMAGE_DIR / name, "size": src.stat().st_size}
             for src, name in filter(None, (box.init_frame_image(r["level"])
                                            for r in box.rows_of(gsweeps, "init_penetration")))]
    ijobs += [{"src": OUT_ROOT / "figs" / name, "dst": IMAGE_DIR / name, "size": (OUT_ROOT / "figs" / name).stat().st_size}
              for name in (E0_FIG,)]
    return {"demos": demos, "tests": tests, "hydro": hydro, "hydro_more": hydro_more, "all_demos": all_demos,
            "gsweeps": gsweeps, "cfg": cfg, "videos": videos, "hy": hy, "vjobs": vjobs, "manifest": manifest,
            "ijobs": ijobs, "commit": genesis_commit(), "unlisted": unlisted}


def print_plan(args, c, pages, vjobs, ijobs):
    """演练输出：每项结果的状态、将写的页面、要压 / 跳过的视频、要复制的图片。"""
    mode = "EXECUTE" if args.execute else "DRY-RUN（只演练，不写任何文件；加 --execute 才真正写）"
    print(f"[build_site] 模式：{mode}")
    print(f"[build_site] demo 结果：{DEMO_ROOT}")
    for r in c["all_demos"]:
        extra = "" if r["state"] == "ok" else f"  {r['reason']}"
        vid = f"  视频: {r['video_src']}" if r["video_src"] else (f"  {r['video_note']}" if r["video_note"] else "")
        print(f"  - {r['key']:<32} {STATE_LABEL[r['state']]}{extra}{vid}")
    print(f"[build_site] 盒子实验这一套：{box.GEN_TAG}（{box.VARIANTS[box.GEN_TAG]['label']}），每档视频：{box.GEN_VIDEO_ROOT}"
          f"（Neural-IPC commit {c['commit']}）")
    for (sw, lv), r in c["videos"].items():
        print(f"  - {sw}/{lv:<14} " + (f"视频: {r['video_src']}  {r['line']}" if r["video_src"] else r["video_note"]))
    hy = c["hy"]
    print(f"[build_site] hydro 扫描（week2）：{c['cfg'].HYDRO_OUT_ROOT}")
    for sw, rows in hy["sweeps"].items():
        print(f"  - {sw:<14} " + "，".join(f"{r['level']}:{STATE_LABEL[r['state']]}" for r in rows))
    for (sw, lv), r in hy["videos"].items():
        print(f"  - 视频 {sw}/{lv:<14} " + (str(r["video_src"]) if r["video_src"] else r["video_note"]))
    for r in hy["official"]:
        print(f"  - 官方 {r['sweep']}/{r['level']:<8} {STATE_LABEL[r['state']]}  "
              + (str(r["video_src"]) if r["video_src"] else (r["video_note"] or "")))
    print(f"[build_site] 扫描结果：{box.GEN_SWEEP_ROOT}")
    for s in c["gsweeps"]:
        states = {}
        for r in s["rows"]:
            states[r["state"]] = states.get(r["state"], 0) + 1
        print(f"  - {s['name']:<18} 共 {len(s['rows'])} 档：" + "，".join(f"{STATE_LABEL[k]} {v}" for k, v in states.items()))
        for r in s["rows"]:
            if r["state"] in ("failed", "unfinished"):
                print(f"      {r['level']}: {r['reason']}")
    print("[build_site] 将写页面：")
    for p, text in pages.items():
        print(f"  - {p}（{len(text.encode('utf-8')) / 1024:.1f} KB）")
    print(f"[build_site] 视频（H.264 / 720p / crf {args.crf} / +faststart；单个上限 {file_size_str(MAX_VIDEO_BYTES)}，"
          f"合计上限 {file_size_str(MAX_TOTAL_VIDEO_BYTES)}）：")
    if not vjobs:
        print("  - 无")
    for j in vjobs:
        act = "压缩" if j["action"] == "encode" else "跳过（encode_manifest.json 记录的源文件和 crf 都没变）"
        print(f"  - {act}：{j['src']}（{file_size_str(j['src_size'])}）-> {j['dst']}")
    print("[build_site] 图片（原样复制）：")
    if not ijobs:
        print("  - 无")
    for j in ijobs:
        print(f"  - {j['src']}（{file_size_str(j['size'])}）-> {j['dst']}")
    referenced = {j["dst"].name for j in vjobs}
    if VIDEO_DIR.is_dir():
        stale = sorted(p.name for p in VIDEO_DIR.glob("*.mp4") if p.name not in referenced)
        if stale:
            print(f"[build_site] 注意：assets/videos/ 里有页面不再引用的视频（本脚本不删除）：{stale}")


def execute(args, pages, vjobs, ijobs, manifest):
    """真正执行：先检查体积、压视频、复制图片，全部成功后再写页面；最后打印发布时要一起上传的附属文件。"""
    for j in ijobs:
        if j["size"] > MAX_IMAGE_BYTES:
            raise SystemExit(f"[build_site] 图片 {j['src']} 有 {file_size_str(j['size'])}，超过 "
                             f"{file_size_str(MAX_IMAGE_BYTES)}，停止。")

    def check_total():
        """页面引用的视频合计体积；超过上限就停止（页面不写）。"""
        total = sum(j["dst"].stat().st_size for j in vjobs if j["dst"].is_file())
        if total > MAX_TOTAL_VIDEO_BYTES:
            raise SystemExit(f"[build_site] 页面引用的视频合计 {file_size_str(total)}，超过上限 "
                             f"{file_size_str(MAX_TOTAL_VIDEO_BYTES)}，停止（页面没有写）。请提高 --crf 或和用户商量删减。")
        return total

    for j in vjobs:  # 跳过的也核对一次体积
        if j["action"] == "skip" and j["dst"].stat().st_size > MAX_VIDEO_BYTES:
            raise SystemExit(f"[build_site] {j['dst']} 有 {file_size_str(j['dst'].stat().st_size)}，"
                             f"超过单个上限，停止。加 --force-videos 并提高 --crf 重压。")
    todo = [j for j in vjobs if j["action"] == "encode"]
    if todo:
        exe = get_ffmpeg_exe()
        print(f"[build_site] ffmpeg：{exe}")
        for j in todo:
            encode_video(exe, j, args.crf, manifest)
            check_total()
    total = check_total()
    if ijobs:
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        for j in ijobs:
            shutil.copy2(j["src"], j["dst"])
            print(f"[build_site] 复制 {j['src']} -> {j['dst']}")
    for p, text in pages.items():
        p.write_text(text, encoding="utf-8")
        print(f"[build_site] 写入 {p}")
    print(f"[build_site] 完成。页面引用的视频共 {len(vjobs)} 个，合计 {file_size_str(total)}。")
    files = {f"assets/videos/{j['dst'].name}": str(j["dst"]) for j in vjobs}
    files.update({f"assets/images/{j['dst'].name}": str(j["dst"]) for j in ijobs})
    print("[build_site] 页面引用的附属文件（published path -> 本地文件）：")
    print(json.dumps(files, indent=1, ensure_ascii=False) if files else "  - 无")


def main():
    """收集 → 生成页面 → 只保留页面真正引用的视频 / 图片 → 按模式写出（回归 / 演练 / 正式）。"""
    args = parse_args()
    c = collect_all(args)
    if c["unlisted"]:
        print(f"[build_site] 注意：NAS 上这些 demo 目录不在 DEMOS / OFFICIAL_TESTS 清单里，不上页面：{c['unlisted']}")
    pages = build_pages(c["demos"], c["tests"], c["hydro"], c["hydro_more"], c["gsweeps"], c["hy"])
    # 讲稿里引用的 NAS 图（draft_md.notion_image / week2_hydro.setup_figure 在生成页面时登记）
    ijobs = c["ijobs"] + [{"src": src, "dst": IMAGE_DIR / src.name, "size": src.stat().st_size} for src in NOTION_IMAGES]
    # 只压缩 / 复制页面真正引用的文件（扫描每档的视频不一定都上页面，没用到的不进 assets）
    used = "".join(pages.values())
    vjobs = [j for j in c["vjobs"] if f"assets/videos/{j['dst'].name}" in used]
    ijobs = [j for j in ijobs if f"assets/images/{j['dst'].name}" in used]

    if args.html_only:   # 回归：只写 html 到指定目录（文件名同仓库里的），其余一概不动
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for p, text in pages.items():
            (args.out_dir / p.name).write_text(text, encoding="utf-8")
            print(f"[build_site] 写入 {args.out_dir / p.name}")
        return 0
    print_plan(args, c, pages, vjobs, ijobs)
    if not args.execute:
        print("[build_site] DRY-RUN 结束，什么都没写。")
        return 0
    execute(args, pages, vjobs, ijobs, c["manifest"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
