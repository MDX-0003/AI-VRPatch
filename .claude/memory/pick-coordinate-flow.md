---
name: pick-coordinate-flow
description: web 选区两级坐标缩放链路；改预览分辨率或交互时必查
metadata:
  type: project
---

pick 的坐标链路有两级缩放：JS 以 CSS 显示尺寸归一化 → 乘 img.naturalWidth 得**预览像素**（ERP 预览 1024 宽；视口预览 ≤960 宽，scale=min(960/vp.width,1)）→ 服务端 `pick_inner` 再除以 scale 还原成**视口全尺寸像素**写 case.toml。ERP 点击直接用 [0,1) 归一化换算 yaw/pitch：λ=(fx−0.5)·360°，φ=(0.5−fy)·180°。

**Why**: 预览分辨率与视口全尺寸解耦（8K 源不等全量渲染），两级换算任何一级漏掉都会让内圈整体偏移/缩放错。
**How to apply**: 改 `render.py` 的 ERP_PREVIEW_W / VIEWPORT_PREVIEW_W 或模板显示宽度时，必须同步核对 `app.pick_inner` 的 scale 还原与 `app.js` 的 naturalWidth 归一化。
