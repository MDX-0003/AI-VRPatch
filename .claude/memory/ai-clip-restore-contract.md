---
name: ai-clip-restore-contract
description: merge 前自动把 AI clip 对齐到段精确时间契约（帧数+fps），rife-ncnn-vulkan 本地补帧
metadata:
  type: project
---

2026-09-20 定稿：外部 AI 产物（常见 24fps、时长偏短）在 merge 前由 `restore.resolve_ai_clip` **自动**对齐到配对段的精确时间契约（帧数、fps 完全一致，分辨率不动）——`index_map` 退化为恒等映射，隐式重采样/末帧冻结不再发生。规则：内容短 → rife-ncnn-vulkan `-n` 插值拉伸铺满整段；帧数不少 → 纯挑选重新压码（修 fps 标签错）。产物 `<ai_stem>_aligned.mp4` 与原始 clip 同目录，契约满足且不旧于原始则复用。二进制在 `bin/`（gitignored，release zip 解压），缺二进制时告警并退回旧重采样行为（`--no-restore` 可关闭自动对齐）。

**Why**: 曾用外部超分工具，产出 570 帧 @ 60fps（且文件尾损坏只能解出 567 帧），merge 静默末帧冻结补 20 帧；"帧数+帧率都精确一致"才能让贴回与原时间轴严格同步。
**How to apply**: 动 `restore.py`/`rife.py` 时保持"计数契约是硬校验"（restore 后 ffprobe/cv2 复检）；exe 输出 PNG 是 1 起始命名且要求输出目录已存在（见 [[extract-version-pairing]] 的配对守卫，merge 在 restore 之前执行）。
