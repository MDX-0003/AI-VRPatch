"""Restore-step contracts: probe, plan selection, aligned-artifact reuse.

Self-contained: fixtures are tiny mp4v clips written through the project's own
writer, so the roundtrip through a real container is what gets tested.
"""

import os
from pathlib import Path

import numpy as np
import pytest

from vrpatch.extract import write_clip
from vrpatch.restore import (ClipInfo, FPS_TOL, aligned_is_current,
                             aligned_path_for, needs_restore, probe_clip,
                             restore_plan)


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
