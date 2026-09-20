"""vrpatch-extract: ERP video -> viewport clip + sidecar + inner mask.

Streaming: one 8K source frame (~96 MB) is decoded, projected and written at a
time — never load the frame range into a list (590 frames would be ~55 GB and
thrash the machine; that was tried once and is why this module looks the way it
does). The mask is part of the extract contract (black = region the external AI
tool regenerates, white = fixed anchor margin); test_extract_contract enforces
it.

Every run mirrors its console output to logs/<name>_<timestamp>.log.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import cv2
import numpy as np
import typer

from ..case import Case, load_case, set_extract_version
from ..sidecar import Sidecar, Segment, Viewport, InnerRect, save_sidecar
from ..extract import extract_viewport_frame, open_writer, make_mask_image
from ..progress import Log, RateMeter, open_log_file

app = typer.Typer(add_completion=False, help=__doc__)


def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _stream_extract(cap, fps, seg: Segment, clip_path: Path, sidecar_path: Path,
                    mask_path: Path, erp_size: tuple[int, int], log: Log):
    n = seg.frame_end - seg.frame_start + 1
    meter = RateMeter(n)
    writer = open_writer(str(clip_path), fps, (seg.viewport.width, seg.viewport.height))
    written = 0
    for _ in range(n):
        ok, frame = cap.read()
        if not ok:
            log.info(f"source ended early at frame {written} of {n}")
            break
        writer.write(extract_viewport_frame(frame, seg.viewport))
        written += 1
        meter.tick()
        log.progress(meter, "extracting")
    writer.release()

    mask = make_mask_image(seg.viewport, seg.inner)
    cv2.imwrite(str(mask_path), mask)
    sc = Sidecar(erp_width=erp_size[0], erp_height=erp_size[1], fps=fps,
                 segments=[seg])
    save_sidecar(sc, sidecar_path)
    log.phase(f"clip    -> {clip_path} ({written} frames)")
    log.phase(f"sidecar -> {sidecar_path}")
    log.phase(f"mask    -> {mask_path} (black=regenerate, white=anchor)")


@app.command("case")
def from_case(
    case_file: Path = typer.Argument(..., exists=True, help="case.toml path"),
    out_dir: Path = typer.Option(None, help="default: <case dir>/derived"),
):
    """Extract using a case.toml (verifies the source hash first)."""
    case: Case = load_case(case_file)  # raises on hash mismatch
    out = out_dir or (case_file.parent / "derived")
    out.mkdir(parents=True, exist_ok=True)
    fh, log_path = open_log_file(f"extract_{case.name}")
    log = Log(fh=fh)
    try:
        log.phase(f"case: {case_file} (source sha256 verified)")
        src = case.source.path
        if not Path(src).is_absolute():
            src = str(case_file.parent / src)
        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            raise typer.Exit(f"cannot open video: {src}")
        fps = cap.get(cv2.CAP_PROP_FPS) or case.fps
        seg = Segment(id="seg_0", frame_start=case.frame_start,
                      frame_end=case.frame_end, viewport=case.viewport,
                      inner=case.inner)
        if not cap.set(cv2.CAP_PROP_POS_FRAMES, case.frame_start):
            log.info("WARNING: could not seek; decoding from the start instead.")
        # Versioned snapshot (workflow decision: picking is a draft; extract
        # records). Immutable per run; derived/ mirrors the latest version so
        # plain `vrpatch-merge ... --sidecar derived/clip.json` keeps working.
        version = time.strftime("%Y%m%d-%H%M%S")
        vdir = case_file.parent / "extracts" / version
        vdir.mkdir(parents=True, exist_ok=True)
        _stream_extract(cap, fps, seg, vdir / "clip.mp4", vdir / "clip.json",
                        vdir / "clip_mask.png",
                        (case.erp_width, case.erp_height), log)
        cap.release()
        geometry_sha = _sha256_file(vdir / "clip.json")
        set_extract_version(case_file, version, geometry_sha)
        derived = case_file.parent / "derived"
        derived.mkdir(parents=True, exist_ok=True)
        for f in ("clip.mp4", "clip.json", "clip_mask.png"):
            shutil.copyfile(vdir / f, derived / f)
        log.phase(f"extract version: {version} (geometry sha {geometry_sha[:12]}…)")
        log.phase(f"log -> {log_path}")
    finally:
        fh.close()


@app.command("args")
def from_args(
    input_video: Path = typer.Option(..., help="source ERP (360) video"),
    clip: Path = typer.Option(...),
    sidecar: Path = typer.Option(...),
    start: int = typer.Option(0),
    end: int = typer.Option(..., help="inclusive frame index"),
    yaw: float = typer.Option(..., help="deg"),
    pitch: float = typer.Option(..., help="deg"),
    fov: float = typer.Option(..., help="horizontal FOV deg"),
    vpw: int = typer.Option(..., help="viewport width px"),
    vph: int = typer.Option(..., help="viewport height px"),
    inner: str = typer.Option(..., help="X,Y,W,H"),
    mask: Path = typer.Option(None, help="default: <clip stem>_mask.png"),
):
    """Extract with explicit arguments (no case.toml needed)."""
    ix, iy, iw, ih = (int(v) for v in inner.split(","))
    seg = Segment(id="seg_0", frame_start=start, frame_end=end,
                  viewport=Viewport(yaw_deg=yaw, pitch_deg=pitch,
                                    fov_h_deg=fov, width=vpw, height=vph),
                  inner=InnerRect(x=ix, y=iy, width=iw, height=ih))
    fh, log_path = open_log_file(f"extract_{input_video.stem}")
    log = Log(fh=fh)
    try:
        log.phase(f"input: {input_video}")
        cap = cv2.VideoCapture(str(input_video))
        if not cap.isOpened():
            raise typer.Exit(f"cannot open video: {input_video}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        erp_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        erp_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not cap.set(cv2.CAP_PROP_POS_FRAMES, start):
            log.info("WARNING: could not seek; decoding from the start instead.")
        _stream_extract(cap, fps, seg, clip, sidecar,
                        mask or clip.with_name(clip.stem + "_mask.png"),
                        (erp_w, erp_h), log)
        cap.release()
        log.phase(f"log -> {log_path}")
    finally:
        fh.close()


if __name__ == "__main__":
    app()
