"""Detect and correct the global scale/shift the external AI tool's spatial
pipeline imprints on the viewport clip.

The AI tool re-renders the clip through its own working resolution and often
hands back a picture that is slightly (anisotropically) scaled and shifted.
Left uncorrected, that mismatch shows up as ghosting along the blend seam at
merge. The transform is a property of the tool's pipeline, not of the scene:
measured per frame it is constant to ~0.1 px across the whole clip, so one
fit per AI clip is enough.

Measurement region: the ring OUTSIDE the inner rect. The inner is the region
merge replaces with AI content (where the redraw lives), so template matches
inside it are polluted by regenerated content; the ring is background the
tool tends to reproduce faithfully. That fidelity is an empirical property of
these tools, NOT a contract -- the mask never reaches the external tool -- so
every fit carries two confidence numbers (ring correlation, inner static-patch
residual) and merge refuses to apply a fit whose ring correlation is low.
See .claude/memory/inner-is-merge-only.md.

Direction convention (verified against a known injected warp on real footage):
cv2.findTransformECC returns the template->input map, so the correction to
apply on AI frames is its inverse, fed to cv2.warpAffine as a plain forward
map (no WARP_INVERSE_MAP).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np

RING_FEATHER = 24     # exclude the mask transition band around the inner rect
RING_BORDER = 24      # exclude the frame border (edge artifacts)
RING_NCC_MIN = 0.90   # below this ring correlation the fit is not trusted
SCALE_EPS = 0.002     # |s - 1| at or below this counts as "no scale"
SHIFT_EPS = 0.5       # px of translation at or below this counts as "none"
ECC_CRITERIA = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-7)
CACHE_VERSION = 1

# inner-validation sampling (robustness check on the region merge pastes)
VAL_PATCH = 96
VAL_WIN = 40
VAL_N = 60
VAL_NCC_MIN = 0.70


@dataclass
class ScaleFit:
    """Global correction for one AI clip: warp AI frames by `matrix` (2x3,
    AI -> clip, plain forward warpAffine) before compositing."""

    matrix: list        # [[a, b, tx], [c, d, ty]]
    sx: float
    sy: float
    rot_deg: float
    tx: float
    ty: float
    ring_ncc: float
    inner_median_px: float
    identity: bool
    reason: str         # ok | identity | low_ring_ncc | off
    frames: list
    source: str         # fresh | cache | file

    @property
    def applied(self) -> bool:
        return self.reason == "ok"

    def to_dict(self) -> dict:
        return asdict(self)

    def matrix32(self) -> np.ndarray:
        return np.float32(self.matrix)


def ring_mask(w: int, h: int, inner) -> np.ndarray:
    """255 where measurement is allowed: outside inner (+feather, the blend
    transition band) and inside the frame (-border)."""
    m = np.full((h, w), 255, np.uint8)
    x0 = max(0, inner.x - RING_FEATHER); x1 = min(w, inner.x + inner.width + RING_FEATHER)
    y0 = max(0, inner.y - RING_FEATHER); y1 = min(h, inner.y + inner.height + RING_FEATHER)
    m[y0:y1, x0:x1] = 0
    m[:RING_BORDER, :] = 0; m[-RING_BORDER:, :] = 0
    m[:, :RING_BORDER] = 0; m[:, -RING_BORDER:] = 0
    return m


def decompose(m) -> tuple:
    """Affine -> (sx, sy, rot_deg, tx, ty). Column norms give per-axis scale."""
    sx = float(np.hypot(m[0, 0], m[1, 0]))
    sy = float(np.hypot(m[0, 1], m[1, 1]))
    rot = float(np.degrees(np.arctan2(m[1, 0], m[0, 0])))
    return sx, sy, rot, float(m[0, 2]), float(m[1, 2])


def recompose(sx: float, sy: float, rot_deg: float, tx: float, ty: float) -> list:
    th = np.radians(rot_deg)
    return [[float(sx * np.cos(th)), float(-sy * np.sin(th)), float(tx)],
            [float(sx * np.sin(th)), float(sy * np.cos(th)), float(ty)]]


def _ecc_once(tpl, inp, mask, init=None):
    warp = np.eye(2, 3, dtype=np.float32) if init is None else np.float32(init)
    try:
        _, warp = cv2.findTransformECC(tpl, inp, warp, cv2.MOTION_AFFINE,
                                       ECC_CRITERIA, mask, 5)
        return warp
    except cv2.error:
        return None


def _correction(g_clip, g_ai, mask):
    """Ring-masked ECC, coarse-to-fine. Returns the AI->clip correction
    matrix (inverse of what findTransformECC reports), or None."""
    h, w = g_clip.shape
    W = None
    if max(h, w) > 960:  # coarse level first: robustness for larger errors
        f = 0.5
        small = cv2.resize(g_clip, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        sai = cv2.resize(g_ai, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        smask = cv2.resize(mask, None, fx=f, fy=f, interpolation=cv2.INTER_NEAREST)
        Ws = _ecc_once(small, sai, smask)
        if Ws is not None:
            init = Ws.astype(np.float64)
            init[:, 2] *= 2.0
            W = _ecc_once(g_clip, g_ai, mask, init)
    else:
        W = _ecc_once(g_clip, g_ai, mask)
    if W is None:
        return None
    return np.linalg.inv(np.vstack([W, [0, 0, 1]]))[:2]


def _ncc(a, b, mask) -> float:
    av = a[mask > 0].astype(np.float32); bv = b[mask > 0].astype(np.float32)
    av -= av.mean(); bv -= bv.mean()
    d = float(np.linalg.norm(av) * np.linalg.norm(bv))
    return float((av * bv).sum() / d) if d > 0 else 0.0


def _inner_residual(g_clip, g_ai_warped, inner, rng) -> float:
    """Median displacement of strict static patches inside the inner rect,
    measured AFTER correction. Content that the redraw genuinely changed is
    filtered by NCC; the median survives the rest (regenerative drift)."""
    h, w = g_clip.shape
    patch = max(16, min(VAL_PATCH, inner.width // 3, inner.height // 3))
    pts, disp = [], []
    for _ in range(400):
        if len(pts) >= VAL_N:
            break
        x = int(rng.integers(inner.x, inner.x + inner.width - patch))
        y = int(rng.integers(inner.y, inner.y + inner.height - patch))
        t = g_clip[y:y + patch, x:x + patch]
        if t.std() < 12:
            continue
        x0, y0 = max(0, x - VAL_WIN), max(0, y - VAL_WIN)
        sea = g_ai_warped[y0:y + patch + VAL_WIN, x0:x + patch + VAL_WIN]
        r = cv2.matchTemplate(sea, t, cv2.TM_CCOEFF_NORMED)
        _, peak, _, loc = cv2.minMaxLoc(r)
        if peak < VAL_NCC_MIN:
            continue
        pts.append(1.0)
        disp.append(np.hypot((x0 + loc[0]) - x, (y0 + loc[1]) - y))
    if not disp:
        return -1.0  # nothing static enough to check; caller reports as unknown
    return float(np.median(disp))


def fit_core(pairs, inner, size, ring_ncc_min: float = RING_NCC_MIN,
             seed: int = 7, frame_ids=None) -> ScaleFit:
    """pairs: iterable of (clip_gray, ai_gray), same size. Fits the global
    AI->clip correction by ring-masked ECC per pair and median-aggregates.
    frame_ids: optional indices of the sampled frames, for the report only."""
    w, h = size
    mask = ring_mask(w, h, inner)
    rng = np.random.default_rng(seed)

    comps, frames = [], []
    for g_clip, g_ai in pairs:
        if g_ai.shape != (h, w):
            g_ai = cv2.resize(g_ai, (w, h), interpolation=cv2.INTER_AREA)
        C = _correction(g_clip, g_ai, mask)
        if C is None:
            continue
        comps.append(decompose(C))
        frames.append(len(comps) - 1)
    if not comps:
        return ScaleFit(recompose(1, 1, 0, 0, 0), 1.0, 1.0, 0.0, 0.0, 0.0,
                        -1.0, -1.0, True, "low_ring_ncc", [], "fresh")

    med = [float(np.median(np.array(comps)[:, j])) for j in range(5)]
    sx, sy, rot, tx, ty = med
    M = np.float32(recompose(sx, sy, rot, tx, ty))

    # confidence 1: ring correlation after correction (median across pairs)
    ring_scores = []
    for g_clip, g_ai in pairs:
        g_w = cv2.warpAffine(g_ai, M, (w, h), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REFLECT)
        ring_scores.append(_ncc(g_clip, g_w, mask))
    ring = float(np.median(ring_scores))

    # confidence 2: static-patch residual inside the pasted region
    inner_med = _inner_residual(pairs[len(pairs) // 2][0],
                                cv2.warpAffine(pairs[len(pairs) // 2][1], M, (w, h),
                                               flags=cv2.INTER_LINEAR,
                                               borderMode=cv2.BORDER_REFLECT),
                                inner, rng)

    identity = (abs(sx - 1) <= SCALE_EPS and abs(sy - 1) <= SCALE_EPS
                and float(np.hypot(tx, ty)) <= SHIFT_EPS)
    reason = "identity" if identity else (
        "low_ring_ncc" if ring < ring_ncc_min else "ok")
    return ScaleFit(M.tolist(), sx, sy, rot, tx, ty, ring, inner_med,
                    identity, reason, frame_ids or list(range(len(comps))),
                    "fresh")


def fit_videos(clip_path, ai_path, inner, size, frame_start: int, n_seg: int,
               fractions=(0.10, 0.30, 0.50, 0.70, 0.90), log=None) -> ScaleFit:
    """Fit pairing frame i of the (aligned) AI clip with frame frame_start+i
    of the reference viewport clip -- the AI tool's own input, so the fitted
    transform isolates the tool's pipeline error. Both must be viewport-size;
    anything else (missing reference, wrong geometry) degrades to a
    non-applied fit: scale correction is an enhancement, never a crash."""
    def failed(reason):
        return ScaleFit(recompose(1, 1, 0, 0, 0), 1.0, 1.0, 0.0, 0.0, 0.0,
                        -1.0, -1.0, True, reason, [], "fresh")

    cap_c = cv2.VideoCapture(str(clip_path))
    cap_a = cv2.VideoCapture(str(ai_path))
    if not cap_c.isOpened() or not cap_a.isOpened():
        if log is not None:
            log.info(f"scale fit: WARNING cannot open reference pair "
                     f"({clip_path} / {ai_path}), skipping the correction")
        cap_c.release(); cap_a.release()
        return failed("no_reference")
    w, h = size
    cw = int(cap_c.get(cv2.CAP_PROP_FRAME_WIDTH))
    ch = int(cap_c.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if (cw, ch) != (w, h):
        if log is not None:
            log.info(f"scale fit: WARNING reference clip is {cw}x{ch}, "
                     f"expected {w}x{h} viewport geometry -- not a fit "
                     f"reference; skipping the correction")
        cap_c.release(); cap_a.release()
        return failed("bad_reference_geometry")

    n_ai = int(cap_a.get(cv2.CAP_PROP_FRAME_COUNT)) or n_seg
    n = min(n_ai, n_seg)
    idxs = sorted({min(n - 1, max(0, int(round(f * (n - 1))))) for f in fractions})

    def grab(cap, i):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        return cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY) if ok else None

    pairs = []
    for i in idxs:
        g_c = grab(cap_c, frame_start + i)
        g_a = grab(cap_a, i)
        if g_c is not None and g_a is not None:
            pairs.append((g_c, g_a))
    cap_c.release(); cap_a.release()
    return fit_core(pairs, inner, size, frame_ids=idxs)


# ---- cache: one json next to the AI clip, invalidated by its mtime/size ----

def cache_path(ai_path) -> Path:
    p = Path(ai_path)
    return p.with_name(p.stem + ".scalefit.json")


def save_cache(fit: ScaleFit, ai_path) -> None:
    p = Path(ai_path)
    st = p.stat()
    d = fit.to_dict() | {"ai_mtime": st.st_mtime, "ai_size": st.st_size,
                         "cache_version": CACHE_VERSION}
    cache_path(ai_path).write_text(json.dumps(d, indent=2), encoding="utf-8")


def _from_cache(d: dict, source: str) -> ScaleFit:
    return ScaleFit(d["matrix"], d["sx"], d["sy"], d["rot_deg"], d["tx"],
                    d["ty"], d["ring_ncc"], d["inner_median_px"],
                    d["identity"], d["reason"], d.get("frames", []), source)


def _cache_fresh(ai_path) -> bool:
    p = cache_path(ai_path)
    if not p.is_file():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    st = Path(ai_path).stat()
    return (d.get("cache_version") == CACHE_VERSION
            and d.get("ai_mtime") == st.st_mtime and d.get("ai_size") == st.st_size)


def load_cache_file(path) -> ScaleFit:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if "matrix" not in d:
        raise ValueError(f"not a scalefit json: {path}")
    return _from_cache(d, "file")


def resolve(clip_path, ai_path, inner, size, frame_start, n_seg, mode: str,
            log=None) -> ScaleFit:
    """mode: 'off' | 'auto' | path to a .scalefit.json. 'auto' fits (cached
    next to the AI clip, invalidated when the AI file changes). The returned
    fit says whether to apply: never apply when `applied` is False."""
    def info(msg):
        if log is not None:
            log.info(msg)

    if mode == "off":
        return ScaleFit(recompose(1, 1, 0, 0, 0), 1.0, 1.0, 0.0, 0.0, 0.0,
                        -1.0, -1.0, True, "off", [], "off")
    if mode != "auto":
        fit = load_cache_file(mode)
        info(f"scale fit: loaded from {mode}: sx={fit.sx:.5f} sy={fit.sy:.5f} "
             f"t=({fit.tx:+.2f},{fit.ty:+.2f}) rot={fit.rot_deg:+.3f}deg")
        return fit
    if _cache_fresh(ai_path):
        fit = _from_cache(json.loads(
            cache_path(ai_path).read_text(encoding="utf-8")), "cache")
        info(f"scale fit: cache hit {cache_path(ai_path).name} "
             f"(sx={fit.sx:.5f} sy={fit.sy:.5f}, reason={fit.reason})")
        return fit
    fit = fit_videos(clip_path, ai_path, inner, size, frame_start, n_seg,
                     log=log)
    save_cache(fit, ai_path)
    info(f"scale fit: fitted from {len(fit.frames)} frame pairs, cached -> "
         f"{cache_path(ai_path).name}")
    info(f"  correction sx={fit.sx:.5f} sy={fit.sy:.5f} rot={fit.rot_deg:+.3f}deg "
         f"t=({fit.tx:+.2f},{fit.ty:+.2f})  ring_ncc={fit.ring_ncc:.4f} "
         f"inner_residual={fit.inner_median_px:.2f}px  -> {fit.reason}")
    if not fit.identity and fit.reason == "low_ring_ncc":
        info("  WARNING: ring correlation too low, NOT applying the correction "
             "(the AI output does not track the source closely enough to trust "
             "a global fit)")
    return fit
