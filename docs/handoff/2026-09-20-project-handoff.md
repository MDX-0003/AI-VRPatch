> 层: handoff    时效: 2026-09-20 固化（对应提交 `a3c55ae` 前后）；接手后请先读完本文件再动代码

# Handoff：vrpatch 项目交接

写给接手的 Agent / 同事：这份文档是"地图 + 当前状态"，不重复细节——细节的权威出处都在文中标注的路径里。

## 1. 一句话理解项目

vrpatch 是一个 360° ERP 全景视频的「视口选区 + AI 重绘贴回」工具：从全景中抠出一个固定矩形视口（人物区 + 边缘余量），交给外部 AI 工具重绘，再把结果贴回全景——**视口 footprint 之外逐像素不变**。仓库自包含、可独立分发（不含任何对旧开发环境的引用）。

## 2. 必读文件（按顺序）

1. `/README.md` — 面向使用者的功能说明与工作流（含"选区是草稿，Extract 生成版本"的核心模型）
2. `/CLAUDE.md` — **开发硬性规则**（9 条，违反即回归事故）+ 文件布局 + 代码/提交规范
3. `docs/knowledge/architecture.md` — 三段流水线（pick/extract/merge）各自的底层链路
4. `docs/knowledge/projection-contract.md` — ERP↔视口投影数学契约（冻结，改动须过回归）
5. `docs/knowledge/verification.md` — 像素回归门槛与已验证结论（改几何/编码参数后必读必跑）
6. `.claude/memory/` — 6 条项目记忆，每条一个主题（坐标契约、编码基线、版本目录模型等），**动手前扫一遍**

## 3. 代码地图（细节见 CLAUDE.md 的布局节）

- `src/vrpatch/` 引擎：`projection.py`（数学契约）→ `extract.py`/`composite.py`（贴回核心，`SegmentMaps` 每段几何一次）→ `blend.py`（多频带融合）→ `framealign.py`（时间重采样**唯一**规则）→ `media.py`（ffmpeg 编码，**参数是基线的一部分**）
- `src/vrpatch/case.py` — `case.toml`（唯一真源）↔ `clip.json`（对外契约，字段集冻结、派生物）+ 版本/草稿的读写器
- `src/vrpatch/cli/` — `extract`（版本化抽取，每次写 `extracts/<时间戳>/`）、`merge`（流式贴回，编码参数=基线）、`serve`（网页总入口）、`pick`（serve 的别名）
- `src/vrpatch/web/` — dashboard：`app.py`（REST API）、`tasks.py`（单任务队列，subprocess 跑 CLI）、`render.py`（预览渲染，源帧解码一次缓存 4K 副本）、`static/pick.js`（**选区坐标唯一权威**，提交用 0..1 分数）、`static/dashboard.js`
- `tests/` — pytest；`reference.py` 是回归门槛 4 的对比参考实现
- 数据约定：`sources/`（素材库，gitignored）→ `cases/<名字>/`（case.toml + `extracts/<时间戳>/` 版本目录 + `derived/` 镜像与成品）+ `logs/`（每次运行的日志）

## 4. 当前工作状态（截至本 handoff）

git 主线干净，所有功能已验证。近期演进脉络（按提交时间，均可 `git log` 查证）：

1. **像素回归已验证**：merge 与参考管线逐帧 maxdiff=0（8K×590 帧）；extract 的 clip.json 与冻结基线语义一致（`tools/compare_videos.py` / `compare_clipjson.py`）
2. **Extract 版本化**：选区编辑=草稿；每次 Extract 生成不可变版本目录；merge 时人在网页上**显式选版本**，无指纹机制（目录归属即配对）
3. **网页控制台**（`vrpatch-serve`）是主交互：建案例（从 `sources/`）→ 选区（点选+拖框+摇杆微调）→ Extract（队列后台跑，页面看进度）→ 按版本选入 AI 结果 → 按版本 Merge
4. **摇杆**：按住持续 0.1°/0.1s 偏移，服务端负责 yaw ±180 回绕、pitch ±89 夹住
5. **重置草稿按钮**：把视口/内圈恢复为**当前选中版本**的 clip.json 记录值
6. 已知兼容点：同事中途加入的 rife 补帧（Restore）环节——AI 产物帧率/帧数不符时 merge 前自动对齐（`bin/` 下放 rife-ncnn-vulkan，README 有说明），与版本模型兼容

## 5. 关键坑（都是踩过的，详见对应记忆文件）

- **前端缓存**：所有响应已加 `Cache-Control: no-store`，但改 JS 后仍要递增 `dashboard.html` 里的 `?v=N`（双保险）；JS 语法错误会让整个列表空白，改完必做页面冒烟
- **坐标**：任何选区坐标只准走 `pick.js` 的 `PickCoords`（css/img/frac 三空间），提交用 frac；禁止 clientX 与 offsetLeft 混算
- **TOML 写 Windows 路径**必须用单引号字面量（`path = 'E:\...'`）
- **`web/` 下模块取项目根**是 `Path(__file__).parents[3]`（比 `progress.py` 多一层）
- **杀 serve 进程 = 杀运行中任务**；任务历史只在内存，重启后 `/api/task` 的 last 为空属正常
- **venv 半损坏**的表现是 pytest 报 `No module named 'vrpatch'`——删 `.venv` 重新 `uv sync` 即可
- 编码参数（libx264 crf18/medium、bgr24 管道、两遍音频 mux）**是像素基线的一部分**，别"顺手优化"

## 6. 环境与命令速查

```bash
uv sync --extra web,dev          # 安装
uv run pytest                    # 46 个测试，<2s，不依赖大素材
uv run vrpatch-serve             # 控制台 http://127.0.0.1:8760
uv run vrpatch-extract case cases/<名>/case.toml
uv run vrpatch-merge --input <全景> --ai <AI结果> --sidecar <clip.json> --output <成品>
```

端口被占时：`Get-NetTCPConnection -LocalPort 8760 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }`

## 7. 未完成 / 已知边界（接手者可考虑的方向）

- 网页没有"删除旧 Extract 版本"的入口（磁盘会随次数增长，每版约 15MB）
- AI 结果与版本的配对靠用户自觉（选错文件系统无法察觉——这是显式选择模型的代价，README 已说明）
- `pick.py`（serve 别名）将来可移除
- 任务队列无"取消"功能（需要进程组管理）
- 大文件分发：`sources/`、`cases/*/extracts|derived/`、冻结基线视频不随 git 走，需按 sha256 指认版本另行同步

## 8. Suggested skills

接手 Agent 在对应场景应调用：

- **动几何/编码/合成代码前后**：读 `docs/knowledge/verification.md` 并按其重跑像素回归；可用 `spreadsheets`/`pdf` 技能整理回归报告
- **继续做网页功能**：先读 `.claude/memory/pick-coordinate-flow.md` 与 `js-drag-overlay-coords.md`；浏览器验证可用会话内的 Playwright 工具（注意 StaticFiles 改 JS 后递增 `?v=N`）
- **交接/继续对话压缩**：本文件即由 `handoff` 技能产出，后续可再次调用更新
- **文档类产出**：`docx`（对外说明书）、`pptx`（演示）按需调用
