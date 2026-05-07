"""Single source of truth for Claude credential detection.

Both ``notebookai status`` and the agent runtime need to know whether any
form of Claude auth is reachable. Two acceptable sources:

* ``ANTHROPIC_API_KEY`` env var (commercial / multi-user use).
* OAuth credential file written by ``claude setup-token`` (Max plan).

We never read the file content — its presence is enough. Permission errors
are treated as "missing" so we never fail closed.
"""

from __future__ import annotations

import os
from pathlib import Path


def _oauth_credential_paths() -> list[Path]:
    """Return the candidate OAuth credential file locations.

    Ordered: macOS/Linux default, XDG-style override.
    """
    home = Path.home()
    candidates = [
        home / ".claude" / ".credentials.json",
        home / ".config" / "claude" / "credentials.json",
    ]
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        candidates.append(Path(xdg) / "claude" / "credentials.json")
    return candidates


def claude_credentials_available() -> bool:
    """True when any reachable Claude credential is configured."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    for cand in _oauth_credential_paths():
        try:
            if cand.is_file():
                return True
        except OSError:
            continue
    return False


__all__ = ["claude_credentials_available"]
