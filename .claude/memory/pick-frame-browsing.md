---
name: pick-frame-browsing
description: 选区页逐帧走查的设计：ERP 走 <video> 原生解码、视口重投影按帧服务端渲染、derived/pick 是可再生缓存
metadata:
  type: project
---

2026-09-21 选区页支持逐帧走查（目的：检查 inner 整段框住人物；明确不做 [frames] 范围编辑）：

1. ERP 侧是原生 `<video>`（/sources Range 路由）：浏览器硬解 8K，零新增文件；红十字/绿框 overlay 是客户端分数算术（`dashboard.js` drawErpOverlays）。视口重投影**不下放浏览器**（投影唯一权威），走 `/img/vp.png?frame=N`，8K 随机 seek ~1s/帧（实测 957ms），JPEG 缓存于 `vpframes/<视口几何key>/`（上界=源帧数，实测 ~87KB/帧）。
2. 帧缓存 key 用**视口几何**（`_vp_geo_key`，不含 inner）——拖 inner 框绝不触发重投影；视口一动整目录失效并 GC。`derived/pick` 整体定位是**可再生缓存**：固定名 vp.png + 有界帧缓存，每次渲染 GC 旧命名残留与旧几何目录，任何时候可整体删除（曾因内容 key 残留三天堆 65MB——no-store 中间件 + 时间戳双防缓存后，内容 key 只剩副作用）。
3. 前端轮询有 infoSig 脏检查（`dashboard.js`）：case 信息没变就不碰 video/overlay/预览（旧版空闲时每 1.2s 盲重换图）。

**Why**: 这三条都是踩坑后的收敛：缓存膨胀、投影权威唯一性、轮询churn。
**How to apply**: 改 render.py/app.py 预览逻辑前读本条；给 pick 加任何新缓存先回答"何时失效、何时 GC、上界是多少"。关联 [[pick-coordinate-flow]] [[web-dashboard-architecture]]。
