"""ERP <-> rectilinear (gnomonic) reprojection.

Coordinate conventions (all self-consistent):

ERP (equirectangular) image of size (W, H), W == 2*H:
    pixel (x, y) ->
        longitude lam = (x / W - 0.5) * 2*pi      # in [-pi, pi]
        latitude  phi = (0.5 - y / H) * pi        # in [-pi/2, pi/2]
    world direction (unit):
        dx = cos(phi) * sin(lam)
        dy = sin(phi)
        dz = cos(phi) * cos(lam)
    So (lam=0, phi=0) -> +Z (forward), +X right, +Y up.

Viewport camera: yaw around +Y (positive = turn right), pitch around +X
(positive = look up). Forward direction at (yaw=0, pitch=0) is +Z.
    forward f = (sin(yaw)*cos(pitch), sin(pitch), cos(yaw)*cos(pitch))
    right   r = (cos(yaw), 0, -sin(yaw))
    up      u = f x r
    world = R @ cam,  R = [r | u | f] (columns).

Rectilinear image (w, h), focal length f = (w/2) / tan(fov_h/2):
    pixel (u, v) -> camera-space ray (Xc, Yc, Zc) = ((u-cx)/f, (cy-v)/f, 1)
    with cx=w/2, cy=h/2; u right, v down.
"""

import numpy as np
import cv2


def camera_rotation(yaw, pitch):
    """Return orthonormal 3x3 R mapping camera space to world (world = R @ cam)."""
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    f = np.array([sy * cp, sp, cy * cp])
    r = np.array([cy, 0.0, -sy])
    u = np.cross(f, r)
    return np.stack([r, u, f], axis=-1)  # columns r, u, f


def focal_from_fov(fov_h, w):
    """Focal length in pixels for a horizontal FOV (radians) and image width."""
    return (w / 2.0) / np.tan(fov_h / 2.0)


def _direction_to_erp_px(d, w, h):
    """Unit world directions (...,3) -> ERP pixel coords (...,2)."""
    dx, dy, dz = d[..., 0], d[..., 1], d[..., 2]
    lam = np.arctan2(dx, dz)
    phi = np.arcsin(np.clip(dy, -1.0, 1.0))
    px = ((lam / (2.0 * np.pi) + 0.5) % 1.0) * w
    py = np.clip((0.5 - phi / np.pi) * h, 0.0, h - 1.0)
    return px, py


def erp_to_rect(erp, yaw, pitch, fov_h, out_w, out_h):
    """Extract a rectilinear viewport from an ERP image.

    Returns uint8 image of shape (out_h, out_w, C) matching `erp` dtype.
    """
    h, w = erp.shape[:2]
    f = focal_from_fov(fov_h, out_w)
    cx, cy = out_w / 2.0, out_h / 2.0
    R = camera_rotation(yaw, pitch)

    u = np.arange(out_w, dtype=np.float64)
    v = np.arange(out_h, dtype=np.float64)
    U, V = np.meshgrid(u, v)
    Xc = (U - cx) / f
    Yc = (cy - V) / f
    Zc = np.ones_like(Xc)
    n = np.sqrt(Xc * Xc + Yc * Yc + Zc * Zc)
    d = np.stack([Xc / n, Yc / n, Zc / n], axis=-1)  # (h,w,3) camera space
    dw = d @ R.T  # world
    map_x, map_y = _direction_to_erp_px(dw, w, h)
    return cv2.remap(
        erp,
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_WRAP,
    )


def rect_to_erp(rect, yaw, pitch, fov_h, erp_w, erp_h):
    """Inverse-project a rectilinear image back into an ERP canvas.

    Returns (patch, mask):
        patch: float32 array (erp_h, erp_w, C) sampled from `rect`.
        mask:  bool array (erp_h, erp_w) True where the viewport covers.
    Pixels outside the viewport are 0 in `patch`.
    """
    h, w = rect.shape[:2]
    f = focal_from_fov(fov_h, w)
    cx, cy = w / 2.0, h / 2.0
    R = camera_rotation(yaw, pitch)

    x = np.arange(erp_w, dtype=np.float64)
    y = np.arange(erp_h, dtype=np.float64)
    X, Y = np.meshgrid(x, y)
    lam = (X / erp_w - 0.5) * 2.0 * np.pi
    phi = (0.5 - Y / erp_h) * np.pi
    dx = np.cos(phi) * np.sin(lam)
    dy = np.sin(phi)
    dz = np.cos(phi) * np.cos(lam)
    d_world = np.stack([dx, dy, dz], axis=-1)
    d_cam = d_world @ R  # world -> cam, R^T == R^-1
    Xc, Yc, Zc = d_cam[..., 0], d_cam[..., 1], d_cam[..., 2]
    u = cx + f * Xc / Zc
    v = cy - f * Yc / Zc
    # Exclude the outer 1px ring where bilinear taps would go out of bounds
    # (this ring is viewport margin that gets discarded/replaced on paste-back).
    mask = (Zc > 0) & (u >= 0) & (u < w - 1) & (v >= 0) & (v < h - 1)

    rectf = rect.astype(np.float32)
    patch = cv2.remap(rectf, u.astype(np.float32), v.astype(np.float32),
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return patch, mask


def _viewport_erp_bounds(rect_w, rect_h, yaw, pitch, fov, erp_w, erp_h):
    """Bounding box (x0, y0, x1, y1) in ERP pixels covering the whole viewport.

    Samples the viewport's four edges (the curved footprint in ERP) and takes
    the min/max with padding. Falls back to the full canvas if the viewport
    crosses the longitude seam.
    """
    f = focal_from_fov(fov, rect_w)
    cx, cy = rect_w / 2.0, rect_h / 2.0
    R = camera_rotation(yaw, pitch)

    n = 24
    t = np.linspace(0.0, 1.0, n + 1)
    us = np.concatenate([t * rect_w, t * rect_w,
                         np.zeros_like(t), np.full_like(t, float(rect_w))])
    vs = np.concatenate([np.zeros_like(t), np.full_like(t, float(rect_h)),
                         t * rect_h, t * rect_h])
    Xc = (us - cx) / f
    Yc = (cy - vs) / f
    Zc = np.ones_like(Xc)
    nn = np.sqrt(Xc * Xc + Yc * Yc + Zc * Zc)
    d = np.stack([Xc / nn, Yc / nn, Zc / nn], axis=-1)
    dw = d @ R.T
    px, py = _direction_to_erp_px(dw, erp_w, erp_h)

    if px.max() - px.min() > erp_w / 2.0:
        return 0, 0, erp_w, erp_h  # crosses the seam; use full width

    pad = max(4, erp_w // 200)
    x0 = max(0, int(np.floor(px.min())) - pad)
    x1 = min(erp_w, int(np.ceil(px.max())) + pad)
    y0 = max(0, int(np.floor(py.min())) - pad)
    y1 = min(erp_h, int(np.ceil(py.max())) + pad)
    return x0, y0, x1, y1


def rect_to_erp_bbox(rect, yaw, pitch, fov, erp_w, erp_h):
    """Like rect_to_erp but only computes over the viewport's ERP bounding box.

    Returns (patch_crop, mask_crop, x0, y0) where patch_crop/mask_crop cover
    [y0:y1, x0:x1] of the full ERP canvas.
    """
    u, v, cover, x0, y0 = build_paste_map_raw(yaw, pitch, fov, rect.shape[1],
                                              rect.shape[0], erp_w, erp_h)
    # INTER_CUBIC: the paste is always a downscale (viewport canvas is larger
    # than its ERP footprint), where bilinear drops samples; this is a
    # documented quality decision (2026-09-21), kept in lockstep with the
    # product remap in composite.py so gate 4 stays maxdiff==0
    patch = cv2.remap(rect.astype(np.float32), u, v, cv2.INTER_CUBIC,
                      borderMode=cv2.BORDER_CONSTANT)
    return patch, cover, x0, y0


def build_view_map(viewport, erp_w, erp_h):
    """Precompute the ERP -> viewport sampling maps for one fixed viewport.

    Returns (map_x, map_y) float32 arrays of shape (viewport.height,
    viewport.width), ready for `cv2.remap(erp, map_x, map_y, ...,
    borderMode=cv2.BORDER_WRAP)`.

    These depend only on the viewport and the ERP canvas size — **not on the
    frame** — so `composite_segment` computes them once per segment instead of
    rebuilding a (H,W,3) ray grid for every frame.
    """
    yaw = np.radians(viewport.yaw_deg)
    pitch = np.radians(viewport.pitch_deg)
    fov_h = np.radians(viewport.fov_h_deg)
    out_w, out_h = viewport.width, viewport.height

    f = focal_from_fov(fov_h, out_w)
    cx, cy = out_w / 2.0, out_h / 2.0
    R = camera_rotation(yaw, pitch)

    # float64 internally to match erp_to_rect exactly; this runs once per
    # segment, so the precision costs nothing.
    U, V = np.meshgrid(np.arange(out_w, dtype=np.float64),
                       np.arange(out_h, dtype=np.float64))
    Xc = (U - cx) / f
    Yc = (cy - V) / f
    n = np.sqrt(Xc * Xc + Yc * Yc + 1.0)
    d = np.stack([Xc / n, Yc / n, 1.0 / n], axis=-1) @ R.T
    map_x, map_y = _direction_to_erp_px(d, erp_w, erp_h)
    return map_x.astype(np.float32), map_y.astype(np.float32)


def remap_viewport(erp_frame, view_map):
    """Apply a map from `build_view_map` to one ERP frame."""
    return cv2.remap(erp_frame, view_map[0], view_map[1], cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_WRAP)


def build_paste_map_raw(yaw, pitch, fov, rect_w, rect_h, erp_w, erp_h):
    """Precompute the viewport -> ERP sampling maps over the viewport's bbox.

    Returns (u, v, cover, x0, y0): float32 sample coordinates sized to the ERP
    bounding box starting at (x0, y0), plus the bool `cover` mask of pixels the
    viewport actually covers.

    Frame-invariant, so it is computed once per segment rather than per frame.
    `rect_to_erp_bbox` wraps this with the remap call.
    """
    f = focal_from_fov(fov, rect_w)
    cx, cy = rect_w / 2.0, rect_h / 2.0
    R = camera_rotation(yaw, pitch)
    x0, y0, x1, y1 = _viewport_erp_bounds(rect_w, rect_h, yaw, pitch, fov,
                                          erp_w, erp_h)

    # float64 internally to match the original rect_to_erp_bbox numerics; this
    # runs once per segment, so the precision costs nothing.
    X, Y = np.meshgrid(np.arange(x0, x1, dtype=np.float64),
                       np.arange(y0, y1, dtype=np.float64))
    lam = (X / erp_w - 0.5) * 2.0 * np.pi
    phi = (0.5 - Y / erp_h) * np.pi
    d_world = np.stack([np.cos(phi) * np.sin(lam), np.sin(phi),
                        np.cos(phi) * np.cos(lam)], axis=-1)
    d_cam = d_world @ R
    Zc = d_cam[..., 2]
    # Pixels behind the camera have Zc <= 0, so the projection divides by zero;
    # they are discarded by `cover` below. Silenced because it is expected, not
    # a problem — and this runs once per segment, not per frame.
    with np.errstate(divide="ignore", invalid="ignore"):
        u = cx + f * d_cam[..., 0] / Zc
        v = cy - f * d_cam[..., 1] / Zc
    cover = (Zc > 0) & (u >= 0) & (u < rect_w - 1) & (v >= 0) & (v < rect_h - 1)
    return u.astype(np.float32), v.astype(np.float32), cover, x0, y0


def build_paste_map(viewport, rect_w, rect_h, erp_w, erp_h):
    """`build_paste_map_raw` for a Viewport, ready to cache per segment."""
    return build_paste_map_raw(np.radians(viewport.yaw_deg),
                               np.radians(viewport.pitch_deg),
                               np.radians(viewport.fov_h_deg),
                               rect_w, rect_h, erp_w, erp_h)
