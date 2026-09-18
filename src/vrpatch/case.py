"""case.toml -> Case -> sidecar (clip.json).

A case is the single source of truth for one job: where the source ERP video
lives (path + sha256 so references stay traceable), the viewport, the inner
rect, and free-form notes. The sidecar JSON stays the *external* contract
(what downstream tools read) but is a derived artifact: regenerate it instead
of hand-editing it.

Single-segment model (frozen decision #3): a case has exactly one viewport;
the sidecar's `segments` list is kept for contract compatibility, and a
segments>1 sidecar is rejected loudly rather than silently truncated.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, asdict
from pathlib import Path

from .sidecar import Sidecar, Segment, Viewport, InnerRect, save_sidecar


@dataclass
class SourceRef:
    path: str
    sha256: str


@dataclass
class Case:
    name: str
    source: SourceRef
    erp_width: int
    erp_height: int
    fps: float
    frame_start: int
    frame_end: int  # inclusive
    viewport: Viewport
    inner: InnerRect
    notes: str = ""


def _sha256_of(path: Path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_case(path: str | Path, *, verify: bool = True) -> Case:
    """Parse case.toml; by default verify the source file's sha256."""
    p = Path(path)
    with open(p, "rb") as f:
        d = tomllib.load(f)
    src = d["source"]
    case = Case(
        name=d["name"],
        source=SourceRef(path=src["path"], sha256=src.get("sha256", "")),
        erp_width=d["erp"]["width"],
        erp_height=d["erp"]["height"],
        fps=d["erp"]["fps"],
        frame_start=d["frames"]["start"],
        frame_end=d["frames"]["end"],
        viewport=Viewport(**d["viewport"]),
        inner=InnerRect(**d["inner"]),
        notes=d.get("notes", ""),
    )
    if verify:
        verify_case(p, case)
    return case


def verify_case(case_path: str | Path, case: Case | None = None) -> None:
    """Check the referenced source still exists and hashes to the recorded
    sha256. Raises FileNotFoundError / ValueError — traceability is a load-time
    concern, not an optional report."""
    p = Path(case_path)
    c = case or load_case(p, verify=False)
    src = (p.parent / c.source.path) if not Path(c.source.path).is_absolute() \
        else Path(c.source.path)
    if not src.is_file():
        raise FileNotFoundError(f"case source not found: {src}")
    if not c.source.sha256:
        return  # recorded lazily by `record_sha256`
    actual = _sha256_of(src)
    if actual != c.source.sha256:
        raise ValueError(
            f"case source hash mismatch for {src}: case.toml says "
            f"{c.source.sha256}, file is {actual}")


def record_sha256(case_path: str | Path) -> str:
    """Compute and write the source's sha256 back into case.toml (used once at
    case creation; keeps the toml a hand-editable file otherwise)."""
    p = Path(case_path)
    c = load_case(p, verify=False)
    src = (p.parent / c.source.path) if not Path(c.source.path).is_absolute() \
        else Path(c.source.path)
    digest = _sha256_of(src)
    text = p.read_text(encoding="utf-8")
    lines = []
    in_source = False
    for line in text.splitlines():
        if line.strip().startswith("[source]"):
            in_source = True
        elif line.strip().startswith("[") and line.strip().endswith("]"):
            in_source = False
        if in_source and line.strip().startswith("sha256"):
            line = f'sha256 = "{digest}"'
        lines.append(line)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    c.source.sha256 = digest
    return digest


def case_to_sidecar(case: Case) -> Sidecar:
    seg = Segment(
        id="seg_0",
        frame_start=case.frame_start,
        frame_end=case.frame_end,
        viewport=case.viewport,
        inner=case.inner,
    )
    return Sidecar(erp_width=case.erp_width, erp_height=case.erp_height,
                   fps=case.fps, segments=[seg])


def save_sidecar_for_case(case: Case, path: str | Path) -> None:
    save_sidecar(case_to_sidecar(case), path)


def load_sidecar_single_segment(path: str | Path) -> Segment:
    """Contract guard (R5): only single-segment sidecars are supported, and a
    multi-segment one is an error, never a silent segments[0]."""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    segs = d.get("segments", [])
    if len(segs) != 1:
        raise ValueError(
            f"{path}: expected exactly 1 segment, found {len(segs)}. "
            f"vrpatch is single-segment by design; split the job instead.")
    return Segment(
        id=segs[0]["id"],
        frame_start=segs[0]["frame_start"],
        frame_end=segs[0]["frame_end"],
        viewport=Viewport(**segs[0]["viewport"]),
        inner=InnerRect(**segs[0]["inner"]),
    )
