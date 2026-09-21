"""Server-side image rendering for the picker's viewport pane.

The ERP pane needs no server rendering at all: the dashboard scrubs the
source video in a native <video> element (browser decode, zero files). Only
the viewport preview is a reprojection, so it stays server-side (projection
math has one authority). Decoded 4K ERP frames are kept in a small in-RAM LRU
(geometry-independent, survives viewport moves); the reprojected JPEG cache
under derived/pick/vpframes/ is bounded by the source frame count. Nothing is
decoded at store construction — every case.toml write rebuilds the store, and
eager decoding used to burn ~0.5s per geometry edit.

The preview response is composed in memory (no shared file to rewrite under a
streaming reader — that once produced torn downloads). derived/pick/ itself
is a *regenerable cache*: safe to delete at any time; each render drops
leftovers from older schemes.
"""

from __future__ import annotations

import hashlib
import shutil
import threading
from pathlib import Path

import cv2
import numpy as np

from ..case import load_case
from ..projection import erp_to_rect

VIEWPORT_PREVIEW_W = 960  # viewport preview cap
MEDIUM_W = 4096        # cached working copy of the source frame
FRAME_JPEG_Q = 85      # per-frame viewport cache quality
ERP_MEDIUM_LRU = 8     # decoded 4K ERP frames kept in RAM (8 * ~25MB ≈ 200MB)


def _read_frame(video: str, index: int) -> np.ndarray:
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"cannot read frame {index} from {video}")
    return frame


class PreviewStore:

    def __init__(self, case_path: str):
        self.case_path = Path(case_path)
        self.case = load_case(self.case_path)
        self.dir = self.case_path.parent / "derived" / "pick"
        self.dir.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(self._video())
        self.frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        self.key = self._new_key()
        # memoized (geometry, frame) -> preview PNG bytes; the response never
        # touches a shared file (see viewport_png)
        self._vp_bytes: tuple | None = None
        # LRU of decoded 4K ERP frames. Deliberately NOT filled here: the
        # dashboard almost always asks for frame=N, and every case.toml write
        # rebuilds this store — eagerly decoding 8K frame 0 used to cost ~0.5s
        # of wasted CPU per geometry edit (nudge click).
        self._erp_lru: dict[int, np.ndarray] = {}

    def _medium_of(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if w > MEDIUM_W:
            return cv2.resize(frame, (MEDIUM_W, round(h * MEDIUM_W / w)),
                              interpolation=cv2.INTER_AREA)
        return frame

    def _erp_medium(self, frame: int) -> np.ndarray:
        """Decoded 4K ERP frame, LRU-cached in RAM. Geometry-independent, so
        it survives viewport moves: after a nudge, reprojecting any LRU-hit
        frame costs ~50ms instead of an 8K re-seek (~1s)."""
        med = self._erp_lru.get(frame)
        if med is not None:
            self._erp_lru.pop(frame)           # re-insert at the end: LRU touch
            self._erp_lru[frame] = med
            return med
        med = self._medium_of(_read_frame(self._video(), frame))
        self._erp_lru[frame] = med
        while len(self._erp_lru) > ERP_MEDIUM_LRU:
            self._erp_lru.pop(next(iter(self._erp_lru)))   # evict oldest
        return med

    def _video(self) -> str:
        p = Path(self.case.source.path)
        return str(p if p.is_absolute() else self.case_path.parent / p)

    def _new_key(self) -> str:
        return hashlib.sha1(
            f"{self.case.viewport}|{self.case.inner}".encode()).hexdigest()[:10]

    def _vp_geo_key(self) -> str:
        """Viewport geometry only (inner excluded on purpose: dragging the
        inner rect must not invalidate the per-frame reprojection cache)."""
        return hashlib.sha1(str(self.case.viewport).encode()).hexdigest()[:10]

    def touch(self):
        """Invalidate after a geometry mutation that bypassed set_viewport/
        set_inner (e.g. the joystick nudge), so the next preview URL changes."""
        self.key = self._new_key()

    # ---- previews (cheap: overlay on cached bases) ---------------------------

    def viewport_png(self, frame: int | None = None) -> bytes:
        """PNG bytes of the viewport preview: the frame reprojection with the
        inner overlay drawn on. Composed in memory and memoized by (geometry,
        frame) — a shared vp.png file got rewritten under concurrent responses
        and served torn downloads. frame=None reprojects the startup frame
        (frame 0); frame=N goes through the vpframes/ JPEG cache, decoding
        that source frame (~1s on 8K) only on a cold LRU."""
        stamp = (self.key, frame)
        if self._vp_bytes and self._vp_bytes[0] == stamp:
            return self._vp_bytes[1]
        if frame is None:
            view = self._reproject(self._erp_medium(0))
        else:
            cached = self.viewport_frame_path(frame)
            view = cv2.imread(str(cached))
            if view is None:
                raise RuntimeError(f"frame cache unreadable: {cached}")
        self._draw_inner(view)
        ok, buf = cv2.imencode(".png", view)
        if not ok:
            raise RuntimeError("viewport preview PNG encode failed")
        data = buf.tobytes()
        self._vp_bytes = (stamp, data)
        self._gc()
        return data

    def viewport_frame_path(self, frame: int) -> Path:
        """Clean reprojection of one source frame (NO overlay: geometry moves
        must not invalidate these). Bounded by the frame count; invalidated
        per viewport geometry via the vpframes/<geo key>/ layout. Written
        once, atomically (unique temp name + replace), so a concurrent reader
        never sees a half-written JPEG."""
        if not 0 <= frame < self.frame_count:
            raise ValueError(f"frame {frame} out of range 0..{self.frame_count - 1}")
        d = self.dir / "vpframes" / self._vp_geo_key()
        out = d / f"vp_{frame:06d}.jpg"
        if not out.exists():
            view = self._reproject(self._erp_medium(frame))
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / f"{out.stem}.{threading.get_ident()}.tmp.jpg"
            cv2.imwrite(str(tmp), view, [cv2.IMWRITE_JPEG_QUALITY, FRAME_JPEG_Q])
            tmp.replace(out)
        return out

    def _reproject(self, med: np.ndarray) -> np.ndarray:
        vp = self.case.viewport
        scale = min(VIEWPORT_PREVIEW_W / vp.width, 1.0)
        vw, vh = int(round(vp.width * scale)), int(round(vp.height * scale))
        return erp_to_rect(med, np.radians(vp.yaw_deg),
                           np.radians(vp.pitch_deg),
                           np.radians(vp.fov_h_deg), vw, vh)

    def _draw_inner(self, view: np.ndarray):
        vp = self.case.viewport
        scale = min(VIEWPORT_PREVIEW_W / vp.width, 1.0)
        inner = self.case.inner
        cv2.rectangle(view,
                      (int(inner.x * scale), int(inner.y * scale)),
                      (int((inner.x + inner.width) * scale),
                       int((inner.y + inner.height) * scale)),
                      (0, 0, 255), 2)

    def _gc(self):
        """Keep derived/pick bounded: this directory is a regenerable cache,
        so anything in the preview namespace we did not just write is deleted
        — leftovers from the older content-keyed / fixed-name schemes, temp
        files, and vpframes dirs of older viewport geometries."""
        for legacy in (*self.dir.glob("erp_*.png"), *self.dir.glob("vp_*.png"),
                       *self.dir.glob("*.tmp"), *self.dir.glob("*.tmp.jpg")):
            legacy.unlink(missing_ok=True)
        for name in ("erp.png", "vp.png"):   # removed fixed-name previews
            (self.dir / name).unlink(missing_ok=True)
        vpf = self.dir / "vpframes"
        if vpf.is_dir():
            for d in vpf.iterdir():
                if d.is_dir() and d.name != self._vp_geo_key():
                    shutil.rmtree(d, ignore_errors=True)
                elif d.is_file() and d.name.endswith(".tmp.jpg"):
                    d.unlink(missing_ok=True)

    # ---- state updates -------------------------------------------------------

    def set_viewport_from_erp_click(self, fx: float, fy: float):
        """fx, fy in [0,1) of the ERP preview -> viewport yaw/pitch."""
        lam = (fx - 0.5) * 360.0
        phi = (0.5 - fy) * 180.0
        self.case.viewport.yaw_deg = round(lam, 1)
        self.case.viewport.pitch_deg = round(max(-89.0, min(89.0, phi)), 1)
        self._refresh()

    def set_inner(self, x: int, y: int, w: int, h: int):
        self.case.inner = type(self.case.inner)(x=x, y=y, width=w, height=h)
        self._refresh()

    def _refresh(self):
        self.key = self._new_key()
        self.save()

    def save(self):
        """Write viewport/inner back into case.toml (textual, section-scoped)."""
        p = self.case_path
        lines = p.read_text(encoding="utf-8").splitlines()
        section = None
        want = {"viewport": {"yaw_deg", "pitch_deg", "fov_h_deg"},
                "inner": {"x", "y", "width", "height"}}
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                section = s[1:-1]
                continue
            if "=" not in s or section not in want:
                continue
            key = s.split("=")[0].strip()
            if key not in want[section]:
                continue
            val = getattr(self.case,
                          "viewport" if section == "viewport" else "inner")
            lines[i] = f"{key} = {getattr(val, key)}"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
