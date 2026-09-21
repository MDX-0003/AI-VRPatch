---
name: ai-output-scale-fit
description: AI 产物全局缩放/平移的检测与修正（scalefit.py）设计、默认值决定、以及 OpenCC ECC 方向约定坑
metadata:
  type: project
---

（2026-09-21 实现并验收通过）外部 AI 工具的输出常带**各向异性的全局缩放+平移**（内部工作分辨率重采样所致；Mono_dance_4k 实测 AI 画面缩小 x1.3%/y2.4% + 平移 ~16px@中心，全片恒定、旋转≈0），不修正会在融合缝产生错位。`scalefit.py`：inner 外环带掩膜 ECC（粗到细两级）逐帧拟合 → 中位数聚合成一个全局 2x3 修正 → `AiFrameSource` 每帧 resize 后 warpAffine；inner 内静态块残差作第二置信指标；缓存 `<AI名>.scalefit.json`（AI 文件 mtime/size 失效即重拟）。验收合并日志实测 sx=1.01295/sy=1.02339、环 NCC 0.976、内圈中位残差 1.00px，接缝错位消除。

**决定**：网页 merge **强制** `--scale-fit auto`；CLI 默认 off（恪守像素基线，off/auto 都不改编码路径）。环 NCC < 0.90 拒绝施加回退 identity（环外可靠性是经验行为非契约，见 [[inner-is-merge-only]]）。identity 阈值 |s−1|≤0.002、|t|≤0.5px。旋转不修但报告，|rot|>0.5° 属意外模型漂移要告警。

**踩过的坑**：拟合参考必须是**版本 clip.mp4**（AI 工具的实际输入，与 sidecar 同目录），绝不能传 ERP 源——等距柱状全景与透视图几何完全不同，尺寸也不一致；merge 接线曾传错导致 IndexError 崩掉整个 merge（子进程死了、日志冻结在 restore 行，traceback 只在 web 任务日志里）。修后 fit_videos 对"参考缺失/几何不符"降级为 no_reference/bad_reference_geometry（告警回退 identity，不炸 merge）。方向约定：`cv2.findTransformECC` 返回 **template→input** 映射——修正矩阵必须取逆、再按普通前向 warpAffine 施加（不要 WARP_INVERSE_MAP）；`estimateAffinePartial2D(from,to)` 返回 from→to 前向映射，与 ECC 相反；方向错时缩放恰互为倒数、极易误判缩放方向，校准靠注入已知变换看恢复值（tests/test_scalefit.py 的合成自测即此用途）。ECC 在纯点阵/无纹理图上不收敛，合成校准要用带纹理图像；另 VideoWriter 喂错尺寸的帧会静默丢弃写入，产物是空视频。

**Why**: 环外背景"未被改"只是工具的通常行为，AI 换工具/换参数后可能不成立——所以设计成带门控的自动拟合而不是无条件信任；内圈重绘内容还有生成性布局漂移（中位 1px、均值 ~4px 的尾巴），全局变换修不了也不该修，残差只记录不门控。
**How to apply**: 改 scalefit/融合逻辑前先跑 `tests/test_scalefit.py`；换 AI 工具后看 merge 日志的 scale fit 行与 `out_<版本>.merge.json` 的 scale_fit 块；关联 [[inner-is-merge-only]] [[case-toml-vs-clip-json]]。
