---
name: extract-version-pairing
description: Extract 版本目录=自描述单元；merge 显式选版本，无指纹机制
metadata:
  type: project
---

2026-09-20 简化定稿：`cases/<案例>/extracts/<时间戳>/` 是**自描述单元**（clip.mp4/clip.json/掩膜 + 可选 ai_clip.json 标记 {"path":...}）。选区编辑只是草稿；每次 extract 新建版本目录互不覆盖，`[extract] current` 仅记最新版号；AI 结果按版本注册（写在版本目录里的 ai_clip.json 标记，大文件按路径引用不拷贝）；**merge 时人显式选版本**，用该目录的 clip.json + 标记的 ai_clip，成品 `derived/out_<版本>.mp4`。没有指纹/配对校验——目录归属即配对。

**Why**: 上一版的全局 [ai_clip] 配对 + 几何指纹是为"只有一个隐式当前版本"设计的补丁；版本目录显式化后，选择权交给用户，指纹反而冗余。
**How to apply**: 改 merge/extract 时保持"版本目录自描述"不变；`set_ai_clip`（全局段）已废弃勿再用；前端改 JS 记得递增 `?v=N`（见 [[web-dashboard-architecture]]）。
