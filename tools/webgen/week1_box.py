"""盒子实验（week1 讲稿第 4 节）的结果收集：选结果集、读各档记录、找每档视频 / 硬跑视频 / 初始穿插图。
页面正文来自讲稿 web_week1.md，本模块只提供讲稿引用的视频、图片的源文件和首页摘要里的档位数。
盒子扫描的结果文件由 Neural-IPC tools/ipc_sweep/sweep.py 写出，档位取 configs.GENESIS_SWEEPS。

盒子实验有两套结果（VARIANTS）；set_variant(tag) 选定一套后，本模块的读取函数都指向那一套的目录。
"""

import functools

from .collect import collect_level, load_sweep_configs
from .common import MISSING, load_json
from .config import DEMO_ROOT, SWEEP_ROOT

# 盒子场景的结果集（run_sweep_queue.sh TAG / BASE_OV）：tag -> 每档共用的 overrides + 说明
VARIANTS = {
    "stiffball": {"base_ov": {"ball_E": 1.0e5},
                  "label": "所有软球 E = 1e5 Pa（官方 1e3 太软，在盒子里会被压塌）"},
    "officialball": {"base_ov": {"pile_layout": "clear"},
                     "label": "软球保持官方 E = 1e3 Pa，额外物体落在远离官方软球的四角"},
}
# 由 set_variant() 设定：选中那套的扫描 json 与每档视频所在目录
GEN_TAG, GEN_BASE_OV = None, {}
GEN_SWEEP_ROOT = SWEEP_ROOT / "genesis"
GEN_VIDEO_ROOT = DEMO_ROOT / "genesis_box_levels"   # 每档视频：<扫描>_<档位>/genesis_ipc_objects_in_box.mp4


def set_variant(tag):
    """让盒子实验的读取函数指向结果集 tag（VARIANTS 的键）：genesis_<tag>/ 与 genesis_box_levels_<tag>/。"""
    global GEN_TAG, GEN_BASE_OV, GEN_SWEEP_ROOT, GEN_VIDEO_ROOT
    GEN_TAG, GEN_BASE_OV = tag, dict(VARIANTS[tag]["base_ov"])
    GEN_SWEEP_ROOT = SWEEP_ROOT / f"genesis_{tag}"
    GEN_VIDEO_ROOT = DEMO_ROOT / f"genesis_box_levels_{tag}"


def _tag_prefix():
    """视频 / 图片 key 里的结果集前缀：「_<tag>」，没选结果集时为空。"""
    return GEN_TAG and '_' + GEN_TAG or ''


def collect_sweeps(cfg=None):
    """选中那套的盒子扫描：GEN_SWEEP_ROOT/<扫描>/<档位>.json，覆盖 cfg.GENESIS_SWEEPS 的每一档；每档的 overrides =
    GEN_BASE_OV + 该档自己的（同 sweep.py --base-overrides）。NAS 上有、configs 里没有的档也列出。
    返回 (cfg, [{"name", "why", "rows"}])。"""
    cfg = cfg or load_sweep_configs()
    root, tbl, base = GEN_SWEEP_ROOT, cfg.GENESIS_SWEEPS, GEN_BASE_OV
    sweeps = []
    known = set()
    for sweep, spec in tbl.items():
        rows = []
        for level, ov in spec["levels"].items():
            rows.append(collect_level(sweep, level, {**base, **ov}, root))
            known.add((sweep, level))
        sd = root / sweep
        if sd.is_dir():  # NAS 上有、configs.py 里没有的档位
            for jp in sorted(sd.glob("*.json")):
                d, _ = load_json(jp)
                if not isinstance(d, dict) or d.get("sweep") != sweep:  # 例如 run_gpu_job 的 gpu_job_result.json
                    continue
                if (sweep, jp.stem) not in known:
                    rows.append(collect_level(sweep, jp.stem, MISSING, root))
                    known.add((sweep, jp.stem))
        sweeps.append({"name": sweep, "why": spec.get("why", ""), "rows": rows})
    return cfg, sweeps


def rows_of(sweeps, name):
    """collect_sweeps 结果里名为 name 的扫描的各档记录；没有返回 []。"""
    for s in sweeps:
        if s["name"] == name:
            return s["rows"]
    return []


def gen_level_videos(gsweeps):
    """{(扫描, 档位): 视频记录}，记录格式同 collect_demo（plan_videos 直接复用）。
    认 GEN_VIDEO_ROOT/<扫描>_<档位>/ 下 mp4 非空、且 job.exit 为 0 / 3 / 4 的（run_genesis_ipc_example.py：
    3 = 官方相机下有帧部分出画面，4 = 第二遍重新仿真的范围超出第一遍，即 GPU 运行不逐位一致；两种情况视频和
    camera_fit.json 都照常写出）；否则写「视频未生成」，不拿别的视频顶替。初始穿插那组开跑前就被拒，不建记录。"""
    out = {}
    for s in gsweeps:
        if s["name"] == "init_penetration":
            continue
        for r in s["rows"]:
            d = GEN_VIDEO_ROOT / f"{r['sweep']}_{r['level']}"
            ex = d / "job.exit"
            code = ex.read_text().strip() if ex.is_file() else None
            mp4 = d / "genesis_ipc_objects_in_box.mp4"
            done = code in ("0", "3", "4") and mp4.is_file() and mp4.stat().st_size > 0
            out[(r["sweep"], r["level"])] = {
                "key": f"box{_tag_prefix()}_{r['sweep']}_{r['level']}", "expects_video": True,
                "title": "", "line": "", "dir": d, "state": "ok", "reason": None, "images": [],
                "video_src": mp4 if done else None,
                "video_note": None if done else ("视频未生成" if code is None else f"视频未生成（录像退出码 {code}）")}
    return out


@functools.lru_cache(maxsize=None)  # 同一档只建一个记录对象：plan_videos 在它上面写 video_web
def bypass_video_record(level):
    """初始穿插某档关掉 libuipc 开跑前检查（sanity_check_enable = false）硬跑的视频记录（collect_demo 字段；
    GEN_VIDEO_ROOT/init_penetration_<level>_bypass/），没录则 None。"""
    d = GEN_VIDEO_ROOT / f"init_penetration_{level}_bypass"
    mp4, ex = d / "genesis_ipc_objects_in_box.mp4", d / "job.exit"
    if not (ex.is_file() and ex.read_text().strip() in ("0", "3", "4") and mp4.is_file() and mp4.stat().st_size > 0):
        return None
    return {"key": f"box{_tag_prefix()}_init_penetration_{level}_bypass", "expects_video": True,
            "title": "关掉开跑前检查、硬跑", "line": "", "dir": d, "state": "ok", "reason": None, "images": [],
            "video_src": mp4, "video_note": None}


def init_frame_image(level):
    """初始穿插某档第 0 帧图（run_genesis_ipc_example.py --initial-frame，写在该档视频旁）：
    (源 png, 发布文件名)；没渲染则 None。"""
    src = GEN_VIDEO_ROOT / f"init_penetration_{level}" / "initial_frame.png"
    return (src, f"box{_tag_prefix()}_init_penetration_{level}.png") if src.is_file() else None
