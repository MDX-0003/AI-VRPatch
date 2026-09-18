"""vrpatch-serve: the single entry point.

Starts the local dashboard (create cases from sources/, pick regions, run
extract/merge, watch progress). One command; everything else happens in the
browser. The CLIs remain fully functional for scripted use — both drive the
same code.
"""

from __future__ import annotations

import typer

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def serve(
    port: int = typer.Option(8760, help="local port"),
):
    from ..web.app import serve as _serve
    _serve(None, port)


if __name__ == "__main__":
    app()
