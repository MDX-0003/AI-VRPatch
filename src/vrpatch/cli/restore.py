"""vrpatch-restore: bring an external AI clip to the segment's exact time contract.

Runs the same pipeline merge's auto-restore uses (vrpatch.restore.restore_clip)
as a standalone command — useful to pre-warm the aligned artifact, to inspect
what merge would do, and to pick a non-default RIFE model. The target contract
(frame count + fps) comes from the paired extract's clip.json, never from the
raw AI clip or the current draft.

rife-ncnn-vulkan (Vulkan, no Python deps) is only needed when the clip is
short of frames (stretch); a mislabeled-fps or over-long clip just re-encodes.
"""

from __future__ import annotations

from pathlib import Path

import typer

from ..case import load_sidecar_single_segment
from ..progress import Log, open_log_file
from ..rife import DEFAULT_MODEL, RifeInterpolator, find_rife
from ..restore import (aligned_is_current, aligned_path_for, needs_restore,
                       probe_clip, restore_clip, restore_plan, sidecar_target)

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def restore(
    ai: Path = typer.Option(..., help="raw AI clip (any fps/frame count)"),
    sidecar: Path = typer.Option(..., help="clip.json of the paired extract"),
    output: Path = typer.Option(None, help="default: <ai stem>_aligned.mp4 next to it"),
    model: str = typer.Option(DEFAULT_MODEL, help="rife-ncnn-vulkan model dir name"),
    gpu: int = typer.Option(None, help="Vulkan device index (default: device 0)"),
    crf: int = typer.Option(14, help="x264 crf for the aligned intermediate"),
    preset: str = typer.Option("medium", help="x264 preset"),
    force: bool = typer.Option(False, help="re-run even if the contract is already met"),
    progress_every: int = typer.Option(0),
    quiet: bool = typer.Option(False, "-q"),
):
    seg = load_sidecar_single_segment(sidecar)  # R5 guard, loud
    n, fps = sidecar_target(sidecar)
    out = output or aligned_path_for(ai)

    fh, log_path = open_log_file(f"restore_{ai.stem}")
    log = Log(every=progress_every, quiet=quiet, fh=fh)
    typer.echo(f"log -> {log_path}")
    try:
        info = probe_clip(ai)
        log.phase(f"target  : {n} frames @ {fps:g}fps (sidecar {sidecar})")
        log.info(f"ai clip : {info.frames} frames @ {info.fps:g}fps, "
                 f"{info.width}x{info.height}")

        if not force and not needs_restore(info, n, fps):
            log.phase(f"already matches the contract; nothing to do "
                      f"(--force to re-run)")
            return
        if not force and aligned_is_current(out, ai, n, fps):
            log.phase(f"aligned clip is current: {out} (reusing; --force to re-run)")
            return

        interpolator = None
        if restore_plan(info, n) == "stretch":
            exe = find_rife()
            if not exe:
                raise typer.Exit(
                    f"rife-ncnn-vulkan not found (stretch needs it: {info.frames} "
                    f"-> {n} frames). Install the release zip under bin/ or set "
                    f"VRPATCH_RIFE.")
            log.info(f"interpolator: {exe} (model {model})")
            interpolator = RifeInterpolator(exe, model, gpu)

        restore_clip(ai, out, n, fps, interpolator=interpolator,
                     crf=crf, preset=preset, log=log)
    finally:
        fh.close()


if __name__ == "__main__":
    app()
