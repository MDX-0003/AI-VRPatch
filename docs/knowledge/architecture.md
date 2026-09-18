> 层: knowledge    时效: 随代码演进更新（最后核对 2026-09-18）

# 架构与核心链路

三段式工作流：**选区（pick）→ 抽取（extract）→ 合并（merge）**。`case.toml` 是唯一真源；
`clip.json` 是对外契约（派生物，字段集冻结）。

```
                       vrpatch-pick（web）
 case.toml  <──────────── 写回 viewport/inner ──────────────┐
    │                                                        │
    │ case.py（sha256 校验）                                  │
    ▼                                                        │
clip.json（派生契约）+ clip_mask.png ──→ 外部 AI 工具重绘 ──→ ai_clip.mp4
    ▲   clip.mp4（viewport+margin 画面）                     │
    │                                                       │
vrpatch-extract ────────────────────────────────────────────┘（人只参与 AI 一段）

ERP video ──vrpatch-merge──> 贴回后的 360 视频
                 （流式：逐帧 read → composite → encode）
```

## merge 底层链路（`cli/merge.py`）

1. **sidecar 解析**：`case.load_sidecar_single_segment` 解析并强制单段（R5 守卫）；`--inner` 可覆盖内圈。
2. **源视频探测**：分辨率/帧数与 sidecar 不符时告警并以源为准；`--max-frames` 只缩短写入帧数（预览），不改变 AI 对齐帧数 `n_seg`。
3. **几何预计算**：`composite.SegmentMaps` 每段构建一次——视口采样图（`build_view_map`）、footprint bbox 内的逆投影贴回图（`build_paste_map`）、羽化内圈掩膜。8K 下这一步 ~0.2s，换来每帧不再重建 (H,W,3) 射线网格。
4. **AI clip 对齐**：`AiFrameSource` 顺序解码，`framealign.index_map` 产出目标→源帧号映射（单调，源帧至多解码一次，只 resize 用到的帧）；帧数不足时尾帧重复补齐并告警。
5. **编码**：`media.FfmpegSink`，rawvideo bgr24 stdin → libx264 crf/preset → yuv420p；有音轨则两遍（video-only 编码后 `-c copy` remux，防止 muxer 改变帧数）。参数是像素基线的一部分（门槛 2）。
6. **逐帧合成**（`SegmentMaps.composite_frame`）：
   `remap_viewport`（ERP→视口，BORDER_WRAP）→ `blend.multiband_blend`（AI 内圈 + 原外圈，Laplacian 5 层 + feather 16px 高斯羽化掩膜）→ 逆投影 remap 到 footprint bbox → **只写 `cover` 掩膜内像素**。footprint 外逐像素不变是本工具的核心保证。

## extract 底层链路（`cli/extract.py`）

case 模式：`case.load_case`（sha256 校验失败即拒）→ `VideoCapture` seek 到 `frames.start` → 逐帧 `erp_to_rect` 投影 → `write_clip`（mp4v）→ `make_mask_image`（内圈黑=重绘，外圈白=锚，硬二值无羽化）→ sidecar 写盘。产物三件套：`clip.mp4` + `clip.json` + `clip_mask.png`。

## pick 底层链路（`web/`）

服务端渲染（starlette + jinja2，零 npm）。分辨率策略：源帧只解码一次、缓存 4K 工作副本；ERP 预览 1024 宽缩略图，视口预览按比例重投影 ≤960 宽——选区只需看位置，不做全量渲染。交互两条路：
- ERP `input[type=image]` 点击 → POST `fx,fy`（[0,1) 归一化）→ 服务端换算 yaw/pitch（经度 = (fx-0.5)·360°，纬度 = (0.5-fy)·180°）；
- 视口上 JS 拖拽画内圈矩形（纯 div overlay），**松手才 POST**，服务端按预览/全尺寸比例还原成视口像素坐标。
两条路都落盘回写 `case.toml`（文本级、按 TOML 节定位的键覆写），并按内容哈希换key 重渲染预览。

## case / sidecar 关系（`case.py`）

`case.toml`（人编辑，唯一真源）→ `case_to_sidecar` → `clip.json`（机器读，派生物）。加载 case 即校验源 sha256（`record_sha256` 在建 case 时写入）。对外契约的字段集以 `sidecar.py` dataclass 为准，测试 `test_case` 冻结。
