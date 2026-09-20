"""Restore-step contracts: probe, plan selection, aligned-artifact reuse.

Self-contained: fixtures are tiny mp4v clips written through the project's own
writer, so the roundtrip through a real container is what gets tested.
"""

import os
from pathlib import Path

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from vrpatch.cli.restore import app as restore_cli
from vrpatch.extract import write_clip
from vrpatch.media import FfmpegSink
from vrpatch.restore import (ClipInfo, FPS_TOL, aligned_is_current,
                             aligned_path_for, needs_restore, png_name,
                             probe_clip, restore_clip, restore_plan,
                             sidecar_target)
from vrpatch.sidecar import (InnerRect, Segment, Sidecar, Viewport,
                             save_sidecar)


def make_clip(path: Path, n: int = 12, fps: float = 30.0, w: int = 64, h: int = 48):
    """Tiny mp4v clip: frame k is a flat gray level k*10 (content is checkable)."""
    frames = np.full((n, h, w, 3), 0, np.uint8)
    for k in range(n):
        frames[k, ...] = min(255, k * 10)
    write_clip(frames, str(path), fps)
    return path


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    return make_clip(tmp_path / "ai.mp4")


# ---- probe ------------------------------------------------------------------

def test_probe_clip_reads_container_contract(clip: Path):
    info = probe_clip(clip)
    assert info.frames == 12
    assert abs(info.fps - 30.0) <= FPS_TOL
    assert (info.width, info.height) == (64, 48)


def test_probe_clip_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        probe_clip(tmp_path / "nope.mp4")


# ---- needs_restore / restore_plan -------------------------------------------

def test_exact_clip_needs_nothing():
    info = ClipInfo(frames=590, fps=60.0, width=1920, height=1080)
    assert not needs_restore(info, 590, 60.0)
    assert restore_plan(info, 590) == "identity"


def test_fps_tolerance_is_tight():
    exact = ClipInfo(frames=590, fps=60.0, width=1920, height=1080)
    assert not needs_restore(exact, 590, 60.0 + FPS_TOL / 2)
    assert needs_restore(exact, 590, 59.94)  # NTSC-ified label must be fixed
    assert needs_restore(exact, 590, 24.0)   # count right, label wrong


def test_short_clip_plans_stretch():
    info = ClipInfo(frames=570, fps=60.0, width=1920, height=1080)
    assert needs_restore(info, 590, 60.0)
    assert restore_plan(info, 590) == "stretch"


def test_long_or_mislabeled_plans_select():
    long_clip = ClipInfo(frames=1180, fps=24.0, width=1920, height=1080)
    assert restore_plan(long_clip, 590) == "select"
    assert needs_restore(long_clip, 590, 60.0)


# ---- aligned artifact path + reuse ------------------------------------------

def test_aligned_path_sits_next_to_raw(tmp_path: Path):
    assert aligned_path_for(tmp_path / "AIGC_60fps.mp4").name == "AIGC_60fps_aligned.mp4"


def test_reuse_rejects_missing_or_stale(clip: Path):
    aligned = aligned_path_for(clip)
    assert not aligned_is_current(aligned, clip, 12, 30.0)  # does not exist
    make_clip(aligned, n=12, fps=30.0)
    # same contract, but force mtime older than the raw clip
    raw_mtime = clip.stat().st_mtime
    os.utime(aligned, (raw_mtime - 10, raw_mtime - 10))
    assert not aligned_is_current(aligned, clip, 12, 30.0)


def test_reuse_accepts_fresh_matching_contract(clip: Path, tmp_path: Path):
    aligned = aligned_path_for(clip)
    make_clip(aligned, n=12, fps=30.0)
    os.utime(aligned, None)  # now
    assert aligned_is_current(aligned, clip, 12, 30.0)
    # a contract mismatch is never trusted, however fresh
    wrong = tmp_path / "wrong_aligned.mp4"
    make_clip(wrong, n=10, fps=30.0)
    assert not aligned_is_current(wrong, clip, 12, 30.0)


# ---- restore_clip pipeline ----------------------------------------------------

class Rec:
    """Log-shaped recorder."""

    def __init__(self):
        self.lines = []

    def phase(self, m):
        self.lines.append(m)

    def info(self, m):
        self.lines.append(m)

    def progress(self, *a, **k):
        pass

    def done(self):
        pass


def frame_level(video: Path, i: int) -> int:
    """Mean pixel value of frame i (fixtures are flat gray levels)."""
    cap = cv2.VideoCapture(str(video))
    for k in range(i + 1):
        ok, f = cap.read()
    cap.release()
    assert ok
    return float(f.mean())


def rife_like_interpolator(in_dir: Path, target_n: int, out_dir: Path) -> None:
    """What rife-ncnn-vulkan promises: exactly target_n PNGs, source frames
    spread endpoint-to-endpoint over the target span."""
    srcs = sorted(in_dir.glob("*.png"))
    m = len(srcs)
    out_dir.mkdir(parents=True, exist_ok=True)
    for k in range(target_n):
        j = round(k * (m - 1) / (target_n - 1)) if target_n > 1 else 0
        cv2.imwrite(str(out_dir / png_name(k)), cv2.imread(str(srcs[j])))


def test_stretch_path_exact_contract_and_content(tmp_path: Path):
    src = make_clip(tmp_path / "ai.mp4", n=8, fps=30.0)  # levels 0..70
    out = tmp_path / "ai_aligned.mp4"
    rep = restore_clip(src, out, 20, 60.0, interpolator=rife_like_interpolator,
                       log=Rec())
    assert rep["mode"] == "stretch"
    got = probe_clip(out)
    assert got.frames == 20
    assert abs(got.fps - 60.0) <= FPS_TOL
    # endpoint-preserving spread over 8 source frames: output 19 takes source
    # round(19*7/19)=7 (level 70), output 10 takes round(10*7/19)=4 (level 40);
    # a lossy mp4v roundtrip shifts levels a few points, hence the slack
    assert abs(frame_level(out, 19) - 70) < 15
    assert abs(frame_level(out, 10) - 40) < 15


def test_select_path_truncates_without_interpolator(tmp_path: Path):
    long = make_clip(tmp_path / "long.mp4", n=20, fps=30.0)
    out = tmp_path / "long_aligned.mp4"

    def must_not_run(in_dir, target_n, out_dir):
        raise AssertionError("select path must not interpolate")

    rep = restore_clip(long, out, 10, 30.0, interpolator=must_not_run, log=Rec())
    assert rep["mode"] == "select"
    got = probe_clip(out)
    assert got.frames == 10
    assert abs(got.fps - 30.0) <= FPS_TOL
    # same fps: nearest selection keeps frames 0..9 in order
    assert abs(frame_level(out, 9) - 90) < 15


def test_select_path_fixes_fps_label_lie(tmp_path: Path):
    # 12 real frames written at 24fps: right count, wrong label — the
    # dangerous case that would send merge's index_map off the timeline
    lie = tmp_path / "lie.mp4"
    sink = FfmpegSink(str(lie), (64, 48), 24.0)
    for k in range(12):
        sink.write(np.full((48, 64, 3), k * 10, np.uint8))
    sink.close()
    out = tmp_path / "lie_aligned.mp4"
    rep = restore_clip(lie, out, 12, 60.0, log=Rec())
    assert rep["mode"] == "identity"  # counts match; only the label is wrong
    got = probe_clip(out)
    assert got.frames == 12
    assert abs(got.fps - 60.0) <= FPS_TOL


def test_short_interpolator_output_is_padded(tmp_path: Path):
    clip = make_clip(tmp_path / "ai.mp4", n=8, fps=30.0)
    out = tmp_path / "ai_aligned.mp4"

    def short_interpolator(in_dir, target_n, out_dir):
        rife_like_interpolator(in_dir, target_n - 3, out_dir)

    rec = Rec()
    restore_clip(clip, out, 20, 60.0, interpolator=short_interpolator, log=rec)
    assert probe_clip(out).frames == 20
    assert any("repeating the last frame" in ln for ln in rec.lines)


def test_overflow_interpolator_output_is_trimmed(tmp_path: Path):
    clip = make_clip(tmp_path / "ai.mp4", n=8, fps=30.0)
    out = tmp_path / "ai_aligned.mp4"

    def over_interpolator(in_dir, target_n, out_dir):
        rife_like_interpolator(in_dir, target_n + 5, out_dir)

    restore_clip(clip, out, 20, 60.0, interpolator=over_interpolator, log=Rec())
    assert probe_clip(out).frames == 20


def test_stretch_without_interpolator_raises(clip: Path, tmp_path: Path):
    with pytest.raises(RuntimeError, match="no interpolator"):
        restore_clip(clip, tmp_path / "x.mp4", 20, 60.0, log=Rec())


def test_scratch_dirs_are_cleaned(clip: Path, tmp_path: Path):
    out = tmp_path / "ai_aligned.mp4"
    restore_clip(clip, out, 20, 60.0, interpolator=rife_like_interpolator,
                 log=Rec())
    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.name.endswith(".frames_in") or p.name.endswith(".frames_out")]
    assert leftovers == []


# ---- sidecar target + CLI wiring ----------------------------------------------

@pytest.fixture
def sidecar_file(tmp_path: Path) -> Path:
    sc = Sidecar(erp_width=1024, erp_height=512, fps=60.0, segments=[
        Segment(id="seg_0", frame_start=0, frame_end=589,
                viewport=Viewport(yaw_deg=0, pitch_deg=0, fov_h_deg=59,
                                  width=1920, height=1080),
                inner=InnerRect(x=10, y=10, width=100, height=100)),
    ])
    p = tmp_path / "clip.json"
    save_sidecar(sc, p)
    return p


def test_sidecar_target_reads_segment_contract(sidecar_file: Path):
    n, fps = sidecar_target(sidecar_file)
    assert (n, fps) == (590, 60.0)


def test_cli_no_op_when_target_matches(tmp_path: Path, sidecar_file: Path):
    good = tmp_path / "good.mp4"
    # the sidecar wants 590 frames; writing that many tiny frames is still fast
    frames = np.zeros((590, 48, 64, 3), np.uint8)
    write_clip(frames, str(good), 60.0)
    r = CliRunner().invoke(restore_cli, ["--ai", str(good),
                                         "--sidecar", str(sidecar_file), "-q"])
    assert r.exit_code == 0, r.output
    assert "nothing to do" in r.output
    assert not aligned_path_for(good).exists()  # no artifact was produced


def test_cli_clean_error_when_rife_missing_for_stretch(clip: Path,
                                                       sidecar_file: Path,
                                                       monkeypatch):
    import vrpatch.cli.restore as cli_mod
    monkeypatch.setattr(cli_mod, "find_rife", lambda: None)
    r = CliRunner().invoke(restore_cli, ["--ai", str(clip),
                                         "--sidecar", str(sidecar_file), "-q"])
    assert r.exit_code != 0
    assert "rife-ncnn-vulkan not found" in r.output
