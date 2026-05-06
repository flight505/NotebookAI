"""Tool surface configuration for the wiki agent.

Implements the bash-allowlist enforcement and the path guards required by
docs/CONTRACTS.md § AgentTool inventory and § AGENTS.md write rules.

The runtime wires these helpers into the Claude Agent SDK
``can_use_tool`` permission callback so a denied command never reaches
shell execution.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

# ---------------------------------------------------------------------------
# Bash allowlist
# ---------------------------------------------------------------------------

# Read-only commands and the single mutating program (git) we permit.
# Note that several "git X" shapes are explicitly denied below regardless of
# the allowlist match (push/pull/fetch/remote/reset/rm/checkout).
BASH_ALLOWLIST: frozenset[str] = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "grep",
        "rg",
        "find",
        "tree",
        "sort",
        "uniq",
        "diff",
        "echo",
        "pwd",
        "git",
    }
)

# Subcommands of "git" that we always reject — these break the "agent never
# touches the network" and "every op = exactly one commit on main" invariants.
_DENIED_GIT_SUBCMDS: frozenset[str] = frozenset(
    {
        "push",
        "pull",
        "fetch",
        "remote",
        "reset",
        "rm",
        "clone",
        "merge",
        "rebase",
        "cherry-pick",
        "tag",
        "branch",
        "stash",
        "submodule",
        "config",  # read-only `git config --get` is allowed via the explicit prefix below
    }
)

# Explicit allowlist of read-only "git config" forms — only `--get` shapes.
_ALLOWED_GIT_CONFIG_PREFIXES: tuple[str, ...] = (
    "config --get",
    "config --get-all",
    "config --get-regexp",
    "config --list",
)

_PIPE_SPLIT_RE = re.compile(r"\s*(?:\|\||&&|;|\|)\s*")


def is_bash_allowed(command: str) -> tuple[bool, str]:
    """Decide whether a Bash invocation may run.

    Splits on shell control operators (``&&``, ``||``, ``;``, ``|``) and
    inspects each segment's first 1–2 tokens. Returns ``(False, reason)``
    for the first denied segment; otherwise ``(True, "ok")``.

    The check is intentionally syntactic — we do not run the shell to
    expand variables. Anything we can't parse cleanly is denied.
    """
    if not command or not command.strip():
        return False, "empty command"

    segments = [seg.strip() for seg in _PIPE_SPLIT_RE.split(command) if seg.strip()]
    if not segments:
        return False, "empty command"

    for seg in segments:
        try:
            tokens = shlex.split(seg)
        except ValueError as exc:
            return False, f"unparsable segment: {seg!r} ({exc})"
        if not tokens:
            return False, f"empty segment in pipeline: {command!r}"

        head = tokens[0]

        # Reject leading env-style assignments like `FOO=bar ls`.
        if "=" in head and not head.startswith("-"):
            return False, f"env-style assignment not allowed: {head!r}"

        if head not in BASH_ALLOWLIST:
            return False, f"command not in allowlist: {head!r}"

        if head == "git":
            if len(tokens) < 2:
                return False, "bare 'git' not allowed"
            sub = tokens[1]

            # Special-case: only `git config --get*` / `--list` shapes.
            if sub == "config":
                rest = " ".join(tokens[1:])
                if not any(rest.startswith(prefix) for prefix in _ALLOWED_GIT_CONFIG_PREFIXES):
                    return False, f"git config form not allowed: {rest!r}"
                continue

            if sub in _DENIED_GIT_SUBCMDS:
                return False, f"git subcommand denied: {sub!r}"

            # Reject `git checkout` except `git checkout HEAD` / specific SHAs
            # (we don't track current SHAs here; deny outright to be safe — the
            # runtime performs its own commit via subprocess).
            if sub == "checkout":
                return False, "git checkout not allowed (would change worktree)"

    return True, "ok"


# ---------------------------------------------------------------------------
# Path guards
# ---------------------------------------------------------------------------


def is_path_in_notebook(path: Path | str, notebook_root: Path) -> bool:
    """True iff ``path`` resolves to a location inside ``notebook_root``."""
    try:
        target = Path(path).resolve()
        root = Path(notebook_root).resolve()
    except OSError:
        return False
    try:
        return target.is_relative_to(root)
    except AttributeError:  # pragma: no cover - 3.9 fallback
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False


# Top-level files the agent is permitted to write at the notebook root.
_ALLOWED_TOP_LEVEL_FILES: frozenset[str] = frozenset(
    {"AGENTS.md", "README.md", ".gitignore"}
)

# Forbidden subtree prefixes (relative to notebook root, POSIX-style).
_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    ".git/",
    ".notebookai/",
    "raw/",
)

# Allowed subtree prefixes for writes.
_ALLOWED_PREFIXES: tuple[str, ...] = (
    "wiki/",
    "chats/",
)


def is_path_writable(path: Path | str, notebook_root: Path) -> tuple[bool, str]:
    """Decide whether the agent may write to ``path``.

    Enforces the "Do not edit" sections of AGENTS.md and the read-only
    contract on raw/, .git/, and .notebookai/. ``wiki/**`` and ``chats/**``
    are writable, plus a small set of top-level meta files.
    """
    abs_path = Path(path)
    if not abs_path.is_absolute():
        abs_path = (Path(notebook_root) / abs_path).resolve()
    else:
        abs_path = abs_path.resolve()

    root = Path(notebook_root).resolve()

    # Outside the notebook entirely — denied.
    if not is_path_in_notebook(abs_path, root):
        return False, f"path {str(path)!r} is outside notebook root"

    rel = abs_path.relative_to(root).as_posix()

    # Forbid the read-only subtrees first.
    for forbid in _FORBIDDEN_PREFIXES:
        if rel == forbid.rstrip("/") or rel.startswith(forbid):
            return False, f"writes to {forbid!r} are not allowed"

    # Allow the writable subtrees.
    for allow in _ALLOWED_PREFIXES:
        if rel.startswith(allow):
            return True, "ok"

    # Top-level meta files.
    if "/" not in rel and rel in _ALLOWED_TOP_LEVEL_FILES:
        return True, "ok"

    # Anything else (including new top-level files we didn't authorise) is denied.
    return False, f"path {rel!r} is not in the writable surface"


# ---------------------------------------------------------------------------
# WebFetch op gate
# ---------------------------------------------------------------------------

# The ingest op is the only mode where the agent may resolve a URL — and
# even then only via the user-supplied source. Other ops have WebFetch
# disabled by the permission callback.
WEBFETCH_ALLOWED_FOR_OPS: frozenset[str] = frozenset({"ingest"})


__all__ = [
    "BASH_ALLOWLIST",
    "is_bash_allowed",
    "is_path_in_notebook",
    "is_path_writable",
    "WEBFETCH_ALLOWED_FOR_OPS",
]
