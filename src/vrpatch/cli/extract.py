"""vrpatch-extract: ERP video -> viewport clip + sidecar + inner mask.

The mask is part of the extract contract (black = region the external AI tool
regenerates, white = fixed anchor margin); test_extract_contract enforces it.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import typer

from ..case import Case, load_case, case_to_sidecar, save_sidecar_for_case
from ..sidecar import Sidecar, Segment, Viewport, InnerRect, save_sidecar
from ..extract import extract_segment, write_clip, make_mask_image

app = typer.Typer(add_completion=False, help=__doc__)


def _extract(frames, fps, seg: Segment, clip_path: Path, sidecar_path: Path,
             mask_path: Path, erp_size: tuple[int, int]):
    clip = extract_segment(frames, seg)
    write_clip(clip, str(clip_path), fps)
    mask = make_mask_image(seg.viewport, seg.inner)
    cv2.imwrite(str(mask_path), mask)
    sc = Sidecar(erp_width=erp_size[0], erp_height=erp_size[1], fps=fps,
                 segments=[seg])
    save_sidecar(sc, sidecar_path)
    typer.echo(f"clip     -> {clip_path} ({clip.shape[0]} frames)")
    typer.echo(f"sidecar  -> {sidecar_path}")
    typer.echo(f"mask     -> {mask_path} (black=regenerate, white=anchor)")


@app.command("case")
def from_case(
    case_file: Path = typer.Argument(..., exists=True, help="case.toml path"),
    out_dir: Path = typer.Option(None, help="default: <case dir>/derived"),
):
    """Extract using a case.toml (verifies the source hash first)."""
    case: Case = load_case(case_file)  # raises on hash mismatch
    out = out_dir or (case_file.parent / "derived")
    out.mkdir(parents=True, exist_ok=True)
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
    # stream the frame range rather than loading the whole ERP video
    frames = []
    cap.set(cv2.CAP_PROP_POS_FRAMES, case.frame_start)
    for _ in range(case.frame_end - case.frame_start + 1):
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    _extract(frames, fps, seg, out / "clip.mp4", out / "clip.json",
             out / "clip_mask.png",
             (case.erp_width, case.erp_height))


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
    cap = cv2.VideoCapture(str(input_video))
    if not cap.isOpened():
        raise typer.Exit(f"cannot open video: {input_video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    erp_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    erp_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames = []
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    for _ in range(end - start + 1):
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    _extract(frames, fps, seg, clip, sidecar,
             mask or clip.with_name(clip.stem + "_mask.png"), (erp_w, erp_h))


if __name__ == "__main__":
    app()
