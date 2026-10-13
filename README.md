# Neural-IPC-web

Neural-IPC 项目的组会网页：每周一页，内容是文献讲解、原代码说明、仿真 demo 视频、实验方案与结果。

在线地址（GitHub Pages）：https://delluluwxy.github.io/Neural-IPC-web/

| 页面 | 内容 |
|---|---|
| `index.html` | 首页，链接到各周 |
| `week1.html` | 第 1 周：IPC / Genesis 官方 demo 与参数扫描 |
| `week2.html` | 第 2 周：hydroelastic 与 Hertz、神经网络接触模型、原代码碰撞能量、Genesis hydro demo、与 hydro 对比的实验方案（E0–E5） |

## 仓库内容

| 路径 | 用途 |
|---|---|
| `tools/build_site.py` | 生成脚本：读讲稿与 NAS 上的结果，写三个 html，压缩视频到 `assets/videos/`，复制图片到 `assets/images/` |
| `assets/videos/`、`assets/images/` | 页面引用的视频（H.264 / 720p）和图片 |

页面全部由脚本生成，不要手改 html。week2 的文字来自 Neural-IPC-sandbox 仓库的 `docs/drafts/web_week2.md`。

## 重新生成

```
# 演练：只打印将写哪些文件、压哪些视频，不写任何东西
/data/xiaoyingwang/projects/Neural-IPC-sandbox/.conda/genesis/bin/python /data/xiaoyingwang/projects/Neural-IPC-web/tools/build_site.py

# 真正生成
/data/xiaoyingwang/projects/Neural-IPC-sandbox/.conda/genesis/bin/python /data/xiaoyingwang/projects/Neural-IPC-web/tools/build_site.py --execute
```

可选参数：`--crf N`（默认 26，越大视频越小）、`--force-videos`（全部重压）。单个视频超过 10 MB 或合计超过 60 MB 时停止，页面不更新。

## 发布

生成后 commit 并 push，GitHub Pages 自动更新。
