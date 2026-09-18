"""Local web picker: starlette + jinja2, server-rendered, zero npm.

Interaction model (frozen decision #2 + plan Phase 7):
- clicking the ERP preview posts the picked yaw/pitch (server recomputes and
  re-renders);
- the inner rect is dragged on the viewport preview *client-side* (a plain
  div overlay, no canvas), and only the release POSTs the final rect.
"""

from __future__ import annotations

from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, FileResponse, RedirectResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from ..case import load_case
from . import render
from .render import PreviewStore

_TEMPLATES = Path(__file__).parent / "templates"
_STATIC = Path(__file__).parent / "static"


def _store(request) -> PreviewStore:
    return request.app.state.store


async def index(request):
    store = _store(request)
    case = load_case(store.case_path, verify=False)
    html = (_TEMPLATES / "index.html").read_text(encoding="utf-8")
    vp = case.viewport
    inner = case.inner
    body = (
        html.replace("__CASE__", case.name)
            .replace("__ERP__", f"/img/{store.erp_png().name}?k={store.key}")
            .replace("__VP__", f"/img/{store.viewport_png().name}?k={store.key}")
            .replace("__YAW__", str(vp.yaw_deg)).replace("__PITCH__", str(vp.pitch_deg))
            .replace("__FOV__", str(vp.fov_h_deg))
            .replace("__IN__", f"{inner.x},{inner.y},{inner.width},{inner.height}")
            .replace("__MSGS__", request.query_params.get("msg", ""))
    )
    return HTMLResponse(body)


async def img(request):
    store = _store(request)
    name = request.path_params["name"]
    p = store.dir / name
    if not p.is_file() or p.parent != store.dir:
        return HTMLResponse("not found", status_code=404)
    return FileResponse(p)


async def pick_erp(request):
    form = await request.form()
    store = _store(request)
    store.set_viewport_from_erp_click(float(form["fx"]), float(form["fy"]))
    return RedirectResponse("/", 303)


async def pick_inner(request):
    form = await request.form()
    store = _store(request)
    # JS posts coords in preview pixels; scale back to viewport space
    scale = min(render.VIEWPORT_PREVIEW_W / store.case.viewport.width, 1.0)
    x, y, w, h = (int(float(v) / scale) for v in
                  (form["x"], form["y"], form["w"], form["h"]))
    if w > 0 and h > 0:
        store.set_inner(x, y, w, h)
    return RedirectResponse("/", 303)


def serve(case_file: str, port: int = 8760):
    app = Starlette(routes=[
        Route("/", index),
        Route("/img/{name}", img),
        Route("/pick/erp", pick_erp, methods=["POST"]),
        Route("/pick/inner", pick_inner, methods=["POST"]),
    ])
    app.state.store = PreviewStore(case_file)
    _STATIC.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
    print(f"vrpatch pick: http://127.0.0.1:{port}/  ({case_file})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
