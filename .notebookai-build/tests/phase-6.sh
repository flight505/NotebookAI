#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 6

# Required files
assert_file_exists backend/notebookai/agent/__init__.py
assert_file_exists backend/notebookai/agent/runtime.py
assert_file_exists backend/notebookai/agent/tools.py
assert_file_exists backend/notebookai/agent/operations.py
assert_file_exists backend/notebookai/agent/events.py
assert_file_exists backend/tests/test_agent.py

# Symbol contracts
grep -qE 'class AgentRuntime|class AgentSession' backend/notebookai/agent/runtime.py \
  || fail "runtime.py missing AgentRuntime/AgentSession"
grep -qE 'async def ingest|def ingest' backend/notebookai/agent/operations.py \
  || fail "operations.py missing ingest"
grep -qE 'async def query|def query' backend/notebookai/agent/operations.py \
  || fail "operations.py missing query"
grep -qE 'async def lint|def lint' backend/notebookai/agent/operations.py \
  || fail "operations.py missing lint"

# Event types match CONTRACTS § SSE
grep -qE 'class AgentToolCall|agent\.tool_call' backend/notebookai/agent/events.py \
  || fail "events.py missing agent.tool_call"
grep -qE 'class AgentMessage|agent\.message' backend/notebookai/agent/events.py \
  || fail "events.py missing agent.message"
grep -qE 'class AgentDone|agent\.done' backend/notebookai/agent/events.py \
  || fail "events.py missing agent.done"
grep -qE 'class AgentError|agent\.error' backend/notebookai/agent/events.py \
  || fail "events.py missing agent.error"

# pyproject deps
grep -qE 'claude-agent-sdk|claude_agent_sdk|anthropic' backend/pyproject.toml \
  || fail "pyproject missing claude-agent-sdk or anthropic"

# Bash allowlist exists
grep -qE 'BASH_ALLOWLIST|bash_allowlist|allowed_commands' backend/notebookai/agent/tools.py \
  || fail "tools.py missing bash allowlist"

# Pytest unit tests pass (must use mocked SDK so no creds needed for the gate)
( cd backend && uv sync --quiet 2>/dev/null || uv sync 2>&1 | tail -5 )
( cd backend && uv run pytest tests/test_agent.py -q -m "not requires_claude" ) \
  || fail "agent unit tests failed"

# Cumulative
( cd backend && uv run pytest tests/test_scaffold.py tests/test_index.py tests/test_adapters.py -q -m "not requires_claude" >/dev/null ) \
  || fail "prior tests regressed"

assert_state_phase_pass 6
print_cookie 6
