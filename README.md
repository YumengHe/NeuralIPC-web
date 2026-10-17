# Neural-IPC-web

Neural-IPC 项目的组会网页：每周一页，内容是文献讲解、原代码说明、仿真 demo 视频、实验方案与结果。

在线地址（GitHub Pages，两个仓库内容相同）：

- https://delluluwxy.github.io/Neural-IPC-web/ （delluluwxy/Neural-IPC-web）
- http://heyumeng.com/NeuralIPC-web/ （YumengHe/NeuralIPC-web）

| 页面 | 内容 |
|---|---|
| `index.html` | 首页，链接到各周 |
| `week1.html` | 第 1 周：IPC 接触能量、Genesis + libuipc 官方例子与官方测试、盒子实验与参数扫描 |
| `week2.html` | 第 2 周：hydroelastic 与 Hertz、神经网络接触模型、原代码碰撞能量、Genesis hydro demo、与 hydro 对比的实验方案（E0–E5） |

页面全部由脚本生成，**不要手改 html**。

## 目录结构

| 路径 | 用途 |
|---|---|
| `index.html`、`week*.html` | 生成的页面（GitHub Pages 直接发布） |
| `assets/videos/` | 页面引用的视频（H.264 / 720p），`encode_manifest.json` 记录每个视频由哪个源文件、什么参数压成 |
| `assets/images/` | 页面引用的图片（从 NAS 原样复制） |
| `tools/build_site.py` | 生成脚本入口（命令行） |
| `tools/webgen/` | 生成脚本的各模块，见下表 |
| `docs/` | 本仓库的开发文档（重构方案等） |
| `build_tmp/` | 视频压缩的中间文件，不进仓库 |

## 代码结构

入口 `tools/build_site.py` 只做四件事：解析参数 → 收集结果 → 生成页面 → 按模式写出。具体工作分在 `tools/webgen/`：

| 模块 | 做什么 |
|---|---|
| `config.py` | 路径（本仓库、NAS 结果根目录、讲稿目录、assets）、体积上限、站点标题、周清单 `WEEKS` |
| `common.py` | 通用小工具：HTML 转义、读 json、按 key 链取值、数字格式化 |
| `catalog.py` | 页面上放哪些 demo、官方测试、用户录屏、hydro 测试、标签视频（纯数据清单） |
| `collect.py` | 读 NAS 结果文件，整理成统一的记录（状态、原因、视频源文件） |
| `media.py` | 决定哪些视频要压缩、哪些图片要复制，调用 ffmpeg |
| `html_parts.py` | 整页模板（CSS、MathJax）、表格、视频卡片 |
| `draft_md.py` | 讲稿 Markdown → HTML 的转换器 |
| `drafts.py` | 整页讲稿 → 页面各节（`page_from_draft`） |
| `week1_box.py` | week1 盒子实验的结果收集：选结果集、各档记录、每档视频 / 硬跑视频 / 初始穿插图（讲稿引用的视频图片由它找到源文件） |
| `week2_hydro.py` | week2 里由代码生成的块：hydro 参数扫描表、hydro 官方测试卡片、E0 图、标签视频、实验示意图 |
| `pages.py` | 组装首页与每周页面 |

依赖只从上往下：`config / common` → `catalog` → `collect / media` → `week1_box / html_parts / draft_md` → `drafts / week2_hydro` → `pages` → `build_site.py`。

## 如何生成

必须用 Neural-IPC 的 genesis 环境（它带有 imageio-ffmpeg、numpy、markdown）：

```
# 1. 演练：打印每项结果的状态、将写哪些文件、压哪些视频，不写任何东西
/data/xiaoyingwang/projects/Neural-IPC-sandbox/.conda/genesis/bin/python /data/xiaoyingwang/projects/Neural-IPC-web/tools/build_site.py

# 2. 正式生成：压缩视频、复制图片、写三个 html
/data/xiaoyingwang/projects/Neural-IPC-sandbox/.conda/genesis/bin/python /data/xiaoyingwang/projects/Neural-IPC-web/tools/build_site.py --execute

# 3. 回归：只把三个 html 写到指定目录（不压视频、不复制图片、不写仓库），改代码前后各跑一次再逐字节比较
/data/xiaoyingwang/projects/Neural-IPC-sandbox/.conda/genesis/bin/python /data/xiaoyingwang/projects/Neural-IPC-web/tools/build_site.py --html-only --out-dir /nas/xiaoyingwang/Neural-IPC/outputs/web_refactor/after
cmp /nas/xiaoyingwang/Neural-IPC/outputs/web_refactor/before/week2.html /nas/xiaoyingwang/Neural-IPC/outputs/web_refactor/after/week2.html
```

可选参数：`--crf N`（默认 26，越大视频越小）、`--force-videos`（全部重压）、`--variant stiffball|officialball`（week1 盒子实验用哪套结果）。讲稿 `web_week1.md` / `web_week2.md` 缺失时停止，不生成旧内容。
单个视频超过 10 MB 或页面引用的视频合计超过 60 MB 时停止，页面不更新。

数据来源（只读）：

- 讲稿：`/data/xiaoyingwang/projects/Neural-IPC-sandbox/docs/drafts/web_<周>.md`
- demo 与官方测试：`/nas/xiaoyingwang/Neural-IPC/outputs/ipc_demos/<目录>/`
- 参数扫描：`/nas/xiaoyingwang/Neural-IPC/outputs/ipc_sweep/<结果集>/<扫描>/<档位>.json`，档位清单在 Neural-IPC-sandbox 的 `tools/ipc_sweep/configs.py`

## 如何发布

生成后在本仓库 commit，然后推到两个 remote，两边的 GitHub Pages 都会自动更新：

```
git -C /data/xiaoyingwang/projects/Neural-IPC-web push origin main   # https://github.com/delluluwxy/Neural-IPC-web
git -C /data/xiaoyingwang/projects/Neural-IPC-web push yumeng main   # https://github.com/YumengHe/NeuralIPC-web
```

## 讲稿标记

每周讲稿是一个 Markdown 文件。生成器认识的全部写法如下。

**页面结构**

```
## A. 网页稿            （可选）有它时只取 A 部分，到「## B.」为止
## INTRO               页首导语
**本页结论：……**        INTRO 里整行加粗、以「本页结论」开头 → 醒目色总结句
## SECTION w1: 标题     一节；锚点 w1，标题进页面的二级标题，节号自动编排
### 小标题              节内小标题，自动编号 1.1、1.2 ……
TAKEAWAY: ……           醒目色总结句
**结论：……**            整行加粗、以「结论」开头 → 醒目色总结句
---                    分隔线，生成时删掉
```

**正文**

| 写法 | 效果 |
|---|---|
| `**粗体**`、`` `代码` `` | 粗体、等宽字 |
| `- 条目`、`1. 条目` | 列表；缩进 2 / 3 / 4 格都认，按缩进分层 |
| `$E=mc^2$` 或 `` $`E=mc^2`$ `` | 行内公式（MathJax） |
| `$$F=\pi H\delta^2$$`，或 `$$` 单独成行包住多行 | 块级公式 |
| pipe 表格（`\| a \| b \|` + `\|---\|---\|`） | 表格 |
| 独占一行的 `[视频](assets/videos/x.mp4)` | 内嵌播放器 |
| 独占一行的 `![说明](assets/images/x.png)`，同一行写多张则并排 | 图片 |
| 行内 `[文字](链接)` | 普通链接（例如表格里的 `[▶](assets/videos/x.mp4)`） |
| `<details><summary>标题</summary>……</details>` | 可折叠块（可嵌套，内容照常写 Markdown） |
| `<table><tr><td>…</td></tr></table>` | Notion 导出的表格，第一行为表头 |
| `<image src="/nas/…/x.png"></image>` | NAS 上的图，生成时复制进 `assets/images/` |
| `[[名字]]` | 占位符，换成代码生成的块（week2 认 `DEMO_VIDEO`、`E0_FIG`、`HYDRO_MORE`、`HYDRO_SWEEP`、`E0_VIDEO`、`E1_VIDEO`、`SETUP_E0`–`SETUP_E5`） |

讲稿里引用的视频 / 图片文件名必须是 `assets/` 下由生成器产出的名字；页面没引用到的视频不会被压缩、也不进仓库。
