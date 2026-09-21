"""scalefit: recovery of a known injected warp, identity detection, and the
cache round-trip. Synthetic smooth textures only -- no video files."""

import json

import cv2
import numpy as np
import pytest

from vrpatch import scalefit
from vrpatch.sidecar import InnerRect

W, H = 320, 180
INNER = InnerRect(x=80, y=45, width=160, height=90)


def texture(seed=0):
    rng = np.random.default_rng(seed)
    small = rng.uniform(0, 255, (18, 32)).astype(np.float32)
    img = cv2.resize(small, (W, H), interpolation=cv2.INTER_CUBIC)
    return cv2.GaussianBlur(img, (5, 5), 0).astype(np.uint8)


def warp(img, m):
    return cv2.warpAffine(img, np.float32(m), (W, H), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REFLECT)


def test_fit_recovers_known_warp():
    """AI = clip warped by a known shrink+shift -> the fitted correction must
    be (close to) the inverse, and confident enough to apply."""
    base = texture()
    K = np.float32([[0.97, 0.0, 7.8], [0.0, 0.95, 5.4]])  # shrink + shift
    ai = warp(base, K)
    fit = scalefit.fit_core([(base, ai), (base, ai), (base, ai)], INNER,
                            (W, H))
    Kinv = np.linalg.inv(np.vstack([K, [0, 0, 1]]))[:2]
    assert abs(fit.sx - np.hypot(Kinv[0, 0], Kinv[1, 0])) < 0.004
    assert abs(fit.sy - np.hypot(Kinv[0, 1], Kinv[1, 1])) < 0.004
    assert abs(fit.tx - Kinv[0, 2]) < 1.0
    assert abs(fit.ty - Kinv[1, 2]) < 1.0
    assert fit.applied and not fit.identity
    assert fit.ring_ncc > 0.95
    assert fit.inner_median_px >= 0


def test_fit_identity_when_aligned():
    base = texture(3)
    fit = scalefit.fit_core([(base, base)], INNER, (W, H))
    assert fit.identity and not fit.applied
    assert fit.reason == "identity"


def test_cache_roundtrip(tmp_path, monkeypatch):
    """load_or_fit('auto') reuses the cached fit while the AI file is
    unchanged, without re-running the (expensive) fit."""
    ai = tmp_path / "ai.mp4"
    ai.write_bytes(b"fake")
    fit = scalefit.ScaleFit([[1.01, 0, 2.0], [0, 1.02, 3.0]], 1.01, 1.02, 0.0,
                            2.0, 3.0, 0.97, 1.0, False, "ok", [0], "fresh")
    scalefit.save_cache(fit, ai)
    assert scalefit.cache_path(ai).is_file()

    def boom(*a, **k):  # the fit must NOT run on a cache hit
        raise AssertionError("fit ran despite a fresh cache")

    monkeypatch.setattr(scalefit, "fit_videos", boom)
    got = scalefit.resolve("unused_clip.mp4", ai, INNER, (W, H), 0, 10, "auto")
    assert got.source == "cache" and got.applied
    assert got.matrix == fit.matrix

    # a changed AI file invalidates the cache -> the fit would run
    ai.write_bytes(b"changed")
    assert not scalefit._cache_fresh(ai)


def test_cache_invalidated_by_mtime(tmp_path):
    ai = tmp_path / "ai.mp4"
    ai.write_bytes(b"v1")
    fit = scalefit.ScaleFit([[1, 0, 0], [0, 1, 0]], 1, 1, 0, 0, 0,
                            0.99, 0.5, True, "identity", [0], "fresh")
    scalefit.save_cache(fit, ai)
    assert scalefit._cache_fresh(ai)
    ai.write_bytes(b"v2 - different size")
    assert not scalefit._cache_fresh(ai)


def _write_video(path, w, h, gray_frames, fps=30.0):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert vw.isOpened(), f"cannot open VideoWriter for {path}"
    for f in gray_frames:
        vw.write(cv2.cvtColor(f, cv2.COLOR_GRAY2BGR))
    vw.release()


def test_fit_videos_rejects_mismatched_reference(tmp_path):
    """Regression: merge once fed the ERP source (8K equirect) as the fit
    reference and scalefit died on the mask-size mismatch. A reference that
    is not the viewport geometry must degrade to a non-applied fit."""
    base = texture()
    good = tmp_path / "clip.mp4"
    bad = tmp_path / "erp.mp4"
    ai = tmp_path / "ai.mp4"
    K = np.float32([[0.97, 0.0, 7.8], [0.0, 0.95, 5.4]])
    frames = [base] * 4
    _write_video(good, W, H, frames)
    _write_video(bad, 640, 320, [base] * 4)          # wrong geometry on purpose
    _write_video(ai, W, H, [warp(base, K) for _ in frames])

    fit = scalefit.fit_videos(good, ai, INNER, (W, H), 0, 4)
    assert fit.applied
    assert abs(fit.sx - 1 / 0.97) < 0.005            # real fit through real files

    bad_frame = cv2.resize(base, (640, 320))         # own-size content, wrong geometry
    _write_video(bad, 640, 320, [bad_frame] * 4)
    fit2 = scalefit.fit_videos(bad, ai, INNER, (W, H), 0, 4)
    assert not fit2.applied and fit2.reason == "bad_reference_geometry"
    assert fit2.matrix == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


def test_fit_videos_missing_reference(tmp_path):
    fit = scalefit.fit_videos(tmp_path / "missing.mp4", tmp_path / "alsono.mp4",
                              INNER, (W, H), 0, 4)
    assert not fit.applied and fit.reason == "no_reference"


def test_resolve_off_and_file_modes(tmp_path):
    off = scalefit.resolve(None, None, INNER, (W, H), 0, 10, "off")
    assert off.reason == "off" and not off.applied
    with pytest.raises(FileNotFoundError):
        scalefit.resolve(None, None, INNER, (W, H), 0, 10, str(tmp_path / "no.json"))
