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


Event = Union[AgentToolCall, AgentToolResult, AgentMessage, AgentDone, AgentError]


EVENT_NAMES: dict[type, str] = {
    AgentToolCall: AgentToolCall._event_name,
    AgentToolResult: AgentToolResult._event_name,
    AgentMessage: AgentMessage._event_name,
    AgentDone: AgentDone._event_name,
    AgentError: AgentError._event_name,
}


__all__ = [
    "AgentToolCall",
    "AgentToolResult",
    "AgentMessage",
    "AgentDone",
    "AgentError",
    "Event",
    "EVENT_NAMES",
    "OpName",
]
