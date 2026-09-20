---
name: case-toml-vs-clip-json
description: case.toml 与 clip.json 的职能分工、merge 各取哪个、选入 AI 结果时检查哪个文件及校验项
metadata:
  type: project
---

**职能**：`case.toml` = 人编辑的唯一真源，几何字段是**活的草稿**（网页拖框就是在改它），另含 `[source]` sha256、`[extract]` current+指纹、`[ai_clip]` 配对状态。`clip.json` = Extract 瞬间从 case.toml 生成的**定版快照 + 对外契约**（字段集冻结、带 version），存于 `extracts/<时间戳>/`，永不再变。erp 尺寸/fps/帧范围/视口/内圈五组字段有意重叠：生成瞬间相等，之后允许分叉，分叉本身就是"草稿≠已导出版本"的信号。

**合成时各取哪个**：几何（视口/内圈/帧范围/fps）只读**配对版本的 clip.json**（`extracts/<时间戳>/clip.json`，不是 derived/、绝不是 case.toml 草稿）；源视频与 AI 产物路径来自 case.toml，由网页拼进命令行。

**选入 AI 结果（`api_ai_clip`）时检查的是 case.toml 侧**：
1. `body.path` 指向的文件存在且是文件（不存在 → 400）；
2. `[extract]` 必须已有 current 版本（没有 → 400 "run extract first"）；
3. 把该版本的 `current + geometry_sha256` 写入 `[ai_clip]` 完成配对——此动作**不读不校验 clip.json**，也不校验 mp4 内容（mp4 像素与几何无推导关系，只能靠注册时刻显式绑定）。

**Merge 前检查的是 clip.json 侧**：`[ai_clip].geometry_sha256 == [extract].geometry_sha256`（不一致 → 409）；执行层再现场重算 sidecar 文件 sha256 与 `--expect-geometry-sha256` 比对（不一致拒绝，`--force` 跳过）。

**Why**: 这组分工是"导出后改选区零影响"的数据流保证；谁开始从 case.toml 读几何做合成，或在注册时乱动 clip.json 校验顺序，就破坏了定版模型。
**How to apply**: 改 web 流水线或 merge sidecar 解析前先读本条；关联 [[extract-version-pairing]] [[project-overview]]。
