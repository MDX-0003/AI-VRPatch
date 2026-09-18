"""The one time-resampling rule (R1) and its documented edge cases."""

import numpy as np

from vrpatch.framealign import index_map, short_by


def test_identity_when_fps_match():
    idx = index_map(10, 30.0, 30.0, 10)
    assert idx.tolist() == list(range(10))


def test_nearest_and_clamp():
    # upsampling: 24fps -> 60fps, 5 output frames
    idx = index_map(5, 24.0, 60.0, 5)
    assert idx.tolist() == [0, 0, 1, 1, 2]
    # short source: everything clamps to the last available frame
    idx = index_map(6, 24.0, 60.0, 2)
    assert idx.max() == 1
    assert short_by(6, 2) == 4
    # empty source degrades gracefully (all zeros, caller raises on no frames)
    assert index_map(3, 24.0, 60.0, 0).tolist() == [0, 0, 0]
