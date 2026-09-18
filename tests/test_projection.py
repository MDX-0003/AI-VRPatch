"""Correctness tests for ERP <-> rectilinear projection ."""

import numpy as np
from vrpatch.projection import (
    erp_to_rect, rect_to_erp, camera_rotation, focal_from_fov,
    _direction_to_erp_px,
)


def make_smooth_erp(w=1024, h=512):
    x = np.arange(w, dtype=np.float64)
    y = np.arange(h, dtype=np.float64)
    X, Y = np.meshgrid(x, y)
    img = (
        np.sin(X / w * 2 * np.pi * 2) * 40.0
        + np.cos(Y / h * 2 * np.pi * 2) * 40.0
        + X / w * 100.0
        + 40.0 * np.exp(-((X - w * 0.6) ** 2 + (Y - h * 0.4) ** 2) / 60.0 ** 2)
        + 127.0
    )
    img = np.clip(img, 0, 255).astype(np.uint8)
    return np.repeat(img[..., None], 3, axis=-1)


def test_viewport_center():
    erp = make_smooth_erp()
    h, w = erp.shape[:2]
    yaw, pitch = np.radians(30.0), np.radians(10.0)
    R = camera_rotation(yaw, pitch)
    fwd = R[:, 2]
    lam = np.arctan2(fwd[0], fwd[2])
    phi = np.arcsin(np.clip(fwd[1], -1, 1))
    assert abs(lam - yaw) < 1e-9
    assert abs(phi - pitch) < 1e-9


def test_smooth_roundtrip():
    erp = make_smooth_erp()
    h, w = erp.shape[:2]
    yaw, pitch = np.radians(-25.0), np.radians(8.0)
    fov = np.radians(75.0)

    rect = erp_to_rect(erp, yaw, pitch, fov, 400, 225)
    patch, mask = rect_to_erp(rect, yaw, pitch, fov, w, h)

    n = int(mask.sum())
    assert n > 0
    mse = float(np.mean((erp.astype(np.float32)[mask] - patch[mask]) ** 2))
    psnr = float("inf") if mse == 0 else 10.0 * np.log10(255.0 ** 2 / mse)
    assert psnr > 40.0, f"round-trip PSNR too low: {psnr:.2f} dB"


def test_marker_alignment():
    w, h = 1024, 512
    erp = np.zeros((h, w, 3), np.uint8)
    yaw, pitch = np.radians(20.0), np.radians(5.0)
    fov = np.radians(70.0)
    out_w, out_h = 480, 270
    f = focal_from_fov(fov, out_w)
    R = camera_rotation(yaw, pitch)

    dirs = [R[:, 2]]
    for du, dv in [(100.0, 0.0), (0.0, 60.0), (-120.0, -40.0)]:
        cam = np.array([du / f, -dv / f, 1.0])
        cam /= np.linalg.norm(cam)
        dirs.append(R @ cam)

    for d in dirs:
        px, py = _direction_to_erp_px(d[None, :], w, h)
        px, py = int(round(px[0])), int(round(py[0]))
        erp[max(0, py - 2):py + 3, max(0, px - 2):px + 3] = 255

    rect = erp_to_rect(erp, yaw, pitch, fov, out_w, out_h)
    cx, cy = out_w / 2.0, out_h / 2.0
    for d in dirs:
        cam = R.T @ d
        u = cx + f * cam[0] / cam[2]
        v = cy - f * cam[1] / cam[2]
        ui, vi = int(round(u)), int(round(v))
        win = rect[max(0, vi - 3):vi + 4, max(0, ui - 3):ui + 4].max()
        assert win > 200, f"marker not found near ({ui},{vi})"
