#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 11

# Backend
assert_file_exists backend/notebookai/git/__init__.py
assert_file_exists backend/notebookai/git/notebook_repo.py
assert_file_exists backend/tests/test_git.py

# Frontend
assert_file_exists frontend/app/curate/history/page.tsx
assert_file_exists frontend/components/HistoryTimeline.tsx
assert_file_exists frontend/components/CommitDetail.tsx

# Symbol contracts
grep -qE 'class NotebookRepo|def commit_op|def get_history' backend/notebookai/git/notebook_repo.py \
  || fail "notebook_repo.py missing API"

# Tests
( cd backend && uv sync --quiet 2>/dev/null || uv sync 2>&1 | tail -5 )
( cd backend && uv run pytest tests/test_git.py -q -m "not requires_claude" ) || fail "git tests failed"

# Frontend builds
require_cmd pnpm
( cd frontend && pnpm build 2>&1 | tail -5 ) || fail "frontend build failed"

# Cumulative
( cd backend && uv run pytest tests/ -q -m "not requires_claude" >/dev/null ) || fail "cumulative regressed"

assert_state_phase_pass 11
print_cookie 11
