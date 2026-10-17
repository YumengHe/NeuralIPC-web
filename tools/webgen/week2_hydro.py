"""Week 2 页：讲稿 web_week2.md 里由代码生成的块——hydro 官方测试卡片、Genesis hydro 参数扫描（[[HYDRO_SWEEP]]）、
E0 收敛图、标签仿真视频、实验示意图——以及把它们填进讲稿的 week2_sections。

hydro 扫描数据：sandbox tools/ipc_sweep/sweep.py --backend hydro 写的 <HYDRO_OUT_ROOT>/<扫描>/<档位>.json；
视频：run_genesis_ipc_example.py --example hydro_press（<HYDRO_PRESS_VIDEO_ROOT>/<扫描>_<档位>/genesis_hydro_press.mp4）；
官方测试各档：--official-test --hydro-log（<HYDRO_OFFICIAL_VIDEO_ROOT>/<扫描>_<档位>/）。档位与基准取
configs.HYDRO_SWEEPS / HYDRO_OFFICIAL_SWEEPS；每档的按原理期待与判据见 sandbox docs/drafts/hydro_sweep_design.md。
"""

from pathlib import Path

from .catalog import E0_FIG, HYDRO, HYDRO_MORE, LABEL_VIDEOS, SETUP_ROOT
from .collect import collect_level
from .common import ANSI_RE, MISSING, OUTCOME_LABEL, dig, esc, g3, is_num, load_json, pct, sci
from .drafts import page_from_draft, sections_html
from .draft_md import NOTION_IMAGES
from .html_parts import demo_card, setting, table

# ---------------- 结论与小节清单 ----------------
HYDRO_CONCL_TODO = "结论待数据"   # 还没写结论的小节显示这句
# 每节最后一句结论（.kp 醒目色）。用户 / 主会话 2026-10-12 逐档核对 hydro_press/ 36 档后定稿；
# "official" = 官方测试各档（2026-10-12 读各档 hydro_log 末步后定稿）
HYDRO_CONCLUSIONS = {
    "b1_H": "压力场刚度在 10⁸ Pa（Genesis 默认）以内 hydro 公式成立：1e5–1e7 Pa 压深每 ×10 缩小 3.16 倍、实测 / 公式 "
            "1.03–1.04；1e8 Pa 时 1.11（球面离散使力偏低）；再大则部分接触被求解器的近刚性正则化接管"
            "（1e9 Pa 时 6/43 个接触块），压深不再按公式缩小（实测 / 公式 1.74）。",
    "b1_R": "刚球自带压力场时，压深与球半径无关（R = 0.05 / 0.1 / 0.2 m：1.804 / 1.797 / 1.800 mm），因为 Genesis "
            "用球自身的最大深度 D = R 归一化压力场；弹性解析解随半径增大而减小（同载荷半径加倍减小 21%）。",
    "b1_taud": "τd 只改变趋于平衡的快慢：τd = 0.01、0.1 s 在 0.2 s 内停稳，压深 1.78、1.80 mm；τd = 1 s 需约 8 s，"
               "之后压深在 1.84–1.88 mm 间小幅波动，比 τd = 0.1 s 大约 3%（原因未查明）。",
    "b1_beta": "近刚性区间里结果随纯数值参数 β 变化 3.6 倍（H = 1e9 Pa，β = 0.25 / 1 / 4：0.073 / 0.094 / 0.263 mm）；"
               "正常区间与 β 无关（H = 1e6 Pa 三档逐位相同）。",
    "b1_dt": "刚度小时压深与时间步无关（H = 1e6 Pa，dt 1/30–1/240 s 差别 < 1%）；刚度大时结果依赖时间步"
             "（H = 1e9 Pa：0.117 / 0.094 / 0.076 / 0.073 mm，dt = 1/240 s 时近刚性接触才消失）。",
    "b2_R": "hydro 对球半径的依赖（\\(R^{-1/2}\\)：半径每加倍压深 ×0.706、×0.722）与弹性解析解（\\(R^{-1/3}\\)，×0.794）"
            "不同，调参无法消除；对应实验方案 E1。",
    "b2_Eh": "压力场模量每 ×10，压深 ÷3.07、÷2.96，符合 \\(E_h^{-1/2}\\)。",
    "b2_E_over_Eh": "hydro 部分只有在材料杨氏模量不小于压力场模量时才主导结果：E = 1e5 Pa 时压深只有预测的 0.60"
                    "（块自身的弹性变形分担位移），E ≥ 1e6 Pa 时 0.99–1.04。",
    "official": "官方 hydro 用例在默认参数下，盒子 77% 的支撑力来自求解器的近刚性正则化而非压力场：H 从 10⁸ 增到 10⁹ "
                "下沉几乎不变（8.0 → 7.95 µm），改阻尼时间 τd（压力场里没有这个量）下沉却随之变化（τd = 0.01 s：1.83 µm）；"
                "只有 H 降到 10⁷ 时近刚性占比降到 9%，下沉才按压力场增大（16.1 µm）。",
    "b2_H": "刚球压 FEM 块时全局刚度 H 不影响压深（1e6 / 1e8 / 1e10 Pa：5.589 / 5.594 / 5.602 mm）：静力只由块的压力场模量决定。",
}
# 每个扫描一小节：(扫描名, 小标题, 想验证什么（HTML，\\(…\\) 交给 MathJax）, 小表的列类型，见 _hydro_rows)
HYDRO_SWEEP_PAGE = [
    ("b1_H", "刚球压地面：改压力场刚度 H",
     "球的压力场随深度线性增长、斜率 \\(H/D\\)（\\(D=R\\)），地面截面上积分得 "
     "\\(F=\\pi H\\delta^2(1-\\tfrac{2\\delta}{3R})\\)：力随压深按平方增长，同一重量下压深 \\(\\propto H^{-1/2}\\)。"
     "\\(H\\) 大到一定程度后，求解器把接触块换成近刚性处理，压深不再随 \\(H\\) 减小。",
     "b1"),
    ("b1_R", "刚球压地面：改球半径（同为 1 kg）",
     "球的 \\(D=R\\)，半径变大时压力场变缓、接触面变大，两者抵消：压深与半径无关。"
     "Hertz（弹性球压刚性平面，\\(F=\\tfrac43E^*R^{1/2}\\delta^{3/2}\\)）同一重量下压深 \\(\\propto R^{-1/3}\\)。",
     "b1_R"),
    ("b1_taud", "刚球压地面：改阻尼时间尺度 τd",
     "阻尼力 \\(\\tau_d k v_n\\) 只在运动时出现：静止压深不变；\\(\\tau_d\\) 小则落下后弹跳、晃动，\\(\\tau_d\\) 大则慢慢压下，"
     "停稳用时约与 \\(\\tau_d\\) 成正比。",
     "b1_taud"),
    ("b1_beta", "刚球压地面：改 β（近刚性处理的参数）",
     "\\(\\beta\\) 只在接触块进入近刚性处理时起作用：刚度小（\\(H=10^6\\)）时结果与 \\(\\beta\\) 无关；"
     "刚度大（\\(H=10^9\\)）时近刚性弹簧的刚度 \\(\\propto 1/\\beta^2\\)，\\(\\beta\\) 越大压得越深。",
     "b1"),
    ("b1_dt", "刚球压地面：改时间步长 dt",
     "柔顺时静止压深与步长无关；近刚性阈值 \\(\\propto 1/(\\delta t(\\delta t+\\tau_d))\\)，步长越小越多接触块回到"
     "「面积 × 压力」的正常处理，\\(H=10^9\\) 时压深向公式预测靠拢。",
     "b1"),
    ("b2_R", "刚球压 FEM 块：改球半径（同为 1 kg）",
     "块的压力场斜率 \\(E_h/D\\) 与球无关，\\(F_A=\\frac{E_h}{D}\\pi R\\delta^2(1-\\tfrac{\\delta}{3R})\\)："
     "同一重量下压深 \\(\\propto R^{-1/2}\\)；Hertz（刚球压弹性块）\\(\\propto R^{-1/3}\\)。",
     "b2_R"),
    ("b2_Eh", "刚球压 FEM 块：改块的压力场模量 E_h",
     "压深 \\(\\propto E_h^{-1/2}\\)；\\(E_h\\) 接近块的杨氏模量 \\(E\\) 时，块自身的弹性下陷占比上升。",
     "b2"),
    ("b2_E_over_Eh", "刚球压 FEM 块：改块的杨氏模量 E（E_h = 1e6 Pa）",
     "\\(E\\ge100E_h\\) 时块几乎不变形，重叠只由压力场决定；\\(E\\) 小时块自己被压下去，结果主要是有限元弹性，不再是 hydro 的公式。",
     "b2"),
    ("b2_H", "刚球压 FEM 块：改全局刚度 H",
     "刚球与 FEM 块接触时，全局 \\(H\\) 只当刚体一侧的梯度，静止时的力仍是「面积 × 块的压力」：压深与 \\(H\\) 无关。",
     "b2"),
]
HYDRO_PRECHECK = ["b1_mesh", "b1_probe", "b2_mesh"]   # 折叠在最后的网格前置检查
HYDRO_OFFICIAL_TITLE = {"baseline": "官方原样（H = 1e8 Pa，τd = 0.1 s）"}
HYDRO_STATE_TEXT = {"not_run": "未跑", "stale": "重跑中", "unfinished": "没跑完"}

# 未静止 = 最后 HYDRO_CREEP_WINDOW_S 秒的首尾净变化 |x(T) − x(T − 1 s)| / |x(T)| > HYDRO_CREEP_REL。
# 用首尾净变化，不用 max − min，避免把抖动当下沉（β = 4、E = 1e5 两档末段 ±1% 抖动、净变化 < 1%）
HYDRO_CREEP_WINDOW_S, HYDRO_CREEP_REL = 1.0, 0.01
# 官方测试各档只有 80 步 = 1.33 s，末 1 s 窗口会包进链条落下的冲击段，静止的档也被判成未静止；官方档改用末 0.25 s
HYDRO_OFFICIAL_CREEP_WINDOW_S = 0.25
# GPU 后端非逐位确定，两遍包围盒差几 µm 就打这条 ERROR（视频本身完好），判视频能否上页时忽略它
BBOX_NONDETERMINISM_ERROR = "[genesis_ipc] ERROR: pass-2 bounding box exceeds pass 1"

# demo 节的官方 hydro 测试设置说明
HYDRO_DEMO_SETTING = ("Genesis 官方测试 test_sap_rigid_rigid_hydroelastic_contact，场景和检查条件原样；地上一个 "
                      "0.5 × 0.5 × 0.2 m 的方盒，两条由球和胶囊（半径 24 mm）连成的链从上方落下；全部接触用 hydroelastic；"
                      "压力场刚度 1e8 Pa，阻尼时间尺度 0.1 s；80 步 = 1.33 s，视频慢放约 3.75 倍；"
                      "为便于观察接触，仅修改了光照、箱体颜色和相机仰角，物理过程与检查条件不变")


# ---------------- 收集 ----------------
def hydro_level_label(sweep, ov):
    """档位的人话标签，从该档 overrides 现算（没跑的档也能标）。"""
    cp, fem = ov.get("coupler", {}), ov.get("fem", {})
    H = cp.get("hydroelastic_stiffness", 1e8)   # SAPCouplerOptions 默认 1e8（genesis/options/solvers.py:187）
    if sweep in ("b1_mesh", "b1_probe"):
        return f"球面细分 {ov['sphere_subdiv']} 次"
    if sweep == "b2_mesh":
        return f"块表面细分 {ov['block_subdiv']} 次"
    if sweep in ("b1_H", "b2_H"):
        return f"H = {sci(H)} Pa"
    if sweep in ("b1_R", "b2_R"):
        return f"R = {g3(ov['R'])} m"
    if sweep == "b1_taud":
        return f"τd = {g3(cp.get('sap_taud', 0.1))} s"
    if sweep == "b1_beta":
        return f"H = {sci(H)} Pa，β = {g3(cp.get('sap_beta', 1.0))}"
    if sweep == "b1_dt":
        return f"H = {sci(H)} Pa，dt = 1/{round(1 / ov['dt'])} s"
    if sweep == "b2_Eh":
        return f"E_h = {sci(fem['hydroelastic_modulus'])} Pa"
    if sweep == "b2_E_over_Eh":
        return f"E = {sci(fem['E'])} Pa"
    return sweep


def net_drift_exceeds(t, x, window=HYDRO_CREEP_WINDOW_S):
    """时序 x(t) 末尾是否还在漂移：|x(T) − x(T − window)| / |x(T)| > HYDRO_CREEP_REL
    （x(T − window) 取窗口内第一步）。window 默认 HYDRO_CREEP_WINDOW_S（受控档）；官方测试档传 HYDRO_OFFICIAL_CREEP_WINDOW_S。"""
    start = x[t >= t[-1] - window][0]
    return bool(abs(x[-1]) > 0 and abs(x[-1] - start) / abs(x[-1]) > HYDRO_CREEP_REL)


def hydro_still_creeping(data):
    """该档末尾是否还在下沉：读该档的逐步数组（sweep.py 写的 <档位>.npz，路径在 run.npz），取压深时序
    （刚球压地面 delta_mesh，压 FEM 块 delta_overlap）交给 net_drift_exceeds。速度判据在缓慢蠕变时一开始就满足，
    不能用来判静止。返回 True / False；位置给定模式（probe）或 npz 缺失返回 None。"""
    import numpy as np   # 只为读该档的 npz（genesis 环境自带）
    run = data.get("run") or {}
    path = Path(run.get("npz") or "")
    if run.get("mode") != "press" or not path.is_file():
        return None
    arr = np.load(path)
    key = "delta_mesh" if run.get("scene") == "sphere_floor" else "delta_overlap"
    return net_drift_exceeds(arr["t"], arr[key])


def hydro_video_check(d, mp4, fit_json):
    """hydro 视频能否上页：mp4 存在且非空，且 camera_fit json 的 verify.n_frames_out == 0（逐帧没有出画面）。
    不看 job.exit（包围盒不一致的退出码 4 不影响视频）；job.log 里除 BBOX_NONDETERMINISM_ERROR 外还有 ERROR /
    Traceback 判失败。返回 (能否上页, 不能时的说明)。"""
    log = d / "job.log"
    if log.is_file():
        bad = [ln for ln in ANSI_RE.sub("", log.read_text(encoding="utf-8", errors="replace")).splitlines()
               if ("ERROR" in ln or "Traceback" in ln) and BBOX_NONDETERMINISM_ERROR not in ln]
        if bad:
            return False, "录像失败"
    if not (mp4.is_file() and mp4.stat().st_size > 0):
        return False, "视频还没录完" if not (d / "job.exit").is_file() else "视频未生成"
    fit, err = load_json(fit_json)
    if fit is None or err:
        return False, "取景检查结果缺失"
    if dig(fit, "verify", "n_frames_out") != 0:
        return False, "有帧物体出了画面"
    return True, None


def collect_hydro_sweeps(cfg):
    """所有 hydro 扫描（configs.HYDRO_SWEEPS）与官方测试各档（HYDRO_OFFICIAL_SWEEPS）的结果记录 + 视频记录。
    press 档复用 collect_level（overrides 与 configs 不一致 = 旧结果，标「重跑中」）；视频记录格式同 collect_demo，
    交给 plan_videos 压缩。没有 json / 视频的档照样留在表里（未跑），不跳过。
    返回 {"sweeps": {扫描: [档位记录]}, "videos": {(扫描, 档位): 视频记录}, "official": [官方测试各档记录]}。"""
    root = Path(cfg.HYDRO_OUT_ROOT)
    sweeps = {}
    videos = {}
    for sweep, spec in cfg.HYDRO_SWEEPS.items():
        rows = []
        for level in spec["levels"]:
            ov = cfg.hydro_overrides(sweep, level)
            r = collect_level(sweep, level, ov, root)
            r["label"] = hydro_level_label(sweep, ov)
            r["creeping"] = hydro_still_creeping(r["data"]) if r["state"] == "ok" else None
            rows.append(r)
            d = Path(cfg.HYDRO_PRESS_VIDEO_ROOT) / f"{sweep}_{level}"
            if not d.is_dir():
                continue   # 这一档没安排视频
            mp4 = d / "genesis_hydro_press.mp4"
            done, note = hydro_video_check(d, mp4, d / "camera_fit.json")
            videos[(sweep, level)] = {
                "key": f"hydro_{sweep}_{level}", "expects_video": True, "title": r["label"], "line": "", "dir": d,
                "state": "ok", "reason": None, "images": [], "video_src": mp4 if done else None, "video_note": note}
        sweeps[sweep] = rows
    official = []
    for sweep, spec in cfg.HYDRO_OFFICIAL_SWEEPS.items():
        for level, lv in spec["levels"].items():
            d = Path(cfg.HYDRO_OFFICIAL_VIDEO_ROOT) / f"{sweep}_{level}"
            cp = lv.get("coupler", {})
            label = HYDRO_OFFICIAL_TITLE.get(sweep) or "，".join(
                {"hydroelastic_stiffness": f"H = {sci(v)} Pa", "sap_taud": f"τd = {g3(v)} s"}.get(k, f"{k} = {v}")
                for k, v in cp.items())
            rec, err = load_json(d / "official_test.json")
            r = {"key": f"hydro_official_{sweep}_{level}", "expects_video": True, "title": label, "line": "", "dir": d,
                 "state": "ok", "reason": None, "images": [], "video_src": None, "video_note": None,
                 "rec": rec, "sweep": sweep, "level": level}
            if rec is None and not err:
                r.update(state="not_run", reason="未跑")
            elif err or "hydro_log" not in ((rec.get("scenes") or [{}])[0]) or rec.get("outcome") != "passed":
                # 跑过但没写出读数、或官方断言没过：失败，不当成未跑
                r.update(state="failed", reason="失败" if not err else "结果文件损坏")
            else:
                vp = Path(rec["scenes"][0]["video"])
                done, note = hydro_video_check(d, vp, d / "camera_fit_scene0.json")
                r["video_src"], r["video_note"] = (vp if done else None), note
            official.append(r)
    return {"sweeps": sweeps, "videos": videos, "official": official}


# ---------------- 扫描小表 ----------------
def _hydro_state_cell(r):
    """没跑完的档在表里的状态格：(人话状态, "muted")。"""
    return (HYDRO_STATE_TEXT.get(r["state"], r["reason"] or "失败"), "muted")


def _mm(v):
    """米 → 毫米、3 位有效数字；不是数时「—」。"""
    return g3(v * 1e3) if is_num(v) else "—"


def _hydro_rows(sweep, rows, kind):
    """一个扫描的小表：返回 (列名, 行)。只放判据要的量：压深/重叠实测、公式预测、两者之比，再按 kind 加列
    （b1：近刚性接触块；b1_taud：停稳用时；b1_R / b2_R：相对值与 Hertz 相对值；b2：块自身下陷）。
    数字全部取自该档 json 的 summary / run。"""
    depth = "重叠" if kind.startswith("b2") else "压深"
    heads = ["档位", f"{depth}实测（mm）", "公式预测（mm）", "实测 / 预测"]
    extra = {"b1": ["近刚性接触块 / 全部接触块"], "b1_taud": ["停稳用时（s）"],
             "b1_R": ["实测相对 R = 0.1 m", "Hertz 相对值"], "b2_R": ["实测相对 R = 0.1 m", "Hertz 相对值"],
             "b2": ["块自身下陷（mm）"]}[kind]
    base = next((r for r in rows if r["state"] == "ok" and abs(r["data"]["overrides"]["R"] - 0.1) < 1e-12), None)
    base_d = dig(base["data"], "summary", "delta_measured") if base else MISSING
    out = []
    for r in rows:
        if r["state"] != "ok":
            out.append([r["label"], _hydro_state_cell(r)] + ["—"] * (len(heads) + len(extra) - 2))
            continue
        s, run = r["data"]["summary"], r["data"]["run"]
        settle = dig(s, "settle_time_s", "0.0018")
        # 还在下沉（hydro_still_creeping，压深时序判）：末步压深与静力公式不可比，停稳时间也没有
        creeping = r.get("creeping") is True or (kind == "b1_taud" and not is_num(settle))
        cells = [r["label"], _mm(s.get("delta_measured")), _mm(s.get("delta_pred")),
                 "未静止" if creeping else g3(s.get("ratio_measured_over_pred"))]
        if kind == "b1":
            cells.append(f"{s.get('final_n_near_rigid')} / {s.get('final_n_pairs')}")
        elif kind == "b1_taud":
            cells.append("未静止" if creeping else g3(settle))
        elif kind in ("b1_R", "b2_R"):
            d = s.get("delta_measured")
            cells.append(g3(d / base_d) if is_num(d) and is_num(base_d) and base_d else "—")
            cells.append(g3((run["R"] / 0.1) ** (-1.0 / 3.0)))
        else:
            cells.append(_mm(dig(run, "final_depths", "u_el")))
        out.append(cells)
    return heads + extra, out


def _hydro_fact_line(rows):
    """由数据自动填的一句：跑完几档、实测/预测的范围、哪些档有近刚性接触块。"""
    ok = [r for r in rows if r["state"] == "ok" and r["data"]["summary"].get("mode") == "press"]
    still = [r for r in ok if r.get("creeping") is True]
    ratios = [r["data"]["summary"]["ratio_measured_over_pred"] for r in ok
              if r not in still and is_num(r["data"]["summary"].get("ratio_measured_over_pred"))]
    near = [r["label"] for r in ok if (r["data"]["summary"].get("final_n_near_rigid") or 0) > 0]
    txt = f"已跑完 {len(ok)} / {len(rows)} 档"
    if still:
        txt += "；末尾仍在下沉（未静止）的档：" + "、".join(r["label"] for r in still)
    if ratios:
        txt += f"；静止各档实测 / 预测在 {g3(min(ratios))}–{g3(max(ratios))} 之间"
    if ok:
        txt += "；末步有近刚性接触块的档：" + ("、".join(near) if near else "无")
    return txt + "。"


def _hydro_precheck_html(hy):
    """前置检查（网格、位置给定的力–压深曲线）：折叠起来，一句话 + 小表。"""
    parts = ['<details class="repro"><summary>前置检查：网格够不够细</summary>',
             '<p class="small">先确认网格误差小于要比较的效应，再用定下的网格跑上面各档。球面网格：同一刚球压地面，'
             '细分次数不同；力–压深曲线：把球按给定压深放好、只算一步，比较 Genesis 给出的力与公式（与动力学、求解器无关）；'
             '块网格：刚球压 FEM 块，块表面细分次数不同。</p>']
    for sweep in HYDRO_PRECHECK:
        rows = hy["sweeps"].get(sweep, [])
        if sweep == "b1_probe":
            trs = []
            for r in rows:
                if r["state"] != "ok":
                    trs.append([r["label"], _hydro_state_cell(r), "—", "—"])
                    continue
                ratio = [x for x in r["data"]["summary"].get("probe_ratio") or [] if is_num(x)]
                depths = [p["depth_set"] for p in r["data"]["run"]["probe"]]
                trs.append([r["label"], f"{_mm(depths[0])}–{_mm(depths[-1])}",
                            g3(ratio[0]) if ratio else "—", f"{g3(min(ratio))}–{g3(max(ratio))}" if ratio else "—"])
            parts.append(table(["球面细分", "压深范围（mm）", "最浅处 力实测 / 公式", "全程 力实测 / 公式"], trs))
        else:
            heads, trs = _hydro_rows(sweep, rows, "b2" if sweep.startswith("b2") else "b1")
            parts.append(table(heads[:4], [t[:4] for t in trs]))
    parts.append("</details>")
    return "".join(parts)


def _hydro_official_html(hy):
    """官方测试各档：视频卡片 + 小表（官方检查、盒子压进地面、近刚性接触承担的静力占比、停稳用时）。
    盒子下沉取 rigid_trajectory_scene0.npz 每步盒心高度（0.1 − z），静力取 hydro_log_scene0.npz 末步的
    total_F_static_z / total_F_static_z_near_rigid；下沉末 0.25 s 净变化 > 1% 则下沉与占比都标「未静止」。"""
    import numpy as np   # 只为读两个 npz（genesis 环境自带）
    trs, cards = [], []
    for r in hy["official"]:
        if r["state"] != "ok":
            trs.append([r["title"], _hydro_state_cell(r), "—", "—", "—"])
            cards.append(demo_card(dict(r, line=r["reason"]), {}))
            continue
        rec = r["rec"]
        hl = rec["scenes"][0]["hydro_log"]
        npz, hl_npz = r["dir"] / "rigid_trajectory_scene0.npz", Path(hl["npz"])
        sink, share, creeping = MISSING, MISSING, False
        log = np.load(hl_npz) if hl_npz.is_file() else None
        if log is not None and log["total_F_static_z"][-1] > 0:
            share = float(log["total_F_static_z_near_rigid"][-1] / log["total_F_static_z"][-1])
        if npz.is_file():
            traj = np.load(npz)
            names = [str(x) for x in traj["names"]]
            if "Box" in names:   # 盒子高 0.2 m、放在地上：压进地面 = 0.1 − 盒心高度（docs/drafts/T2.4_web_chapter_plan.md:82）
                sinks = 0.1 - traj["pos"][:, names.index("Box"), 2]
                sink = float(sinks[-1])
                if log is not None and len(log["t"]) == len(sinks):   # 两者都是第二遍每步一条
                    creeping = net_drift_exceeds(log["t"], sinks, HYDRO_OFFICIAL_CREEP_WINDOW_S)
        outcome = OUTCOME_LABEL.get(rec.get("outcome"), "无结果")
        settle = dig(hl, "settle_time_s", "0.03")
        trs.append([r["title"], outcome,
                    "未静止" if creeping else (g3(sink * 1e6) if is_num(sink) else "—"),
                    "未静止" if creeping else pct(share),
                    "未静止" if creeping else (g3(settle) if is_num(settle) else "80 步内未停稳")])
        cards.append(demo_card(dict(r, line=f"官方检查：{outcome}"), {}))
    return ('<div class="grid">' + "".join(cards) + "</div>"
            + table(["档位", "官方检查", "盒子压进地面（µm）", "近刚性接触承担的静力占比",
                     "停稳用时（s，速度 < 0.03 m/s）"], trs))


def hydro_sweep_html(hy):
    """[[HYDRO_SWEEP]] 的内容：每个参数一小节（想验证什么 → 视频 → 小表 → 自动填数的一句 → 结论），
    然后官方测试各档，最后折叠的前置检查。hy 是 collect_hydro_sweeps 的结果。"""
    parts = ['<p class="small muted">表里的词：压深 = 球最低点进入支撑面的深度；公式预测 = 用该档实际质量和 Genesis '
             "实际用的最大距离 \\(D\\) 解出的压深；近刚性接触块 = 刚度大到被求解器改按近刚性处理的接触块，"
             "它们的力不再是「面积 × 压力」。</p>"]
    for sweep, title, expect, kind in HYDRO_SWEEP_PAGE:
        rows = hy["sweeps"].get(sweep, [])
        parts.append(f"<h4>{esc(title)}</h4>")
        parts.append(f'<p class="expect"><b>按原理期待：</b>{expect}</p>')
        cards = [demo_card(dict(v, line=(f"压深 {_mm(dig(r['data'], 'summary', 'delta_measured'))} mm"
                                         if r["state"] == "ok" else "未跑")), {})
                 for r in rows for k, v in hy["videos"].items() if k == (sweep, r["level"])]
        if cards:
            parts.append('<div class="grid">' + "".join(cards) + "</div>")
        heads, trs = _hydro_rows(sweep, rows, kind)
        parts.append(table(heads, trs))
        parts.append(f'<p class="small">{esc(_hydro_fact_line(rows))}</p>')
        if sweep in HYDRO_CONCLUSIONS:
            parts.append(f'<p class="kp">{esc(HYDRO_CONCLUSIONS[sweep])}</p>')
        else:
            parts.append(f'<p class="concl"><b>结论：</b>{esc(HYDRO_CONCL_TODO)}</p>')
    parts.append("<h4>官方测试：改刚度 H 与阻尼时间尺度 τd</h4>")
    parts.append('<p class="expect"><b>按原理期待：</b>盒子底面平贴地面，力 ≈ \\(\\frac{H}{D}A\\delta\\)，'
                 "柔顺时盒子压进地面的深度 \\(\\propto 1/H\\)；\\(\\tau_d\\) 只改链落下时的弹跳和停稳快慢。</p>")
    parts.append(_hydro_official_html(hy))
    parts.append(f'<p class="kp">{esc(HYDRO_CONCLUSIONS["official"])}</p>')
    parts.append(_hydro_precheck_html(hy))
    return "".join(parts)


# ---------------- 讲稿里的其他图 / 视频块 ----------------
def hydro_more_html(hydro_more):
    """[[HYDRO_MORE]]：其余官方 hydro 测试，每个一张视频卡片（官方检查结果）+ 卡片底部小号灰字设置。"""
    cards = []
    for r, (_key, _nodeid, title, text) in zip(hydro_more, HYDRO_MORE):
        outcome = OUTCOME_LABEL.get(r.get("outcome"), "无结果") if r["state"] == "ok" else r["reason"]
        card = demo_card(dict(r, title=title, line=f"官方检查：{outcome}"), {})
        cards.append(card[:-len("</div>")] + setting(text) + "</div>")   # 设置放进卡片底部
    return '<div class="grid">' + "".join(cards) + "</div>"


def e0_figure():
    """[[E0_FIG]]：E0 实测图（标签能量 / Hertz 能量随 d̂ 的变化）。"""
    return (f'<figure><img src="assets/images/{E0_FIG}" alt="标签收敛图">'
            f'<figcaption class="small">E0 实测（外推前的原始数据）：标签能量 / Hertz 能量（1 表示一致），'
            f'横轴为 \\(\\hat d\\)，\\(\\hat d\\) 越大能量越偏高，故外推到 0</figcaption></figure>')


def label_video(exp):
    """[[E0_VIDEO]] / [[E1_VIDEO]]：标签仿真视频（catalog.LABEL_VIDEOS[exp]，每个压深一帧）。"""
    v = LABEL_VIDEOS[exp]
    return (f'<figure><video controls muted playsinline preload="metadata" src="assets/videos/{v["key"]}.mp4">'
            f'</video><figcaption class="small">{v["caption"]}；左为过球心的竖直截面（竖直方向放大），'
            f'右为俯视块顶面的竖直位移</figcaption></figure>')


def setup_figure(exp):
    """[[SETUP_En]]：该实验两张示意图并排，图注取渲染脚本记下的 caption（experiment_setups.json）；图登记进
    NOTION_IMAGES 由 build 复制。"""
    meta, err = load_json(SETUP_ROOT / "experiment_setups.json")
    if meta is None or err or exp not in meta.get("experiments", {}):
        raise SystemExit(f"[build_site] 找不到 {exp} 的示意图（{SETUP_ROOT}/experiment_setups.json）")
    figs = []
    for tag, img in sorted(meta["experiments"][exp]["images"].items()):
        src = Path(img["png"])
        NOTION_IMAGES.append(src)   # build 时复制进 assets/images/
        figs.append(f'<figure><img src="assets/images/{esc(src.name)}" alt="{esc(exp)} 示意图 {tag}" loading="lazy">'
                    f'<figcaption class="small">（{tag}）{esc(img["caption"])}</figcaption></figure>')
    return '<div class="grid">' + "".join(figs) + "</div>"


# ---------------- 整页 ----------------
def week2_sections(hydro, hydro_more, hy):
    """Week 2 页的各节 HTML：讲稿 web_week2.md 经 page_from_draft 转换，占位符填入本模块生成的块。
    hydro / hydro_more：collect_official_test 的记录；hy：collect_hydro_sweeps 的结果。讲稿不存在就停止。"""
    outcome = OUTCOME_LABEL.get(hydro.get("outcome"), "无结果") if hydro["state"] == "ok" else hydro["reason"]
    demo_html = ('<div class="grid">' + demo_card(dict(hydro, title=HYDRO["title"], line=f"官方检查：{outcome}"), {})
                 + "</div>" + setting(HYDRO_DEMO_SETTING))
    placeholders = {"DEMO_VIDEO": demo_html, "E0_FIG": e0_figure,
                    "HYDRO_MORE": lambda: hydro_more_html(hydro_more), "HYDRO_SWEEP": lambda: hydro_sweep_html(hy)}
    placeholders.update({f"{e}_VIDEO": (lambda e=e: label_video(e)) for e in LABEL_VIDEOS})
    placeholders.update({f"SETUP_E{i}": (lambda i=i: setup_figure(f"E{i}")) for i in range(6)})
    whole = page_from_draft("week2", placeholders)
    if whole is None:
        raise SystemExit("[build_site] 找不到 week2 讲稿 web_week2.md，停止（不退回旧内容）")
    return sections_html(whole)
