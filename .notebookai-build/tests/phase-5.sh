#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 5

# Required files
assert_file_exists backend/notebookai/adapters/__init__.py
assert_file_exists backend/notebookai/adapters/base.py
assert_file_exists backend/notebookai/adapters/pdf.py
assert_file_exists backend/notebookai/adapters/url.py
assert_file_exists backend/notebookai/adapters/youtube.py
assert_file_exists backend/notebookai/adapters/topic.py
assert_file_exists backend/tests/test_adapters.py

# Symbol contracts
grep -qE 'class RawDocument' backend/notebookai/adapters/base.py || fail "base.py missing RawDocument"
grep -qE 'class Adapter|class BaseAdapter' backend/notebookai/adapters/base.py || fail "base.py missing Adapter base"
grep -qE 'def write_to_notebook|def write_to_raw' backend/notebookai/adapters/base.py || fail "base.py missing write_to_notebook"

for a in pdf url youtube; do
  grep -qE 'def fetch' backend/notebookai/adapters/$a.py || fail "$a.py missing fetch()"
done

grep -qE 'def pick_topic|def choose_topic' backend/notebookai/adapters/topic.py || fail "topic.py missing pick_topic"

# pyproject deps for adapters
grep -qE 'pymupdf|PyMuPDF' backend/pyproject.toml || fail "pyproject missing pymupdf"
grep -qE 'beautifulsoup4|bs4' backend/pyproject.toml || fail "pyproject missing beautifulsoup4"
grep -qE 'youtube-transcript-api' backend/pyproject.toml || fail "pyproject missing youtube-transcript-api"

# Tests pass — must use fixtures, not network
( cd backend && uv sync --quiet 2>/dev/null || uv sync 2>&1 | tail -5 )
( cd backend && uv run pytest tests/test_adapters.py -q ) || fail "pytest failed for test_adapters.py"

# Cumulative: prior tests still pass
( cd backend && uv run pytest tests/test_scaffold.py tests/test_index.py -q >/dev/null ) || fail "prior tests regressed"

assert_state_phase_pass 5
print_cookie 5
