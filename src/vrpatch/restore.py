"""Bring an external AI clip to the segment's exact time contract.

Why: the external AI tool returns whatever fps/frame count it likes (typically
24 fps, sometimes a shorter duration). merge's nearest-frame resample
(framealign.index_map) silently tolerates that, at the cost of frozen tails and
whole-timeline resampling; an fps metadata lie even maps the wrong frames. The
frozen decision (2026-09-20): merge must receive an AI clip that matches the
segment *exactly* — same frame count, same fps — so index_map becomes the
identity map and no implicit time resampling ever runs. This module owns the
rule that produces such a clip.

The time rule (companion to framealign's nearest-frame rule, documented here
because it is the one other place time is touched):

- Target contract: ``n`` frames @ ``fps`` — the paired extract's segment.
- Assumption: the AI clip is a redrawing of the *whole* segment, so its frames
  are spread evenly over the target span. A clip that comes back short is
  stretched (interpolated), never truncated — "interpolation stretch" was the
  user's choice over freezing the tail.
- ``src_n < n``  → stretch: RIFE interpolates exactly ``n`` frames from the
  source sequence. Whatever count comes back is then made exact: pad by
  repeating the last frame, trim the overflow.
- ``src_n >= n`` → select: plain nearest-frame selection through
  framealign.index_map (frame counts stand in for fps), no interpolation. The
  dangerous "right frame count, wrong fps label" case lands here and is fixed
  by re-stamping fps on re-encode.
- ``src_n == n`` with matching fps → identity: nothing to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2

#: container fps read back within this of the target counts as matching
FPS_TOL = 0.01


@dataclass
class ClipInfo:
    frames: int
    fps: float
    width: int
    height: int


def probe_clip(path: str | Path) -> ClipInfo:
    """Read frame count / fps / size off a video file (cv2, like merge does)."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video: {path}")
    info = ClipInfo(
        frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        fps=float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    cap.release()
    return info


def needs_restore(info: ClipInfo, target_frames: int, target_fps: float) -> bool:
    """True unless the clip already satisfies the segment's time contract."""
    return info.frames != target_frames or abs(info.fps - target_fps) > FPS_TOL


def restore_plan(info: ClipInfo, target_frames: int) -> str:
    """Which time path applies: "identity" | "select" | "stretch"."""
    if info.frames == target_frames:
        return "identity"
    return "stretch" if info.frames < target_frames else "select"


def aligned_path_for(ai_path: str | Path) -> Path:
    """The aligned artifact lives next to the raw AI clip: <stem>_aligned.mp4."""
    p = Path(ai_path)
    return p.with_name(p.stem + "_aligned.mp4")


def aligned_is_current(aligned: str | Path, ai: str | Path,
                       target_frames: int, target_fps: float) -> bool:
    """True when an aligned artifact already satisfies the contract and is at
    least as new as the raw clip — merge can then skip the restore pass.

    The contract check (count + fps) is the same predicate merge enforces on
    any AI clip, so a stale or half-written aligned file is never trusted.
    """
    a, r = Path(aligned), Path(ai)
    if not a.is_file() or not r.is_file():
        return False
    if a.stat().st_mtime < r.stat().st_mtime:
        return False
    info = probe_clip(a)
    return not needs_restore(info, target_frames, target_fps)
