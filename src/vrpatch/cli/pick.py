"""vrpatch-pick: local web UI for choosing the viewport + inner rect (Phase 7).

Placeholder until the starlette app lands; installed as a console script from
Phase 1 so `uv run vrpatch-pick --help` works before the web extra does.
"""

from __future__ import annotations

import typer

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def pick(
    case_file: str = typer.Argument(..., help="case.toml path"),
    port: int = typer.Option(8760),
):
    from ..web.app import serve
    serve(case_file, port)


if __name__ == "__main__":
    app()
