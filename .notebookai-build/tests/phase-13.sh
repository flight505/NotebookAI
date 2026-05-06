#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 13

# Backend
assert_file_exists backend/notebookai/library/__init__.py
assert_file_exists backend/notebookai/library/scanner.py
assert_file_exists backend/tests/test_library.py

# Frontend
assert_file_exists frontend/components/LibraryPanel.tsx

# Cross-CLI verification script
assert_file_exists scripts/verify-cross-cli.sh

# Symbol contracts
grep -qE 'def scan_library|class LibraryScanner' backend/notebookai/library/scanner.py \
  || fail "scanner.py missing scan_library"

# Tests
( cd backend && uv sync --quiet 2>/dev/null || uv sync 2>&1 | tail -5 )
( cd backend && uv run pytest tests/test_library.py -q -m "not requires_claude" ) || fail "library tests failed"

# Cross-CLI verification — manual confirmation marker
[[ -x scripts/verify-cross-cli.sh ]] || fail "verify-cross-cli.sh not executable"

# Frontend builds
require_cmd pnpm
( cd frontend && pnpm build 2>&1 | tail -5 ) || fail "frontend build failed"

# Cumulative
( cd backend && uv run pytest tests/ -q -m "not requires_claude" >/dev/null ) || fail "cumulative regressed"

assert_state_phase_pass 13
print_cookie 13
