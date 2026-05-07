"""Typed events emitted by the agent runtime.

Matches docs/CONTRACTS.md § SSE event types — payload field names line up
with the wire format the API surface in Phase 8 will fan out as
``text/event-stream`` to the frontend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Union

OpName = Literal["ingest", "compile", "cascade", "archive", "lint-fix", "ask", "query"]


@dataclass
class AgentToolCall:
    """`agent.tool_call` — fires before each tool invocation."""

    _event_name: ClassVar[str] = "agent.tool_call"

    notebook_id: str
    op_id: str
    tool: str
    input: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "op_id": self.op_id,
            "tool": self.tool,
            "input": self.input,
        }


@dataclass
class AgentToolResult:
    """`agent.tool_result` — fires after each tool invocation."""

    _event_name: ClassVar[str] = "agent.tool_result"

    notebook_id: str
    op_id: str
    tool: str
    output_preview: str
    is_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "op_id": self.op_id,
            "tool": self.tool,
            "output_preview": self.output_preview,
            "is_error": self.is_error,
        }


@dataclass
class AgentMessage:
    """`agent.message` — streaming text chunk from the agent."""

    _event_name: ClassVar[str] = "agent.message"

    notebook_id: str
    op_id: str
    text: str
    kind: Literal["thinking", "user-visible"] = "user-visible"

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "op_id": self.op_id,
            "text": self.text,
            "kind": self.kind,
        }


@dataclass
class AgentDone:
    """`agent.done` — terminal success event for an op."""

    _event_name: ClassVar[str] = "agent.done"

    notebook_id: str
    op_id: str
    op: str
    summary: str
    commit_sha: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "op_id": self.op_id,
            "op": self.op,
            "commit_sha": self.commit_sha,
            "summary": self.summary,
            "usage": self.usage,
        }


@dataclass
class AgentError:
    """`agent.error` — terminal failure event for an op."""

    _event_name: ClassVar[str] = "agent.error"

    notebook_id: str
    op_id: str
    error_type: str
    message: str
    retriable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "op_id": self.op_id,
            "error_type": self.error_type,
            "message": self.message,
            "retriable": self.retriable,
        }


@dataclass
class LintScheduled:
    """`lint.scheduled` — fired when the scheduler picks up a tick."""

    _event_name: ClassVar[str] = "lint.scheduled"

    notebook_id: str
    op_id: str
    scheduled_at: str  # RFC3339 UTC
    reason: Literal["interval", "manual"] = "interval"

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "op_id": self.op_id,
            "scheduled_at": self.scheduled_at,
            "reason": self.reason,
        }


@dataclass
class LintSkipped:
    """`lint.skipped` — fired when a scheduled tick decides not to run."""

    _event_name: ClassVar[str] = "lint.skipped"

    notebook_id: str
    op_id: str
    reason: Literal[
        "idle",
        "budget_exhausted",
        "claude_unavailable_no_findings",
        "already_running",
    ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "op_id": self.op_id,
            "reason": self.reason,
        }


@dataclass
class LintRunComplete:
    """`lint.run_complete` — top-level summary at the end of a scheduled run."""

    _event_name: ClassVar[str] = "lint.run_complete"

    notebook_id: str
    op_id: str
    finding_count: int
    tokens_used: int
    duration_ms: int
    mode: Literal["haiku", "passive_only"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "op_id": self.op_id,
            "finding_count": self.finding_count,
            "tokens_used": self.tokens_used,
            "duration_ms": self.duration_ms,
            "mode": self.mode,
        }


@dataclass
class AgentUnavailable:
    """`agent.unavailable` — fired at the start of a degraded (wiki-only) op.

    Surfaces to the UI that Claude credentials were not available so the op
    is running through the local-only fallback path.
    """

    _event_name: ClassVar[str] = "agent.unavailable"

    notebook_id: str
    op_id: str
    op: str
    reason: str
    degraded_mode: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "op_id": self.op_id,
            "op": self.op,
            "reason": self.reason,
            "degraded_mode": self.degraded_mode,
        }


Event = Union[
    AgentToolCall,
    AgentToolResult,
    AgentMessage,
    AgentDone,
    AgentError,
    AgentUnavailable,
    LintScheduled,
    LintSkipped,
    LintRunComplete,
]


EVENT_NAMES: dict[type, str] = {
    AgentToolCall: AgentToolCall._event_name,
    AgentToolResult: AgentToolResult._event_name,
    AgentMessage: AgentMessage._event_name,
    AgentDone: AgentDone._event_name,
    AgentError: AgentError._event_name,
    AgentUnavailable: AgentUnavailable._event_name,
    LintScheduled: LintScheduled._event_name,
    LintSkipped: LintSkipped._event_name,
    LintRunComplete: LintRunComplete._event_name,
}


__all__ = [
    "AgentToolCall",
    "AgentToolResult",
    "AgentMessage",
    "AgentDone",
    "AgentError",
    "AgentUnavailable",
    "LintScheduled",
    "LintSkipped",
    "LintRunComplete",
    "Event",
    "EVENT_NAMES",
    "OpName",
]
