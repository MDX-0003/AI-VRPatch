---
name: case-toml-vs-clip-json
description: case.toml 与 clip.json 的职能分工、merge 各取哪个（inner 例外取草稿）、选入 AI 结果时的校验
metadata:
  type: project
---

**职能**：`case.toml` = 人编辑的唯一真源，几何字段是**活的草稿**（网页拖框就是在改它），另含 `[source]` sha256、`[extract]` current。`clip.json` = Extract 瞬间从 case.toml 生成的**定版快照 + 对外契约**（字段集冻结、带 version），存于 `extracts/<时间戳>/`，永不再变。erp 尺寸/fps/帧范围/视口/内圈五组字段有意重叠：生成瞬间相等，之后允许分叉，分叉本身就是"草稿≠已导出版本"的信号。

**合成时各取哪个**：视口/帧范围/fps 只读**配对版本的 clip.json**（`extracts/<时间戳>/clip.json`，不是 derived/、绝不是 case.toml 草稿）。**inner 是唯一例外**（2026-09-21 定稿）：融合框是活的创作参数——网页 merge 把当前草稿 inner 以 `--inner` 传给 CLI（CLI 不传时仍用版本值）；因 inner 是视口像素坐标，传之前守卫「草稿视口==版本视口」（`case.viewports_match`，容差=半步摇杆 0.05°，yaw 按 ±180 回绕比较，宽高须相等），不一致 409 提示"请重置视口"。版本 clip.json 里的 inner 仍冻结——它是 merge 混合区域的版本记录（掩膜不提供给 AI 工具，见 [[inner-is-merge-only]]），也是 reset-draft 的恢复源。

**选入 AI 结果（`api_ai_clip`）时检查**：`body.path` 存在且是文件；目标版本目录有 clip.json；把路径写进该版本目录的 `ai_clip.json` 标记（`{"path": ...}`）完成配对——不读不校验 mp4 内容（像素与几何无推导关系，只能靠注册时刻显式绑定）。

**Merge 前检查（`api_merge`）**：版本目录有 clip.json 且已注册 ai_clip 标记；草稿视口与版本视口一致（见上）。无指纹机制（2026-09-20 简化定稿：目录归属即配对，旧的全局 `[ai_clip]`/geometry_sha256 校验已删）。

**Why**: 这组分工是"导出后改选区零影响"的数据流保证；inner 解耦后挪融合框不再需要重跑 extract（视口没变时重抽出的 clip.mp4 逐像素相同，纯属浪费一个版本号）。
**How to apply**: 改 web 流水线或 merge sidecar 解析前先读本条；关联 [[extract-version-pairing]] [[project-overview]]。
