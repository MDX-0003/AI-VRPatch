> 层: knowledge    时效: 随代码演进更新（最后核对 2026-09-20）

# 架构与核心链路

三段式工作流：**选区（pick）→ 抽取（extract）→ 对齐（restore，自动）→ 合并（merge）**。`case.toml` 是唯一真源；
`clip.json` 是对外契约（派生物，字段集冻结）。

```
                       vrpatch-pick（web）
 case.toml  <──────────── 写回 viewport/inner ──────────────┐
    │                                                        │
    │ case.py（sha256 校验）                                  │
    ▼                                                        │
clip.json（派生契约）+ clip.mp4 ──→ 外部 AI 工具重绘 ──→ ai_clip.mp4（任意 fps/帧数）
    ▲   clip.mp4（viewport+margin 画面）                     │   （clip_mask.png 不进入 AI：
    │                                                       │     它是本工具 merge 融合的记录）
vrpatch-extract ────────────────────────────────────────────┘（人只参与 AI 一段）

ai_clip.mp4 ──restore（merge 自动触发；rife 补帧拉伸）──> ai_clip_aligned.mp4（精确 N 帧 @ 段 fps）
ERP video ──vrpatch-merge──> 贴回后的 360 视频
                 （流式：逐帧 read → composite → encode）
```

## merge 底层链路（`cli/merge.py`）

1. **sidecar 解析**：`case.load_sidecar_single_segment` 解析并强制单段（R5 守卫）；`--inner` 可覆盖内圈。网页 merge 恒传当前草稿 inner 作为 `--inner`（融合框是活的创作参数，挪框不必重跑 extract），前置守卫「草稿视口==版本视口」（`case.viewports_match`，yaw 循环比较、半步摇杆容差），不一致拒绝；不传时仍用版本记录值。
2. **源视频探测**：分辨率/帧数与 sidecar 不符时告警并以源为准；`--max-frames` 只缩短写入帧数（预览），不改变 AI 对齐帧数 `n_seg`。
3. **几何预计算**：`composite.SegmentMaps` 每段构建一次——视口采样图（`build_view_map`）、footprint bbox 内的逆投影贴回图（`build_paste_map`）、羽化内圈掩膜。8K 下这一步 ~0.2s，换来每帧不再重建 (H,W,3) 射线网格。
4. **AI clip 对齐**：先经 `restore.resolve_ai_clip`（见下节）拿到满足精确时间契约的 clip，`AiFrameSource` 再顺序解码，`framealign.index_map` 产出目标→源帧号映射（单调，源帧至多解码一次，只 resize 用到的帧）；契约已被 restore 满足时 index_map 是恒等映射，尾帧重复只作为缺失二进制时的降级路径。`--scale-fit` 开启时（网页强制 auto），`scalefit.resolve` 先在 inner 之外的环带拟合 AI 相对源片段的全局缩放/平移修正（缓存于 AI 产物旁 `<名称>.scalefit.json`，AI 文件变更即失效），`AiFrameSource` 在每帧 resize 后按该矩阵 warp；环相关性低于阈值则拒绝施加并告警。
5. **编码**：`media.FfmpegSink`，rawvideo bgr24 stdin → libx264 crf/preset → yuv420p；有音轨则两遍（video-only 编码后 `-c copy` remux，防止 muxer 改变帧数）。参数是像素基线的一部分（门槛 2）。
6. **逐帧合成**（`SegmentMaps.composite_frame`）：
   `remap_viewport`（ERP→视口，BORDER_WRAP）→ `blend.multiband_blend`（AI 内圈 + 原外圈，Laplacian 5 层 + feather 16px 高斯羽化掩膜）→ 逆投影 remap 到 footprint bbox → **只写 `cover` 掩膜内像素**。footprint 外逐像素不变是本工具的核心保证。

## restore 底层链路（`restore.py` + `rife.py`，merge 自动触发）

目标契约：与配对 extract 的段**帧数、fps 完全一致**（`sidecar_target`），分辨率不动（merge 负责缩放）。时间规则（`restore.py` docstring 是唯一权威）：内容短于段 → **插值拉伸**（rife-ncnn-vulkan `-n` 精确目标帧数，端点保持铺满整段）；帧数不少 → `framealign.index_map` 纯挑选（fps 标签错时重新压码修正）。产物 `<ai_stem>_aligned.mp4` 与原始 clip 同目录；`aligned_is_current`（契约满足 + 不旧于原始）命中即复用。rife 二进制（Vulkan、免 Python 依赖）发现顺序：`$VRPATCH_RIFE` → `bin/rife-ncnn-vulkan*/` → `PATH`；缺二进制且需要拉伸时 merge 大声告警并退回旧重采样行为。1080p 590 帧的实测 ~72s（RTX 5080）。

## extract 底层链路（`cli/extract.py`）

case 模式：`case.load_case`（sha256 校验失败即拒）→ `VideoCapture` seek 到 `frames.start` → 逐帧 `erp_to_rect` 投影 → `write_clip`（mp4v）→ `make_mask_image`（内圈黑=被 AI 内容替换、外圈白=保留原画面，硬二值无羽化；掩膜仅用于本工具 merge 融合，不提供给外部 AI）→ sidecar 写盘。产物三件套：`clip.mp4` + `clip.json` + `clip_mask.png`。

## pick 底层链路（`web/`）

服务端渲染（starlette + jinja2，零 npm）。分辨率策略：源帧只解码一次、缓存 4K 工作副本；ERP 预览 1024 宽缩略图，视口预览按比例重投影 ≤960 宽——选区只需看位置，不做全量渲染。交互两条路：
- ERP `input[type=image]` 点击 → POST `fx,fy`（[0,1) 归一化）→ 服务端换算 yaw/pitch（经度 = (fx-0.5)·360°，纬度 = (0.5-fy)·180°）；
- 视口上 JS 拖拽画内圈矩形（纯 div overlay），**松手才 POST**，服务端按预览/全尺寸比例还原成视口像素坐标。
两条路都落盘回写 `case.toml`（文本级、按 TOML 节定位的键覆写），并按内容哈希换key 重渲染预览。

## case / sidecar 关系（`case.py`）

`case.toml`（人编辑，唯一真源）→ `case_to_sidecar` → `clip.json`（机器读，派生物）。加载 case 即校验源 sha256（`record_sha256` 在建 case 时写入）。对外契约的字段集以 `sidecar.py` dataclass 为准，测试 `test_case` 冻结。
