---
name: js-drag-overlay-coords
description: web pick 拖拽虚线框曾因混用视口坐标与元素坐标而偏移；overlay 拖拽坐标铁律
metadata:
  type: feedback
---

2026-09-18 修复 pick 内圈拖拽 bug：拖拽中的虚线框用 `e.clientX - img.offsetLeft` 定位（视口坐标混元素偏移），而提交矩形用 `clientX - getBoundingClientRect().left`（正确的图片相对坐标），导致虚线框偏离鼠标、提交却正确。

**Why**: `offsetLeft/offsetTop` 只描述元素相对**定位父级**（`.wrap`）的偏移，不能把 `clientX`（相对浏览器视口）换算成图片内坐标；两者相减恰好漏掉图片在页面中的原点，偏移量随页面布局变化。
**How to apply**: `.wrap` 下 overlay 的拖拽框，坐标一律从单一来源派生——用 `getBoundingClientRect()` 把 mousedown/mousemove 都换算成**图片内坐标**（见 `static/app.js` 的 `pt()`），显示（box.style.left/top）和提交（POST 数值）共用同一组数；禁止 clientX 与 offsetLeft 混算。关联 [[pick-coordinate-flow]]。
