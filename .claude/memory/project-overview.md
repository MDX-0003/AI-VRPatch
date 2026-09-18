---
name: project-overview
description: vrpatch 的核心功能、目录布局与不可违反的硬性规则入口
metadata:
  type: project
---

vrpatch：360° ERP 视频的「视口选区 + AI 重绘贴回」工具，仓库自包含、可独立分发。

- 三段工作流：pick（web 选区，写回 case.toml）→ extract（视口 clip + clip.json + 掩膜）→ merge（流式贴回，footprint 外逐像素不变）。
- `case.toml` 是唯一真源；`clip.json` 是对外契约（字段集/version 冻结，派生物，不手改）。
- 布局与规范权威：`CLAUDE.md`；链路权威：`docs/knowledge/architecture.md`。
- 硬性规则：单段（多段报错）、时间重采样只在 `framealign.index_map`、禁止模块级可变缓存、几何改动必须保持 `test_stitch_identity` maxdiff==0。

**Why**: 这些规则分散在测试与文档里，违反任何一条都会破坏对外契约或像素回归。
**How to apply**: 动手前读 CLAUDE.md；碰几何/编码先跑 `uv run pytest`，见 [[pixel-baseline]]。
