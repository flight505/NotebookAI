"""NotebookAI CLI (Typer)."""

from __future__ import annotations

import json as _json
import logging
import os
import shutil
import signal
import sys
from pathlib import Path

import structlog
import typer

# When stdout is piped to ``grep -q`` (or ``head``) the consumer can close
# the pipe before we finish writing. Default Python behaviour raises
# BrokenPipeError; restore the SIGPIPE default so we exit cleanly instead.
try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):  # pragma: no cover - Windows / non-main thread
    pass

# Silence the default structlog/stdlib loggers for CLI subcommands so output
# pipelines stay focused on user-visible text. The API server re-enables
# logging in :func:`notebookai.api.main.run`.
logging.getLogger().setLevel(logging.ERROR)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR),
)

from notebookai import __version__
from notebookai.config import get_config
from notebookai.library.scanner import LibraryScanner
from notebookai.scaffold import create_notebook

app = typer.Typer(
    add_completion=False,
    help="NotebookAI command-line interface.",
    no_args_is_help=True,
    rich_markup_mode=None,
)


def _write_or_swallow(text: str) -> None:
    """Write to stdout, swallowing BrokenPipeError from short consumers."""
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:
        # Reader closed the pipe (e.g. ``| head -n1``). Drop the rest of
        # the output and exit cleanly.
        try:
            sys.stdout.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# new / version
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@app.command()
def serve(
    host: str | None = typer.Option(None, "--host", help="Bind host."),
    port: int | None = typer.Option(None, "--port", help="Bind port."),
) -> None:
    """Start the FastAPI server (uvicorn)."""
    cfg = get_config()
    bind_host = host or cfg.api_host
    bind_port = port or cfg.api_port

    import uvicorn

    typer.echo(f"NotebookAI API: http://{bind_host}:{bind_port}")
    uvicorn.run(
        "notebookai.api.app:create_app",
        factory=True,
        host=bind_host,
        port=bind_port,
        reload=False,
    )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def _claude_credentials_available() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    candidates = [
        Path.home() / ".claude" / ".credentials.json",
        Path.home() / ".config" / "claude" / "credentials.json",
    ]
    for cand in candidates:
        try:
            if cand.is_file():
                return True
        except OSError:
            continue
    return False


@app.command()
def status(
    root: Path | None = typer.Option(
        None, "--root", help="Library root override."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Print library root, notebook list, API URL, agent model, claude auth."""
    cfg = get_config()
    library_root = Path(root).expanduser() if root else cfg.library_root

    scanner = LibraryScanner(library_root)
    entries = scanner.scan()
    notebooks = [
        {
            "id": e.id,
            "name": e.name,
            "article_count": e.article_count,
            "last_op_at": e.last_op_at,
        }
        for e in entries
    ]
    payload = {
        "library_root": str(library_root),
        "notebooks": notebooks,
        "api_url": f"http://{cfg.api_host}:{cfg.api_port}/api",
        "agent_model": cfg.agent_model,
        "lint_model": cfg.lint_model,
        "claude_credentials_available": _claude_credentials_available(),
    }

    if json_out:
        _write_or_swallow(_json.dumps(payload, indent=2) + "\n")
        return

    lines = [
        f"library_root: {payload['library_root']}",
        f"api_url:      {payload['api_url']}",
        f"agent_model:  {payload['agent_model']}",
        f"lint_model:   {payload['lint_model']}",
        f"claude_auth:  {'available' if payload['claude_credentials_available'] else 'missing'}",
        f"notebooks ({len(notebooks)}):",
    ]
    for nb in notebooks:
        last = nb["last_op_at"] or "-"
        lines.append(
            f"  - {nb['id']}  ({nb['name']})  articles={nb['article_count']}  last_op={last}"
        )
    _write_or_swallow("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# claude / codex — exec a CLI inside a notebook folder
# ---------------------------------------------------------------------------


def _resolve_notebook(notebook_id: str, root: Path | None = None) -> Path | None:
    cfg = get_config()
    library_root = Path(root).expanduser() if root else cfg.library_root
    scanner = LibraryScanner(library_root)
    for e in scanner.scan():
        if e.id == notebook_id:
            return Path(e.path)
    return None


def _exec_cli_in_notebook(cli_name: str, notebook_id: str) -> None:
    nb_path = _resolve_notebook(notebook_id)
    if nb_path is None:
        typer.echo(f"error: notebook {notebook_id!r} not found", err=True)
        raise typer.Exit(code=2)
    cli_path = shutil.which(cli_name)
    if cli_path is None:
        typer.echo(
            f"error: {cli_name!r} CLI not found on PATH. "
            f"Install it and try again.",
            err=True,
        )
        raise typer.Exit(code=2)
    os.chdir(nb_path)
    os.execvp(cli_path, [cli_path])  # noqa: S606 - intentional exec


@app.command(name="claude")
def claude_cmd(notebook_id: str = typer.Argument(..., help="Notebook id.")) -> None:
    """cd into the notebook folder and exec the ``claude`` CLI."""
    _exec_cli_in_notebook("claude", notebook_id)


@app.command(name="codex")
def codex_cmd(notebook_id: str = typer.Argument(..., help="Notebook id.")) -> None:
    """cd into the notebook folder and exec the ``codex`` CLI."""
    _exec_cli_in_notebook("codex", notebook_id)


# ---------------------------------------------------------------------------
# library
# ---------------------------------------------------------------------------


library_app = typer.Typer(
    add_completion=False, help="Library operations.", no_args_is_help=False
)
app.add_typer(library_app, name="library")


@library_app.callback(invoke_without_command=True)
def library_default(ctx: typer.Context) -> None:
    """List notebooks (default when no subcommand is given)."""
    if ctx.invoked_subcommand is not None:
        return
    cfg = get_config()
    scanner = LibraryScanner(cfg.library_root)
    entries = scanner.scan()
    if not entries:
        typer.echo("(no notebooks)")
        return
    for e in entries:
        typer.echo(f"{e.id}\t{e.name}\t{e.path}")


@library_app.command("register")
def library_register(path: Path = typer.Argument(..., help="Absolute path to an existing notebook.")) -> None:
    """Register an external notebook path with the library."""
    cfg = get_config()
    scanner = LibraryScanner(
        cfg.library_root,
        config_path=cfg.default_config_file(),
    )
    try:
        entry = scanner.register_external(Path(path).expanduser())
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"registered: {entry.id}\t{entry.path}")


if __name__ == "__main__":  # pragma: no cover
    app()
