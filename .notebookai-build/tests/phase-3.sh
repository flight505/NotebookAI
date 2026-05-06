#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 3

# Required files exist
assert_file_exists backend/pyproject.toml
assert_file_exists backend/notebookai/__init__.py
assert_file_exists backend/notebookai/scaffold.py
assert_file_exists backend/notebookai/cli.py
assert_file_exists backend/tests/test_scaffold.py

# pyproject.toml has required deps
grep -qE 'pydantic' backend/pyproject.toml || fail "pyproject.toml missing pydantic"
grep -qE 'sqlalchemy' backend/pyproject.toml || fail "pyproject.toml missing sqlalchemy"
grep -qE 'watchfiles' backend/pyproject.toml || fail "pyproject.toml missing watchfiles"
grep -qE 'structlog' backend/pyproject.toml || fail "pyproject.toml missing structlog"
grep -qE 'pytest' backend/pyproject.toml || fail "pyproject.toml missing pytest"

# scaffold.py exposes create_notebook
grep -qE 'def create_notebook' backend/notebookai/scaffold.py || fail "scaffold.py missing create_notebook"

# Pytest runs and passes
require_cmd uv
( cd backend && uv sync --quiet 2>/dev/null || uv sync 2>&1 | tail -5 )
( cd backend && uv run pytest tests/test_scaffold.py -q ) || fail "pytest failed"

# Round-trip scaffold smoke test: create a notebook in /tmp, verify CONTRACTS-mandated layout
TMPNB=$(mktemp -d -t nbai-scaffold-XXXXXX)
( cd backend && uv run python -c "
from pathlib import Path
from notebookai.scaffold import create_notebook
h = create_notebook(Path('$TMPNB'), 'smoke-test')
print(h)
" )

# CONTRACTS § Notebook Directory Schema invariants
nb="$TMPNB/smoke-test"
assert_dir_exists "$nb"
assert_file_exists "$nb/.notebookai/notebook.json"
assert_dir_exists "$nb/.notebookai/locks"
assert_dir_exists "$nb/raw"
assert_dir_exists "$nb/wiki"
assert_dir_exists "$nb/chats"
assert_file_exists "$nb/wiki/index.md"
assert_file_exists "$nb/wiki/log.md"
assert_file_exists "$nb/AGENTS.md"
assert_file_exists "$nb/README.md"
assert_file_exists "$nb/.gitignore"
assert_file_exists "$nb/.claude/skills/karpathy-llm-wiki/SKILL.md"
assert_file_exists "$nb/.agents/skills/karpathy-llm-wiki/SKILL.md"

# Symlink (or copy) of the skill must resolve to a SKILL.md with valid frontmatter
head -5 "$nb/.claude/skills/karpathy-llm-wiki/SKILL.md" | grep -qE '^name:' \
  || fail "skill symlink does not resolve to a valid SKILL.md"

# notebook.json conforms to CONTRACTS schema
jq -e '.id == "smoke-test" and (.name | length > 0) and (.created_at | length > 0) and (.schema_version | type == "number") and (.git_enabled | type == "boolean")' \
  "$nb/.notebookai/notebook.json" >/dev/null \
  || fail "notebook.json does not conform to CONTRACTS schema"

# Cleanup
rm -rf "$TMPNB"

assert_state_phase_pass 3
print_cookie 3
