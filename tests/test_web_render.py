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
    for i in range(N_FRAMES):  # a bar sweeping across the default viewport
        img = np.zeros((H, W, 3), np.uint8)
        x = 400 + i * 20
        cv2.rectangle(img, (x, 0), (x + 8, H), (0, 200, 0), -1)
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
    legacy3 = pick / "erp.png"      # fixed name of the removed ERP preview
    legacy1.write_bytes(b"x")
    legacy2.write_bytes(b"x")
    legacy3.write_bytes(b"x")
    assert store.viewport_png() == pick / "vp.png"
    assert (pick / "vp.png").is_file()
    assert not legacy1.exists() and not legacy2.exists() and not legacy3.exists()
    assert sorted(p.name for p in pick.iterdir()) == ["vp.png"]


def test_geometry_change_rewrites_same_file(store):
    pick = store.dir
    store.viewport_png()
    first = (pick / "vp.png").read_bytes()
    store.set_inner(10, 10, 100, 80)          # new content key, same path
    assert store.viewport_png() == pick / "vp.png"
    assert (pick / "vp.png").read_bytes() != first
    # the old keyed scheme would have left vp_<newkey>.png behind
    assert sorted(p.name for p in pick.iterdir()) == ["vp.png"]


def test_unchanged_geometry_does_not_rewrite(store):
    p = store.viewport_png()
    before = p.stat().st_mtime_ns
    store.viewport_png()
    assert p.stat().st_mtime_ns == before


def test_frame_preview_cache(store):
    p3 = store.viewport_png(frame=3)
    p5 = store.viewport_png(frame=5)
    geo = store.dir / "vpframes" / store._vp_geo_key()
    jpg3, jpg5 = geo / "vp_000003.jpg", geo / "vp_000005.jpg"
    assert jpg3.is_file() and jpg5.is_file()
    assert jpg3.read_bytes() != jpg5.read_bytes()   # moving content differs
    m0 = jpg3.stat().st_mtime_ns
    assert store.viewport_png(frame=3) == p3        # cached: same file
    assert jpg3.stat().st_mtime_ns == m0            # ...not rewritten
    # the response image carries the inner overlay, the cache does not
    assert p3.read_bytes() != jpg3.read_bytes()


def test_frame_cache_invalidated_by_viewport_move(store):
    old_geo = store._vp_geo_key()
    store.viewport_png(frame=3)
    old_jpg = store.dir / "vpframes" / old_geo / "vp_000003.jpg"
    assert old_jpg.is_file()
    store.set_viewport_from_erp_click(0.75, 0.25)   # yaw/pitch move
    store.viewport_png(frame=3)
    vpf = store.dir / "vpframes"
    assert [d.name for d in vpf.iterdir()] == [store._vp_geo_key()]
    assert not old_jpg.exists()


def test_inner_drag_keeps_frame_cache(store):
    store.viewport_png(frame=3)
    jpg = store.dir / "vpframes" / store._vp_geo_key() / "vp_000003.jpg"
    m0 = jpg.stat().st_mtime_ns
    store.set_inner(10, 10, 100, 80)                # frequent: must not re-reproject
    store.viewport_png(frame=3)
    assert jpg.stat().st_mtime_ns == m0


def test_frame_out_of_range(store):
    with pytest.raises(ValueError):
        store.viewport_png(frame=N_FRAMES)
    with pytest.raises(ValueError):
        store.viewport_png(frame=-1)


# ---- /img route: frame parameter handling ---------------------------------

class _ImgRequest:
    def __init__(self, name, file, query=None):
        self.path_params = {"name": name, "file": file}
        self.query_params = query or {}


def _route_env(tmp_path, monkeypatch):
    import vrpatch.web.app as webapp
    monkeypatch.setattr(webapp, "cases_dir", lambda: tmp_path)
    monkeypatch.setattr(webapp, "_stores", {})
    case_dir = tmp_path / "t"
    case_dir.mkdir()
    _write_video(case_dir / "src.mp4")
    _write_case(case_dir, case_dir / "src.mp4")
    return webapp


def test_img_route_frame_param(tmp_path, monkeypatch):
    import asyncio
    webapp = _route_env(tmp_path, monkeypatch)
    ok = asyncio.run(webapp.img(_ImgRequest("t", "vp.png", {"frame": "2"})))
    assert ok.status_code == 200
    plain = asyncio.run(webapp.img(_ImgRequest("t", "vp.png")))
    assert plain.status_code == 200
    for bad in ({"frame": "9999"}, {"frame": "-1"}, {"frame": "abc"}):
        r = asyncio.run(webapp.img(_ImgRequest("t", "vp.png", bad)))
        assert r.status_code == 400, bad
    # the server-side ERP preview is gone: the browser scrubs the video itself
    for missing in ("other.png", "erp.png"):
        r = asyncio.run(webapp.img(_ImgRequest("t", missing)))
        assert r.status_code == 404, missing
