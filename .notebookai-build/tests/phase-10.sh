#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 10

# Backend
assert_file_exists backend/notebookai/agent/lint.py
assert_file_exists backend/notebookai/agent/passive_watcher.py
assert_file_exists backend/notebookai/agent/budget.py
assert_file_exists backend/tests/test_lint.py
assert_file_exists backend/tests/test_passive_watcher.py

# Frontend
assert_file_exists frontend/app/curate/page.tsx
assert_file_exists frontend/components/ActivityStream.tsx
assert_file_exists frontend/components/FindingCard.tsx
assert_file_exists frontend/components/LintLog.tsx
assert_file_exists frontend/components/BudgetMeter.tsx

# Symbol contracts
grep -qE 'class TokenBudget|def check_budget|class BudgetTracker' backend/notebookai/agent/budget.py \
  || fail "budget.py missing TokenBudget"
grep -qE 'class PassiveWatcher|class IndexAuditor' backend/notebookai/agent/passive_watcher.py \
  || fail "passive_watcher.py missing class"
grep -qE 'async def light_lint|def light_lint|class LintEngine' backend/notebookai/agent/lint.py \
  || fail "lint.py missing light_lint or LintEngine"

# Backend tests
( cd backend && uv sync --quiet 2>/dev/null || uv sync 2>&1 | tail -5 )
( cd backend && uv run pytest tests/test_lint.py tests/test_passive_watcher.py -q -m "not requires_claude" ) \
  || fail "lint/passive tests failed"

# Frontend builds
require_cmd pnpm
( cd frontend && pnpm build 2>&1 | tail -5 ) || fail "frontend build failed"

# Cumulative
( cd backend && uv run pytest tests/ -q -m "not requires_claude" >/dev/null ) \
  || fail "cumulative tests regressed"

assert_state_phase_pass 10
print_cookie 10
