# 交接：生成脚本重构（截至 2026-10-17 08:35）

方案见 `docs/refactor_plan.md`（主会话已同意）。

**08:36 更新**：第 3 步与 README 已由主会话回归后提交（6a68348：三页与拆分前、与已发布页面均逐字节相同）；
第 4 步已按下文「第 4 步改动」写入并提交（661495d），README 补了 YumengHe 的 Pages 地址。剩余：主会话跑第 4 步回归
（`--week1-legacy` 三页与 before 全同；不带时 index、week2 全同）与正式生成；下文「第 4 步之后」各项。下面的状态表是 08:35 前的记录。

## 状态

| 步骤 | 状态 |
|---|---|
| 1 方案 | 完成，commit e068696 |
| 2 `--html-only --out-dir` | 代码完成，commit e889adf；**before 基准没生成**：code_run_gate 要的票据是 `~/.claude/hooks/code_run_ab3d244ce15d415bc_receipt.json`（按 agent_id 命名），主会话签的票不在这个槽位，agent 不碰 ~/.claude |
| 3 拆模块 | 代码已写完，**未运行、未 commit**（工作区：`tools/webgen/` 12 个文件 + 改写后的 `tools/build_site.py`），等回归 |
| 4 week1 从讲稿生成 | `drafts.page_from_draft(name, placeholders)` 已写好且 week2 已改用它；week1 的接线（下文「第 4 步改动」）因 change gate 拦截未跟踪文件 `pages.py` 未写入 |
| 5 README | 已改写，**未 commit**（描述的是新结构，应和第 3 步一起提交） |
| 6 docstring / 死代码 | 新模块每个函数都有 docstring；死代码按方案表删除（旧 week2 底稿拼接路径整段、`_ul/_pt/_math`、`GEN_PY/GEN_ENV`、`ast/shlex`、`build_pages` 的 `commit` 参数、`images_note`）。另发现未删：`week1_box.gen_ball_verts`、`gen_ground_out`、`BALL_SIZE_RE`（全仓无调用） |

## 回归怎么做（按顺序，全部只写 NAS 的 web_refactor 目录）

```
PY=/data/xiaoyingwang/projects/Neural-IPC-sandbox/.conda/genesis/bin/python
R=/nas/xiaoyingwang/Neural-IPC/outputs/web_refactor
W=/data/xiaoyingwang/projects/Neural-IPC-web

# 1) before：用改动前的代码（commit e889adf）生成。工作区已被第 3 步改写，所以从 worktree 跑
git -C $W worktree add /tmp/claude-1024/-data-xiaoyingwang-projects/88b47c9c-9d44-4059-a590-1f2f4ce7dac4/scratchpad/web_before e889adf
$PY /tmp/claude-1024/-data-xiaoyingwang-projects/88b47c9c-9d44-4059-a590-1f2f4ce7dac4/scratchpad/web_before/tools/build_site.py --html-only --out-dir $R/before
git -C $W worktree remove /tmp/claude-1024/-data-xiaoyingwang-projects/88b47c9c-9d44-4059-a590-1f2f4ce7dac4/scratchpad/web_before

# 2) after：当前工作区的新代码
$PY $W/tools/build_site.py --html-only --out-dir $R/after
for f in index week1 week2; do cmp $R/before/$f.html $R/after/$f.html && echo "$f 相同"; done

# 3) 演练输出不应报错（只打印）
$PY $W/tools/build_site.py | tail -5
```

worktree 里的旧 build_site.py 用 `Path(__file__).parents[1]` 当仓库根，`--html-only` 分支在过滤任务之后、写任何东西之前返回，
此前只读 NAS、stat 文件、`git log`，不会写 worktree 或本仓库。

三个都「相同」→ 提交第 3 步（`tools/webgen/`、`tools/build_site.py`）和 README。不同 → 用 `diff` 看差在哪一节，对应模块回到 e889adf 的写法。
可能的差异点（已静态核对，理论上不会变）：
- `drafts.page_from_draft` 的占位符换成通用 `@@PH<序号>@@`；当前 web_week2.md 没有任何 `[[…]]`，不影响输出。
- week2 的 `HYDRO_MORE` / `HYDRO_SWEEP` 块改为讲稿用到时才生成；讲稿不用时页面里本来也没有它们。
- `demo_card` 去掉了从不设置的 `images_note` 分支。

## 第 4 步改动（回归通过、第 3 步提交后再写入）

`tools/webgen/pages.py`：

```python
from .drafts import page_from_draft, sections_html

def build_pages(demos, tests, hydro, hydro_more, gsweeps, cfg, facts, videos, hy, week1_legacy=False):
    summary = week_summaries(demos, tests, gsweeps)
    toc = {wid: items for wid, _, items in WEEKS}
    sections = {"week2": week2_sections(hydro, hydro_more, hy)}
    week1 = None if week1_legacy else page_from_draft("week1", {})
    if week1 is None:
        sections["week1"] = week1_sections(demos, tests, gsweeps, cfg, facts, videos)
    else:
        sections["week1"] = sections_html(week1)
        toc["week1"] = [(a, t) for a, t, _ in week1 if t is not None]
    # 其余照旧，只把每周页面目录的 items 换成 toc[wid]（首页卡片仍用 WEEKS，保证 index 不变）
```

`tools/build_site.py`：加 `--week1-legacy`（store_true，「week1 走旧路径，回归对照用」），传给 `build_pages(..., week1_legacy=args.week1_legacy)`。

验收：`--html-only --week1-legacy` 三页与 before 全同；不带它时 index、week2 与 before 全同，week1 变为讲稿内容。
web_week1.md（sandbox，另一个 agent 写，已有 w1–w4 四节，commit a40bc99）里的视频文件名（`box_stiffball_*`、
`genesis_*`、`user_local_*`）与生成器的视频 key 一致；表格里的 `[▶](assets/videos/…)` 是普通链接，生成器照常处理，
被引用的视频会进入压缩清单。讲稿用到的图 `box_stiffball_init_penetration_overlap_0p5R.png` 来自 `init_frame_image`。

## 第 4 步之后

- week1 讲稿上线后，`week1_box.py` 的旧路径（`videos_section`、`sweep_section`、`data_section` 及其数据）可删；删前列清单给用户。
  注意 `gen_level_videos`、`bypass_video_record`、`init_frame_image`、`collect_sweeps`、`compute_facts` 仍被 build_site 用来排视频 / 图片 / 摘要，不能一起删。
- `media.plan_images` 与记录里的 `images` 字段：所有记录 images 恒为空，可连同 `demo_card` 的 `images_web` 循环一起删（会不会改输出：不会）。
- 首页 week1 卡片的节名仍是 `WEEKS` 里的旧四节，讲稿上线后应改成讲稿各节标题（这一改会让 index 变化，单独一个 commit）。
