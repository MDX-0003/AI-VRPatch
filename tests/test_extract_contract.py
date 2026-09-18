"""Extract contract (R6): the mask is written, black inside inner, white outside;
the clip round-trips through the sidecar geometry."""

import numpy as np
import cv2

from vrpatch.sidecar import Segment, Viewport, InnerRect
from vrpatch.extract import extract_segment, make_mask_image


def test_mask_contract():
    vp = Viewport(yaw_deg=0, pitch_deg=0, fov_h_deg=70, width=320, height=180)
    inner = InnerRect(x=80, y=45, width=160, height=90)
    m = make_mask_image(vp, inner)
    assert m.shape == (180, 320) and m.dtype == np.uint8
    assert (m[45:135, 80:240] == 0).all(), "inner must be black"
    assert (m[:45, :] == 255).all() and (m[135:, :] == 255).all()
    assert (m[:, :80] == 255).all() and (m[:, 240:] == 255).all()


def test_clip_shape_matches_segment():
    rng = np.random.default_rng(1)
    vp = Viewport(yaw_deg=15, pitch_deg=-5, fov_h_deg=60, width=160, height=90)
    seg = Segment(id="s", frame_start=0, frame_end=3, viewport=vp,
                  inner=InnerRect(x=40, y=20, width=80, height=45))
    frames = rng.integers(0, 256, (4, 64, 128, 3), dtype=np.uint8)
    clip = extract_segment(frames, seg)
    assert clip.shape == (4, 90, 160, 3)
