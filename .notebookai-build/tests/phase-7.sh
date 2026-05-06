#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 7

# Required files
assert_file_exists backend/notebookai/api/__init__.py
assert_file_exists backend/notebookai/api/app.py
assert_file_exists backend/notebookai/api/sse.py
assert_file_exists backend/notebookai/api/main.py
assert_file_exists backend/notebookai/api/dependencies.py

for r in notebooks library ingest ask lint articles log history events; do
  assert_file_exists "backend/notebookai/api/routers/${r}.py"
done

assert_file_exists backend/tests/test_api.py

# pyproject deps
grep -qE 'fastapi' backend/pyproject.toml || fail "pyproject missing fastapi"
grep -qE 'uvicorn' backend/pyproject.toml || fail "pyproject missing uvicorn"
grep -qE 'sse-starlette|httpx' backend/pyproject.toml || fail "pyproject missing sse/httpx"

# Symbol contracts
grep -qE 'def create_app|app = ' backend/notebookai/api/app.py || fail "app.py missing factory"
grep -qE 'EventSource|sse|StreamingResponse' backend/notebookai/api/sse.py || fail "sse.py missing streaming"

# Pytest passes (TestClient-driven)
( cd backend && uv sync --quiet 2>/dev/null || uv sync 2>&1 | tail -5 )
( cd backend && uv run pytest tests/test_api.py -q -m "not requires_claude" ) || fail "API tests failed"

# Cumulative
( cd backend && uv run pytest tests/test_scaffold.py tests/test_index.py tests/test_adapters.py tests/test_agent.py -q -m "not requires_claude" >/dev/null ) || fail "prior tests regressed"

assert_state_phase_pass 7
print_cookie 7
