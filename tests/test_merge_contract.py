"""Merge-stage output contract: what the compositor may and may not touch.

Self-contained (no fixture files): the AI clip is derived from a redrawn ERP
through the project's own projection, so the expected result is known exactly.

1. Outside the viewport footprint the output is bit-identical to the input.
2. Inside the inner rect the redrawn content actually arrives.
3. The outer ring stays original and discards AI perturbation (seam anchor).
4. Hoisted maps == legacy reference (gate 4, exercised on this scene too).
"""

import numpy as np

from vrpatch.sidecar import Segment, Viewport, InnerRect
from vrpatch.composite import SegmentMaps
from vrpatch.extract import extract_viewport_frame
from vrpatch.projection import camera_rotation, _direction_to_erp_px
from tests.reference import legacy_composite_frame


def scene(erp_w, erp_h, vpx, vpy, mark_bgr, radius):
    y = np.linspace(0, 1, erp_h, dtype=np.float32)[:, None]
    x = np.linspace(0, 1, erp_w, dtype=np.float32)[None, :]
    bg = (90 + 60 * y + 25 * np.sin(10 * np.pi * x))
    img = np.repeat(np.clip(bg, 0, 255).astype(np.uint8)[..., None], 3, axis=2)
    yy, xx = np.ogrid[:erp_h, :erp_w]
    img[(xx - vpx) ** 2 + (yy - vpy) ** 2 <= radius ** 2] = mark_bgr
    return img


def make_fixtures():
    erp_w, erp_h = 1024, 512
    vpw, vph = 512, 288
    vp = Viewport(yaw_deg=20.0, pitch_deg=-8.0, fov_h_deg=70.0,
                  width=vpw, height=vph)
    inner = InnerRect(x=180, y=90, width=150, height=110)
    seg = Segment(id="t", frame_start=0, frame_end=2, viewport=vp, inner=inner)

    d = camera_rotation(np.radians(vp.yaw_deg), np.radians(vp.pitch_deg))[:, 2]
    px, py = _direction_to_erp_px(d[None, :], erp_w, erp_h)
    cx, cy = int(round(px[0])), int(round(py[0]))

    original = scene(erp_w, erp_h, cx, cy, (200, 90, 40), 70)
    redrawn = scene(erp_w, erp_h, cx, cy, (60, 40, 235), 90)
    return seg, vp, inner, original, extract_viewport_frame(redrawn, vp)


def test_merge_output_contract():
    seg, vp, inner, original, ai_frame = make_fixtures()
    maps = SegmentMaps(seg, original.shape[1], original.shape[0], feather_px=16)
    out = maps.composite_frame(original, ai_frame, levels=5)

    # 1. outside the viewport footprint: bit-identical
    oy, ox, oh, ow = maps.y0, maps.x0, maps.cover.shape[0], maps.cover.shape[1]
    d = np.abs(out[oy:oy + oh, ox:ox + ow].astype(np.int16)
               - original[oy:oy + oh, ox:ox + ow].astype(np.int16))
    assert int(d[~maps.cover].max()) == 0

    # 2. inner rect follows the AI clip
    out_view = extract_viewport_frame(out, vp)
    ic = out_view[inner.y + 40:inner.y + 70, inner.x + 50:inner.x + 100]
    d_ai = float(np.abs(ic.astype(np.float32)
                        - ai_frame[inner.y + 40:inner.y + 70,
                                   inner.x + 50:inner.x + 100].astype(np.float32)).mean())
    assert d_ai < 30.0, f"inner mean|diff| vs ai = {d_ai:.1f}"


def test_outer_ring_stays_original():
    seg, vp, inner, original, ai_frame = make_fixtures()
    vph, vpw = vp.height, vp.width
    maps = SegmentMaps(seg, original.shape[1], original.shape[0], feather_px=16)

    leak = ai_frame.copy()
    outside_inner = np.ones((vph, vpw), bool)
    outside_inner[inner.y:inner.y + inner.height,
                  inner.x:inner.x + inner.width] = False
    leak[outside_inner] = np.clip(
        leak[outside_inner].astype(np.int32) + 60, 0, 255).astype(np.uint8)
    out_leak = maps.composite_frame(original, leak, levels=5)
    leak_view = extract_viewport_frame(out_leak, vp)
    orig_view = extract_viewport_frame(original, vp)

    ring = (slice(8, 48), slice(8, 60))
    d_orig = float(np.abs(leak_view[ring].astype(np.float32)
                          - orig_view[ring].astype(np.float32)).mean())
    d_leak = float(np.abs(leak_view[ring].astype(np.float32)
                          - leak[ring].astype(np.float32)).mean())
    assert d_orig < 6.0, f"ring drifted from original: {d_orig:.1f}"
    assert d_leak > 25.0, f"AI perturbation leaked into ring: {d_leak:.1f}"


def test_hoisted_equals_legacy_this_scene():
    seg, _, _, original, ai_frame = make_fixtures()
    maps = SegmentMaps(seg, original.shape[1], original.shape[0], feather_px=16)
    out = maps.composite_frame(original, ai_frame, levels=5)
    legacy = legacy_composite_frame(original, ai_frame, seg, 16, 5)
    assert int(np.abs(out.astype(np.int16)
                      - legacy.astype(np.int16)).max()) == 0
