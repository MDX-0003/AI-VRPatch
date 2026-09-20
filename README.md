# vrpatch

把 360° 全景视频里的一个人物**用 AI 重新生成**，再贴回全景，且保证画面其余部分一像素都不变。

## 它解决什么问题

全景视频里的人物想换动作/换形象，直接对整段全景跑 AI 是不现实的（画面太大、成本太高，AI 还会顺手改掉背景）。vrpatch 的做法是：

1. 在全景里框出人物所在的**一小块区域**，抠出来交给 AI；
2. AI 只重绘这一小块；
3. 把重绘结果**贴回原位**——块外逐像素不动，块边缘做融合，看不出接缝。

```
① Extract            ② 你自己拿去跑 AI            ③ Merge
   抠出小块画面+蒙版 →    （VACE / Viggle / …）   →    贴回全景，输出成品
        ↑                                         
   （选区域用网页上的选区面板，点点拖拖就行）
                     ↘ Merge 前自动补帧对齐（Restore）：
                       AI 产物帧率/帧数与原段不一致时，
                       本地 rife 自动插值到精确一致
```

中间第 ② 步必须由人完成（AI 工具是外部的），所以流水线断成两段。

**AI 产物帧率不一致？Merge 会自动对齐（Restore）**：外部 AI 工具常输出 24fps，甚至比原段少一小截。Merge 前会自动把 AI 产物补帧/拉伸到与原段**帧数、帧率完全一致**（`<AI文件名>_aligned.mp4`，放在 AI 产物旁边，已对齐则直接复用），不再出现"结尾定格 1/3 秒"这类隐式补齐。这需要本机有 [rife-ncnn-vulkan](https://github.com/nihui/rife-ncnn-vulkan)（免 Python 依赖的预编译 exe，Vulkan 直驱任意显卡）：下载 release zip 解压到项目根 `bin/` 即可（1080p 590 帧约 1 分钟，RTX 5080 实测 72s）。没装也能跑 merge——会告警并退回旧的"重采样+末帧补齐"行为。也可单独执行：`vrpatch-restore --ai <AI结果> --sidecar <clip.json>`。

**选区是草稿，Extract 生成版本**：网页上拖框、点选随时可改、可反悔，只影响预览；每次点 Extract 生成一个独立版本目录 `cases/<案例>/extracts/<时间戳>/`（clip.mp4 / clip.json / 掩膜），互不覆盖。每个版本可独立"选入 AI 结果"（在该目录记录 ai_clip 路径标记）；**Merge 时选一个版本**，就用那一版的 clip.json 和 AI 结果合并，成品为 `derived/out_<版本>.mp4`——导出后再怎么改选区、或选择合并旧版本，都由你显式决定，不存在隐式错位。

## 快速上手

前提：装好 [uv](https://docs.astral.sh/uv/)、Python 3.11、ffmpeg（在 PATH 上）。

```bash
uv sync --extra web,dev         # 安装依赖（纯命令行使用可去掉 web）
uv run pytest                   # 自检，应全部通过
uv run vrpatch-serve            # 启动控制台，浏览器打开 http://127.0.0.1:8760
```

**推荐：全程在网页（vrpatch 控制台）上操作。** 把源视频放进项目根的 `sources/` 目录，然后：

1. **新建案例**：左侧素材库下拉框选视频，一键生成案例；
2. **选区**：全景图点一下定视口中心；视口图上拖框圈住人物，松手保存；
3. **Extract**：点按钮后台执行，页面实时显示帧进度与日志；
4. 把 `cases/<案例>/derived/` 里的 `clip.mp4 + clip_mask.png` 交给外部 AI 工具重绘；
5. **选入 AI 结果**：点按钮浏览本机目录，指认 AI 产出的 `ai_clip.mp4`（帧率/帧数不必和原段一致）；
6. **Merge**：点按钮贴回全景（需要时会先自动补帧对齐），成品在 `cases/<案例>/derived/out.mp4`。

命令行始终可用（与网页驱动同一套代码，适合脚本化）：`vrpatch-extract case <case.toml>` 抽取、
`vrpatch-merge --input <全景> --ai <AI结果> --sidecar <clip.json> --output <成品>` 合并
（`--no-restore` 可关闭自动补帧对齐）、`vrpatch-restore --ai <AI结果> --sidecar <clip.json>` 单独对齐。
每次 extract/restore/merge 运行都会同时在 `logs/` 下写一份带时间戳的日志。

每次新建案例，都会在E:\360AIGC\vrpatch\cases下新建文件夹，内容示范如下：

```
E:\360AIGC\vrpatch\
├── sources\
│   └── Mono_dance_4k.mp4        ← 源视频放这里（唯一要你手动放的东西）
├── cases\
│   └── Mono_dance_4k\           ← 新建案例生成的文件夹
│       ├── case.toml            ← 全部配置（指向 ../../sources/ 里的源视频 + sha256）
│       └── derived\             ← 这个案例的所有产物，越跑越多
│           ├── clip.mp4         ← Extract：抠出的视口画面（交给 AI 的就是它）
│           ├── clip.json        ← sidecar（对外契约，自动生成）
│           ├── clip_mask.png    ← 内圈掩膜（和 clip.mp4 一起交给 AI）
│           ├── pick\            ← 选区预览缓存（erp/vp 两张小图）
│           └── out.mp4          ← Merge：最终成品
└── logs\                        ← 注意：运行日志不进案例文件夹，统一在这（按命令+案例名+时间戳命名）
```



## case.toml：一个任务的全部配置

每个案例一个文件夹（`cases/<名字>/`），`case.toml` 记录全部配置，是唯一真源：

| 段 | 含义 |
| --- | --- |
| `[source]` | 用哪个源视频（路径 + sha256，文件被换过会直接报错） |
| `[frames]` | 处理哪一段帧（start/end） |
| `[viewport]` | 在全景的什么位置开"观察窗口"（方向 yaw/pitch、视野角 fov、窗口像素宽高） |
| `[inner]` | 窗口内哪一块是要 AI 重绘的人物区（x/y/宽高，其余部分贴回时保持原样） |
| `[ai_clip]` | （可选）外部 AI 产物路径，由网页"选入 AI 结果"写入 |

`derived/clip.json` 由它自动生成、供命令行传参，是**对外契约**（字段集冻结），不要手改。

## 常用场景

- **换素材**：丢进 `sources/`，网页上新建案例即可。
- **微调选区**：网页上重新点/拖，重跑 Extract。
- **改了 merge/几何代码**：`uv run pytest`（秒级）；动了编码或几何，按 `docs/knowledge/verification.md` 重跑像素回归。

## 杀掉已有进程

```
Get-NetTCPConnection -LocalPort 8760 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

逐步执行：找到当前占据端口的进程，输出里找 `LISTENING` 那一行，最后一列的数字就是 PID，比如：

```
netstat -ano | findstr :8760
//杀掉进程
taskkill /PID 12345 /F
```



## 更多文档

- [docs/knowledge/architecture.md](docs/knowledge/architecture.md) — 各命令与网页的内部流程
- [docs/knowledge/projection-contract.md](docs/knowledge/projection-contract.md) — 全景↔窗口投影的数学约定
- [docs/knowledge/verification.md](docs/knowledge/verification.md) — 成品与基准逐像素比对的方法与记录
- [CLAUDE.md](CLAUDE.md) — 开发规范（布局、硬性规则、提交约定）
