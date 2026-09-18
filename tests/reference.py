"""Reference implementations kept out of the product path (R3).

``legacy_composite_frame`` is the pre-optimisation single-frame paste-back,
verbatim from the pre-port composite implementation. It exists only
so tests can A/B the hoisted ``SegmentMaps`` path against it (regression gate 4).
"""

import numpy as np

from vrpatch.blend import make_inner_mask, multiband_blend
from vrpatch.projection import erp_to_rect, rect_to_erp_bbox


def legacy_composite_frame(erp_frame, ai_frame, segment, feather_px=16, levels=5):
    """Same formulas as ``SegmentMaps.composite_frame`` but rebuilding every map
    from scratch and copying the whole ERP canvas to float32, exactly as the
    original ``composite_segment`` did."""
    vp = segment.viewport
    erp_h, erp_w = erp_frame.shape[0], erp_frame.shape[1]
    mask = make_inner_mask((vp.height, vp.width), segment.inner, feather_px)
    orig_view = erp_to_rect(erp_frame, np.radians(vp.yaw_deg),
                            np.radians(vp.pitch_deg), np.radians(vp.fov_h_deg),
                            vp.width, vp.height)
    blended = multiband_blend(orig_view, ai_frame, mask, levels)
    patch, cover, x0, y0 = rect_to_erp_bbox(
        blended, np.radians(vp.yaw_deg), np.radians(vp.pitch_deg),
        np.radians(vp.fov_h_deg), erp_w, erp_h)
    frame = erp_frame.astype(np.float32).copy()
    sub = frame[y0:y0 + patch.shape[0], x0:x0 + patch.shape[1]]
    sub[cover] = patch[cover]
    return np.clip(frame, 0, 255).astype(np.uint8)
