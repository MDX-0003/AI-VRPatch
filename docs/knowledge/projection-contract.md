> 层: knowledge    时效: 冻结的数学契约，改动须走回归门槛

# 投影契约（ERP ↔ rectilinear）

权威实现：`src/vrpatch/projection.py`（模块 docstring 与本文一致；不一致时以代码 + 本文档同时修订为准）。

## 坐标约定

- ERP (W×H, W=2H)：pixel (x,y) → 经度 λ=(x/W−0.5)·2π ∈ [−π,π]，纬度 φ=(0.5−y/H)·π ∈ [−π/2,π/2]；世界方向 (cosφ·sinλ, sinφ, cosφ·cosλ)。λ=0,φ=0 朝 +Z，+X 右，+Y 上。
- 视口相机：yaw 绕 +Y（正=向右转），pitch 绕 +X（正=抬头）；R 的列 = [right|up|forward]。
- rectilinear (w×h)：焦距 f=(w/2)/tan(fov_h/2)；pixel (u,v) → 相机空间射线 ((u−cx)/f, (cy−v)/f, 1)，u 右 v 下。

## 不变量（tests/test_projection.py 冻结）

1. 视口中心方向与 (yaw,pitch) 精确一致（误差 < 1e-9）。
2. 平滑图像经"抽取→逆投影"，覆盖区 PSNR > 40 dB。
3. 已知方向的标记点落在预测的视口像素上（前向投影 vs remap 逆投影互相印证）。
4. **贴回不越界**：`cover` 掩膜外的 ERP 像素 bit 级不变（`tests/test_merge_contract.py`）。
5. 经度缝合线跨越时 `_viewport_erp_bounds` 回退全宽；极点附近 φ 截断；遮挡像素（Zc≤0）由 `cover` 丢弃。

## 数值精度规则

预计算映射（`build_view_map` / `build_paste_map_raw`）内部用 float64 构建、float32 供 `cv2.remap`——float64 是为了与逐帧一次性路径（`tests/reference.py`）bit 级一致（回归门槛 4）。
