"""Web merge composition: paste-back takes the DRAFT inner rect, guarded by
viewport equality with the selected extract version. No videos are touched —
the task queue is faked and only the composed argv is inspected."""

import asyncio
import json

import pytest

from vrpatch.case import set_draft_geometry
from vrpatch.sidecar import save_sidecar, Sidecar, Segment, Viewport, InnerRect

MSG_DRIFTED = "当前视口与视频切分时有所偏差，请重置视口"


def _write_case(p):
    p.write_text(
        f'name = "t"\n'
        f'[source]\npath = "src.bin"\nsha256 = ""\n'
        f"[erp]\nwidth = 1024\nheight = 512\nfps = 30.0\n"
        f"[frames]\nstart = 0\nend = 9\n"
        f"[viewport]\nyaw_deg = 1.0\npitch_deg = 2.0\nfov_h_deg = 60.0\n"
        f"width = 320\nheight = 180\n"
        f"[inner]\nx = 80\ny = 45\nwidth = 160\nheight = 90\n",
        encoding="utf-8")


def _write_version(case_dir, version, ai_path):
    vdir = case_dir / "extracts" / version
    vdir.mkdir(parents=True)
    seg = Segment(id="seg_0", frame_start=0, frame_end=9,
                  viewport=Viewport(1.0, 2.0, 60.0, 320, 180),
                  inner=InnerRect(70, 40, 150, 80))  # deliberately != draft inner
    save_sidecar(Sidecar(erp_width=1024, erp_height=512, fps=30.0,
                         segments=[seg]), vdir / "clip.json")
    (vdir / "ai_clip.json").write_text(
        json.dumps({"path": str(ai_path)}), encoding="utf-8")


class _Request:
    def __init__(self, body, name):
        self.path_params = {"name": name}
        self._body = body

    async def json(self):
        return self._body


class _Queue:
    def __init__(self):
        self.argv = None

    def submit(self, kind, name, argv):
        self.argv = argv


@pytest.fixture()
def merge_env(tmp_path, monkeypatch):
    import vrpatch.web.app as webapp
    monkeypatch.setattr(webapp, "cases_dir", lambda: tmp_path)
    queue = _Queue()
    monkeypatch.setattr(webapp, "QUEUE", queue)
    case_dir = tmp_path / "t"
    case_dir.mkdir()
    _write_case(case_dir / "case.toml")
    _write_version(case_dir, "v1", tmp_path / "ai.mp4")
    (tmp_path / "ai.mp4").write_bytes(b"0")  # the registered path must exist
    return webapp, case_dir, queue


def test_merge_uses_draft_inner(merge_env):
    webapp, case_dir, queue = merge_env
    resp = asyncio.run(webapp.api_merge(_Request({"version": "v1"}, "t")))
    assert resp.status_code == 200
    argv = queue.argv
    i = argv.index("--inner")
    assert argv[i + 1] == "80,45,160,90"          # the DRAFT rect, not v1's 70,40,150,80
    assert argv[argv.index("--report") + 1].endswith("out_v1.merge.json")
    sidecar = argv[argv.index("--sidecar") + 1]
    assert "v1" in sidecar and sidecar.endswith("clip.json")
    assert json.loads(resp.body)["inner"] == [80, 45, 160, 90]


def test_merge_refuses_when_viewport_drifted(merge_env):
    webapp, case_dir, queue = merge_env
    set_draft_geometry(case_dir / "case.toml", yaw=1.2, pitch=2.0, fov=60.0,
                       vpw=320, vph=180, x=80, y=45, w=160, h=90)
    resp = asyncio.run(webapp.api_merge(_Request({"version": "v1"}, "t")))
    assert resp.status_code == 409
    assert json.loads(resp.body)["error"] == MSG_DRIFTED
    assert queue.argv is None                     # nothing was submitted


def test_merge_passes_after_reset(merge_env):
    webapp, case_dir, queue = merge_env
    set_draft_geometry(case_dir / "case.toml", yaw=1.2, pitch=2.0, fov=60.0,
                       vpw=320, vph=180, x=1, y=2, w=3, h=4)
    drifted = asyncio.run(webapp.api_merge(_Request({"version": "v1"}, "t")))
    assert drifted.status_code == 409
    # what reset-draft does: restore viewport AND inner from the version's clip.json
    set_draft_geometry(case_dir / "case.toml", yaw=1.0, pitch=2.0, fov=60.0,
                       vpw=320, vph=180, x=70, y=40, w=150, h=80)
    resp = asyncio.run(webapp.api_merge(_Request({"version": "v1"}, "t")))
    assert resp.status_code == 200
    assert queue.argv[queue.argv.index("--inner") + 1] == "70,40,150,80"
