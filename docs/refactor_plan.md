# 生成脚本重构方案

目标：把 2251 行的 `tools/build_site.py` 拆成「一个模块一件事」的小模块，提高可读性；week1 页改为和 week2 一样从讲稿 md 生成。
页面输出在拆分期间逐字节不变（用 `--html-only` 回归，见下）。

## 约束

- 命令行入口不变：`python tools/build_site.py [--execute] [--crf N] [--force-videos] [--variant TAG]`，默认仍是演练（什么都不写）。
- 新增只用于回归的 `--html-only --out-dir <目录>`：不编码视频、不复制图片、不写仓库，只把三个 html 写进指定目录。
- 不改任何页面文字；CSS 原样搬移。
- 包名不用 `site`（与 Python 标准库 `site` 模块同名，`import site.xxx` 会失败），用 `webgen`。
  `markdown` 转换模块也不叫 `markdown.py`（会遮住第三方 `markdown` 包），叫 `draft_md.py`。

## 回归方法

1. 改动前：`build_site.py --html-only --out-dir /nas/xiaoyingwang/Neural-IPC/outputs/web_refactor/before` 生成基准。
2. 每拆一块：生成到 `.../after/`，`cmp before/X.html after/X.html`（index / week1 / week2 三个），全部相同才 commit；不同就回退这一块。
3. week1 改为讲稿生成那一步：只要求 index、week2 逐字节不变，week1 允许变。

## 新文件结构

```
tools/
  build_site.py            命令行入口：解析参数 → 收集 → 生成页面 → 打印计划 → （--execute）压视频、复制图片、写页面
  webgen/
    __init__.py            包说明（一句话）
    config.py              路径（仓库、NAS 结果根目录、assets）、体积上限、站点标题、WEEKS 周清单
    common.py              通用小工具：esc、load_json、MISSING / dig、is_num、g3 / sci / pct、file_size_str、ANSI_RE
    catalog.py             页面上放哪些 demo / 官方测试 / 用户录屏 / hydro 测试的清单（纯数据：DEMOS、OFFICIAL_TESTS、
                           OFFICIAL_TEST_NOTES、USER_RECORDINGS、HYDRO、HYDRO_MORE、LABEL_VIDEOS、E0_FIG 等）
    collect.py             读 NAS 结果 → 统一的记录 dict：collect_demo、collect_official_test、collect_user_recording、
                           collect_demos、load_sweep_configs、collect_level、collect_sweeps
    media.py               视频 / 图片：encode_manifest、ffmpeg 参数、plan_videos、plan_images、encode_video、get_ffmpeg_exe
    html_parts.py          （不叫 html.py，避免遮住标准库 html）页面骨架与通用 HTML 片段：PAGE_CSS、page()、table()、demo_card()、setting()、takeaway()
    draft_md.py            讲稿 Markdown → HTML 转换：normalize_list_indent、notion_md_to_html、notion_image（登记引用的 NAS 图）
    drafts.py              讲稿整页生成：page_from_draft(name, placeholders) → [(锚点, 标题, HTML)]；
                           按「## SECTION wN: 标题」分节、TAKEAWAY / 结论行、[[占位符]] 替换
    week1_box.py           week1 旧路径：Demo 视频节、盒子实验与 IPC 参数扫描（GENESIS_TABLES、OBSERVE、OBSERVATIONS、
                           FINDINGS、FORMULA_BLOCK、初始穿插日志摘录等）、对生成数据的意义节
    week2_hydro.py         week2 的 Genesis hydro 参数扫描（[[HYDRO_SWEEP]]）、其余 hydro 官方测试卡片（[[HYDRO_MORE]]）、
                           E0 图 / 标签视频 / 实验示意图占位符的 HTML
    pages.py               build_pages：index 的各周卡片 + 每周一页（页首、目录、各节）
docs/
  refactor_plan.md         本文件
  handoff_refactor.md      （若没做完）交接说明
```

依赖方向（只从上往下 import，不循环）：`config/common` ← `catalog` ← `collect/media` ← `html_parts/draft_md` ← `drafts/week1_box/week2_hydro` ← `pages` ← `build_site.py`。

`set_variant` 改写的全局（GEN_TAG、GEN_BASE_OV、GEN_SWEEP_ROOT、GEN_VIDEO_ROOT）集中放进 `week1_box.py` 的一个小状态对象，
`collect_sweeps` 从那里读，避免跨模块改全局变量。

## 死代码（删除前逐个 grep 确认无调用，删除后回归逐字节一致）

已确认 `web_week2.md` 存在且在核对名单里，所以 week2 走整页讲稿路径，以下「逐篇讲稿 / Notion 底稿拼接」旧路径不再执行：

| 符号 | 原用途 | 处理 |
|---|---|---|
| `week2_sections` 里 `whole is None` 之后的整段 | 没有 web_week2.md 时用 Notion 底稿拼 week2 | 删；讲稿缺失时报错停止，不静默退回旧内容 |
| `HANDOUTS`、`_handout_sections`、`_handout_bullet`、`_trim`、`CUTS_*` | 从 docs/handouts 截节、删减 | 删 |
| `PAPER_FULL_NAMES`、`FULL_NAME_*`、`_full_names` | 底稿论文简称换全名 | 删 |
| `HYDRO_PAPERS`、`PAPER_CONTRIBUTIONS`、`_contribution`、`_hydro_papers` | 逐篇 hydro 论文 | 删 |
| `LECTURES_NEURAL`、`LECTURE_TAKEAWAYS`、`_lectures`、`_web_draft`、`_draft_html`、`VERIFIED_DRAFTS` 里除 week2 外的名字 | 逐篇神经网络论文 | 删 |
| `TAKEAWAYS`、`_add_takeaways`、`_with_e0_figure` | 往底稿 HTML 里插总结句、E0 图 | 删 |
| `_ul`、`_pt`、`_math` | 旧 week2 拼 HTML 的小工具（`_math` 从未被调用） | 删 |
| `GEN_PY`、`GEN_ENV` | 未被引用 | 删 |
| `import ast`、`import shlex` | 未被引用 | 删 |
| `build_pages` 的 `commit` 参数 | 未被使用（commit 只在演练打印里用） | 删参数，main 照常读 commit 打印 |
| `collect_demo` 的 `images` / `demo_card` 的 `images_web`、`images_note` / `plan_images` | momentum 图 2026-09-30 起不上页面，images 恒为空 | 保留到 week1 改讲稿后再删（旧 week1 路径仍在用这组字段的结构） |

旧 week1 路径（`videos_section`、`sweep_section`、`data_section` 及其数据）在 `web_week1.md` 存在之前**不删**，
否则无法做逐字节回归；week1 换成讲稿后再评估删除，删除前列清单给主会话。

## week1 改为讲稿生成

- `drafts.page_from_draft(name, placeholders)`：读 `Neural-IPC-sandbox/docs/drafts/web_<name>.md` 的「## A.」部分，
  `placeholders` 是 {`[[标记]]`: HTML} 字典；week2 现有的 `[[DEMO_VIDEO]]`、`[[E0_FIG]]`、`[[HYDRO_MORE]]`、`[[HYDRO_SWEEP]]`、
  `[[SETUP_En]]`、`[[En_VIDEO]]` 全部通过它传入，week2 输出逐字节不变。
- week1：`web_week1.md` 存在时 `page_from_draft("week1", {...})`；不存在时走旧 week1 路径。
- 页首摘要、目录：讲稿路径下从 `## SECTION` 标题生成目录（week2 现在的目录写在 `WEEKS` 里，保持不变）。

## README

改写为：仓库用途、目录结构表、每个模块干什么、如何生成（演练 / 正式 / 回归）、如何发布（push 到 `origin` 与 `yumeng` 两个 remote，
GitHub Pages 自动更新）、讲稿 md 的全部标记及示例。
