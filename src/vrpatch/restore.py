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

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .case import load_sidecar_single_segment
from .framealign import index_map
from .media import FfmpegSink
from .sidecar import load_sidecar

#: container fps read back within this of the target counts as matching
FPS_TOL = 0.01

#: the interpolator role: (frames_in_dir, target_n, frames_out_dir) -> None.
#: rife.RifeInterpolator is the real one; tests substitute a fake.
Interpolator = Callable[[Path, int, Path], None]

PNG_PATTERN = "%08d.png"


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


def sidecar_target(sidecar_path: str | Path) -> tuple[int, float]:
    """(frame count, fps) an AI clip must match — the sidecar's segment.

    Goes through the single-segment guard (R5), so a multi-segment sidecar
    fails loudly here too.
    """
    seg = load_sidecar_single_segment(sidecar_path)
    fps = float(load_sidecar(sidecar_path).fps)
    return seg.frame_end - seg.frame_start + 1, fps


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


class _NullLog:
    """Log-shaped no-op so the pipeline is callable without a reporter."""

    def phase(self, msg): pass
    def info(self, msg): pass
    def progress(self, *args, **kwargs): pass
    def done(self): pass


def png_name(i: int) -> str:
    return PNG_PATTERN % i


def _decode_to_png_dir(video: str, out_dir: Path, log) -> int:
    """Decode every frame to out_dir/%08d.png (lossless handoff to the exe);
    returns the number actually decoded (CAP_PROP counts can lie)."""
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video: {video}")
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        cv2.imwrite(str(out_dir / png_name(written)), frame)
        written += 1
    cap.release()
    log.info(f"decoded {written} frames -> {out_dir}")
    return written


def _encode_png_dir(in_dir: Path, n: int, fps: float, out_path: Path,
                    size: tuple[int, int], crf: int, preset: str, log) -> None:
    """Stream PNGs into ffmpeg at exactly n frames @ fps; short input repeats
    its last frame, overflow is trimmed (the count contract is not optional)."""
    sink = FfmpegSink(str(out_path), size, fps, crf, preset)
    last = None
    for i in range(n):
        p = in_dir / png_name(i)
        if p.is_file():
            last = cv2.imread(str(p))
        if last is None:
            raise RuntimeError(f"no decodable frames in {in_dir}")
        sink.write(last)
    sink.close()
    log.info(f"encoded {n} frames @ {fps:g}fps -> {out_path}")


def _encode_selected(video: str, n: int, src_fps: float, dst_fps: float,
                     src_n: int, out_path: Path, size: tuple[int, int],
                     crf: int, preset: str, log) -> None:
    """select/identity path: nearest-frame pick through framealign.index_map
    (the single resampling rule), streamed straight into ffmpeg — no PNGs."""
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video: {video}")
    idx = index_map(n, src_fps, dst_fps, src_n)
    sink = FfmpegSink(str(out_path), size, dst_fps, crf, preset)
    cur, last = -1, None
    for i in range(n):
        want = int(idx[i])
        while cur < want:
            ok, f = cap.read()
            if not ok:
                break
            last, cur = f, cur + 1
        if last is None:
            cap.release()
            sink.close()
            raise RuntimeError(f"AI clip {video!r} yielded no decodable frames")
        sink.write(last)
    sink.close()
    cap.release()
    log.info(f"selected {n} of {src_n} frames "
             f"({src_fps:g}->{dst_fps:g}fps) -> {out_path}")


def restore_clip(ai_path: str | Path, out_path: str | Path,
                 target_frames: int, target_fps: float, *,
                 interpolator: Interpolator | None = None,
                 crf: int = 14, preset: str = "medium",
                 log=None) -> dict:
    """Write ``out_path``: the AI clip brought to exactly ``target_frames`` @
    ``target_fps`` (resolution untouched — merge owns resizing).

    Stretch runs ``interpolator`` (caller resolves the binary first and says
    so in the log); select/identity never needs one. Returns a report dict.
    Raises RuntimeError if the re-encoded file misses the contract.
    """
    log = log or _NullLog()
    ai_path, out_path = Path(ai_path), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    info = probe_clip(ai_path)
    mode = restore_plan(info, target_frames)
    log.phase(f"restore: {info.frames} frames @ {info.fps:g}fps -> "
              f"{target_frames} @ {target_fps:g}fps (plan: {mode})")

    if mode == "stretch":
        if interpolator is None:
            raise RuntimeError("plan is stretch but no interpolator is available")
        in_dir = out_path.parent / (out_path.name + ".frames_in")
        out_dir = out_path.parent / (out_path.name + ".frames_out")
        try:
            src_n = _decode_to_png_dir(str(ai_path), in_dir, log)
            log.phase(f"interpolating {src_n} -> {target_frames} frames")
            interpolator(in_dir, target_frames, out_dir)
            made = len(list(out_dir.glob("*.png")))
            if made < target_frames:
                log.info(f"WARNING: interpolator returned {made} of "
                         f"{target_frames} frames; repeating the last frame.")
            elif made > target_frames:
                log.info(f"interpolator returned {made} frames; trimming to {target_frames}.")
            _encode_png_dir(out_dir, target_frames, target_fps, out_path,
                            (info.width, info.height), crf, preset, log)
        finally:
            shutil.rmtree(in_dir, ignore_errors=True)
            shutil.rmtree(out_dir, ignore_errors=True)
    else:
        # select/identity: index_map with the real fps stamps the right
        # playback rate on re-encode even when only the label was wrong
        _encode_selected(str(ai_path), target_frames, info.fps, target_fps,
                         info.frames, out_path, (info.width, info.height),
                         crf, preset, log)

    got = probe_clip(out_path)
    if got.frames != target_frames or abs(got.fps - target_fps) > FPS_TOL:
        raise RuntimeError(
            f"aligned clip missed the contract: wrote {got.frames} frames @ "
            f"{got.fps:g}fps, wanted {target_frames} @ {target_fps:g}fps")
    log.phase(f"restore done: {out_path} ({got.frames} frames @ "
              f"{got.fps:g}fps, {time.time() - t0:.1f}s)")
    return {"mode": mode, "src": info, "out": got,
            "target_frames": target_frames, "target_fps": target_fps,
            "elapsed_s": round(time.time() - t0, 1)}


def resolve_ai_clip(ai_path: str | Path, target_frames: int, target_fps: float,
                    *, no_restore: bool = False, log=None,
                    interpolator_factory=None) -> tuple[str, dict | None]:
    """The clip merge should actually read, given the raw AI clip.

    Frozen workflow decision: auto-restore runs here, not as a separate user
    step — merge is the only consumer of the exact contract, so it owns
    producing it. Returns (path, restore_report|None):
    - clip already matches → the raw path itself, no artifact touched;
    - mismatch and an aligned artifact is current → reused, not rebuilt;
    - mismatch → built once next to the raw clip (see restore_clip);
    - stretch required but no rife binary → loud WARNING and the raw path,
      letting merge's tolerant resampler degrade gracefully (installing the
      binary must not be a hard prerequisite for an otherwise valid merge);
    - ``no_restore`` → raw path always (escape hatch for regression runs).

    ``interpolator_factory``: None→exe | RifeInterpolator; tests inject a fake.
    """
    log = log or _NullLog()
    if no_restore:
        return str(ai_path), None
    info = probe_clip(ai_path)
    if not needs_restore(info, target_frames, target_fps):
        log.info(f"ai clip matches the segment contract "
                 f"({info.frames} frames @ {info.fps:g}fps); no restore needed")
        return str(ai_path), None
    from .rife import RifeInterpolator, find_rife

    aligned = aligned_path_for(ai_path)
    if aligned_is_current(aligned, ai_path, target_frames, target_fps):
        log.info(f"restore: reusing current aligned clip {aligned}")
        return str(aligned), None
    plan = restore_plan(info, target_frames)
    if plan == "stretch" and find_rife() is None:
        log.info(f"WARNING: AI clip is {info.frames} frames short of the "
                 f"segment ({target_frames}) and rife-ncnn-vulkan was not found "
                 f"(bin/ or VRPATCH_RIFE); falling back to resample + freeze fill. "
                 f"Install it to restore properly.")
        return str(ai_path), None
    if interpolator_factory is None:
        interpolator_factory = (lambda exe: RifeInterpolator(exe))
    interpolator = (interpolator_factory(find_rife())
                    if plan == "stretch" else None)
    report = restore_clip(ai_path, aligned, target_frames, target_fps,
                          interpolator=interpolator, log=log)
    return str(aligned), report
