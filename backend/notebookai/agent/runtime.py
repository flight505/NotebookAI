"""Claude Agent SDK runtime for NotebookAI.

Wraps the upstream ``claude-agent-sdk`` (`query()` / `ClaudeSDKClient`) so
operations.py can drive ingest/query/lint without touching SDK internals
directly. Translates SDK messages into the typed events declared in
``events.py`` and enforces the tool surface from ``tools.py``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from ulid import ULID

from notebookai.agent import tools as agent_tools
from notebookai.agent.events import (
    AgentDone,
    AgentError,
    AgentMessage,
    AgentToolCall,
    AgentToolResult,
    Event,
)

log = structlog.get_logger(__name__)


_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_LINT_MODEL = "claude-haiku-4-5-20251001"
_TOOL_RESULT_PREVIEW_LIMIT = 1024  # 1 KB cap per CONTRACTS § agent.tool_result


def _read_notebook_id(notebook_root: Path) -> str:
    """Read ``notebook.json.id`` from disk; falls back to the directory name."""
    meta_path = Path(notebook_root) / ".notebookai" / "notebook.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Path(notebook_root).name
    nb_id = meta.get("id")
    if isinstance(nb_id, str) and nb_id:
        return nb_id
    return Path(notebook_root).name


def _truncate(text: str, *, limit: int = _TOOL_RESULT_PREVIEW_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


class AgentRuntime:
    """Top-level handle for running operations against the Claude Agent SDK.

    One ``AgentRuntime`` instance is reused across many operations; each
    operation opens an :class:`AgentSession` for the duration of that op.
    """

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        lint_model: str = _DEFAULT_LINT_MODEL,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.lint_model = lint_model
        # Don't override existing env if api_key is None — let the SDK pick up
        # whatever auth source is configured (env var or `claude setup-token`
        # OAuth credential file).
        self._api_key = api_key
        if api_key:
            os.environ.setdefault("ANTHROPIC_API_KEY", api_key)

    # ------------------------------------------------------------------
    # Session factory
    # ------------------------------------------------------------------
    def session(
        self,
        notebook_root: Path,
        *,
        op: str,
        model: str | None = None,
    ) -> AgentSession:
        return AgentSession(
            runtime=self,
            notebook_root=Path(notebook_root),
            op=op,
            model=model or self.model,
        )

    # ------------------------------------------------------------------
    # Credential availability — lets tests skip live calls cleanly.
    # ------------------------------------------------------------------
    def credentials_available(self) -> bool:
        from notebookai.agent.credentials import claude_credentials_available

        return claude_credentials_available()


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class _PermissionConfig:
    notebook_root: Path
    op: str


def _make_permission_callback(cfg: _PermissionConfig):
    """Build the ``can_use_tool`` callback the SDK invokes before tool use.

    Returns either a ``PermissionResultAllow`` or ``PermissionResultDeny``.
    """
    # Defer SDK import so test files that don't touch the SDK keep working.
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

    notebook_root = cfg.notebook_root
    op = cfg.op

    async def can_use_tool(tool_name: str, tool_input: dict[str, Any], context):  # noqa: ARG001
        # WebFetch gate — only available during ingest.
        if tool_name == "WebFetch":
            if op not in agent_tools.WEBFETCH_ALLOWED_FOR_OPS:
                return PermissionResultDeny(
                    message=f"WebFetch not allowed for op {op!r}",
                )
            return PermissionResultAllow()

        # Bash allowlist.
        if tool_name == "Bash":
            command = (tool_input or {}).get("command", "")
            ok, reason = agent_tools.is_bash_allowed(command)
            if not ok:
                return PermissionResultDeny(message=f"Bash denied: {reason}")
            return PermissionResultAllow()

        # Write/Edit path guard.
        if tool_name in {"Write", "Edit"}:
            path = (tool_input or {}).get("path") or (tool_input or {}).get("file_path")
            if not path:
                return PermissionResultDeny(
                    message=f"{tool_name} call missing 'path'/'file_path'",
                )
            ok, reason = agent_tools.is_path_writable(path, notebook_root)
            if not ok:
                return PermissionResultDeny(message=reason)
            return PermissionResultAllow()

        # Read/Glob/Grep — confine to notebook root.
        if tool_name in {"Read", "Glob", "Grep"}:
            path_field = (
                (tool_input or {}).get("path")
                or (tool_input or {}).get("file_path")
                or (tool_input or {}).get("pattern")
            )
            # Glob/Grep patterns are allowed even without a leading slash —
            # only deny when an absolute path escapes the notebook.
            if path_field and isinstance(path_field, str) and path_field.startswith("/"):
                if not agent_tools.is_path_in_notebook(path_field, notebook_root):
                    return PermissionResultDeny(
                        message=f"path {path_field!r} is outside notebook root",
                    )
            return PermissionResultAllow()

        # Anything else — allow by default. The runtime restricts the tool
        # set via ``allowed_tools`` so unknown names should not appear.
        return PermissionResultAllow()

    return can_use_tool


_DEFAULT_ALLOWED_TOOLS: list[str] = [
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Bash",
    "WebFetch",
]

# Relative paths the SDK looks for when ``setting_sources=["project"]`` —
# either of these satisfies skill discovery so cross-CLI portability holds
# (Claude Code reads .claude/skills/, agentskills.io CLIs read .agents/skills/).
_SKILL_BUNDLE_RELATIVE_PATHS: tuple[Path, ...] = (
    Path(".claude") / "skills" / "karpathy-llm-wiki" / "SKILL.md",
    Path(".agents") / "skills" / "karpathy-llm-wiki" / "SKILL.md",
)


def _skill_bundle_present(notebook_root: Path) -> bool:
    """True if at least one supported skill-discovery path resolves on disk."""
    for rel in _SKILL_BUNDLE_RELATIVE_PATHS:
        if (notebook_root / rel).is_file():
            return True
    return False


class AgentSession:
    """One active operation against the Claude Agent SDK.

    Use as an async context manager — `__aenter__` initialises the SDK
    options/client and `__aexit__` closes the SDK client. `run()` yields
    typed :class:`Event` instances translated from the SDK message stream.
    """

    def __init__(
        self,
        *,
        runtime: AgentRuntime,
        notebook_root: Path,
        op: str,
        model: str,
    ) -> None:
        self.runtime = runtime
        self.notebook_root = Path(notebook_root).resolve()
        self.op = op
        self.model = model
        self.notebook_id = _read_notebook_id(self.notebook_root)
        self.op_id: str = str(ULID())

        # Populated in __aenter__.
        self._options = None  # type: ignore[assignment]
        self._client = None  # type: ignore[assignment]

    # ------------------------------------------------------------------
    async def __aenter__(self) -> AgentSession:
        # Defer SDK import so the package is importable even in environments
        # without claude-agent-sdk available (the gate's mocked tests).
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        cfg = _PermissionConfig(notebook_root=self.notebook_root, op=self.op)
        self._options = ClaudeAgentOptions(
            cwd=str(self.notebook_root),
            model=self.model,
            allowed_tools=list(_DEFAULT_ALLOWED_TOOLS),
            setting_sources=["project"],  # picks up .claude/skills/karpathy-llm-wiki
            can_use_tool=_make_permission_callback(cfg),
            permission_mode="default",
        )
        # ClaudeSDKClient instances are cheap; store on the session so
        # callers can reuse the connection between runs of the same op.
        self._client = ClaudeSDKClient(options=self._options)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        # Some SDK versions expose `.disconnect()`, others rely on async
        # context manager support. Call whichever is present.
        close = getattr(client, "disconnect", None) or getattr(client, "close", None)
        if callable(close):
            try:
                result = close()
                if hasattr(result, "__await__"):
                    await result
            except Exception:  # noqa: BLE001
                log.warning("agent_session_close_failed", op=self.op, op_id=self.op_id)

    # ------------------------------------------------------------------
    async def run(
        self,
        prompt: str,
        *,
        system_prompt_extra: str | None = None,
    ) -> AsyncIterator[Event]:
        """Run a single prompt and stream typed events back.

        The session's underlying ``ClaudeSDKClient`` is used as the
        transport. `system_prompt_extra` is appended to the user prompt
        as a leading instruction block — we don't override the SDK's
        skill-loading via the system_prompt option because that bypasses
        ``setting_sources=["project"]``.
        """
        log.info(
            "agent_run_start",
            op=self.op,
            op_id=self.op_id,
            notebook_id=self.notebook_id,
            prompt_preview=prompt[:200],
        )

        # Skill loading depends on ``cwd=notebook_root`` + ``setting_sources=["project"]``
        # plus the skill bundle existing on disk. Missing-skill silently degrades
        # the operation (SDK proceeds without the karpathy-llm-wiki prompt), so
        # surface it explicitly rather than letting the agent flounder.
        if not _skill_bundle_present(self.notebook_root):
            yield AgentError(
                notebook_id=self.notebook_id,
                op_id=self.op_id,
                error_type="skill_missing",
                message=(
                    "karpathy-llm-wiki skill bundle not found under "
                    ".claude/skills/ or .agents/skills/. Run `notebookai new` "
                    "to scaffold the bundle, or copy it from skills/karpathy-llm-wiki/."
                ),
                retriable=False,
            )
            return

        # Build the prompt — keep it stable so prompt caching can work.
        full_prompt = (
            f"{system_prompt_extra.strip()}\n\n{prompt}"
            if system_prompt_extra
            else prompt
        )

        usage: dict[str, Any] = {}
        summary_parts: list[str] = []

        # Late SDK import — same reasoning as in __aenter__.
        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ResultMessage,
                TextBlock,
                ThinkingBlock,
                ToolResultBlock,
                ToolUseBlock,
                UserMessage,
            )
        except ImportError as exc:  # pragma: no cover - SDK must be installed
            yield AgentError(
                notebook_id=self.notebook_id,
                op_id=self.op_id,
                error_type="sdk_unavailable",
                message=f"claude-agent-sdk not importable: {exc}",
                retriable=False,
            )
            return

        if self._client is None:
            yield AgentError(
                notebook_id=self.notebook_id,
                op_id=self.op_id,
                error_type="session_not_open",
                message="AgentSession.run called without entering the context manager",
                retriable=False,
            )
            return

        client = self._client

        try:
            # `query` is a top-level convenience helper but for multi-turn
            # ergonomics we drive ClaudeSDKClient directly.
            await client.query(full_prompt)
            async for message in client.receive_messages():
                # Tool-use and assistant text live on AssistantMessage.
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            yield AgentToolCall(
                                notebook_id=self.notebook_id,
                                op_id=self.op_id,
                                tool=block.name,
                                input=dict(block.input or {}),
                            )
                        elif isinstance(block, TextBlock):
                            text = (block.text or "").strip()
                            if text:
                                summary_parts.append(text)
                                yield AgentMessage(
                                    notebook_id=self.notebook_id,
                                    op_id=self.op_id,
                                    text=text,
                                    kind="user-visible",
                                )
                        elif isinstance(block, ThinkingBlock):
                            thought = getattr(block, "thinking", "") or ""
                            if thought:
                                yield AgentMessage(
                                    notebook_id=self.notebook_id,
                                    op_id=self.op_id,
                                    text=thought,
                                    kind="thinking",
                                )

                elif isinstance(message, UserMessage):
                    # Tool-result blocks come back wrapped in a UserMessage.
                    content = message.content
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, ToolResultBlock):
                                preview = block.content
                                if isinstance(preview, list):
                                    preview = " ".join(
                                        getattr(p, "text", str(p)) for p in preview
                                    )
                                preview_str = _truncate(str(preview or ""))
                                yield AgentToolResult(
                                    notebook_id=self.notebook_id,
                                    op_id=self.op_id,
                                    tool="",  # tool name lives on the matching ToolUseBlock
                                    output_preview=preview_str,
                                    is_error=bool(block.is_error),
                                )

                elif isinstance(message, ResultMessage):
                    if message.usage:
                        usage = dict(message.usage)
                    if message.is_error:
                        err = message.errors or [message.result or "unknown error"]
                        yield AgentError(
                            notebook_id=self.notebook_id,
                            op_id=self.op_id,
                            error_type="result_error",
                            message=str(err[0]) if err else "unknown error",
                            retriable=False,
                        )
                        return
                    summary = message.result or " ".join(summary_parts).strip()
                    yield AgentDone(
                        notebook_id=self.notebook_id,
                        op_id=self.op_id,
                        op=self.op,
                        commit_sha=None,  # operations.py rewrites this after committing
                        summary=_truncate(summary or "", limit=4096),
                        usage=usage,
                    )
                    return

        except Exception as exc:  # noqa: BLE001
            log.exception("agent_run_failed", op=self.op, op_id=self.op_id)
            yield AgentError(
                notebook_id=self.notebook_id,
                op_id=self.op_id,
                error_type=type(exc).__name__,
                message=str(exc),
                retriable=False,
            )


@asynccontextmanager
async def session_scope(runtime: AgentRuntime, notebook_root: Path, *, op: str, model: str | None = None):
    """Convenience async context manager around ``AgentRuntime.session``."""
    session = runtime.session(notebook_root, op=op, model=model)
    async with session as s:
        yield s


__all__ = [
    "AgentRuntime",
    "AgentSession",
    "session_scope",
]
