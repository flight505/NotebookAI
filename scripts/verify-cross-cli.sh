#!/usr/bin/env bash
#
# verify-cross-cli.sh — manual proof that NotebookAI notebooks are
# agent-portable. Scaffolds a fresh notebook, then asks the human operator
# to drive an external CLI (Claude Code, Codex, Cursor, Antigravity, …)
# against it. After they return, we assert the expected wiki article was
# written.
#
# Phase 13 gate only checks executability; only the human runs the steps.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="/tmp/nbai-cross-cli-test"
NOTEBOOK_NAME="cross-cli-demo"
NOTEBOOK_DIR="${TEST_ROOT}/${NOTEBOOK_NAME}"
EXPECTED_ARTICLE="wiki/test/test-article.md"

print_step() {
  printf '\n=== %s ===\n' "$1"
}

print_step "Cross-CLI portability verification"

if [[ -d "${NOTEBOOK_DIR}" ]]; then
  echo "Removing prior test notebook at ${NOTEBOOK_DIR}"
  rm -rf "${NOTEBOOK_DIR}"
fi

mkdir -p "${TEST_ROOT}"

print_step "Scaffolding fresh notebook"
cd "${REPO_ROOT}/backend"
uv run python -c "
from pathlib import Path
from notebookai.scaffold import create_notebook
handle = create_notebook(Path('${TEST_ROOT}'), '${NOTEBOOK_NAME}', git_enabled=True)
print('Scaffolded:', handle.root)
"

if [[ ! -f "${NOTEBOOK_DIR}/.notebookai/notebook.json" ]]; then
  echo "FAIL: scaffold did not produce ${NOTEBOOK_DIR}/.notebookai/notebook.json"
  exit 1
fi
if [[ ! -f "${NOTEBOOK_DIR}/.claude/skills/karpathy-llm-wiki/SKILL.md" ]]; then
  echo "FAIL: skill bundle not installed at .claude/skills/karpathy-llm-wiki/SKILL.md"
  exit 1
fi
if [[ ! -f "${NOTEBOOK_DIR}/.agents/skills/karpathy-llm-wiki/SKILL.md" ]]; then
  echo "FAIL: skill bundle not installed at .agents/skills/karpathy-llm-wiki/SKILL.md"
  exit 1
fi

print_step "Manual step"
cat <<EOF

Now \`cd ${NOTEBOOK_DIR} && claude\` (or codex/cursor/antigravity)
and execute:

  Use the karpathy-llm-wiki skill to write a wiki article called
  Test Article in topic test about anything you know.

When done, return here and press Enter.

EOF

read -r _

print_step "Verifying"
if [[ -f "${NOTEBOOK_DIR}/${EXPECTED_ARTICLE}" ]]; then
  echo "PASS: external CLI wrote a wiki article. Cross-CLI portability verified."
  echo "  -> ${NOTEBOOK_DIR}/${EXPECTED_ARTICLE}"
  exit 0
else
  echo "FAIL: no wiki article written. Check that the CLI honored the skill at"
  echo "      .claude/skills/karpathy-llm-wiki/SKILL.md"
  echo "      (expected file: ${NOTEBOOK_DIR}/${EXPECTED_ARTICLE})"
  exit 1
fi
