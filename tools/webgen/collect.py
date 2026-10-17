"""读 NAS 上的结果文件，整理成页面用的统一记录（dict）。只读，不写任何文件。

记录的公共字段：key（也是压缩后视频的文件名）、title、line（卡片说明）、dir、state（ok / failed / not_run /
unfinished / stale / rejected）、reason（state 不是 ok 时的人话原因）、video_src（NAS 上的原视频，没有为 None）、
video_note（没有视频时的说明）。media.plan_videos 会再加上 video_web（页面里引用的相对路径）。
"""

import importlib.util
import json
import subprocess
from pathlib import Path

from .catalog import DEMOS, HYDRO, HYDRO_MORE, OFFICIAL_TEST_NOTES, OFFICIAL_TESTS, USER_RECORDINGS
from .common import MISSING, dig, load_json
from .config import DEMO_ROOT, PROJECT, SWEEP_CONFIGS, SWEEP_ROOT


def collect_demo(key, expects_video, title, line):
    """一个官方例子（catalog.DEMOS 的一条）：读 DEMO_ROOT/<key>/run_info.json，找它记录的视频。"""
    d = DEMO_ROOT / key
    info_path = d / "run_info.json"
    r = {"key": key, "expects_video": expects_video, "title": title, "line": line,
         "dir": d, "info_path": info_path, "info": None, "state": None, "reason": None,
         "video_src": None, "video_note": None, "images": []}
    if not d.is_dir():
        r["state"], r["reason"] = "not_run", "还没跑"
        return r
    info, err = load_json(info_path)
    if err:
        r["state"], r["reason"] = "failed", f"结果文件损坏（{err}）"
        return r
    if info is None:
        r["state"], r["reason"] = "failed", "没跑完（没有结果记录）"
        return r
    r["info"], r["state"] = info, "ok"

    v = info.get("video", MISSING)
    if v is None or v is MISSING:
        r["video_note"] = "这个 demo 本来就不出视频" if not expects_video else "这次运行没有产出视频"
    else:
        vp = Path(v)
        if vp.is_file() and vp.stat().st_size > 0:
            r["video_src"] = vp
        else:
            r["video_note"] = "视频文件缺失"

    # ipc_momentum 的 momentum_plot.png 不上页面（2026-09-30 用户：图表小、放不大、看不清，页面只放视频）；
    # 动量误差这个数字已写在卡片说明里（run.final_rel_momentum_error），原图仍在 NAS 该 demo 目录。
    return r


def collect_official_test(key, nodeid, title, line):
    """一个录了像的 Genesis 官方测试（run_genesis_ipc_example.py --official-test）：字段同 collect_demo，
    另加 nodeid 和 outcome（测试自己断言的 pytest 结果，读自 official_test.json）。"""
    d = DEMO_ROOT / key
    r = {"key": key, "expects_video": True, "title": title, "line": line, "dir": d, "info": None, "state": None,
         "reason": None, "video_src": None, "video_note": None, "images": [], "nodeid": nodeid, "outcome": None}
    rec, err = load_json(d / "official_test.json")
    if rec is None or err:
        r["state"], r["reason"] = "not_run", "还没跑" if rec is None and not err else f"结果文件损坏（{err}）"
        return r
    r["state"], r["outcome"] = "ok", rec.get("outcome")
    r["line"] = (f"{line} 官方断言：" + {"passed": "通过", "failed": "未通过", "skipped": "跳过"}.get(
        rec.get("outcome"), f"无结果（pytest 退出码 {rec.get('pytest_exit_code')}）") + "。"
                 + OFFICIAL_TEST_NOTES.get(key, ""))
    scenes = rec.get("scenes") or []
    vp = Path(scenes[0]["video"]) if scenes else None
    if vp and vp.is_file() and vp.stat().st_size > 0:
        r["video_src"] = vp
    else:
        r["video_note"] = "没有录到视频"
    return r


def collect_user_recording(key, video, title, line):
    """catalog.USER_RECORDINGS 的一条：字段同 collect_demo，视频就是那个录屏文件。"""
    ok = video.is_file() and video.stat().st_size > 0
    return {"key": key, "expects_video": True, "title": title, "line": line, "dir": video.parent,
            "info_path": None, "info": None, "state": "ok" if ok else "not_run",
            "reason": None if ok else f"找不到录屏文件 {video}", "video_src": video if ok else None,
            "video_note": None, "images": []}


def collect_demos():
    """页面只放 DEMOS、USER_RECORDINGS、OFFICIAL_TESTS 清单里的条目。DEMO_ROOT 下的其他目录（单独 libuipc 的 demo、
    计时运行等）不上页面，由 build_site 打印出来，不静默藏掉。返回 (demos, 官方测试, 清单外的目录名)。"""
    known = ({k for k, *_ in DEMOS} | {k for k, *_ in OFFICIAL_TESTS} | {k for k, *_ in USER_RECORDINGS}
             | {HYDRO["key"]} | {k for k, *_ in HYDRO_MORE})
    demos = [collect_demo(*spec) for spec in DEMOS] + [collect_user_recording(*spec) for spec in USER_RECORDINGS]
    tests = [collect_official_test(*spec) for spec in OFFICIAL_TESTS]
    unlisted = []
    if DEMO_ROOT.is_dir():
        unlisted = sorted(p.name for p in DEMO_ROOT.iterdir() if p.is_dir() and p.name not in known
                          and not p.name.startswith("genesis_box_levels") and not p.name.startswith("hydro_"))
    return demos, tests, unlisted


def load_sweep_configs():
    """按路径加载 Neural-IPC 的 tools/ipc_sweep/configs.py（纯数据文件；build_site 已关掉写 __pycache__）。"""
    spec = importlib.util.spec_from_file_location("neural_ipc_sweep_configs", SWEEP_CONFIGS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def collect_level(sweep, level, ov_cfg, root=SWEEP_ROOT):
    """参数扫描的一档：读 root/<sweep>/<level>.json（sweep.py 写的），按 status 判定 state / reason。
    ov_cfg 是 configs.py 里该档当前的 overrides（MISSING = configs 里没有这一档）；结果文件里的 overrides 与它不一致
    即旧配置的结果，标 stale、数据不上页面。"""
    jp = root / sweep / f"{level}.json"
    r = {"sweep": sweep, "level": level, "ov_cfg": ov_cfg, "json_path": jp, "data": None,
         "state": None, "reason": None}
    data, err = load_json(jp)
    if err:
        r["state"], r["reason"] = "failed", "结果文件损坏"
        return r
    if data is None:
        r["state"], r["reason"] = "not_run", "还没跑"
        return r
    r["data"] = data
    st = data.get("status", MISSING)
    # 结果文件里的 overrides 与当前 configs.py 的档位不一致 = 旧配置的结果，等重跑覆盖（json 往返后比较：tuple 存成 list）
    if ov_cfg is not MISSING and isinstance(data.get("overrides"), dict) \
            and data["overrides"] != json.loads(json.dumps(ov_cfg)):
        r["state"], r["reason"], r["data"] = "stale", "重跑中", None  # 旧数据一律不上页面
        return r
    if st == "ok":
        r["state"], r["reason"] = "ok", "跑完"
    elif st == "exception":
        tb = data.get("exception_traceback") or ""
        last = [ln for ln in tb.strip().splitlines() if ln.strip()]
        r["state"] = "failed"
        r["reason"] = "运行出错" + (f"：{last[-1].strip()}" if last else "")
    elif st == "init_invalid" and dig(data, "sanity_at_init", "penetration") is True:
        r["state"], r["reason"] = "rejected", "被 sanity check 拒绝（预期内）"
    elif st == "init_invalid":
        r["state"], r["reason"] = "failed", "初始化失败"
    elif st == "build_failed":  # genesis：scene.build 抛异常（sweep.py run_one_genesis）
        tb = data.get("build_traceback") or ""
        flagged = " ".join(x.get("text", "") for x in (dig(data, "log_flagged", "flagged_first") or [])
                           if isinstance(x, dict))
        last = [ln for ln in tb.strip().splitlines() if ln.strip()]
        if "intersect" in (tb + flagged).lower():
            r["state"], r["reason"] = "rejected", "开跑前被拒绝（检测到相交）"
        else:
            r["state"] = "failed"
            r["reason"] = "建场景出错" + (f"：{last[-1].strip()}" if last else "")
    elif st == "invalid_during_run":
        r["state"], r["reason"] = "failed", "仿真中途失效"
    elif st == "nonfinite_positions":
        r["state"], r["reason"] = "failed", "顶点坐标出现 NaN / inf"
    elif st in ("starting", "initializing", "running") and "summary" not in data:
        r["state"], r["reason"] = "unfinished", "没跑完"
    else:
        r["state"], r["reason"] = "failed", "状态未知"
    return r


def genesis_commit():
    """生成页面时 Neural-IPC 仓库的 HEAD（短哈希），只在演练输出里打印。读不到就停，不写猜的值。"""
    p = subprocess.run(["git", "-C", str(PROJECT), "log", "-1", "--format=%h"], capture_output=True, text=True)
    if p.returncode != 0 or not p.stdout.strip():
        raise SystemExit(f"[build_site] 读不到 {PROJECT} 的 git commit：{p.stderr}")
    return p.stdout.strip()
