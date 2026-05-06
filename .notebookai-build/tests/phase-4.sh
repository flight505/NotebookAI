#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 4

# Required files
assert_file_exists backend/notebookai/index/__init__.py
assert_file_exists backend/notebookai/index/schema.py
assert_file_exists backend/notebookai/index/store.py
assert_file_exists backend/notebookai/index/embeddings.py
assert_file_exists backend/notebookai/index/watcher.py
assert_file_exists backend/notebookai/index/builder.py
assert_file_exists backend/tests/test_index.py

# pyproject.toml gained the heavy deps
grep -qE 'sentence-transformers' backend/pyproject.toml || fail "pyproject missing sentence-transformers"
grep -qE 'sqlite-vec' backend/pyproject.toml || fail "pyproject missing sqlite-vec"
grep -qE 'numpy' backend/pyproject.toml || fail "pyproject missing numpy"

# Symbol contracts
grep -qE 'class IndexStore' backend/notebookai/index/store.py || fail "store.py missing IndexStore"
grep -qE 'class Embedder' backend/notebookai/index/embeddings.py || fail "embeddings.py missing Embedder"
grep -qE 'async def watch' backend/notebookai/index/watcher.py || fail "watcher.py missing async watch"
grep -qE 'class IndexBuilder|def build_for_file|def reindex' backend/notebookai/index/builder.py \
  || fail "builder.py missing IndexBuilder/build_for_file/reindex"

# CONTRACTS § Decisions row 6: kind ∈ {wiki, raw_chunk}
grep -qE "wiki" backend/notebookai/index/schema.py || fail "schema.py missing wiki kind"
grep -qE "raw_chunk" backend/notebookai/index/schema.py || fail "schema.py missing raw_chunk kind"

# Pytest passes (unit tests with mocked embedder so we don't depend on model download)
( cd backend && uv sync --quiet 2>/dev/null || uv sync 2>&1 | tail -5 )
( cd backend && uv run pytest tests/test_index.py -q ) || fail "pytest failed for test_index.py"

# Cumulative: scaffold tests still pass
( cd backend && uv run pytest tests/test_scaffold.py -q >/dev/null ) || fail "scaffold tests regressed"

assert_state_phase_pass 4
print_cookie 4
