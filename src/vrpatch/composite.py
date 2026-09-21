"""Paste-back: re-inject regenerated viewport clips into the ERP video.

For each frame in a segment: re-extract the original viewport, blend the AI clip's
inner rect over the original outer ring, then inverse-project the blended viewport
back into the ERP frame.

Two things here are per-frame and unavoidable: the viewport extraction and the
multi-band blend. Everything else depends only on the segment geometry, so
`SegmentMaps` builds it once — the original code rebuilt a full (H,W,3) ray grid
for the viewport *and* for the ERP footprint on every single frame, which was
about two thirds of the runtime on a 6K canvas.

R2: the old module-level `_MAPS_CACHE` is gone. `SegmentMaps` is built once by
the merge loop's caller and held there; caching behind global mutable state
(no invalidation, no bound) bought nothing the merge loop didn't already do.
"""

import numpy as np
import cv2

from .projection import (build_view_map, build_paste_map, remap_viewport,
                         rect_to_erp_bbox, erp_to_rect)
from .blend import make_inner_mask, multiband_blend
from .framealign import index_map

class SegmentMaps:
    """Frame-invariant geometry for one segment: sampling maps + inner mask.

    Cheap to build relative to the per-frame work it saves, but still worth
    hoisting out of the frame loop rather than rebuilding per call. The caller
    holds one instance for the whole merge pass.
    """

    def __init__(self, segment, erp_w, erp_h, feather_px=16):
        self.segment = segment
        self.erp_w = erp_w
        self.erp_h = erp_h
        vp = segment.viewport
        self.view_map = build_view_map(vp, erp_w, erp_h)
        self.paste_map = build_paste_map(vp, vp.width, vp.height, erp_w, erp_h)
        self.mask = make_inner_mask((vp.height, vp.width), segment.inner,
                                    feather_px)
        self.cover = self.paste_map[2]
        self.x0 = self.paste_map[3]
        self.y0 = self.paste_map[4]

    def composite_frame(self, erp_frame, ai_frame, levels=5):
        """Blend one AI frame into one ERP frame; returns a new uint8 ERP frame.

        Only the viewport footprint is touched: pixels outside `cover` are copied
        through unchanged, so the panorama outside the viewport is bit-identical.
        """
        orig_view = remap_viewport(erp_frame, self.view_map)
        blended = multiband_blend(orig_view, ai_frame, self.mask, levels)

        # INTER_CUBIC: the paste is a x~0.7 downscale (canvas > footprint) where
        # bilinear drops samples; policy documented in verification.md, kept in
        # lockstep with projection.rect_to_erp_bbox (gate 4 reference)
        patch = cv2.remap(blended, self.paste_map[0], self.paste_map[1],
                          cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT)

        out = erp_frame.copy()
        sub = out[self.y0:self.y0 + patch.shape[0],
                  self.x0:self.x0 + patch.shape[1]].astype(np.float32)
        sub[self.cover] = patch[self.cover]
        out[self.y0:self.y0 + patch.shape[0],
            self.x0:self.x0 + patch.shape[1]] = np.clip(sub, 0, 255).astype(np.uint8)
        return out


def align_ai_clip(ai_frames, target_size, src_fps, dst_fps, n):
    """Resize and time-resample an AI clip to exactly `n` frames of `target_size`.

    External AI tools routinely disagree with the sidecar on resolution, fps and
    frame count (Viggle returns 25fps, VACE 16fps, and so on), so this is where
    that mismatch is absorbed. The resampling rule itself lives in
    :mod:`vrpatch.framealign` (R1).

    A clip that comes back short is filled by repeating its last frame — the
    index clamp below does that — rather than refusing to run, because the
    caller cannot control what the external tool produced.
    """
    ai_frames = np.asarray(ai_frames)
    src_n = len(ai_frames)
    if src_n == 0:
        raise ValueError("ai clip has no frames to align")
    resized = np.stack([cv2.resize(f, target_size, interpolation=cv2.INTER_AREA)
                        for f in ai_frames])
    if src_n == n:
        return resized
    idx = index_map(n, src_fps, dst_fps, src_n)
    return resized[idx]
