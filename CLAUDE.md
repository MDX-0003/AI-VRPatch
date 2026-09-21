# vrpatch — 开发契约

360° ERP 视频的「视口选区 + AI 重绘贴回」工具。分发对象是外部协作者，**仓库自包含**：不引用任何本机之外的数据或项目；大素材走 `cases/*/source|derived/`（gitignored），随项目另行同步。

## 环境

- 一切经 uv：`uv sync --extra dev`（web 选区加 `--extra web`）。src layout + editable 安装，改 `src/vrpatch/` 立即生效，无需重装。
- Python 3.11（`.python-version`）；ffmpeg 必须在 PATH（merge 编码依赖）。

## 文件布局

```
src/vrpatch/
├── sidecar.py        clip.json 数据模型 + JSON I/O（对外契约，字段集冻结）
├── projection.py     ERP↔rectilinear 投影（数学契约见 docs/knowledge/projection-contract.md）
├── blend.py          内圈多频带（Laplacian 金字塔）融合 + 内圈掩膜
├── extract.py        视口抽帧、clip 读写、掩膜图生成
├── composite.py      SegmentMaps（每段几何一次）+ composite_frame（贴回一帧）
├── framealign.py     时间重采样唯一规则 index_map()
├── restore.py        AI clip 时间对齐（拉伸/挑选规则唯一权威）；merge 自动触发
├── scalefit.py       AI 产物全局缩放/平移的检测与修正（inner 外环带拟合 + 内圈验证；
│                     环外可靠性是经验行为非契约——掩膜/inner 不提供给外部 AI，--scale-fit）
├── rife.py           rife-ncnn-vulkan 发现与调用（外部预编译 exe，Vulkan，bin/ 内）
├── media.py          ffmpeg 惰性发现 + FfmpegSink（libx264 编码，基线参数冻结）
├── case.py           case.toml ↔ Case ↔ clip.json；sha256 校验；单段守卫
├── detect.py         propose_inner 扩展点（自动内圈建议，默认返回居中半幅）
├── progress.py       Log / RateMeter（TTY \r 刷新 vs 重定向整行的自适应）
├── cli/{extract,merge,restore,serve,pick}.py   console scripts（typer）；serve=网页总入口，pick 是其别名
└── web/
    ├── app.py        dashboard 后端（REST API + 页面路由）
    ├── tasks.py      单任务队列：extract/merge 以 subprocess 跑 CLI，日志落 logs/ 供前端 tail
    ├── render.py     选区预览渲染（源帧解码一次缓存 4K 副本，预览限宽 1024/960）
    └── templates/ + static/   服务端渲染 + 原生 JS（零 npm，轮询，无构建链）
tests/                pytest；reference.py = 参考实现（回归门槛 4 的对比对象）
tools/                独立脚本（视频比对、契约比对），不入包
cases/<name>/         case.toml（唯一真源） + source/（源素材，gitignored） + derived/（产物，gitignored）
docs/                 分层文档（见 docs/README.md）
.claude/memory/       项目记忆（一事实一文件）
```

## 硬性规则（违反即回归事故）

1. **单段**：sidecar `segments` 必须恰为 1，多段报错（`case.load_sidecar_single_segment`），禁止静默取 `segments[0]`。
2. **`clip.json` 是对外契约**：字段集与 `version` 语义不得变动；它是派生物，从 case.toml 再生，不手改。
3. **时间重采样只有一处**：`framealign.index_map`。禁止在任何地方重写 `round(i*src/dst)` 规则。restore 的补帧拉伸是唯一例外（内容短于段时的插值铺满），其规则只记录在 `restore.py` docstring；挑选/修 fps 仍必须走 `index_map`。
4. **不允许模块级可变缓存**；每段几何由调用方持有（`SegmentMaps` 建一次用整段）。
5. **投影/合成几何不得改动**，除非 `tests/test_stitch_identity`（新实现 vs `tests/reference.py`）保持 `maxdiff==0`，且 `docs/knowledge/verification.md` 的像素回归重跑通过。
6. **编码参数（libx264 crf/preset、bgr24 rawvideo、两遍音频 mux）是基线的一部分**：改动即破坏门槛 2，必须重立基线并记录。
7. 派生产物（`cases/*/derived/`、`logs/`、`sources/`、`*.mp4`、`debug_*.png`）不入 git；`case.toml` 必须记录源文件 sha256，且加载时校验。
8. **web 与 CLI 共享同一条执行路径**：网页后台任务以 subprocess 调 `python -m vrpatch.cli.*`，不复制流水线逻辑；`case.toml` 是唯一真源，web 只写它 + 触发 CLI。
9. **选区=草稿，Extract=定版**：每次 extract 写入不可变的 `extracts/<时间戳>/`；AI 结果按版本注册（该目录内 `ai_clip.json` 标记）——目录归属即配对，无指纹机制。merge 几何（视口/帧范围/fps）只读所选版本的 clip.json；融合框 inner 是唯一例外：网页 merge 实时取当前草稿 inner（`--inner` 传入），且以「草稿视口==版本视口」为守卫（`case.viewports_match`），不一致拒绝。

## 代码规范

- 模块 docstring 说明"为什么"（性能约束、契约理由），不是"是什么"；关键公式/坐标约定写在唯一权威处（投影契约在 `projection.py` docstring + docs/knowledge），他处引用不复制。
- 公共函数带简短 docstring；行内注释只写代码本身表达不了的约束。
- CLI 用 typer；新子命令挂到对应 `cli/*.py`，帮助文本说清参数物理含义（deg/px/帧号）。
- 视频处理一律流式（逐帧 read→composite→encode），禁止整片驻留内存。
- 新功能必须带 pytest；涉及几何的，先跑 `uv run pytest tests/test_stitch_identity.py`。

## 提交规范

- 频率：每个可独立验证的变更单元一提交（新功能、修复、文档、回归记录分开）。
- 信息：`<area>: <what> (<why/evidence>)`，英文小写开头，例：
  - `merge: cap preview width to 960 (pick only needs region position)`
  - `tests: add single-segment guard cases (contract R5)`
  - `docs: record pixel regression verdict (gate 2 maxdiff=0)`
- 提交前：`uv run pytest` 全绿；动了 merge/extract 则附对应验证结论于提交信息。
- 不提交：`derived/`、`source/` 之外的生成物；不确定时看 `.gitignore`。
