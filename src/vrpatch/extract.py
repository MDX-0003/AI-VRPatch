"""Extractor: pull fixed-viewport rectilinear clips out of ERP video.

`extract_segment` returns the full rectilinear viewport clip (the "square region
+ margin" that gets handed to the external AI tool). The inner rect (person
region to regenerate) is described in the sidecar, not cropped away here.
"""

import numpy as np
import cv2

from .projection import erp_to_rect
from .sidecar import Segment


def extract_viewport_frame(erp_frame, viewport):
    return erp_to_rect(
        erp_frame,
        np.radians(viewport.yaw_deg),
        np.radians(viewport.pitch_deg),
        np.radians(viewport.fov_h_deg),
        viewport.width,
        viewport.height,
    )


def extract_segment(erp_frames, segment: Segment) -> np.ndarray:
    """erp_frames: (T,H,W,C) uint8 array (or list). Returns (n,Hv,Wv,C) uint8."""
    erp_frames = np.asarray(erp_frames)
    out = [
        extract_viewport_frame(erp_frames[t], segment.viewport)
        for t in range(segment.frame_start, segment.frame_end + 1)
    ]
    return np.stack(out)


def open_writer(path, fps, size):
    """Open an mp4 writer for streaming frames one at a time."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(path, fourcc, fps, size)
    if not vw.isOpened():
        raise RuntimeError(f"cannot open video writer for {path!r} at {size}")
    return vw


def write_clip(frames, path, fps, progress=None):
    """Write a (T,H,W,C) uint8 BGR array to an mp4 file via cv2.

    `progress(i, t)` is called after each frame if given, for progress reporting.
    """
    frames = np.asarray(frames)
    t, h, w, c = frames.shape
    vw = open_writer(path, fps, (w, h))
    for i in range(t):
        vw.write(frames[i])
        if progress is not None:
            progress(i + 1, t)
    vw.release()


def read_clip(path):
    """Read an mp4 into a (T,H,W,C) uint8 BGR array."""
    cap = cv2.VideoCapture(path)
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    return np.stack(frames)


def make_mask_image(viewport, inner):
    """Black (0) inside the inner rect, white (255) outside. Returns (H,W) uint8.

    Conventions for the external AI tool: black = region to regenerate,
    white = fixed anchor region (the margin). Hard binary, no feathering.
    """
    m = np.full((viewport.height, viewport.width), 255, np.uint8)
    x0 = max(0, inner.x)
    y0 = max(0, inner.y)
    x1 = min(viewport.width, inner.x + inner.width)
    y1 = min(viewport.height, inner.y + inner.height)
    if x0 < x1 and y0 < y1:
        m[y0:y1, x0:x1] = 0
    return m
