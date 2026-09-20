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

from ..case import (load_case, set_ai_clip, extract_version, ai_clip_pairing)
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

def _case_info(name: str) -> dict | None:
    cp = case_path(name)
    if cp is None:
        return None
    c = load_case(cp, verify=False)
    derived = cp.parent / "derived"
    ai = c.ai_clip
    ev = extract_version(cp)
    pairing = ai_clip_pairing(cp)
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
        "ai_clip": ai,
        "ai_clip_exists": bool(ai) and Path(ai).is_file(),
        "merged": any(derived.glob("out*.mp4")),
        "derived": str(derived),
        "previews": preview_urls(name),
    }
    if ev:
        info["extract"] = {**ev, "dir": str(cp.parent / "extracts" / ev["version"])}
    if pairing:
        matched = (bool(ev) and pairing.get("geometry_sha256") == ev["geometry_sha256"])
        info["pairing"] = {**pairing, "geometry_matches": matched}
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
    name = request.path_params["name"]
    cp = case_path(name)
    if cp is None:
        return JSONResponse({"error": "no such case"}, status_code=404)
    body = await request.json()
    p = Path(body.get("path", ""))
    if not p.is_file():
        return JSONResponse({"error": f"not a file: {p}"}, status_code=400)
    # Pair with the recorded extract version: this ai_clip was redrawn from
    # THAT geometry, and merge will use it regardless of later draft edits.
    ev = extract_version(cp)
    if ev is None:
        return JSONResponse({"error": "run extract before registering an AI clip"},
                            status_code=400)
    set_ai_clip(cp, str(p), extract_version=ev["version"],
                geometry_sha256=ev["geometry_sha256"])
    _stores.pop(name, None)  # case.toml changed behind the store's back
    return JSONResponse(_case_info(name))


async def api_merge(request):
    name = request.path_params["name"]
    cp = case_path(name)
    if cp is None:
        return JSONResponse({"error": "no such case"}, status_code=404)
    c = load_case(cp, verify=False)
    pairing = ai_clip_pairing(cp)
    if not pairing or not Path(pairing["path"]).is_file():
        return JSONResponse({"error": "register the AI clip first"}, status_code=400)
    ev = extract_version(cp)
    if not ev:
        return JSONResponse({"error": "no recorded extract"}, status_code=400)
    if pairing["geometry_sha256"] != ev["geometry_sha256"]:
        return JSONResponse(
            {"error": "the registered AI clip belongs to an older extract; "
                      "re-register it after extracting (or re-extract)"},
            status_code=409)
    vdir = cp.parent / "extracts" / ev["version"]
    sidecar = vdir / "clip.json"
    if not sidecar.is_file():
        return JSONResponse({"error": f"extract version {ev['version']} is missing "
                                      f"its clip.json"}, status_code=400)
    out = cp.parent / "derived" / "out.mp4"
    argv = [sys_executable(), "-m", "vrpatch.cli.merge",
            "--input", str((cp.parent / c.source.path).resolve()),
            "--ai", pairing["path"], "--sidecar", str(sidecar),
            "--output", str(out),
            "--expect-geometry-sha256", pairing["geometry_sha256"]]
    QUEUE.submit("merge", name, argv)
    return JSONResponse({"submitted": "merge", "case": name})


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
    Route("/api/case/{name}/extract", api_extract, methods=["POST"]),
    Route("/api/case/{name}/ai-clip", api_ai_clip, methods=["POST"]),
    Route("/api/case/{name}/merge", api_merge, methods=["POST"]),
    Route("/api/task", api_task),
    Route("/api/browse", api_browse),
    Route("/api/sources", api_sources),
]


def build_app() -> Starlette:
    app = Starlette(routes=routes)
    app.mount("/static", StaticFiles(directory=str(_TEMPLATES.parent / "static")),
              name="static")
    return app


def serve(case_file: str | None = None, port: int = 8760):
    import uvicorn
    print(f"vrpatch serve: http://127.0.0.1:{port}/")
    print(f"  sources/: {sources_dir()}   cases/: {cases_dir()}")
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning")
