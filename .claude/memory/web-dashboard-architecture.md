---
name: web-dashboard-architecture
description: 网页控制台的架构约束：subprocess 跑 CLI、单任务队列、sources/ 素材库、TOML 路径坑
metadata:
  type: project
---

2026-09-18 新增网页控制台（`vrpatch-serve`），架构约束：

1. **web 不复制流水线逻辑**：extract/merge 由 `web/tasks.py` 以 subprocess 调 `python -m vrpatch.cli.*`（cwd=项目根），stdout 落 logs/ 供前端轮询 tail。改 CLI 参数/输出格式时前端解析会受影响。
2. **单任务队列**：同一时刻一个任务；**杀掉 serve 进程会杀掉运行中的任务**，且 history 只在内存里——重启后 /api/task 的 last 为空，属预期而非 bug。
3. 源视频放 `sources/`（gitignored）；新案例 source 路径是 `../../sources/<file>`（相对 case.toml）。
4. 两个踩过的坑：TOML 写 Windows 路径必须用单引号字面量串（`path = 'E:\...'`），双引号串里 `\` 是转义；`web/` 下模块取项目根是 `Path(__file__).parents[3]`，比 progress.py 多一层。
5. `set_ai_clip` 剥离旧 [ai_clip] 段时必须连段头一起删，否则重复声明。

**Why**: 这些是网页层特有的、代码里一眼看不出的约束；踩过的 TOML/路径坑极易再犯。
**How to apply**: 改 web/tasks、case 写入逻辑前先读本条；见 [[project-overview]] 与 [[pick-coordinate-flow]]。
