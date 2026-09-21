"""Server-side image rendering for the picker: no client-side canvas needed.

Resolution policy (review fix): picking only needs to see *where* the viewport
and inner rect sit, so nothing here touches the full 8K frame after startup.
The source frame is decoded once and kept at MEDIUM_W (4K); the ERP preview is
a 1024-wide downscale of that, and the viewport preview is a proportional
reprojection from the medium ERP (geometry scales linearly, so this is the
same picture at reduced resolution). A refresh redraws overlays on these
cached bases — milliseconds, not seconds.

Previews are written under <case dir>/derived/pick/ under two fixed names
(erp.png / vp.png). The directory is a *regenerable cache*: safe to delete at
any time, and kept bounded — each render drops leftover files from older
schemes (content-keyed names) and stale viewport-geometry cache dirs, so the
directory never grows beyond the fixed previews plus the per-frame viewport
JPEGs, which are bounded by the source frame count and invalidated (then
GC'd) whenever the viewport geometry moves.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import cv2
import numpy as np

from ..case import load_case
from ..projection import (_direction_to_erp_px, camera_rotation, erp_to_rect)

ERP_PREVIEW_W = 1024   # ERP preview (2:1)
VIEWPORT_PREVIEW_W = 960  # viewport preview cap
MEDIUM_W = 4096        # cached working copy of the source frame
FRAME_JPEG_Q = 85      # per-frame viewport cache quality


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
        video = self._video()
        cap = cv2.VideoCapture(video)
        self.frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        self._frame = _read_frame(video, 0)
        self._med = self._medium_of(self._frame)
        self.med_w = self._med.shape[1]
        self.med_h = self._med.shape[0]
        self._erp_small = cv2.resize(self._med, (ERP_PREVIEW_W, ERP_PREVIEW_W // 2),
                                     interpolation=cv2.INTER_AREA)
        self.key = self._new_key()
        # output name -> content key the file on disk was drawn for; fixed
        # filenames are safe because re-render is keyed on this, not on
        # file existence (which would serve a stale picture after a move)
        self._rendered: dict[str, str] = {}

    def _medium_of(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if w > MEDIUM_W:
            return cv2.resize(frame, (MEDIUM_W, round(h * MEDIUM_W / w)),
                              interpolation=cv2.INTER_AREA)
        return frame

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

    def erp_png(self) -> Path:
        out = self.dir / "erp.png"
        self._render("erp", out, self._draw_erp)
        return out

    def viewport_png(self, frame: int | None = None) -> Path:
        """Viewport preview with the inner overlay. frame=None reprojects from
        the cached startup frame (fast default); frame=N decodes that source
        frame (~0.5s on 8K) through the reprojection cache in vpframes/."""
        out = self.dir / "vp.png"
        stamp = (self.key, frame)
        if out.exists() and self._rendered.get("vp") == stamp:
            return out
        if frame is None:
            view = self._reproject(self._med)
        else:
            cached = self.viewport_frame_path(frame)
            view = cv2.imread(str(cached))
            if view is None:
                raise RuntimeError(f"frame cache unreadable: {cached}")
        self._draw_inner(view)
        cv2.imwrite(str(out), view)
        self._rendered["vp"] = stamp
        self._gc()
        return out

    def viewport_frame_path(self, frame: int) -> Path:
        """Clean reprojection of one source frame (NO overlay: geometry moves
        must not invalidate these). Bounded by the frame count; invalidated
        per viewport geometry via the vpframes/<geo key>/ layout."""
        if not 0 <= frame < self.frame_count:
            raise ValueError(f"frame {frame} out of range 0..{self.frame_count - 1}")
        d = self.dir / "vpframes" / self._vp_geo_key()
        out = d / f"vp_{frame:06d}.jpg"
        if not out.exists():
            view = self._reproject(self._medium_of(_read_frame(self._video(), frame)))
            d.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out), view, [cv2.IMWRITE_JPEG_QUALITY, FRAME_JPEG_Q])
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

    def _render(self, name: str, out: Path, draw) -> None:
        if out.exists() and self._rendered.get(name) == self.key:
            return
        draw(out)
        self._rendered[name] = self.key
        self._gc()

    def _draw_erp(self, out: Path):
        small = self._erp_small.copy()
        w, h = small.shape[1], small.shape[0]
        d = camera_rotation(np.radians(self.case.viewport.yaw_deg),
                            np.radians(self.case.viewport.pitch_deg))[:, 2]
        px, py = _direction_to_erp_px(d[None, :], w, h)
        cx, cy = int(round(px[0])), int(round(py[0]))
        cv2.drawMarker(small, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 24, 2)
        # rough viewport footprint: fov as fraction of 360, 16:9-ish aspect
        fw = int(w * self.case.viewport.fov_h_deg / 360.0)
        fh = int(fw * self.case.viewport.height / self.case.viewport.width)
        cv2.rectangle(small, (cx - fw // 2, cy - fh // 2),
                      (cx + fw // 2, cy + fh // 2), (0, 255, 0), 1)
        cv2.imwrite(str(out), small)

    def _gc(self):
        """Keep derived/pick bounded: this directory is a regenerable cache,
        so anything in the preview namespace we did not just write is deleted
        — leftovers from the older content-keyed names, and vpframes dirs of
        older viewport geometries."""
        for legacy in (*self.dir.glob("erp_*.png"), *self.dir.glob("vp_*.png")):
            legacy.unlink(missing_ok=True)
        vpf = self.dir / "vpframes"
        if vpf.is_dir():
            for d in vpf.iterdir():
                if d.is_dir() and d.name != self._vp_geo_key():
                    shutil.rmtree(d, ignore_errors=True)

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
