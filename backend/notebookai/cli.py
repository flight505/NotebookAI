"""NotebookAI CLI (Typer)."""

from __future__ import annotations

from pathlib import Path

import typer

from notebookai import __version__
from notebookai.scaffold import create_notebook

app = typer.Typer(
    add_completion=False,
    help="NotebookAI command-line interface.",
    no_args_is_help=True,
)


@app.command()
def new(
    name: str = typer.Argument(..., help="Notebook display name."),
    root: Path = typer.Option(
        Path.home() / "NotebookAI" / "notebooks",
        "--root",
        help="Library root directory.",
    ),
    no_git: bool = typer.Option(
        False, "--no-git", help="Skip git init for the new notebook."
    ),
) -> None:
    """Scaffold a new notebook folder."""
    handle = create_notebook(root=root, name=name, git_enabled=not no_git)
    typer.echo(str(handle))


@app.command()
def version() -> None:
    """Print the NotebookAI version."""
    typer.echo(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
