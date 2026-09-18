# vrpatch

把 360° 全景视频里的一个人物**用 AI 重新生成**，再贴回全景，且保证画面其余部分一像素都不变。

## 它解决什么问题

全景视频里的人物想换动作/换形象，直接对整段全景跑 AI 是不现实的（画面太大、成本太高，AI 还会顺手改掉背景）。vrpatch 的做法是：

1. 在全景里框出人物所在的**一小块区域**，抠出来交给 AI；
2. AI 只重绘这一小块；
3. 把重绘结果**贴回原位**——块外逐像素不动，块边缘做融合，看不出接缝。

全程三步，对应三个命令：

```
① vrpatch-extract        ② 你自己拿去跑 AI           ③ vrpatch-merge
   抠出小块画面+蒙版   →    （VACE / Viggle / …）    →    贴回全景，输出成品
        ↑
   （选区域用 vrpatch-pick，网页上点点就行）
```

中间第 ② 步必须由人完成（AI 工具是外部的），所以是三个命令而不是一个。

## 快速上手（用自带案例）

前提：装好 [uv](https://docs.astral.sh/uv/)、Python 3.11、ffmpeg（在 PATH 上）。

```bash
uv sync --extra dev                 # 安装依赖
uv run pytest                       # 自检，应显示 14 passed

# ① 从案例的全景视频里抠出人物区域（源视频已含在案例目录）
uv run vrpatch-extract case cases/canal_dance/case.toml

# ② 把 cases/canal_dance/derived/ 里的 clip.mp4 + clip_mask.png 交给你的 AI 工具重绘，
#    得到 ai_clip.mp4（本仓库不管这一步）

# ③ 贴回（此处直接用 clip.mp4 演示"AI 未改动"的情形，产出的全景应与原片一致）
uv run vrpatch-merge --input cases/canal_dance/source/Mono_dance_4k.mp4 \
    --ai cases/canal_dance/derived/clip.mp4 \
    --sidecar cases/canal_dance/derived/clip.json \
    --output cases/canal_dance/derived/out.mp4
```

## 选区域：vrpatch-pick

```bash
uv sync --extra web
uv run vrpatch-pick cases/canal_dance/case.toml     # 浏览器打开 http://127.0.0.1:8760
```

网页左边是整幅全景，**点哪里，观察中心就在哪里**；右边是抠出来的画面，**按住鼠标拖一个框**圈住人物，松手即保存。结果写进 `case.toml`，下次 extract 自动使用。

## case.toml：一个任务的全部配置

每个任务一个文件夹（如 `cases/canal_dance/`），里面的 `case.toml` 记录：

| 段 | 含义 |
| --- | --- |
| `[source]` | 用哪个源视频（路径 + sha256，文件被换过会直接报错） |
| `[frames]` | 处理哪一段帧（start/end） |
| `[viewport]` | 在全景的什么位置开"观察窗口"（方向 yaw/pitch、视野角 fov、窗口像素宽高） |
| `[inner]` | 窗口内哪一块是要 AI 重绘的人物区（x/y/宽高，其余部分贴回时保持原样） |

它是唯一需要人工维护的配置；`derived/clip.json` 由它自动生成，供命令行传参用，**不要手改**。

## 常用场景

- **换素材**：新建 `cases/<名字>/`，放好 `case.toml`（照抄案例改数字）和 `source/`，跑一遍 pick 调区域。
- **只想微调位置**：改 `case.toml` 里的 `[viewport]`/`[inner]` 数字，或用 pick 拖一下，重跑 extract。
- **改了 merge 相关代码**：跑 `uv run pytest`（秒级）；再动了编码/几何，按 `docs/knowledge/verification.md` 重跑像素回归。

## 更多文档

- [docs/knowledge/architecture.md](docs/knowledge/architecture.md) — 三条命令各自的内部流程
- [docs/knowledge/projection-contract.md](docs/knowledge/projection-contract.md) — 全景↔窗口投影的数学约定
- [docs/knowledge/verification.md](docs/knowledge/verification.md) — 成品与基准逐像素比对的方法与记录
- [CLAUDE.md](CLAUDE.md) — 开发规范（布局、硬性规则、提交约定）
