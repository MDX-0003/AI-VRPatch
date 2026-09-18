"""Regression gate 4: hoisted SegmentMaps path == legacy per-frame rebuild.

The legacy implementation lives in tests/reference.py (R3), so this compares
the product path against a reference that ships with the tests, not against a
second product code path.
"""

import numpy as np
import cv2

from vrpatch.sidecar import Segment, Viewport, InnerRect
from vrpatch.composite import SegmentMaps
from vrpatch.projection import build_view_map, erp_to_rect
from tests.reference import legacy_composite_frame

CASES = [
    # (erp_w, erp_h, vpw, vph, yaw, pitch, fov, inner, feather, levels)
    (640, 320, 320, 180, 30.0, -10.0, 70.0, (100, 40, 120, 100), 16, 5),
    (640, 320, 320, 180, 0.0, 0.0, 90.0, (20, 20, 200, 140), 8, 3),
    # viewport straddling the longitude seam -> paste map falls back to full canvas
    (512, 256, 256, 144, 180.0, 0.0, 80.0, (60, 30, 120, 80), 16, 5),
    # looking near the pole, where phi clamping kicks in
    (512, 256, 256, 144, 45.0, 80.0, 60.0, (70, 40, 100, 60), 12, 4),
    # viewport larger than the ERP itself
    (320, 160, 640, 360, 10.0, 5.0, 100.0, (200, 100, 240, 160), 16, 5),
]


def test_hoisted_equals_legacy():
    rng = np.random.default_rng(0)
    for ci, (ew, eh, vw, vh, yaw, pitch, fov, inr, feather, levels) in enumerate(CASES):
        vp = Viewport(yaw_deg=yaw, pitch_deg=pitch, fov_h_deg=fov,
                      width=vw, height=vh)
        inner = InnerRect(x=inr[0], y=inr[1], width=inr[2], height=inr[3])
        seg = Segment(id=f"c{ci}", frame_start=0, frame_end=2,
                      viewport=vp, inner=inner)

        erp = rng.integers(0, 256, (eh, ew, 3), dtype=np.uint8)
        ai = rng.integers(0, 256, (vh, vw, 3), dtype=np.uint8)

        maps = SegmentMaps(seg, ew, eh, feather)
        new = maps.composite_frame(erp, ai, levels)
        old = legacy_composite_frame(erp, ai, seg, feather, levels)
        assert int(np.abs(new.astype(np.int16)
                          - old.astype(np.int16)).max()) == 0, f"case {ci}"

        # the maps themselves match the one-shot projection helper
        vm = build_view_map(vp, ew, eh)
        ref = erp_to_rect(erp, np.radians(yaw), np.radians(pitch),
                          np.radians(fov), vw, vh)
        via_map = cv2.remap(erp, vm[0], vm[1], cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_WRAP)
        assert int(np.abs(ref.astype(np.int16)
                          - via_map.astype(np.int16)).max()) == 0, f"case {ci} view map"
