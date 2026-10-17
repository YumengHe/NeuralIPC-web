"""Week 1 页（旧路径，web_week1.md 不存在时使用）：Demo 视频节、官方测试节、盒子实验与 IPC 参数扫描、
对生成训练数据的意义。盒子扫描的结果文件由 Neural-IPC tools/ipc_sweep/sweep.py 写出，档位取 configs.GENESIS_SWEEPS。

盒子实验有两套结果（VARIANTS）；set_variant(tag) 选定一套后，本模块的读取函数都指向那一套的目录。
"""

import functools
import math
import re
from pathlib import Path

from .collect import collect_level, load_sweep_configs
from .common import ANSI_RE, MISSING, dig, esc, g3, is_num, load_json, sci
from .config import DEMO_ROOT, SWEEP_ROOT
from .html_parts import demo_card, table

# ---------------- 选哪一套结果 ----------------
# 盒子场景的结果集（run_sweep_queue.sh TAG / BASE_OV）：tag -> 每档共用的 overrides + 页面上的说明
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


# ---------------- 收集 ----------------
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
    """{(扫描, 档位): 视频记录}，记录格式同 collect_demo（plan_videos / demo_card 直接复用）。
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


@functools.lru_cache(maxsize=None)  # 同一档只建一个记录对象：plan_videos 在它上面写 video_web，页面再读
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


# ---------------- 扫描表的取值 ----------------
# overrides 里没写的键取官方 ipc_objects_falling.py / Genesis 默认值（出处见 Neural-IPC tools/ipc_sweep/configs.py
# GENESIS_SWEEPS 上方注释：contact_resistance 默认 1e9，FEM friction_mu 默认 0.1；ball_subdiv 不给 = 官方
# gs.morphs.Sphere(radius=0.08)，见 run_genesis_ipc_example.py soft_ball_morph）
GENESIS_DEFAULTS = {"friction_mu": 0.1, "contact_resistance": 1e9, "overlap_balls": 0.0, "ball_subdiv": None,
                    "ball_E": 1.0e3}
GENESIS_KEYS = {"resistance": "contact_resistance", "init_penetration": "overlap_balls",
                "mesh_res": "ball_subdiv"}  # 扫描名 -> configs 里的 override 键
# genesis fem_entity.py:542 打印 (n_elements, n_vertices)；软球是 Sphere（官方）或 Mesh（icosphere），材料都是 FEM.Elastic
BALL_SIZE_RE = re.compile(r"morph: (?:Sphere|Mesh), size: \((\d+), (\d+)\), material: <gs\.materials\.FEM\.Elastic>")


def gen_value(d, sweep):
    """结果文件 d 这一档在该扫描维度上的取值（数）。"""
    if sweep == "d_hat":
        return dig(d, "libuipc_config", "contact", "d_hat")
    if sweep == "dt":
        return d.get("dt", MISSING)
    key = GENESIS_KEYS[sweep]
    return (d.get("overrides") or {}).get(key, GENESIS_DEFAULTS[key])


def gen_ball_verts(d):
    """各 FEM 软球（四面体化后，含内部）的顶点数，从该档 log 里 Genesis 打印的 'size: (单元数, 顶点数)' 读。"""
    lp = d.get("log_path")
    if not lp or not Path(lp).is_file():
        return []
    txt = ANSI_RE.sub("", Path(lp).read_text(encoding="utf-8", errors="replace"))
    return [int(m.group(2)) for m in BALL_SIZE_RE.finditer(txt)]


def gen_ground_out(d):
    """(末帧最低点 m, 低于地面 1 mm 以上的物体名单, 其余越出盒壁的物体名单)。
    地面 z = 0；inside_box 判据见 sweep.py object_summary（xy 不超出内壁 1 mm 且最低点不低于地面 1 mm）。"""
    objs = {k: o for k, o in (d.get("objects_final") or {}).items() if isinstance(o, dict)}
    zs = [o["min_z"] for o in objs.values() if is_num(o.get("min_z"))]
    below = [k for k, o in objs.items() if is_num(o.get("min_z")) and o["min_z"] < -1e-3]
    out = [k for k, o in objs.items() if o.get("inside_box") is False and k not in below]
    return (min(zs) if zs else MISSING), below, out


def gen_level_value(r, sweep, cfg):
    """档位取值：有结果用结果文件里的；没有（没跑 / 重跑中）用 configs.py 里该档的 overrides。"""
    if r["data"]:
        return gen_value(r["data"], sweep)
    if r["sweep"] == "baseline":
        return MISSING
    ov = cfg.GENESIS_SWEEPS[r["sweep"]]["levels"].get(r["level"], {})
    key = {"d_hat": "contact_d_hat", "dt": "dt", **GENESIS_KEYS}[sweep]
    return ov.get(key, MISSING)


def gen_label(r, sweep, cfg):
    """表第一列 / 视频卡片标题：该档在扫描维度上的人话取值（官方默认那档加「（官方默认）」）。"""
    if sweep == "baseline":
        return "官方默认参数"
    v = gen_level_value(r, sweep, cfg)
    dflt = "（官方默认）" if r["sweep"] == "baseline" else ""
    if sweep == "mesh_res":
        if r["sweep"] == "baseline":
            # gs.morphs.Sphere -> mu.create_sphere(radius) 默认 subdivisions=3（genesis/engine/mesh.py:527, utils/mesh.py:1110）
            return "官方 Sphere（官方默认）：icosphere 细分 3 次（表面 642 个顶点）"
        size = {"coarse": "粗", "medium": "中", "fine": "细"}.get(r["level"], r["level"])
        # trimesh.creation.icosphere(subdivisions=k)：表面 10·4^k + 2 个顶点（soft_ball_morph docstring）
        return size + (f"：icosphere 细分 {v} 次（表面 {10 * 4 ** v + 2} 个顶点）" if isinstance(v, int) else "")
    if not is_num(v):
        return r["level"] + dflt
    if sweep == "d_hat":
        return g3(v * 1000) + dflt
    if sweep == "resistance":
        return sci(v) + dflt
    if sweep == "init_penetration":
        return ("不穿插" if v == 0 else f"两个软球互相穿进 {g3(v)} R") + dflt
    return g3(v) + dflt


# ---------------- 每个实验的文字 ----------------
GENESIS_TABLES = [  # (扫描, 标题, 改了什么, 第一列表头, 按 IPC 原理期待的结果)；baseline = 官方参数的盒子 demo
    ("baseline", "官方参数：一堆物体扔进盒子",
     "对照档：下面各节要扫的参数在这里都取官方本例的值和 Genesis 默认（软球 E 是否改过见下一句）。", "配置",
     "物体落下、互相碰撞后堆在盒子里。IPC 的 barrier 让任意两个表面之间始终留着一点小于 d̂ 的间隙，"
     "所以全程不该有穿透。"),
    ("d_hat", "d̂（barrier 作用距离）", "改 contact_d_hat。官方本例取 1 cm，Genesis 注释说应按网格分辨率取。", "d̂（mm）",
     "d̂ 是 barrier 开始起作用的距离。d̂ 变小，停住时每一对接触面之间的间隙跟着变小；\\(\\kappa_{\\min}\\propto 1/\\hat d^{4}\\)（见本节开头的式子），接触更硬，"
     "Newton 迭代一般会变多；d̂ 变大，物体隔得更远就被推开。不论 d̂ 取多少，都不该出现穿透。"),
    ("dt", "时间步长 dt", "改 SimOptions.dt。官方本例 0.02 s；物理时长固定 2 s，帧数随 dt 变。", "dt（s）",
     "dt 变小，每一步物体移动得更少；但 \\(\\kappa_{\\min}\\propto 1/\\Delta t^{2}\\)（见本节开头的式子，dt 缩小 10 倍、κ 区间抬高 100 倍），"
     "所以每步的 Newton 次数不一定减少，总步数则成倍增加。不论 dt 多大都不该穿透。"),
    ("resistance", "接触刚度 κ", "改 Genesis 的 contact_resistance，默认 1e9 Pa。", "设的 κ（Pa）",
     "κ 是 barrier 的刚度（式子见本节开头）。libuipc 会把它夹进区间 \\([\\kappa_{\\min},\\kappa_{\\max}]\\)："
     "在区间内，κ 越大 barrier 这堵墙越陡，物体陷进 barrier 越浅，间隙越接近 d̂；区间外的值会被夹到边界，"
     "结果应该和边界值一样。"
     "§本场景代入得 \\([1.57\\times10^{5},\\,1.57\\times10^{7}]\\) Pa，和日志打印的一致。"),
    ("init_penetration", "初始穿插", "多放一个软球，让它和官方软球一开始就互相穿进去一部分（R 为球半径）。",
     "初始状态",
     "IPC 的 barrier 只在两个表面距离为正时才有定义，一开始就穿插的话能量没有意义，"
     "所以 libuipc 的初始化检查应该直接拒绝开跑。"),
    ("mesh_res", "网格分辨率", "官方 Sphere 本身就是表面细分 3 次的 icosphere；把软球换成同样大小、表面细分 2 / 3 / 4 次的 icosphere，"
     "由 Genesis 自己四面体化。",
     "软球网格",
     "网格越细，球面越接近真球，接触时参与的顶点越多，每步要解的未知数越多、越慢。"
     "只要初始无穿插，网格粗细都不该影响会不会穿透，物体落地后的大致位置应该接近。"),
]

# 每个实验看什么（它的 SWEEP_COLUMNS）以及为什么
OBSERVE = {
    "baseline": "停住时每一对接触面（球–地、球–布、布–方块……）之间的最短距离，每帧 Newton 迭代几次（好不好解）。",
    "d_hat": "每一对接触面之间的最短距离（是否跟着 d̂ 变）、每帧 Newton 迭代几次、软球表面边长（球有没有被自接触撑开）。",
    "dt": "每帧 Newton 迭代几次、总耗时，以及停住时各接触面之间的间隙（接触变硬没有）。",
    "resistance": "每一对接触面之间的最短距离：刚度真的变了，间隙就该跟着变。",
    "init_penetration": "libuipc 开跑前检查的日志原文。",
    "mesh_res": "libuipc 实际用的 κ（日志原文）、停住时各接触面之间的间隙、总耗时。",
}
# 每个实验的简短「原因 → 结果」观察，每条都能从它上面的表读出来（括号里是数字）
OBSERVATIONS = {
    "baseline": ["每一对接触面停住时 → 间隙 0.73–0.99 倍 d̂，不贴死",
                 "接触越重 → 间隙越小（方块–地面 0.8 倍 d̂ < 软球–地面 0.85 < 布–地面 0.97）"],
    "d_hat": ["d̂ ↓ → 间隙 ↓（始终约 0.6–1 倍 d̂）",
              "d̂ ↓ → Newton 次数 ↑（每帧最多：10 mm 7 次 → 5 mm 9 次 → 2 mm 11 次）",
              "d̂ > 软球表面边长（约 12 mm）→ 球被自接触撑开（边长被撑到约 d̂：15 mm 时 15 mm，30 mm 时 26 mm）"],
    "dt": ["dt ↓ → κ 下限 ↑ → 接触更硬 → 间隙更接近 d̂（0.04 s 时 6.7–9.2 mm → 0.002 s 时 9.4–9.6 mm）",
           "dt ↓ → 总步数 ↑ → 耗时 ↑（0.04 s 16 s → 0.002 s 152 s），每帧 Newton 次数基本不变"],
    "resistance": ["区间内 κ ↑ → 接触更硬 → 间隙 ↑（软球–地面：2e5 时 4.6 mm → 1e7 时 8.2 mm）",
                   "κ 在区间外 → 被夹到边界 → 结果不再变（1e4 ≈ 2e5，默认 1e9 ≈ 1e7）"],
    "init_penetration": ["一开始就穿插 → libuipc 开跑前的检查报相交 → 拒绝开跑",
                         "关掉检查硬跑 → 能跑完、不报错，但两个球一直嵌在一起（球心距离始终约 120–136 mm，不穿插至少要 160 mm）"],
    "mesh_res": ["网格越密 → 顶点平均质量 ↓ → κ ↓（粗 4.9e7 → 细 3.4e6）",
                 "κ ↓ → 网格没变的物体接触变软 → 方块–地面间隙 ↓（粗 8.1–8.5 mm → 细 4.1 mm）",
                 "网格越密 → 耗时 ↑（粗 12.1 s → 细 31.7 s）"],
}
# 每个实验的一两句结论（数字在它上面的表里；核对过的数据见 Neural-IPC docs/claude_todo.md 与组会提纲第 4 节）
FINDINGS = {
    "baseline": "与期待一致：全程没有穿透；停住时每一对接触面（不只是和地面，也包括球–布、布–方块）之间都留着一条"
                "0.7–1 倍 d̂ 的缝，物体停在 barrier 起作用的那一层里。越重的接触缝越小：方块压地约 0.8 d̂，"
                "软球约 0.85 d̂，很轻的布只陷到约 0.97 d̂——barrier 的推力随间隙变小急剧增大，越重越要陷得深才托得住。",
    "d_hat": "与期待一致：所有接触的间隙都跟着 d̂ 走（始终约 0.6–1 倍 d̂），d̂ 越小物体靠得越近，但每帧 Newton 迭代越多"
             "（越难解）。d̂ 不能大于软体表面网格的边长（这个软球静止时约 12 mm）：IPC 的 barrier 也作用在同一个球自己的"
             "不相邻面片之间，d̂ 一旦超过边长，球就被自己从里面撑开，边被撑到和 d̂ 差不多长才停——15 mm 时边长变成约 15 mm、"
             "球明显变形，30 mm 时边长约 26 mm、球完全变形；2、5、10 mm 时边长不变。",
    "dt": "与期待一致：每帧迭代次数基本不随 dt 变，总耗时随步数成倍增加；dt 越小，接触间隙越接近 d̂（libuipc 的 \\(\\kappa_{\\min}\\propto 1/\\Delta t^{2}\\)，接触更硬、物体陷得更浅）。",
    "resistance": "与期待一致：libuipc 只认这个场景允许的区间 [1.57e5, 1.57e7] Pa。区间内（2e5 → 1e6 → 3e6 → 1e7）"
                  "κ 越大接触越硬、物体陷得越浅，各接触面的间隙一路变大（软球–地面 4.6 → 6.5 → 7.4 → 8.2 mm，d̂ = 10 mm）；"
                  "区间外被夹到边界：1e4 被夹到下限、结果和 2e5 差不多，默认 1e9 被夹到上限、结果和 1e7 差不多。"
                  "所以在 Genesis 里设 contact_resistance 只有落在这个区间里才有用。",
    "init_penetration": ("与期待一致：一开始就穿插时 libuipc 直接拒绝开跑。即使关掉检查硬跑，IPC 也分不开已经穿进去的两个物体："
                         "barrier 和 CCD 只能阻止「没穿 → 穿进去」，管不了一开始就穿着的部分，结果两个球一直粘在一起、"
                         "互相挤变形——程序不报错但物理上是错的。所以 IPC 必须从无穿透的状态开始。"),
    "mesh_res": ("libuipc 整个场景只用一个 κ，按全场景所有顶点的平均质量定区间（\\(\\kappa_{\\min}\\propto\\bar m\\)，见本节开头的式子）："
                 "软球网格越密，顶点越多、平均质量越小，κ 区间整体往下移（默认 1e9 被夹到的上限从粗网格的 4.9e7 降到细网格的 "
                 "3.4e6）。每对接触的 barrier 不按面积加权，所以加密的软球自己多了接触点、大致抵消（软球–地面间隙 8.4–8.7 → "
                 "6.4 mm）；而网格没变的方块、布没有抵消，接触明显变软（方块–地面 8.1–8.5 → 4.1 mm）。也就是说加密一个物体"
                 "会让场景里其他物体的接触变软。另外最细那档表面边长已小于 d̂，自接触把球撑开；网格越细越慢。"),
}


def gen_defaults_text(gd):
    """官方默认参数一句话（dt、d̂ 读官方默认档的结果文件 gd，κ、μ 是 Genesis 默认值）。"""
    dh = dig(gd, "libuipc_config", "contact", "d_hat")
    ball_e = (gd.get("overrides") or {}).get("ball_E", GENESIS_DEFAULTS["ball_E"])
    return (f"dt = {g3(gd.get('dt', MISSING))} s、d̂ = {g3(dh * 100) if is_num(dh) else '—'} cm、"
            f"κ = {sci(GENESIS_DEFAULTS['contact_resistance'])} Pa、μ = {g3(GENESIS_DEFAULTS['friction_mu'])}、"
            f"软球用官方 Sphere 网格、软球 E = {sci(ball_e)} Pa"
            + ("（官方是 1e3）" if ball_e != GENESIS_DEFAULTS["ball_E"] else "（官方值）"))


# ---------------- 表的列：(表头, 从结果文件取格子文字的函数) ----------------
def col_newton(d):
    """每帧 Newton 迭代次数「中位 / 最多」。"""
    s = d.get("summary") or {}
    return f"{g3(s.get('newton_iter_frame_stats_median'))} / {g3(s.get('newton_iter_frame_stats_max'))}"


def col_wall_seconds(d):
    """仿真总耗时（s）。"""
    return g3(dig(d, "summary", "wall_seconds_total"))


def col_edge(d):
    """各软球末帧表面边长中位数的范围（mm；静止时 12.1 mm）。"""
    es = [o["surface_edge_median_m"] for o in (d.get("objects_final") or {}).values()
          if isinstance(o, dict) and is_num(o.get("surface_edge_median_m"))]
    return f"{g3(min(es) * 1000)}–{g3(max(es) * 1000)}" if es else "—"


CONTACT_KINDS = ("软球", "方块", "布", "墙", "地面")  # 接触间隙各列的顺序


def contact_kind(name):
    """contact_gaps_final 里物体名的人话类别（sweep.py："<i>_Sphere_Elastic" 或 "<i>_Mesh_Elastic"（mesh_res 的
    icosphere 软球）、"<i>_Box_Rigid"、"<i>_Mesh_Cloth"、"<i>_wall"、"ground"）。"""
    for key, kind in (("Elastic", "软球"), ("Box", "方块"), ("Cloth", "布"), ("wall", "墙"), ("ground", "地面")):
        if key in name:
            return kind
    return name


def contact_groups(d):
    """{"<类别>–<类别>": [间隙 mm, …]}：末帧处于接触的表面对（最短表面距离小于 d_hat，libuipc barrier 起作用的范围；
    sweep.py contact_gaps_final），没有这项记录则 None。sweep.py 开始记录之前跑的档，读 genesis_<set>_contact/ 下的重跑。"""
    c = d if "contact_gaps_final" in d else load_json(
        SWEEP_ROOT / f"genesis_{GEN_TAG}_contact" / d["sweep"] / f"{d['level']}.json")[0]
    dh = dig(c, "libuipc_config", "contact", "d_hat") if isinstance(c, dict) else MISSING
    if not (isinstance(c, dict) and c.get("status") == "ok" and "contact_gaps_final" in c and is_num(dh)):
        return None
    groups = {}
    for g in c["contact_gaps_final"]:
        if g["distance_m"] < dh:
            key = "–".join(sorted((contact_kind(g["a"]), contact_kind(g["b"])), key=CONTACT_KINDS.index))
            groups.setdefault(key, []).append(g["distance_m"] * 1000)
    return groups


def contact_columns(rows):
    """rows 里出现过的每种接触类别一列 (表头, 函数)；格子是该类接触的间隙范围（mm）。"""
    kinds = sorted({k for r in rows if r["state"] == "ok" for k in (contact_groups(r["data"]) or {})},
                   key=lambda k: [CONTACT_KINDS.index(p) for p in k.split("–")])

    def cell(d, k):
        """一档在类别 k 上的间隙范围文字。"""
        v = (contact_groups(d) or {}).get(k)
        return (g3(min(v)) + (f"–{g3(max(v))}" if len(v) > 1 else "")) if v else "—"
    return [(f"{k} 间隙（mm）", lambda d, k=k: cell(d, k)) for k in kinds]


def kappa_used(d):
    """(libuipc 实际用的 κ（Pa）, "否" / "夹到下限" / "夹到上限")，读它自己的日志行（sweep.py kappa_log，需要
    --log-level Debug；没开 Debug 的档读 genesis_<set>_kdebug/ 下的重跑），没有记录区间则 None。
    κ 记为 0 的接触对是 Genesis 关掉的对（no-collision 元素，coupler.py:717-720），跳过。"""
    kl = d.get("kappa_log") or {}
    if not kl.get("kappa_corridor"):
        kl = (load_json(SWEEP_ROOT / f"genesis_{GEN_TAG}_kdebug" / d["sweep"] / f"{d['level']}.json")[0] or {}) \
            .get("kappa_log") or {}
    corr = [h["groups"] for h in kl.get("kappa_corridor", [])]
    if not corr:
        return None
    lo, hi = float(corr[0][0]), float(corr[0][1])
    clamped = sorted({float(h["groups"][3]) for h in kl.get("model_kappa_clamped", []) if float(h["groups"][0]) > 0})
    if clamped:
        return clamped[0], ("夹到下限" if abs(clamped[0] - lo) < 1e-3 * lo else "夹到上限")
    return (d.get("overrides") or {}).get("contact_resistance", GENESIS_DEFAULTS["contact_resistance"]), "否"


def col_kappa(d):
    """libuipc 实际用的 κ（Pa）。"""
    k = kappa_used(d)
    return sci(k[0]) if k else "—"


def col_clamped(d):
    """κ 有没有被夹、夹到哪一侧。"""
    k = kappa_used(d)
    return k[1] if k else "—"


NEWTON, SECONDS = ("Newton 次数（中位 / 最多）", col_newton), ("仿真总耗时（s）", col_wall_seconds)
KAPPA = ("libuipc 实际用的 κ（Pa）", col_kappa)
CLAMPED = ("被夹", col_clamped)
CONTACT = ("CONTACT", None)  # 由 contact_columns 展开成每种接触类别一列
EDGE = ("软球表面边长（mm，静止 12.1）", col_edge)
# 每个实验的表只放它的结论关心的量，一眼看出趋势。穿透对每档都一样（没有），在正文里说一次。
# CONTACT 量的是每个物体到它实际接触的表面（布、另一物体、墙或地面）的间隙。
SWEEP_COLUMNS = {"baseline": [CONTACT, NEWTON], "d_hat": [CONTACT, NEWTON, EDGE], "dt": [CONTACT, NEWTON, SECONDS],
                 "resistance": [KAPPA, CLAMPED, CONTACT], "init_penetration": [],
                 "mesh_res": [KAPPA, CLAMPED, CONTACT, SECONDS]}


def gen_raw_cells(r, cols):
    """一档的一行：按 cols 的函数从结果文件取每格；没跑成的档第一格写原因、其余「—」。"""
    if r["state"] != "ok":
        return [r["reason"]] + ["—"] * (len(cols) - 1)
    return [fn(r["data"]) for _, fn in cols]


def genesis_sweep_tables(sweeps, cfg):
    """每个实验一项 (扫描, 标题, 一句话, 期待, 排好序的行, 表 HTML)；每张表都带官方默认那一档对照。"""
    base = rows_of(sweeps, "baseline")
    out = []
    for sweep, title, one, head, expect in GENESIS_TABLES:
        ref = base
        rows = list(base) if sweep == "baseline" else list(rows_of(sweeps, sweep)) + list(ref)

        def key(r):
            """排序键：按扫描维度取值从小到大，官方 Sphere 排在 mesh_res 的「中」前面。"""
            if sweep == "baseline":
                return 0
            if r["sweep"] == "baseline" and sweep == "mesh_res":  # 官方 Sphere 也是细分 3 次，排在「中」前面
                return 2.5
            v = gen_level_value(r, sweep, cfg)
            return v if is_num(v) else float("inf")
        rows.sort(key=key)
        cols = [c for col in SWEEP_COLUMNS[sweep] for c in (contact_columns(rows) if col is CONTACT else [col])]
        trs = [[gen_label(r, sweep, cfg)] + gen_raw_cells(r, cols) for r in rows]
        out.append((sweep, title, one, expect, rows,
                    table([head] + [h for h, _ in cols], trs) if cols else ""))
    return out


# ---------------- 公式块与初始穿插 ----------------
# 下面各实验都用到的接触能量：IPC 论文的 barrier（Li et al. 2020，式 5 与截断 log barrier）、libuipc 的 log² barrier
# （contact_models/sym/codim_ipc_contact.inl KappaBarrierLog2，在 ipc_simplex_normal_contact.cu 里以 kappa * dt^2 调用）、
# Genesis 的逐对 κ（coupler.py:680-717）与 libuipc 的 κ 区间（global_contact_manager.cu:265-303；代入即复现每条日志里的区间）
FORMULA_BLOCK = (
    '<h3>IPC 的接触能量与 κ 区间（下面各实验都用）</h3>'
    '<p class="expect"><b>原版 IPC 论文：</b>每一对距离小于 d̂ 的接触（点–三角形、边–边）加一项 barrier 能量，'
    '距离越近能量越大，距离为 0 时无穷大——这堵「无穷高的墙」保证永远穿不过去：'
    '\\[ b(d)=\\begin{cases}-(d-\\hat d)^2\\ln\\dfrac{d}{\\hat d}, & 0&lt;d&lt;\\hat d\\\\[2pt] 0, & d\\ge\\hat d\\end{cases}'
    '\\qquad E_{\\text{contact}}=\\kappa\\sum_{k\\in C} b(d_k) \\]</p>'
    '<p class="expect"><b>libuipc 实际用的：</b>换成按距离平方 \\(D=d^2\\) 写的 log² 形式（同样 \\(D\\to0\\) 时无穷大、'
    '\\(D\\ge\\hat d^{2}\\) 时为 0），并且整个能量乘了 \\(\\Delta t^2\\)：'
    '\\[ B(D)=\\kappa\\,\\Delta t^{2}\\,(D-\\hat d^{2})^{2}\\Big[\\ln\\frac{D}{\\hat d^{2}}\\Big]^{2},\\qquad '
    '0&lt;D&lt;\\hat d^{2} \\]</p>'
    '<p class="expect"><b>Genesis：</b>自己不算 barrier。它把每个物体的 contact_resistance 当作 κ，两个物体之间取调和平均'
    '\\(\\kappa_{ij}=\\dfrac{2\\,r_i r_j}{r_i+r_j}\\)，交给 libuipc；libuipc 再把它夹进按场景算出的区间：'
    '\\[ \\kappa_{\\min}\\approx\\frac{10^{11}\\,s\\,L^{2}\\,\\bar m}{4\\,\\hat d^{4}\\,\\Delta t^{2}},\\qquad '
    '\\kappa_{\\max}=100\\,\\kappa_{\\min} \\]'
    '直观上：每个顶点的惯性刚度是 \\(\\bar m/\\Delta t^{2}\\)，barrier 必须比它硬才能在一步内挡住物体，所以 '
    '\\(\\bar m\\) 越大 → κ 越大，\\(\\Delta t\\)、\\(\\hat d\\) 越小 → κ 急剧变大。</p>'
    + "<div class=\"tablewrap\"><table><tr><th>符号</th><th>含义</th><th>本场景（官方默认）</th></tr>"
    + "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>" for a, b, c in [
        ("\\(d\\)", "一对接触图元（点–三角形 / 边–边）之间的距离", "—"),
        ("\\(D=d^2\\)", "距离的平方（libuipc 用它算 barrier）", "—"),
        ("\\(\\hat d\\)", "barrier 开始起作用的距离", "10 mm"),
        ("\\(\\kappa\\)", "barrier 的刚度", "设 1e9 Pa，实际被夹到 1.57e7 Pa"),
        ("\\(C\\)，\\(k\\)", "所有距离小于 \\(\\hat d\\) 的接触对，\\(k\\) 是其中一对", "—"),
        ("\\(b(d)\\)，\\(B(D)\\)", "一对接触的 barrier 能量（论文 / libuipc）", "—"),
        ("\\(\\Delta t\\)", "时间步长", "0.02 s"),
        ("\\(r_i\\)", "物体 \\(i\\) 的 contact_resistance", "1e9 Pa"),
        ("\\(s\\)", "libuipc 的缩放系数 kappa_eval_scale", "1e-16"),
        ("\\(L\\)", "整个场景包围盒的对角线长度", "3.69 m"),
        ("\\(\\bar m\\)", "全场景所有顶点的平均质量", "0.0184 kg"),
        ("\\(\\kappa_{\\min}\\)，\\(\\kappa_{\\max}\\)", "libuipc 允许的 κ 下限 / 上限", "1.57e5 / 1.57e7 Pa"),
    ]) + "</table></div>")

# 初始穿插日志里每类句子的意思（libuipc sanity_check/simplicial_surface_intersection_check.cpp:289-336、
# core/internal/world.cpp:46；Genesis coupler）
INIT_LOG_GLOSSARY = [
    ("Intersection detected between Edge(a,b) … and Triangle(c,d,e) …",
     "开跑前检查发现一个球表面的边穿过了另一个球表面的三角形，即两球一开始就互相穿进去了。"),
    ("World is not valid, skipping init.", "libuipc 因此拒绝初始化，仿真不开跑。"),
]


def bypass_distance_table(level):
    """关掉开跑前检查硬跑时，两个互相穿插的软球（官方那个 entity 3 与最后加的那个）在若干帧的球心距离表
    （genesis_<set>_bypass/init_penetration/<level>.json 的 frames[*].objects 质心）；没有那次运行返回 ""。"""
    d, _ = load_json(SWEEP_ROOT / f"genesis_{GEN_TAG}_bypass" / "init_penetration" / f"{level}.json")
    if not (isinstance(d, dict) and d.get("status") == "ok" and d.get("frames")):
        return ""
    balls = [n for n in d["frames"][0]["objects"] if "Sphere" in n]
    a, b = next(n for n in balls if n.startswith("3_")), balls[-1]
    pick = [f for f in d["frames"] if f["frame"] in (1, 5, 10, 25, 50, len(d["frames"]))]
    dist = [math.dist(f["objects"][a][:3], f["objects"][b][:3]) * 1000 for f in pick]
    return table(["帧"] + [str(f["frame"]) for f in pick], [["两球球心距离（mm）"] + [g3(x) for x in dist]])


def init_log_excerpt(log_path):
    """初始穿插档的 libuipc / Genesis 日志原文摘录（只去掉终端颜色码，不改写）：
    前 3 行 Intersection detected、SimplicialSurfaceIntersectionCheck 那一段（到下一条带 [ 开头的日志为止）、
    World is not valid 各行、Genesis 的 IPC world initialized successfully、最后一行 AttributeError。
    返回 (行列表, Intersection detected 总行数)；文件不在返回 (None, 0)。"""
    p = Path(log_path)
    if not p.is_file():
        return None, 0
    lines = ANSI_RE.sub("", p.read_text(encoding="utf-8", errors="replace")).splitlines()
    inter = [ln for ln in lines if "Intersection detected" in ln]
    out = inter[:3]
    i = next((k for k, ln in enumerate(lines) if "SimplicialSurfaceIntersectionCheck" in ln), None)
    if i is not None:
        j = i + 1
        while j < len(lines) and not lines[j].startswith("["):
            j += 1
        out += lines[i:j]
    out += [ln for ln in lines if "World is not valid" in ln]
    out += [ln for ln in lines if "IPC world initialized successfully" in ln]
    out += [ln for ln in lines if ln.startswith("AttributeError")][-1:]
    return out, len(inter)


# ---------------- 各节 HTML ----------------
def genesis_experiment(sweep, title, one, expect, rows, tbl, cfg, videos, gd):
    """一个实验，顺序按 Neural-IPC AGENTS.md：按原理期待 → 设置与看什么 → 视频（初始穿插档是日志摘录）+ 只含
    SWEEP_COLUMNS[sweep] 的表 → 观察 → 结论。gd 是官方默认档的结果文件。"""
    if sweep == "baseline":
        text = f"{one}（{gen_defaults_text(gd)}）。"
    else:
        vals = "、".join(gen_label(r, sweep, cfg) for r in rows if r["sweep"] != "baseline")
        text = f"{one}取值：{vals}；其余参数保持官方默认（{gen_defaults_text(gd)}），表里也放了官方默认那一档对照。"
    # 期待里「§」之后是小字注（代入的数字、交叉核对）
    principle, _, note = expect.partition("§")
    parts = [f"<h3>{esc(title)}</h3>", f'<p class="expect"><b>按原理期待：</b>{esc(principle)}</p>',
             f'<p class="setting">{esc(note)}</p>' if note else "",
             f'<p class="setting">{esc(text)}看：{esc(OBSERVE[sweep])}</p>']
    if sweep == "init_penetration":
        for r in rows:
            if r["sweep"] == "baseline":
                continue
            lines, n_inter = init_log_excerpt((r["data"] or {}).get("log_path")
                                              or GEN_SWEEP_ROOT / sweep / f"{r['level']}.log")
            parts.append(f'<p class="small"><b>{esc(gen_label(r, sweep, cfg))}</b>：开跑前就被拒，没有视频。'
                         "上面是这个初始状态（同一场景只关掉开跑前的相交检查、只渲染第 0 帧，侧面看两个软球；球心相距 2R 减去穿插量，不穿插时至少 2R），"
                         "下面是被拒那次的日志原文摘录。</p>")
            img = init_frame_image(r["level"])
            log = (f'<pre class="log">{esc(chr(10).join(lines))}</pre>' if lines is not None
                   else '<div class="novideo">日志文件不存在</div>')
            parts.append((f'<img class="plot initframe" src="assets/images/{img[1]}" alt="初始状态：两个软球互相穿插" '
                          'loading="lazy">' if img else "") + log)
            parts.append(table(["日志里的句子", "是什么意思"], [list(g) for g in INIT_LOG_GLOSSARY]))
            rec = bypass_video_record(r["level"])
            if rec:
                parts.append('<p class="small"><b>关掉开跑前的相交检查（sanity_check_enable = false）硬跑：</b>'
                             "同一场景、同样的穿插，跑满 2 s。两个半径 80 mm 的球不穿插时球心至少相距 160 mm。</p>")
                parts.append('<div class="grid">' + demo_card(dict(rec, key=rec["key"]), {}) + "</div>")
                parts.append(bypass_distance_table(r["level"]))
    else:
        cards = [demo_card(dict(videos[(r["sweep"], r["level"])], title=gen_label(r, sweep, cfg)), {})
                 for r in rows if (r["sweep"], r["level"]) in videos]
        parts.append('<div class="grid">' + "".join(cards) + "</div>")
    parts.append(tbl)
    parts.append('<ul class="obs">' + "".join(f"<li>{esc(o)}</li>" for o in OBSERVATIONS[sweep]) + "</ul>")
    parts.append(f'<p class="concl"><b>结论：</b>{esc(FINDINGS[sweep])}</p>')
    return "\n".join(parts)


def sweep_section(gsweeps, cfg, videos):
    """「盒子实验与 IPC 参数扫描」节：set_variant 选的那套（主结果）的每个参数扫描。"""
    gb = rows_of(gsweeps, "baseline")
    gd = gb[0]["data"] if gb and gb[0]["data"] else {}
    gscene = ("Genesis 没有「一堆物体扔进盒子」的官方例子，这里用官方 ipc_objects_falling 场景加一个盒子和更多同款物体。"
              f"这一套：{VARIANTS[GEN_TAG]['label']}。所有实验每次只改一个参数。盒子墙画成半透明，盒内物体不透明。"
              "除了一开始就穿插的两档（开跑前被拒），所有档位 libuipc 的穿透检查都没有报穿透。")
    parts = ['<section id="sweep"><h2>盒子实验与 IPC 参数扫描</h2>', f"<p>{esc(gscene)}</p>", FORMULA_BLOCK]
    for sweep, title, one, expect, rows, tbl in genesis_sweep_tables(gsweeps, cfg):
        parts.append(genesis_experiment(sweep, title, one, expect, rows, tbl, cfg, videos, gd))
    parts.append("</section>")
    return "\n".join(parts)


def videos_section(demos, tests, facts):
    """「Demo 视频」与「官方测试场景」两节：官方 Genesis IPC 例子，然后 Genesis 自带的 IPC 测试（各带断言结果）。"""
    parts = ['<section id="videos"><h2>Demo 视频（Genesis + lib IPC）</h2>',
             '<p class="muted small">Genesis 官方 IPC 例子一字未改，相机用官方代码里给的 viewer 位置；物理由 Genesis 底层的 '
             "libuipc 在 GPU 上算，画面在服务器上离屏渲染（CPU 软件渲染）。</p>",
             '<div class="grid">', *[demo_card(r, facts) for r in demos], "</div></section>",
             '<section id="tests"><h2>官方测试场景</h2>',
             '<p class="muted small">Genesis 仓库自带的 IPC 测试（tests/ipc/），场景和断言一字未改，用 pytest 原样运行；'
             "每个测试自己写好了 viewer 相机位置，录像就用它。卡片里写的是官方断言有没有通过。</p>",
             '<div class="grid">', *[demo_card(r, facts) for r in tests], "</div></section>"]
    return "\n".join(parts)


# 上面实验对生成训练数据的意义：(要做什么, 依据的是上面哪个结果)
DATA_IMPLICATIONS = [
    ("接触刚度 κ 要显式设定，并从 libuipc 日志确认没被夹。",
     "κ 实验：Genesis 的 contact_resistance 只有落在 libuipc 按场景算出的区间里才生效，区间外一律被夹到边界。"),
    ("同一批数据里每个样本用同一个显式 κ，不能交给 libuipc 自动选。",
     "网格实验：κ 区间按全场景所有顶点的平均质量定，加密一个物体会让其他物体的接触变软（方块–地面间隙 8.1–8.5 → "
     "4.1 mm）；dt 实验：\\(\\kappa_{\\min}\\propto 1/\\Delta t^{2}\\)，dt 越小接触越硬。"),
    ("d̂ 是数据里接触的尺度：要记录下来，且不能大于物体最短的表面边长。",
     "d̂ 实验：每一对接触都停在约 0.6–1 倍 d̂ 的地方；d̂ 越小越贴近、但每帧 Newton 迭代越多；d̂ = 30 mm 大于软球表面边长时，"
     "自接触把球从里面撑开。"),
    ("初始状态必须无穿透，生成初始条件时先检查。", "初始穿插实验：一开始就互相穿插时 libuipc 拒绝开跑。"),
    ("关掉 libuipc 的半隐式提前终止，或者逐帧检查是否真的收敛。",
     "官方测试「地面滑动」：它默认开着，Newton 没算到收敛就停，误差积累成方块翻倒；关掉后断言通过。"),
]


def data_section():
    """「对生成训练数据的意义」节：DATA_IMPLICATIONS 每条一项（要做什么 + 依据）。"""
    items = "".join(f"<li><b>{esc(what)}</b><br><span class=\"small\">依据：{esc(why)}</span></li>"
                    for what, why in DATA_IMPLICATIONS)
    return f'<section id="data"><h2>对生成训练数据的意义</h2><ol>{items}</ol></section>'


def compute_facts(demos):
    """demo 卡片说明里引用的数字：动量例子末步相对动量误差（run_info.json 的 run.final_rel_momentum_error）。"""
    mom = [r for r in demos if r["key"] == "genesis_ipc_momentum" and r["state"] == "ok"]
    return {"momentum_err": dig(mom[0]["info"], "run", "final_rel_momentum_error") if mom else MISSING}


def week1_sections(demos, tests, gsweeps, cfg, facts, videos):
    """旧 week1 页的各节 HTML：Demo 视频 + 官方测试、盒子实验与参数扫描、对生成数据的意义。"""
    return [videos_section(demos, tests, facts), sweep_section(gsweeps, cfg, videos), data_section()]
