"""vrpatch-merge: paste the regenerated AI viewport clip back into the ERP video.

Streaming (read -> composite -> encode, one frame at a time) — a full-video
in-memory shape peaks near 48 GB on a 6K canvas. Encode parameters match the
verified pixel baseline exactly (libx264 crf/preset via media.FfmpegSink,
two-pass audio remux; see docs/knowledge/verification.md), which is what the
pixel regression gate relies on.

R5: single-segment only, enforced loudly (case.load_sidecar_single_segment).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import typer

from ..sidecar import InnerRect
from ..case import load_sidecar_single_segment
from ..composite import SegmentMaps
from ..framealign import index_map, short_by
from ..media import FfmpegSink, ffmpeg_path, has_audio
from ..progress import Log, RateMeter, format_duration

app = typer.Typer(add_completion=False, help=__doc__)


class AiFrameSource:
    """Yields the AI clip's frames resampled to the segment's frame count.

    Reads the source clip sequentially and keeps only the current frame; the
    target->source index map is monotonic (framealign.index_map), so each source
    frame is decoded at most once and only decoded frames are resized.
    """

    def __init__(self, path, target_size, dst_fps, n, log):
        self.path = path
        self.target_size = target_size
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise typer.Exit(f"cannot open AI clip: {path}")
        self.src_fps = self.cap.get(cv2.CAP_PROP_FPS) or dst_fps
        self.src_n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.src_size = (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                         int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self.n = n
        self.idx = index_map(n, self.src_fps, dst_fps, self.src_n)
        self._raw = None
        self._raw_i = -1
        self._scaled = None
        self._scaled_i = -1
        self.short = short_by(n, self.src_n)

        log.info(f"ai clip : {self.src_n} frames, {self.src_size[0]}x"
                 f"{self.src_size[1]} @ {self.src_fps:.2f}fps -> resample to "
                 f"{n} frames @ {dst_fps:.2f}fps, resize to "
                 f"{target_size[0]}x{target_size[1]}")

    def frame(self, i):
        want = int(self.idx[i])
        while self._raw_i < want:
            ok, f = self.cap.read()
            if not ok:
                break
            self._raw = f
            self._raw_i += 1
        if self._raw is None:
            raise typer.Exit(f"AI clip {self.path!r} yielded no decodable frames")
        if self._scaled_i != self._raw_i:
            self._scaled = cv2.resize(self._raw, self.target_size,
                                      interpolation=cv2.INTER_AREA)
            self._scaled_i = self._raw_i
        return self._scaled

    def close(self):
        self.cap.release()


@app.command()
def merge(
    input_video: Path = typer.Option(..., "--input", help="source ERP (360) video"),
    ai: Path = typer.Option(..., help="AI-regenerated viewport clip"),
    sidecar: Path = typer.Option(..., help="clip.json (single segment)"),
    output: Path = typer.Option(..., help="output ERP mp4"),
    inner: str = typer.Option(None, metavar="X,Y,W,H",
                              help="override the sidecar inner rect"),
    max_frames: int = typer.Option(0, help="stop after N frames (preview)"),
    snapshots: str = typer.Option("", help="comma-separated frame indices to save as PNG"),
    feather: int = typer.Option(16, help="inner-rect boundary feather width"),
    levels: int = typer.Option(5, help="Laplacian pyramid levels"),
    crf: int = typer.Option(18, help="x264 crf"),
    preset: str = typer.Option("medium", help="x264 preset"),
    report: Path = typer.Option(None, help="write a JSON run report here"),
    progress_every: int = typer.Option(0),
    quiet: bool = typer.Option(False, "-q"),
):
    t_start = time.time()
    log = Log(every=progress_every, quiet=quiet)

    # ---- 1. sidecar (single segment, loud) -----------------------------------
    log.phase(f"sidecar: {sidecar}")
    seg = load_sidecar_single_segment(sidecar)
    if inner:
        ix, iy, iw, ih = (int(v) for v in inner.split(","))
        if iw <= 0 or ih <= 0:
            raise typer.Exit("inner width/height must be positive")
        log.info(f"inner rect overridden by --inner: x={ix} y={iy} w={iw} h={ih} "
                 f"(sidecar said x={seg.inner.x} y={seg.inner.y} "
                 f"w={seg.inner.width} h={seg.inner.height})")
        seg.inner = InnerRect(x=ix, y=iy, width=iw, height=ih)
    vp = seg.viewport
    n_seg = seg.frame_end - seg.frame_start + 1
    n = n_seg
    if max_frames and max_frames < n:
        n = max_frames
        log.info(f"preview: writing {n} of {n_seg} frames (--max-frames {max_frames})")
    log.info(f"segment {seg.id}: frames {seg.frame_start}..{seg.frame_end} "
             f"({n_seg} frames) @ {fps_of(input_video):.2f}fps")
    log.info(f"erp {erp_size(input_video)[0]}x{erp_size(input_video)[1]}, "
             f"viewport {vp.width}x{vp.height} yaw={vp.yaw_deg} "
             f"pitch={vp.pitch_deg} fov={vp.fov_h_deg}")
    log.info(f"inner: x={seg.inner.x} y={seg.inner.y} "
             f"w={seg.inner.width} h={seg.inner.height}")

    # ---- 2. source video -----------------------------------------------------
    cap = cv2.VideoCapture(str(input_video))
    if not cap.isOpened():
        raise typer.Exit(f"cannot open source video: {input_video}")
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    src_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sidecar_fps = sidecar_fps_value(sidecar)
    if seg.frame_end >= src_frames:
        log.info(f"WARNING: segment ends at frame {seg.frame_end} but the source "
                 f"has {src_frames} frames; truncating to what exists.")
        n_seg = max(0, src_frames - seg.frame_start)
        n = min(n, n_seg)
        if n_seg <= 0:
            raise typer.Exit("segment starts past the end of the source video")
    log.info(f"source : {src_frames} frames, {src_w}x{src_h}; "
             f"compositing {n} frames -> output {src_w}x{src_h}")

    # ---- 3. geometry once ----------------------------------------------------
    log.phase("building projection maps (once for the segment)")
    t0 = time.time()
    maps = SegmentMaps(seg, src_w, src_h, feather)
    log.info(f"viewport footprint on the ERP: "
             f"{maps.paste_map[0].shape[1]}x{maps.paste_map[0].shape[0]} px at "
             f"({maps.x0},{maps.y0}) = "
             f"{100.0 * maps.cover.size / (src_w * src_h):.1f}% of canvas; "
             f"built in {time.time() - t0:.2f}s")

    # ---- 4. AI clip ----------------------------------------------------------
    log.phase("aligning AI clip")
    ai_src = AiFrameSource(str(ai), (vp.width, vp.height), sidecar_fps, n_seg, log)
    if ai_src.short:
        log.info(f"WARNING: AI clip is {ai_src.short} frames short; the last "
                 f"decodable frame is reused to fill the gap.")

    # ---- 5. encoder ----------------------------------------------------------
    ff = ffmpeg_path()
    if not ff:
        raise typer.Exit("no ffmpeg binary found on PATH; merge needs it "
                         "(same encode path as the verified pixel baseline)")
    audio_from = None
    if has_audio(str(input_video)):
        audio_from = str(input_video)
        log.info("encoder: ffmpeg/libx264 + source audio (video-only encode, "
                 "then audio muxed in with -c:v copy)")
    else:
        log.info("encoder: ffmpeg/libx264 (source has no audio track to keep)")

    # ---- 6. stream -----------------------------------------------------------
    log.phase(f"compositing {n} frames")
    if not cap.set(cv2.CAP_PROP_POS_FRAMES, seg.frame_start):
        log.info("WARNING: could not seek; decoding from the start instead.")

    sink = FfmpegSink(str(output), (src_w, src_h), sidecar_fps, crf, preset,
                      audio_from)
    meter = RateMeter(n)
    snap = {int(v) for v in snapshots.split(",") if v.strip()}
    written = 0
    for i in range(n):
        ok, frame = cap.read()
        if not ok:
            log.info(f"source ended early at output frame {i}; writing {written}.")
            break
        out = maps.composite_frame(frame, ai_src.frame(i), levels)
        if i in snap:
            p = output.with_name(output.stem + f"_f{i}.png")
            cv2.imwrite(str(p), out)
            log.info(f"snapshot -> {p}")
        sink.write(out)
        written += 1
        meter.tick()
        log.progress(meter, "compositing")

    log.done()
    sink.close()
    cap.release()
    ai_src.close()

    size_mb = output.stat().st_size / 1e6 if output.exists() else 0
    log.phase(f"wrote {output} ({src_w}x{src_h}, {written} frames, "
              f"{size_mb:.1f} MB, {format_duration(time.time() - t_start)} total)")
    if written < n:
        typer.echo(f"WARNING: only {written} of {n} frames were written")

    if report:
        report.write_text(json.dumps({
            "input": str(input_video), "ai": str(ai), "sidecar": str(sidecar),
            "output": str(output), "frames_written": written,
            "frames_expected": n, "encoder": "ffmpeg/libx264",
            "crf": crf, "preset": preset, "feather": feather, "levels": levels,
            "inner": [seg.inner.x, seg.inner.y, seg.inner.width, seg.inner.height],
            "warnings": (["ai clip short by %d" % ai_src.short] if ai_src.short else []),
            "elapsed_s": round(time.time() - t_start, 1),
        }, indent=2), encoding="utf-8")
        typer.echo(f"report -> {report}")


def fps_of(path) -> float:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise typer.Exit(f"cannot open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    return float(fps)


def erp_size(path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise typer.Exit(f"cannot open video: {path}")
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    return size


def sidecar_fps_value(path) -> float:
    with open(path, "r", encoding="utf-8") as f:
        return float(json.load(f)["fps"])


if __name__ == "__main__":
    app()
