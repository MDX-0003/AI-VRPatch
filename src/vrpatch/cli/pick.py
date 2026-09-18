"""vrpatch-pick: deprecated alias for `vrpatch-serve`.

The dashboard covers picking (and everything else); this shim only exists so
old instructions and the installed console script keep working.
"""

from __future__ import annotations

import typer

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def pick(
    case_file: str = typer.Argument(None, help="ignored; the dashboard lists all cases"),
    port: int = typer.Option(8760),
):
    from ..web.app import serve as _serve
    _serve(None, port)


if __name__ == "__main__":
    app()
