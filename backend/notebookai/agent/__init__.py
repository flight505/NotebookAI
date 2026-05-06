"""Agent package — wraps the Claude Agent SDK runtime for NotebookAI."""

from notebookai.agent.events import (
    EVENT_NAMES,
    AgentDone,
    AgentError,
    AgentMessage,
    AgentToolCall,
    AgentToolResult,
    Event,
)
from notebookai.agent.operations import (
    OperationResult,
    ingest,
    lint,
    query,
)
from notebookai.agent.runtime import AgentRuntime, AgentSession

__all__ = [
    "AgentRuntime",
    "AgentSession",
    "AgentToolCall",
    "AgentToolResult",
    "AgentMessage",
    "AgentDone",
    "AgentError",
    "Event",
    "EVENT_NAMES",
    "OperationResult",
    "ingest",
    "query",
    "lint",
]
