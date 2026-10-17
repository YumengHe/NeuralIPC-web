"""通用小工具：HTML 转义、读 json、按 key 链取值、数字格式化。"""

import html
import json
import re
from pathlib import Path

MISSING = object()   # dig() 取不到值时的返回值（区别于 json 里真实的 null）
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")   # 终端颜色码，读日志时去掉
OUTCOME_LABEL = {"passed": "通过", "failed": "未通过", "skipped": "跳过"}   # pytest outcome → 页面用词


def esc(x):
    """把任意值转成字符串并做 HTML 转义（含引号），用于放进标签正文或属性。"""
    return html.escape(str(x), quote=True)


def load_json(path):
    """读 json 文件。返回 (data, error)：文件不存在返回 (None, None)；解析失败返回 (None, 错误说明)。"""
    path = Path(path)
    if not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as e:  # 解析失败原样报告，不猜内容
        return None, f"{type(e).__name__}: {e}"


def dig(d, *keys):
    """按 key 链逐层取值（dict 用键、list 用整数下标），任何一层不存在返回 MISSING。"""
    cur = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, list) and isinstance(k, int) and -len(cur) <= k < len(cur):
            cur = cur[k]
        else:
            return MISSING
    return cur


def is_num(v):
    """v 是不是数（int / float，不含 bool）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def g3(v):
    """3 位有效数字；不是数时返回「—」。"""
    return "—" if not is_num(v) else f"{v:.3g}"


def sci(v):
    """科学计数，如 1.71e5、1e9；不是数时返回「—」。"""
    if not is_num(v):
        return "—"
    m, e = f"{v:.2e}".split("e")
    m = m.rstrip("0").rstrip(".")
    return f"{m}e{int(e)}"


def pct(v):
    """小数 → 3 位有效数字的百分数（0.0106 → 1.06%）；不是数时返回「—」。"""
    return "—" if not is_num(v) else f"{v * 100:.3g}%"


def file_size_str(n):
    """字节数 → 「x.xx MB」。"""
    return f"{n / 1024 / 1024:.2f} MB"
