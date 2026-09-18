"""The single time-resampling rule for AI clips.

R1 convergence: this nearest-frame rule is the only place in the codebase that
resamples in time. Everything that needs frame alignment calls
:func:`index_map`; never re-derive the formula elsewhere.

Rule: nearest source frame per output frame — output frame ``i`` takes source
frame ``round(i * src_fps / dst_fps)``, clamped to the last decodable source
frame. A clip that comes back short is therefore filled by repeating its last
frame rather than refusing to run, because the caller cannot control what the
external AI tool produced.
"""

import numpy as np


def index_map(n: int, src_fps: float, dst_fps: float, src_n: int) -> np.ndarray:
    """Target->source frame index map for ``n`` output frames."""
    return np.clip(np.round(np.arange(n) * src_fps / dst_fps),
                   0, max(0, src_n - 1)).astype(int)


def short_by(n: int, src_n: int) -> int:
    """How many output frames the source clip is short (filled by repeat)."""
    return max(0, n - src_n)
