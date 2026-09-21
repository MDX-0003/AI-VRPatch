> 层: knowledge    时效: 2026-09-21 实测固化；改几何/编码参数后必须重跑并更新

# 像素回归门槛与验证记录

本项目的几何与编码正确性由两条硬门槛保证，任何触及 `composite.py` / `projection.py` / `blend.py` / `media.py` 的改动都必须重跑。

## 门槛与结论（2026-09-18，8K 案例 590 帧）

1. **合并像素一致性（门槛 2）**：`vrpatch-merge`（crf18/medium/feather16/levels5）与移植验证用的参考管线输出逐帧 **maxdiff = 0.0**（590/590 帧）。工具：`tools/compare_videos.py`。
2. **抽取契约（门槛 3）**：`vrpatch-extract case` 产出的 `clip.json` 与冻结基线语义逐字段一致（10 字段、version=1，`tools/compare_clipjson.py`）；`clip.mp4` 帧数/尺寸一致；掩膜内圈全黑、外圈全白。clip 帧内容允许编码器构建差异（原 mp4v 基线时代 maxdiff≈20；2026-09-21 起 extract 改用 libx264 crf14，x264 构建间位流差异同理存在），几何一致性由门槛 4 的单元测试保证。
3. **单元级 A/B（门槛 4）**：`tests/test_stitch_identity.py`——预计算映射路径 vs `tests/reference.py` 参考实现（逐帧全量重建），5 组几何（跨缝合线、近极点、视口超画布）全部 maxdiff==0。

## 编码基线（改动须重立）

rawvideo bgr24 stdin → `libx264 -crf 18 -preset medium -pix_fmt yuv420p -threads 0`；有音轨时两遍（video-only 后 `-c copy` remux + `+faststart`）。extract 的视口 clip（交给 AI 的输入）自 2026-09-21 起同为 libx264（crf 14/medium，原 mp4v 默认质量实测低 ~1.8dB，作为 AI 链路第一有损代过软，见下节）。

与不同 ffmpeg **构建**比对合成产物会出现 mean≈0.9、max≈64 的编码噪声——这是编码器位流差异，不是几何错误；判定方法：先跑第 3 条单元 A/B（与编码无关），再决定是否需要同构建重立基线。

## 贴回插值与 extract 编码的画质决策（2026-09-21，用户 directive：可管理位置取最高质量）

1. **贴回下采样 LINEAR→CUBIC**：合成贴回恒为缩小（Mono_dance_4k：footprint bbox 1392×784，×0.72），双线性在缩小场景丢采样。产品路径 `composite.py` 与参考路径 `projection.rect_to_erp_bbox` **同步**改为 INTER_CUBIC，门槛 4（5 组几何）重跑 maxdiff==0；真实帧实测有意像素差异 mean 0.35 / p99 3 / max 25。**旧冻结基线视频代表已退役的 LINEAR 路径，门槛 2 在下次完整 merge 后必须重立新基线**（此改动触及无 AI 的环带路径，与 scale-fit 的"内容校正不入基线"不同）。
2. **extract clip 编码 mp4v→libx264 crf14/medium**：AI 输入的第一有损代不再是最软一环（实测视口内容 mp4v 37.2dB vs crf14 38.9dB）。门槛 3 语义（clip.json/帧数/掩膜）不受影响；extract 需要 ffmpeg 二进制（与 merge 同一前提）。

## scale-fit 与基线的关系（2026-09-21）

`merge --scale-fit off`（默认）下 AI 帧路径不加任何 warp，与上述基线逐字节同路径，门槛 2/3/4 不受影响。`auto`/指定 json 时 AI 帧在校正矩阵下 warp——**输出像素按设计改变**，属内容校正而非几何/编码改动，不入冻结基线；其正确性由 `tests/test_scalefit.py`（注入已知变换的恢复精度、恒等检测、缓存失效、参考几何守卫）与实测记录保证（Mono_dance_4k：sx=1.0129/sy=1.0234、t≈+4px，环 NCC 0.976，内圈静态块中位残差 1.0px）。

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
