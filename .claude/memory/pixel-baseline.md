---
name: pixel-baseline
description: merge 编码参数与几何都是像素基线的一部分；回归 maxdiff≠0 时的判定顺序
metadata:
  type: project
---

merge 的像素基线 = libx264 crf18 preset medium + bgr24 rawvideo 管道 + 两遍音频 remux（`media.FfmpegSink`），几何 = SegmentMaps 预计算映射路径。2026-09-18 实测：与参考管线逐帧 maxdiff=0（590 帧 8K）。

**Why**: 编码参数位流级影响输出——"顺手优化 crf/preset/编码器"会破坏门槛 2 而不自知；不同 ffmpeg 构建之间比对会出现 mean≈0.9 / max≈64 的纯编码噪声，容易误判为几何回归。
**How to apply**: 判定顺序——① 跑 `tests/test_stitch_identity`（与编码无关，定位几何）；② 几何绿则差异来自编码，需同 ffmpeg 构建重立基线；③ 任何编码/几何改动都在 `docs/knowledge/verification.md` 更新结论与日期。见 [[project-overview]]。
