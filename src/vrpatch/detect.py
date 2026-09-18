"""Inner-rect proposal extension point (frozen decision #5).

Only `inner` is ever proposed automatically; the viewport stays human-chosen
(via the web picker or case.toml). Ship the trivial default; better heuristics
plug in by replacing :func:`propose_inner`.
"""

from __future__ import annotations

from .sidecar import InnerRect, Viewport


def propose_inner(viewport: Viewport, *, default: InnerRect) -> list[InnerRect]:
    """Propose candidate inner rects for a viewport.

    Returns a ranked list (best first). The default implementation returns the
    given `default` — the centred half-size rect used by every case so far.
    Deliberately no person detection: that is out of scope (plan §七).
    """
    return [default]
