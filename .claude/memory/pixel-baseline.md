---
name: pixel-baseline
description: merge 编码参数与几何都是像素基线的一部分；回归 maxdiff≠0 时的判定顺序；2026-09-21 画质决策后基线待重立
metadata:
  type: project
---

merge 的像素基线 = libx264 crf18 preset medium + bgr24 rawvideo 管道 + 两遍音频 remux（`media.FfmpegSink`），几何 = SegmentMaps 预计算映射路径。2026-09-18 实测：与参考管线逐帧 maxdiff=0（590 帧 8K）。

2026-09-21 画质决策（用户 directive"可管理位置取最高质量"）后有两处**有意改变输出像素**：① 贴回下采样 INTER_LINEAR→CUBIC（composite.py 与 projection.rect_to_erp_bbox 锁步改，门槛 4 重跑 maxdiff=0，真实帧差异 mean 0.35/max 25）；② extract clip 编码 mp4v→libx264 crf14/medium（AI 输入第一有损代，实测 +1.8dB）。**冻结基线视频仍是退役 LINEAR 路径的产物，下次完整 merge 必须重立基线**才能用门槛 2 做回归判定。

**Why**: 编码参数位流级影响输出——"顺手优化 crf/preset/编码器"会破坏门槛 2 而不自知；不同 ffmpeg 构建之间比对会出现 mean≈0.9 / max≈64 的纯编码噪声，容易误判为几何回归。
**How to apply**: 判定顺序——① 跑 `tests/test_stitch_identity`（与编码无关，定位几何）；② 几何绿则差异来自编码，需同 ffmpeg 构建重立基线；③ 任何编码/几何改动都在 `docs/knowledge/verification.md` 更新结论与日期。合成与参考的插值策略必须锁步改（贴回=CUBIC，视口提取保持 LINEAR）。见 [[project-overview]]。
