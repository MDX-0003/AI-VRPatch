---
name: pick-coordinate-flow
description: 网页选区的坐标契约：提交用 0..1 分数、PickCoords 单一映射、静态资源要带版本号
metadata:
  type: project
---

pick 的坐标链路（2026-09-20 收敛为分数契约）：所有选区坐标经 `static/pick.js` 的 `PickCoords` 单一映射派生（css/img/frac 三种空间）；**提交给服务端一律用 frac（0..1）**，服务端 `api_inner` 乘以视口全尺寸、`api_viewport` 直接用分数换算 yaw/pitch。显示（虚线框）用 css 空间，overlay 定位经 offsetParent 实测偏移换算。

**Why**: 曾两次坏在"提交坐标绑定某一层分辨率"上（先是 clientX 混 offsetLeft，后是提交预览像素依赖 VIEWPORT_PREVIEW_W 与 naturalWidth 恰好一致）。分数契约与预览分辨率、CSS 显示宽度完全解耦。
**How to apply**:
1. 改预览分辨率/前端样式时不要动 frac 契约；新交互一律经 PickCoords，禁止 clientX 与 offsetLeft 混算。
2. `pick.js drag()` 的 onCommit 传**完整 rect**（css+img+frac），别取单层。
3. 元素未就绪时映射返回 null（img 看 naturalWidth=0，video 看 readyState<1，2026-09-21 起双支持），调用方必须 no-op；拖拽中禁止 refreshCase 换图（`vpDrag.active` 守卫）。
4. 改 pick.js/dashboard.js 后必须递增 `dashboard.html` 里的 `?v=N`：StaticFiles 无 max-age，浏览器启发式缓存旧脚本曾让修复"看起来没生效"半小时。
关联 [[js-drag-overlay-coords]] [[project-overview]]。

