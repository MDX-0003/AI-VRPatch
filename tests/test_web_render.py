"""Preview store file discipline: derived/pick is a regenerable cache kept
bounded by two fixed names — every render drops leftovers from the older
content-keyed scheme, and geometry changes rewrite the same files in place
instead of accumulating new ones."""

import hashlib

import cv2
import numpy as np
import pytest

from vrpatch.web.render import PreviewStore

W, H, N_FRAMES = 1024, 512, 12


def _write_video(p):
    wr = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (W, H))
    assert wr.isOpened()
    for i in range(N_FRAMES):  # moving content so frames differ
        img = np.zeros((H, W, 3), np.uint8)
        cv2.circle(img, (40 + i * 40, H // 2), 50, (0, 200, 0), -1)
        wr.write(img)
    wr.release()


def _write_case(case_dir, video):
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    (case_dir / "case.toml").write_text(
        f'name = "t"\n'
        f'[source]\npath = "src.mp4"\nsha256 = "{sha}"\n'
        f"[erp]\nwidth = {W}\nheight = {H}\nfps = 30.0\n"
        f"[frames]\nstart = 0\nend = {N_FRAMES - 1}\n"
        f"[viewport]\nyaw_deg = 0.0\npitch_deg = 0.0\nfov_h_deg = 60.0\n"
        f"width = 320\nheight = 180\n"
        f"[inner]\nx = 80\ny = 45\nwidth = 160\nheight = 90\n",
        encoding="utf-8")


@pytest.fixture()
def store(tmp_path):
    _write_video(tmp_path / "src.mp4")
    _write_case(tmp_path, tmp_path / "src.mp4")
    return PreviewStore(str(tmp_path / "case.toml"))


def test_fixed_names_and_gc_of_legacy_keyed_files(store):
    pick = store.dir
    legacy1 = pick / "erp_078337921b.png"
    legacy2 = pick / "vp_078337921b.png"
    legacy1.write_bytes(b"x")
    legacy2.write_bytes(b"x")
    assert store.erp_png() == pick / "erp.png"
    assert store.viewport_png() == pick / "vp.png"
    assert (pick / "erp.png").is_file() and (pick / "vp.png").is_file()
    assert not legacy1.exists() and not legacy2.exists()
    assert sorted(p.name for p in pick.iterdir()) == ["erp.png", "vp.png"]


def test_geometry_change_rewrites_same_file(store):
    pick = store.dir
    store.erp_png()
    store.viewport_png()
    first = (pick / "vp.png").read_bytes()
    store.set_inner(10, 10, 100, 80)          # new content key, same path
    assert store.viewport_png() == pick / "vp.png"
    assert (pick / "vp.png").read_bytes() != first
    # the old keyed scheme would have left vp_<newkey>.png behind
    assert sorted(p.name for p in pick.iterdir()) == ["erp.png", "vp.png"]


def test_unchanged_geometry_does_not_rewrite(store):
    p = store.viewport_png()
    before = p.stat().st_mtime_ns
    store.viewport_png()
    assert p.stat().st_mtime_ns == before
