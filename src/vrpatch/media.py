"""ffmpeg discovery and encode sink.

Everything here is lazy: nothing runs until a merge actually needs to encode.

ffmpeg resolution order: the project's own ``bin/ffmpeg.exe`` first (ships
with the distribution package, so recipients never touch PATH), then whatever
is on PATH as a fallback. Pin the build used in bin/ (see docs/knowledge) —
the encode parameters are byte-compatible with the project's verified baseline
(see docs/knowledge/verification.md): rawvideo bgr24 stdin -> libx264
crf/preset -> yuv420p, audio carried over in a second ``-c copy`` remux pass
(remuxing a copied stream cannot change the frame count; encoding with the
audio input present can).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

_FFMPEG: str | None = None
_RESOLVED = False


def bundled_ffmpeg() -> Path:
    """bin/ffmpeg.exe next to the project root (src/vrpatch/media.py -> root)."""
    return Path(__file__).resolve().parents[2] / "bin" / "ffmpeg.exe"


def ffmpeg_path() -> str | None:
    """Locate an ffmpeg binary on first use; bin/ wins over PATH."""
    global _FFMPEG, _RESOLVED
    if not _RESOLVED:
        _RESOLVED = True
        bundled = bundled_ffmpeg()
        _FFMPEG = str(bundled) if bundled.is_file() else shutil.which("ffmpeg")
    return _FFMPEG


def has_ffmpeg() -> bool:
    p = ffmpeg_path()
    return bool(p)


def has_audio(path: str) -> bool:
    """True if `path` has an audio stream (probe via ffmpeg stderr)."""
    ff = ffmpeg_path()
    if not ff:
        return False
    probe = subprocess.run([ff, "-hide_banner", "-i", path],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    return "Audio:" in probe.stderr


class FfmpegSink:
    """Streams BGR frames into ffmpeg/libx264, optionally muxing source audio.

    Two passes when audio is requested: encode video-only, then remux the audio
    in with ``-c:v copy`` — see module docstring for why.
    """

    def __init__(self, path, size, fps, crf=18, preset="medium",
                 audio_from=None):
        ff = ffmpeg_path()
        if not ff:
            raise RuntimeError("ffmpeg binary not found")
        self.path = path
        self.audio_from = audio_from
        self.tmp = (path + ".video-only.mp4") if audio_from else path
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "warning",
               "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{size[0]}x{size[1]}", "-r", f"{fps}",
               "-i", "-",
               "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
               "-pix_fmt", "yuv420p", "-threads", "0", self.tmp]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stderr=subprocess.PIPE)

    def write(self, frame):
        self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self):
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace")
        rc = self.proc.wait()
        if rc != 0:
            print(f"WARNING: ffmpeg exited with code {rc}: {err.strip()[:300]}")
        elif err.strip():
            print(f"ffmpeg notes: {err.strip()[:300]}")
        if not self.audio_from:
            return
        ff = ffmpeg_path()
        mux = [ff, "-y", "-hide_banner", "-loglevel", "error",
               "-i", self.tmp, "-i", self.audio_from,
               "-map", "0:v:0", "-map", "1:a:0?", "-c", "copy",
               "-movflags", "+faststart", self.path]
        r = subprocess.run(mux, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError("failed to mux audio:\n" + (r.stderr or "")[:500])
        os.remove(self.tmp)
