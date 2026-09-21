"""vrpatch-serve backend: the single entry point for the whole workflow.

One local web app covers everything that used to be CLI-only: create a case
from a video in sources/, pick viewport/inner, run extract, register the
external AI tool's output, run merge — with a single-lane task queue and live
progress. `case.toml` stays the single source of truth and the CLIs stay the
execution path (the web layer only writes case.toml and spawns `python -m
vrpatch.cli...`), so command-line users and web users share one reality.

Localhost, single user: the file browser is unrestricted on purpose.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import jinja2
from starlette.applications import Starlette
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from ..case import load_case, set_draft_geometry, extract_version, viewports_match
from ..sidecar import Viewport
from .render import PreviewStore
from .tasks import QUEUE

_ROOT = Path(__file__).resolve().parents[3]  # src/vrpatch/web/app.py -> repo root
_TEMPLATES = Path(__file__).parent / "templates"
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi"}

_env = jinja2.Environment(loader=jinja2.FileSystemLoader(_TEMPLATES),
                          autoescape=True)


def sources_dir() -> Path:
    d = _ROOT / "sources"
    d.mkdir(exist_ok=True)
    return d


def cases_dir() -> Path:
    d = _ROOT / "cases"
    d.mkdir(exist_ok=True)
    return d


def case_path(name: str) -> Path | None:
    """Resolve a case name; refuse anything that escapes cases/."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    p = cases_dir() / name / "case.toml"
    return p if p.is_file() else None


# ---- per-case preview stores, invalidated on case.toml mtime change --------

_stores: dict[str, tuple[float, PreviewStore]] = {}


def get_store(name: str) -> PreviewStore | None:
    cp = case_path(name)
    if cp is None:
        return None
    mtime = cp.stat().st_mtime
    hit = _stores.get(name)
    if hit and hit[0] == mtime:
        return hit[1]
    store = PreviewStore(str(cp))
    _stores[name] = (mtime, store)
    return store


def preview_urls(name: str) -> dict:
    store = get_store(name)
    if store is None:
        return {}
    k = store.key
    return {"erp": f"/img/{name}/erp.png?k={k}", "vp": f"/img/{name}/vp.png?k={k}"}


# ---- pages -----------------------------------------------------------------

async def index(request):
    tpl = _env.get_template("dashboard.html")
    return HTMLResponse(tpl.render())


async def img(request):
    name = request.path_params["name"]
    fn = request.path_params["file"]
    store = get_store(name)
    if store is None or "/" in fn or "\\" in fn:
        return JSONResponse({"error": "not found"}, status_code=404)
    # both previews are regenerated on demand under their content-key names
    p = store.erp_png() if fn == "erp.png" else store.viewport_png()
    return FileResponse(p)


# ---- case api ----------------------------------------------------------

def _versions(case_dir: Path) -> list[dict]:
    """Extract version dirs, oldest last. Each dir is the self-contained unit:
    clip + sidecar + mask + optional ai_clip.json marker ({"path": ...}) that
    says which AI output belongs to this version. Location implies pairing —
    no fingerprints."""
    out = []
    vroot = case_dir / "extracts"
    if not vroot.is_dir():
        return out
    for vdir in sorted(p for p in vroot.iterdir() if p.is_dir()):
        clip_json = vdir / "clip.json"
        marker = vdir / "ai_clip.json"
        ai_path = None
        if marker.is_file():
            try:
                ai_path = json.loads(marker.read_text(encoding="utf-8")).get("path")
            except (json.JSONDecodeError, OSError):
                pass
        out.append({
            "version": vdir.name,
            "dir": str(vdir),
            "extracted": clip_json.is_file(),
            "ai_clip": ai_path,
            "ai_clip_exists": bool(ai_path) and Path(ai_path).is_file(),
        })
    return out


def _case_info(name: str) -> dict | None:
    cp = case_path(name)
    if cp is None:
        return None
    c = load_case(cp, verify=False)
    derived = cp.parent / "derived"
    versions = _versions(cp.parent)
    latest = versions[-1] if versions else None
    info = {
        "name": name,
        "frames": [c.frame_start, c.frame_end],
        "fps": c.fps,
        "erp": [c.erp_width, c.erp_height],
        "viewport": {"yaw": c.viewport.yaw_deg, "pitch": c.viewport.pitch_deg,
                     "fov": c.viewport.fov_h_deg,
                     "size": [c.viewport.width, c.viewport.height]},
        "inner": {"x": c.inner.x, "y": c.inner.y,
                  "w": c.inner.width, "h": c.inner.height},
        "extracted": (derived / "clip.mp4").is_file(),
        "extract_version": latest["version"] if latest else None,
        "versions": versions,
        "derived": str(derived),
        "previews": preview_urls(name),
    }
    return info


async def api_cases(request):
    if request.method == "GET":
        names = sorted(p.parent.name for p in cases_dir().glob("*/case.toml"))
        return JSONResponse([_case_info(n) for n in names])

    # POST: create a case from a video already inside sources/
    body = await request.json()
    video = sources_dir() / Path(body.get("video", "")).name
    if not video.is_file():
        return JSONResponse({"error": f"no such video in sources/: {video.name}"},
                            status_code=400)
    name = video.stem
    cdir = cases_dir() / name
    cdir.mkdir(parents=True, exist_ok=True)
    cp = cdir / "case.toml"
    if cp.exists():
        return JSONResponse({"error": f"case '{name}' already exists"}, status_code=409)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return JSONResponse({"error": "cannot open video"}, status_code=400)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()

    vpw = min(1920, w)
    vph = int(vpw * 9 / 16)
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    cp.write_text(
        f'name = "{name}"\n'
        f'notes = "created via web dashboard"\n\n'
        f"[source]\n"
        f'path = "../../sources/{video.name}"\n'
        f'sha256 = "{sha}"\n\n'
        f"[erp]\nwidth = {w}\nheight = {h}\nfps = {fps:.3f}\n\n"
        f"[frames]\nstart = 0\nend = {max(0, n - 1)}\n\n"
        f"[viewport]\nyaw_deg = 0.0\npitch_deg = 0.0\nfov_h_deg = 59.0\n"
        f"width = {vpw}\nheight = {vph}\n\n"
        f"[inner]\nx = {vpw // 4}\ny = {vph // 4}\n"
        f"width = {vpw // 2}\nheight = {vph // 2}\n",
        encoding="utf-8")
    return JSONResponse(_case_info(name))


async def api_case(request):
    name = request.path_params["name"]
    info = _case_info(name)
    if info is None:
        return JSONResponse({"error": "no such case"}, status_code=404)
    return JSONResponse(info)


async def api_viewport(request):
    name = request.path_params["name"]
    store = get_store(name)
    if store is None:
        return JSONResponse({"error": "no such case"}, status_code=404)
    body = await request.json()
    store.set_viewport_from_erp_click(float(body["fx"]), float(body["fy"]))
    _stores[name] = (Path(store.case_path).stat().st_mtime, store)
    return JSONResponse(_case_info(name))


async def api_inner(request):
    name = request.path_params["name"]
    store = get_store(name)
    if store is None:
        return JSONResponse({"error": "no such case"}, status_code=404)
    body = await request.json()
    # Contract: the client submits fractions (0..1) of the preview image —
    # deliberately independent of preview resolution and CSS size, so neither
    # end can drift when styles change. Convert to viewport pixels here.
    fx, fy, fw, fh = (float(body[k]) for k in ("fx", "fy", "fw", "fh"))
    vp = store.case.viewport
    x, y = int(fx * vp.width), int(fy * vp.height)
    w, h = int(fw * vp.width), int(fh * vp.height)
    if w <= 0 or h <= 0:
        return JSONResponse({"error": "width/height must be positive"}, status_code=400)
    store.set_inner(x, y, w, h)
    _stores[name] = (Path(store.case_path).stat().st_mtime, store)
    return JSONResponse(_case_info(name))


# ---- pipeline api --------------------------------------------------------

async def api_extract(request):
    name = request.path_params["name"]
    cp = case_path(name)
    if cp is None:
        return JSONResponse({"error": "no such case"}, status_code=404)
    argv = [sys_executable(), "-m", "vrpatch.cli.extract", "case", str(cp)]
    task = QUEUE.submit("extract", name, argv)
    return JSONResponse({"submitted": task.kind, "case": name})


async def api_ai_clip(request):
    """Register an AI output for one extract version: writes the marker
    ai_clip.json into that version's directory. Location implies pairing."""
    name = request.path_params["name"]
    cp = case_path(name)
    if cp is None:
        return JSONResponse({"error": "no such case"}, status_code=404)
    body = await request.json()
    p = Path(body.get("path", ""))
    version = body.get("version")
    if not p.is_file():
        return JSONResponse({"error": f"not a file: {p}"}, status_code=400)
    vdir = cp.parent / "extracts" / (version or "")
    if not (vdir / "clip.json").is_file():
        return JSONResponse({"error": f"unknown extract version: {version}"},
                            status_code=404)
    (vdir / "ai_clip.json").write_text(
        json.dumps({"path": str(p)}, indent=2), encoding="utf-8")
    _stores.pop(name, None)  # case.toml changed behind the store's back
    return JSONResponse(_case_info(name))


async def api_reset_draft(request):
    """"清空草稿": discard the draft region and restore the viewport/inner
    recorded by the SELECTED extract version (body {"version": ...}; defaults
    to the latest). Only the preview and case.toml draft change — extract
    artifacts are immutable and untouched."""
    name = request.path_params["name"]
    cp = case_path(name)
    if cp is None:
        return JSONResponse({"error": "no such case"}, status_code=404)
    body = await request.json()
    version = body.get("version") or extract_version(cp)
    if not version:
        return JSONResponse({"error": "还没有任何 Extract 版本可回退"}, status_code=400)
    sj = cp.parent / "extracts" / version / "clip.json"
    if not sj.is_file():
        return JSONResponse({"error": f"extract {version} 缺少 clip.json"},
                            status_code=400)
    seg = json.loads(sj.read_text(encoding="utf-8"))["segments"][0]
    vp, inner = seg["viewport"], seg["inner"]
    set_draft_geometry(
        cp, yaw=vp["yaw_deg"], pitch=vp["pitch_deg"], fov=vp["fov_h_deg"],
        vpw=vp["width"], vph=vp["height"],
        x=inner["x"], y=inner["y"], w=inner["width"], h=inner["height"])
    _stores.pop(name, None)
    return JSONResponse(_case_info(name))


async def api_nudge(request):
    """Joystick micro-offset: add small deltas to the draft yaw/pitch.

    The server owns the arithmetic so case.toml always holds legal values:
    yaw wraps at ±180 (ERP longitude is cyclic), pitch clamps to ±89. Called
    every ~100ms while the user holds a joystick button.
    """
    name = request.path_params["name"]
    cp = case_path(name)
    if cp is None:
        return JSONResponse({"error": "no such case"}, status_code=404)
    store = get_store(name)
    if store is None:
        return JSONResponse({"error": "no such case"}, status_code=404)
    body = await request.json()
    dy = float(body.get("dyaw", 0.0))
    dp = float(body.get("dpitch", 0.0))
    vp = store.case.viewport
    yaw = ((vp.yaw_deg + dy + 180.0) % 360.0 + 360.0) % 360.0 - 180.0
    pitch = max(-89.0, min(89.0, vp.pitch_deg + dp))
    vp.yaw_deg = round(yaw, 2)
    vp.pitch_deg = round(pitch, 2)
    store.save()
    store.touch()  # previews must change: the geometry just moved
    _stores[name] = (Path(store.case_path).stat().st_mtime, store)
    return JSONResponse({"yaw": vp.yaw_deg, "pitch": vp.pitch_deg})


async def api_merge(request):
    """Merge one extract version: that directory's clip.json + its registered
    ai_clip. Which version to merge is a human choice in the dashboard.

    The blend window (inner) is a live creative choice, not version state: the
    version's clip.json records the rect the AI was masked with at extract
    time, but paste-back uses the CURRENT DRAFT inner (--report records what
    actually ran). Inner is in viewport pixels, so it is only accepted while
    the draft viewport still matches the version's — otherwise the box would
    land somewhere else than drawn, and the request is refused instead."""
    name = request.path_params["name"]
    cp = case_path(name)
    if cp is None:
        return JSONResponse({"error": "no such case"}, status_code=404)
    c = load_case(cp, verify=False)
    body = await request.json()
    versions = _versions(cp.parent)
    if not versions:
        return JSONResponse({"error": "run extract first"}, status_code=400)
    version = body.get("version") or versions[-1]["version"]
    ver = next((v for v in versions if v["version"] == version), None)
    if ver is None:
        return JSONResponse({"error": f"unknown extract version: {version}"},
                            status_code=404)
    if not ver["extracted"]:
        return JSONResponse({"error": f"extract {version} has no clip.json"},
                            status_code=400)
    if not ver["ai_clip_exists"]:
        return JSONResponse({"error": f"extract {version} has no AI clip "
                                      f"registered"}, status_code=400)
    vdir = cp.parent / "extracts" / version
    seg = json.loads((vdir / "clip.json").read_text(encoding="utf-8"))["segments"][0]
    if not viewports_match(c.viewport, Viewport(**seg["viewport"])):
        return JSONResponse({"error": "当前视口与视频切分时有所偏差，请重置视口"},
                            status_code=409)
    out = cp.parent / "derived" / f"out_{version}.mp4"
    inner = c.inner
    argv = [sys_executable(), "-m", "vrpatch.cli.merge",
            "--input", str((cp.parent / c.source.path).resolve()),
            "--ai", ver["ai_clip"], "--sidecar", str(vdir / "clip.json"),
            "--output", str(out),
            "--inner", f"{inner.x},{inner.y},{inner.width},{inner.height}",
            "--scale-fit", "auto",
            "--report", str(out.with_name(out.stem + ".merge.json"))]
    QUEUE.submit("merge", name, argv)
    return JSONResponse({"submitted": "merge", "case": name, "version": version,
                         "inner": [inner.x, inner.y, inner.width, inner.height]})


async def api_task(request):
    return JSONResponse(QUEUE.status())


async def api_browse(request):
    """Directory browser for picking the AI clip by path (localhost tool:
    unrestricted by design; only video files are listed)."""
    d = Path(request.query_params.get("path", str(_ROOT)))
    if not d.is_dir():
        return JSONResponse({"error": "not a directory"}, status_code=400)
    dirs = sorted(p for p in d.iterdir() if p.is_dir() and not p.name.startswith("."))
    files = sorted(p for p in d.iterdir()
                   if p.is_file() and p.suffix.lower() in _VIDEO_EXTS)
    return JSONResponse({
        "path": str(d),
        "parent": str(d.parent) if d.parent != d else None,
        "dirs": [p.name for p in dirs[:200]],
        "files": [str(p) for p in files[:200]],
    })


async def api_sources(request):
    """Videos available for new cases (fixed library dir, frozen decision)."""
    vids = sorted(p for p in sources_dir().iterdir()
                  if p.is_file() and p.suffix.lower() in _VIDEO_EXTS)
    return JSONResponse({"dir": str(sources_dir()),
                         "files": [p.name for p in vids]})


def sys_executable() -> str:
    import sys
    return sys.executable


routes = [
    Route("/", index),
    Route("/img/{name}/{file}", img),
    Route("/api/cases", api_cases, methods=["GET", "POST"]),
    Route("/api/case/{name}", api_case),
    Route("/api/case/{name}/viewport", api_viewport, methods=["POST"]),
    Route("/api/case/{name}/inner", api_inner, methods=["POST"]),
    Route("/api/case/{name}/nudge", api_nudge, methods=["POST"]),
    Route("/api/case/{name}/reset-draft", api_reset_draft, methods=["POST"]),
    Route("/api/case/{name}/extract", api_extract, methods=["POST"]),
    Route("/api/case/{name}/ai-clip", api_ai_clip, methods=["POST"]),
    Route("/api/case/{name}/merge", api_merge, methods=["POST"]),
    Route("/api/task", api_task),
    Route("/api/browse", api_browse),
    Route("/api/sources", api_sources),
]


def build_app() -> Starlette:
    app = Starlette(routes=routes)
    app.add_middleware(NoStoreMiddleware)
    app.mount("/static", StaticFiles(directory=str(_TEMPLATES.parent / "static")),
              name="static")
    return app


class NoStoreMiddleware:
    """Cache-Control: no-store on everything.

    A localhost single-user tool must never serve a stale UI: heuristic
    browser caching of dashboard.js once made a fix look broken for a whole
    session, and a cached old page referencing a since-deleted script blanked
    the entire dashboard. Bandwidth is free here; staleness is not.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, receive, send_wrapper)


def serve(case_file: str | None = None, port: int = 8760):
    import uvicorn
    print(f"vrpatch serve: http://127.0.0.1:{port}/")
    print(f"  sources/: {sources_dir()}   cases/: {cases_dir()}")
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning")
