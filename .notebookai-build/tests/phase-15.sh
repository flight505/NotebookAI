#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

# Files
assert_file_exists LICENSE
assert_file_exists backend/.env.example
assert_file_exists backend/notebookai/cli.py

# CLI subcommands
( cd backend && uv run notebookai --help 2>&1 | grep -qE 'serve|new|status|claude' ) \
  || fail "notebookai CLI missing subcommands"
( cd backend && uv run notebookai status --root /tmp/nbai-status-test 2>&1 | grep -qiE 'library|notebooks' ) \
  || fail "notebookai status not working"

# Integration test
assert_file_exists backend/tests/test_e2e_integration.py
( cd backend && uv run pytest tests/test_e2e_integration.py -q -m "not requires_claude" ) \
  || fail "integration tests failed"

# First-run library_root auto-create
( cd backend && uv run python -c "
import tempfile
from pathlib import Path
from notebookai.library.scanner import LibraryScanner, load_library_config

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'NotebookAI' / 'notebooks'
    assert not root.exists()
    scanner = LibraryScanner(root)
    scanner.scan()  # must not raise
    assert root.exists(), 'library_root should be auto-created on first scan'
" ) || fail "first-run library_root auto-create failed"

# Centralized config
grep -qE 'API_PORT|api_port' backend/notebookai/config.py 2>/dev/null \
  || fail "no centralized config module"
grep -qE 'NEXT_PUBLIC_API_URL|NOTEBOOKAI_API_URL' frontend/lib/api.ts \
  || fail "frontend api.ts missing centralized URL env"

# Scaffolded notebook AGENTS.md upgrade — must mention key conventions
TMPNB=$(mktemp -d -t nbai-agents-test-XXXXXX)
( cd backend && uv run python -c "
from pathlib import Path
from notebookai.scaffold import create_notebook
h = create_notebook(Path('$TMPNB'), 'agents-md-test', git_enabled=False)
" )
agents_md="$TMPNB/agents-md-test/AGENTS.md"
assert_file_exists "$agents_md"
for keyword in "raw/" "wiki/" "chats/" ".notebookai/" "karpathy-llm-wiki" "Do not edit"; do
  grep -qiE "$keyword" "$agents_md" || fail "AGENTS.md missing keyword: $keyword"
done
rm -rf "$TMPNB"

# Cumulative
( cd backend && uv run pytest tests/ -q -m "not requires_claude" >/dev/null ) || fail "cumulative regressed"

echo "PHASE-15-OK-$(sha256_of BUILD.md | cut -c1-8)"
