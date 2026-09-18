"""Seam blending: fuse the regenerated inner region into the original viewport.

The viewport is split into an inner rect (person, replaced by the AI result) and
an outer ring (margin, kept as the original). `multiband_blend` blends across the
boundary at multiple frequency bands so luminance/color mismatches are absorbed
without a hard seam.
"""

import numpy as np
import cv2


def make_inner_mask(shape, inner_rect, feather_px=0):
    """Return a float mask (H,W) in [0,1]: 1 inside inner rect, 0 outside,
    Gaussian-feathered over `feather_px` at the boundary."""
    h, w = shape
    m = np.zeros((h, w), np.float32)
    x0 = max(0, inner_rect.x)
    y0 = max(0, inner_rect.y)
    x1 = min(w, inner_rect.x + inner_rect.width)
    y1 = min(h, inner_rect.y + inner_rect.height)
    if x0 < x1 and y0 < y1:
        m[y0:y1, x0:x1] = 1.0
    if feather_px > 0:
        k = int(round(feather_px)) * 2 + 1
        m = cv2.GaussianBlur(m, (k, k), 0)
    return m


def _laplacian_pyramid(img, levels):
    g = img.astype(np.float32)
    pyr = []
    for _ in range(levels):
        down = cv2.pyrDown(g)
        up = cv2.pyrUp(down, dstsize=(g.shape[1], g.shape[0]))
        pyr.append(g - up)
        g = down
    pyr.append(g)
    return pyr


def _reconstruct(pyr):
    g = pyr[-1]
    for lap in reversed(pyr[:-1]):
        g = cv2.pyrUp(g, dstsize=(lap.shape[1], lap.shape[0])) + lap
    return g


def multiband_blend(orig, ai, mask, levels=5):
    """Blend `ai` over `orig` weighted by `mask` (float [0,1], 1 == ai).

    orig/ai are (H,W,C) uint8 or float; returns float32 (H,W,C).
    """
    origf = orig.astype(np.float32)
    aif = ai.astype(np.float32)

    gp = [mask.astype(np.float32)]
    for _ in range(levels):
        gp.append(cv2.pyrDown(gp[-1]))

    la = _laplacian_pyramid(origf, levels)
    lb = _laplacian_pyramid(aif, levels)
    ls = []
    for i in range(levels + 1):
        w = gp[i][..., None]
        ls.append(la[i] * (1.0 - w) + lb[i] * w)
    return _reconstruct(ls)
