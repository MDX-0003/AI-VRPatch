> 层: knowledge    时效: 2026-09-18 实测固化；改几何/编码参数后必须重跑并更新

# 像素回归门槛与验证记录

本项目的几何与编码正确性由两条硬门槛保证，任何触及 `composite.py` / `projection.py` / `blend.py` / `media.py` 的改动都必须重跑。

## 门槛与结论（2026-09-18，8K 案例 590 帧）

1. **合并像素一致性（门槛 2）**：`vrpatch-merge`（crf18/medium/feather16/levels5）与移植验证用的参考管线输出逐帧 **maxdiff = 0.0**（590/590 帧）。工具：`tools/compare_videos.py`。
2. **抽取契约（门槛 3）**：`vrpatch-extract case` 产出的 `clip.json` 与冻结基线语义逐字段一致（10 字段、version=1，`tools/compare_clipjson.py`）；`clip.mp4` 帧数/尺寸一致；掩膜内圈全黑、外圈全白。clip 帧内容存在 mp4v 编码器构建差异（maxdiff≈20），几何一致性由门槛 4 的单元测试保证。
3. **单元级 A/B（门槛 4）**：`tests/test_stitch_identity.py`——预计算映射路径 vs `tests/reference.py` 参考实现（逐帧全量重建），5 组几何（跨缝合线、近极点、视口超画布）全部 maxdiff==0。

## 编码基线（改动须重立）

rawvideo bgr24 stdin → `libx264 -crf 18 -preset medium -pix_fmt yuv420p -threads 0`；有音轨时两遍（video-only 后 `-c copy` remux + `+faststart`）。mp4v（OpenCV）仅用于 extract 的视口 clip。

与不同 ffmpeg **构建**比对合成产物会出现 mean≈0.9、max≈64 的编码噪声——这是编码器位流差异，不是几何错误；判定方法：先跑第 3 条单元 A/B（与编码无关），再决定是否需要同构建重立基线。

## 重跑方法

```bash
uv run pytest                                   # 门槛 4（秒级，无素材依赖）
uv run vrpatch-extract case cases/canal_dance/case.toml
uv run vrpatch-merge --input cases/canal_dance/source/Mono_dance_4k.mp4 \
  --ai cases/canal_dance/derived/clip.mp4 \
  --sidecar cases/canal_dance/derived/clip.json \
  --output cases/canal_dance/derived/out.mp4 -q --report cases/canal_dance/derived/merge_report.json
uv run python tools/compare_videos.py <new> <frozen baseline>   # 门槛 2（约 3 分钟）
```

冻结基线文件（out.mp4 的冻结副本）不随 git 分发，随项目素材另行同步；团队内以 sha256 指认版本。
