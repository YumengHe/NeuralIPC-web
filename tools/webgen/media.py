"""视频：决定哪些视频要（重新）压缩，以及调用 ffmpeg 压缩（图片的复制任务在 build_site.collect_all 里排）。

压缩参数：H.264、高度 720（原片更小不放大）、给定 CRF、+faststart、去音轨。是否需要重压由
assets/videos/encode_manifest.json 记录的源文件路径 / 大小 / mtime / crf 决定。
"""

import datetime
import json
import os
import subprocess

from .common import file_size_str, load_json
from .config import BUILD_TMP, MAX_VIDEO_BYTES, PROJECT, VIDEO_DIR, VIDEO_MANIFEST


def load_manifest():
    """读 encode_manifest.json（{视频文件名: 上次压缩的记录}）；不存在返回 {}，损坏则停止。"""
    m, err = load_json(VIDEO_MANIFEST)
    if err:
        raise SystemExit(f"[build_site] {VIDEO_MANIFEST} 无法解析：{err}")
    return m or {}


def ffmpeg_args(exe, src, dst, crf):
    """把 src 压成 dst 的 ffmpeg 命令行（列表）。exe 是 ffmpeg 可执行文件路径。"""
    return [exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(src),
            "-vf", "scale=-2:'min(720,ih)'",   # 高度 720（原片更小则不放大），宽度按比例取偶数
            "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
            str(dst)]


def plan_videos(demos, crf, force):
    """为每条有 video_src 的记录排一个压缩任务，并在记录上写 video_web（页面引用路径）和 video_job。
    force = 忽略 manifest 全部重压。返回 (任务列表, manifest)；任务的 action 是 "encode" 或 "skip"。"""
    manifest = load_manifest()
    jobs = []
    for r in demos:
        if r["video_src"] is None:
            continue
        src = r["video_src"]
        dst = VIDEO_DIR / f"{r['key']}.mp4"
        st = src.stat()
        prev = manifest.get(dst.name)
        uptodate = (not force and dst.is_file() and isinstance(prev, dict)
                    and prev.get("src") == str(src) and prev.get("src_size") == st.st_size
                    and prev.get("src_mtime") == st.st_mtime and prev.get("crf") == crf)
        jobs.append({"key": r["key"], "src": src, "dst": dst, "src_size": st.st_size,
                     "src_mtime": st.st_mtime, "action": "skip" if uptodate else "encode"})
        r["video_web"] = f"assets/videos/{dst.name}"
        r["video_job"] = jobs[-1]
    return jobs, manifest


def merge_video_jobs(jobs, extra):
    """把讲稿 [[视频 …]] 的压缩任务 extra 并入 plan_videos 排好的 jobs，返回合并后的新列表：目标文件名与已有任务相同时，
    源文件也相同就不重复排，源文件不同就停止（否则两个视频会写到同一个 assets/videos/ 文件）。"""
    by_name = {j["dst"].name: j for j in jobs}
    merged = list(jobs)
    for j in extra:
        old = by_name.get(j["dst"].name)
        if old is None:
            merged.append(j)
            by_name[j["dst"].name] = j
        elif old["src"] != j["src"]:
            raise SystemExit(f"[build_site] 讲稿视频 {j['src']} 与 {old['src']} 都要写成 {j['dst'].name}，停止")
    return merged


def get_ffmpeg_exe():
    """genesis 环境自带的 imageio-ffmpeg 二进制路径；不在该环境运行时停止并提示。"""
    try:
        import imageio_ffmpeg  # genesis 环境自带（imageio-ffmpeg 0.6.0，binaries/ffmpeg-linux-x86_64-v7.0.2）
    except ImportError as e:
        raise SystemExit(f"[build_site] 找不到 imageio_ffmpeg（{e}）。请用 "
                         f"{PROJECT}/.conda/genesis/bin/python 运行本脚本。")
    return imageio_ffmpeg.get_ffmpeg_exe()


def encode_video(exe, job, crf, manifest):
    """压缩一个视频：先写 build_tmp/，体积不超限才移进 assets/videos/，并立刻把 manifest 落盘。
    ffmpeg 失败、没有产出或超过单个上限都停止（超限的文件留在 build_tmp/ 供检查）。"""
    BUILD_TMP.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BUILD_TMP / job["dst"].name
    cmd = ffmpeg_args(exe, job["src"], tmp, crf)
    print(f"[build_site] 压缩 {job['src']} -> {job['dst']}", flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"[build_site] ffmpeg 失败（退出码 {p.returncode}）：{job['src']}\n"
                         f"命令：{cmd}\nstderr：\n{p.stderr}")
    if not tmp.is_file() or tmp.stat().st_size == 0:
        raise SystemExit(f"[build_site] ffmpeg 返回 0 但没有产出文件：{tmp}")
    size = tmp.stat().st_size
    if size > MAX_VIDEO_BYTES:
        raise SystemExit(f"[build_site] 压缩后 {file_size_str(size)} 超过上限 {file_size_str(MAX_VIDEO_BYTES)}："
                         f"{tmp}（留在 build_tmp/ 供检查，未放进 assets/）。"
                         f"停止：请提高 --crf 或和用户商量，不要推大文件。")
    os.replace(tmp, job["dst"])
    manifest[job["dst"].name] = {
        "src": str(job["src"]), "src_size": job["src_size"], "src_mtime": job["src_mtime"],
        "crf": crf, "ffmpeg": exe, "args": cmd[1:-1] + ["<out>"],
        "out_size": size, "encoded_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    # 每压完一个就落盘 manifest，中途失败也能知道哪些已经好了
    VIDEO_MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[build_site]   -> {file_size_str(size)}", flush=True)
