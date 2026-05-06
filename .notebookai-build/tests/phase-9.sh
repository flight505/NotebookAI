#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 9

# Frontend Ask mode files
assert_file_exists frontend/app/ask/page.tsx
assert_file_exists frontend/components/ChatTranscript.tsx
assert_file_exists frontend/components/ChatComposer.tsx
assert_file_exists frontend/components/CitationChip.tsx
assert_file_exists frontend/components/StreamingText.tsx

# Backend chats markdown writer
assert_file_exists backend/notebookai/chats/__init__.py
assert_file_exists backend/notebookai/chats/store.py
assert_file_exists backend/tests/test_chats.py

# Symbol contracts
grep -qE 'def write_chat|def append_message|class ChatStore' backend/notebookai/chats/store.py \
  || fail "chats/store.py missing writer"

# Pytest
( cd backend && uv sync --quiet 2>/dev/null || uv sync 2>&1 | tail -5 )
( cd backend && uv run pytest tests/test_chats.py tests/test_api.py -q -m "not requires_claude" ) \
  || fail "tests failed"

# Frontend builds
require_cmd pnpm
( cd frontend && pnpm build 2>&1 | tail -10 ) || fail "frontend build failed"

# Cumulative backend tests
( cd backend && uv run pytest tests/test_scaffold.py tests/test_index.py tests/test_adapters.py tests/test_agent.py -q -m "not requires_claude" >/dev/null ) \
  || fail "prior tests regressed"

assert_state_phase_pass 9
print_cookie 9
