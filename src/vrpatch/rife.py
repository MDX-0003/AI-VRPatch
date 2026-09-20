"""Locate and drive rife-ncnn-vulkan — the one external binary restore needs.

Deliberately prebuilt-exe-with-no-Python-deps (frozen tool decision
2026-09-20): the binary speaks Vulkan directly, so restore works on any GPU
without pulling torch into the project. It interpolates a directory of PNGs
into exactly ``-n`` output PNGs (frame-domain stretch), which is exactly the
"spread the content over the target span" semantics restore.docstring
promises.

Discovery order (first hit wins):
1. ``$VRPATCH_RIFE`` — the exe path, or a directory containing it
2. ``<repo root>/bin/rife-ncnn-vulkan*/`` — release zips extract to a folder;
   ``bin/`` is gitignored, the binary is machine-local like sources/
3. ``PATH``
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

EXE_NAME = "rife-ncnn-vulkan.exe" if os.name == "nt" else "rife-ncnn-vulkan"

#: release zip bundles these; rife-v4.x models take arbitrary timesteps,
#: which is what makes the exact -n frame count possible
DEFAULT_MODEL = "rife-v4.6"


def find_rife(root: str | Path | None = None, env: dict | None = None) -> str | None:
    """Path to the rife-ncnn-vulkan executable, or None if not installed.

    ``root``/``env`` are injectable for tests; defaults are the repo ``bin/``
    and the real environment.
    """
    env = os.environ if env is None else env
    hint = env.get("VRPATCH_RIFE", "")
    if hint:
        p = Path(hint)
        if p.is_dir():
            p = p / EXE_NAME
        if p.is_file():
            return str(p)
    base = Path(root) if root else _repo_bin()
    if base.is_dir():
        for d in sorted(base.glob("rife-ncnn-vulkan*")):
            p = d / EXE_NAME if d.is_dir() else d
            if p.is_file():
                return str(p)
    return shutil.which("rife-ncnn-vulkan")


def _repo_bin() -> Path:
    return Path(__file__).resolve().parents[2] / "bin"


class RifeInterpolator:
    """Callable(viewport: in_dir, target_n, out_dir) — the Interpolator role.

    Raises RuntimeError with the stderr tail if the binary fails, so the
    caller's log keeps one line of truth instead of a silent empty output dir.
    """

    def __init__(self, exe: str, model: str = DEFAULT_MODEL, gpu: int | None = None):
        self.exe = exe
        self.model = model
        self.gpu = gpu

    def __call__(self, in_dir: Path, target_n: int, out_dir: Path) -> None:
        cmd = [self.exe, "-i", str(in_dir), "-o", str(out_dir),
               "-n", str(target_n), "-m", self.model,
               "-f", "%08d.png"]
        if self.gpu is not None:
            cmd += ["-g", str(self.gpu)]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "").strip()[-500:]
            raise RuntimeError(f"rife-ncnn-vulkan failed (exit {r.returncode}):\n{tail}")
