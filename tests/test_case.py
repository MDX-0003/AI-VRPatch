"""case.toml <-> sidecar mapping, sha256 verification, single-segment guard."""

import json

import pytest

from vrpatch.case import (load_case, case_to_sidecar, record_sha256,
                          load_sidecar_single_segment, set_draft_geometry)
from vrpatch.sidecar import save_sidecar, Sidecar, Segment, Viewport, InnerRect


def write_case(tmp_path, sha256=""):
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello world")
    p = tmp_path / "case.toml"
    p.write_text(
        f'name = "t"\n'
        f'[source]\npath = "src.bin"\nsha256 = "{sha256}"\n'
        f"[erp]\nwidth = 1024\nheight = 512\nfps = 30.0\n"
        f"[frames]\nstart = 0\nend = 9\n"
        f'[viewport]\nyaw_deg = 1.0\npitch_deg = 2.0\nfov_h_deg = 60.0\n'
        f"width = 320\nheight = 180\n"
        f"[inner]\nx = 80\ny = 45\nwidth = 160\nheight = 90\n",
        encoding="utf-8")
    return p


def test_load_and_record_sha256(tmp_path):
    p = write_case(tmp_path)
    case = load_case(p, verify=False)
    assert case.erp_width == 1024 and case.frame_end == 9

    digest = record_sha256(p)
    assert len(digest) == 64
    # now verification passes and tampering is caught
    load_case(p)
    (tmp_path / "src.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        load_case(p)


def test_case_to_sidecar_roundtrip(tmp_path):
    import tomllib
    p = write_case(tmp_path, sha256="%064d" % 0)
    # patch in a real hash so load_case(verify=True) passes
    import hashlib
    digest = hashlib.sha256(b"hello world").hexdigest()
    p.write_text(p.read_text(encoding="utf-8").replace("%064d" % 0, digest),
                 encoding="utf-8")
    case = load_case(p)
    sc = case_to_sidecar(case)
    assert sc.erp_width == 1024
    assert len(sc.segments) == 1
    assert sc.segments[0].frame_end == 9
    assert sc.segments[0].viewport.fov_h_deg == 60.0
    assert sc.segments[0].inner.width == 160
    # roundtrip through the external contract
    out = tmp_path / "clip.json"
    save_sidecar(sc, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["version"] == 1 and loaded["fps"] == 30.0


def test_set_draft_geometry(tmp_path):
    """Reset-draft action: overwrite viewport/inner, leave the rest intact."""
    p = write_case(tmp_path)
    import hashlib
    digest = hashlib.sha256(b"hello world").hexdigest()
    text = p.read_text(encoding="utf-8").replace("%064d" % 0, digest)
    p.write_text(text, encoding="utf-8")
    set_draft_geometry(p, yaw=-33.5, pitch=12.0, fov=45.0, vpw=640, vph=360,
                       x=1, y=2, w=3, h=4)
    c = load_case(p, verify=True)
    assert (c.viewport.yaw_deg, c.viewport.pitch_deg, c.viewport.fov_h_deg) == (-33.5, 12.0, 45.0)
    assert (c.viewport.width, c.viewport.height) == (640, 360)
    assert (c.inner.x, c.inner.y, c.inner.width, c.inner.height) == (1, 2, 3, 4)
    assert c.source.path == "src.bin" and c.frame_end == 9  # rest untouched


def test_single_segment_guard(tmp_path):
    good = Sidecar(erp_width=10, erp_height=5, fps=30.0, segments=[
        Segment(id="a", frame_start=0, frame_end=1,
                viewport=Viewport(0, 0, 60, 32, 18),
                inner=InnerRect(0, 0, 8, 8))])
    p1 = tmp_path / "one.json"
    save_sidecar(good, p1)
    assert load_sidecar_single_segment(p1).id == "a"

    bad = Sidecar(erp_width=10, erp_height=5, fps=30.0, segments=[
        good.segments[0],
        Segment(id="b", frame_start=2, frame_end=3,
                viewport=Viewport(0, 0, 60, 32, 18),
                inner=InnerRect(0, 0, 8, 8))])
    p2 = tmp_path / "two.json"
    save_sidecar(bad, p2)
    with pytest.raises(ValueError, match="exactly 1 segment"):
        load_sidecar_single_segment(p2)
