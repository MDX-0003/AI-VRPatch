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
4. **web 服务器的重活必须进 `asyncio.to_thread`**（img 渲染、store 构造、case info 组装）：事件循环被 8K 解码卡住时 nudge 等小请求排队，曾把摇杆 start/stop 竞态窗口从 ~15ms 放大到 ~1s（连点后 yaw/pitch 永久漂移=前端 interval 在 await 之后才装上，stop 空转；现已改为同步装拆）。预览响应从**内存字节**返回（memoize by (几何,帧)），不落共享文件——固定名 vp.png 曾被并发请求重写、下载撕裂（ERR_CONTENT_LENGTH_MISMATCH）；帧 JPEG 只写一次（唯一临时名 + replace）。
5. **预览提速三层结构（2026-09-21）**：store 构造**必须零解码**（每次 case.toml 写盘都重建 store，曾每次白解 8K 第 0 帧 ~0.5s）；解码后的 4K ERP 帧放在 store 内 **LRU**（`ERP_MEDIUM_LRU=8`，~200MB，与几何无关，视口移动后重投影 ~53ms 而非 ~1s）；前端 ◁▷ 步进 0ms debounce、滑条 150ms，预览落地后**错峰去重预取** N±1。

**Why**: 这几条都是踩坑后的收敛：缓存膨胀、投影权威唯一性、轮询churn、事件循环阻塞与共享文件并发写、组合操作下的预览延迟。
**How to apply**: 改 render.py/app.py 预览逻辑前读本条；给 pick 加任何新缓存先回答"何时失效、何时 GC、上界是多少"；在 web 层加任何重计算先问"会不会卡事件循环、会不会并发写同一文件"；改 store 构造别加任何解码/缩放。关联 [[pick-coordinate-flow]] [[web-dashboard-architecture]]。
