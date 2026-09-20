---
name: extract-version-pairing
description: 选区=草稿、Extract=定版的版本/配对机制；merge 按配对指纹执行
metadata:
  type: project
---

2026-09-20 定稿的工作流契约：网页拖框/点选只是**草稿**（改 case.toml，仅影响预览）；每次 extract 把当时区域固化为不可变的 `cases/<案例>/extracts/<时间戳>/`（clip.mp4/clip.json/掩膜），并在 case.toml `[extract]` 记录 current + 几何指纹（clip.json sha256）；`derived/` 只是最新版镜像（兼容 CLI 老用法）。`[ai_clip]` 注册时绑定 extract 版本 + 指纹；**merge 用配对版本的 clip.json 并校验指纹**（`--expect-geometry-sha256`，不一致拒绝，`--force` 跳过）。

**Why**: 用户导出 clip 给外部 AI 后任意改选区，曾会导致 AI 旧画面被贴到新位置的静默错位；配对机制让"导出后的草稿修改"零影响。
**How to apply**: 改动 merge/extract 的 sidecar 解析时，必须保持"配对版本优先于草稿"；web 每次大改前端后静态引用 `?v=N` 要递增（见 [[web-dashboard-architecture]] [[pick-coordinate-flow]]）。
