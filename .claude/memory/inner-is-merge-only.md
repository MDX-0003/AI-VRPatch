---
name: inner-is-merge-only
description: inner/clip_mask.png 从未提供给外部 AI 工具——inner 只在 merge 阶段决定混合区域；环外像素的可靠性是经验行为而非契约
metadata:
  type: project
---

（2026-09-21 用户纠正）**inner/clip_mask.png 不提供给外部 AIGC 工具**：AI 只拿到 clip.mp4 整帧。inner 唯一的职责是在 merge 阶段决定「哪里取 AI 像素、哪里保留原画面」的过渡混合。extract 生成的 clip_mask.png（黑=内圈、白=锚定环）是本工具自己 merge 用的记录与输入，**不是给 AI 的指令**。

**推论**：

1. 没有任何契约保证 AI 输出的任何区域（内圈或环外）一定与原画面对齐——工具对背景的高保真是经验行为（背景被条件复现、人物被重绘），不是被指示的。
2. 用 inner 取反（环外）检测 AI 管线缩放/平移的理由因此是「**那里最可能未变**」：环外是背景静态区，匹配可信度最高；内圈是被重绘的人物区，匹配会被换姿势/重生成内容系统性污染。每次环拟合必须带置信验证（环 NCC + 内圈静态块残差），不能默认成立——`scalefit.py` 的门控即为此设。
3. 掩膜语义（黑=merge 时被 AI 内容替换、白=保留原画面）只在合成时成立；任何「把掩膜交给 AI」的文档表述都是误导（README/architecture 2026-09-21 已改）。

**Why**: 曾误以为「环内 AI 被掩膜要求锚定」，把环可信度当成契约保证，会漏掉验证环节、并在文档上错误引导用户给工具喂掩膜。
**How to apply**: 改 scalefit/merge 融合、写 AI 对接文档前先读本条；关联 [[merge-draft-inner-decoupling]] [[ai-output-scale-fit]]。
