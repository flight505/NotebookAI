#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 2
assert_file_exists skills/karpathy-llm-wiki/SKILL.md
assert_file_exists skills/karpathy-llm-wiki/references/raw-template.md
assert_file_exists skills/karpathy-llm-wiki/references/article-template.md
assert_file_exists skills/karpathy-llm-wiki/references/index-template.md
assert_file_exists skills/karpathy-llm-wiki/references/archive-template.md
assert_file_exists skills/karpathy-llm-wiki/README.md

grep -qE "^name: " skills/karpathy-llm-wiki/SKILL.md || fail "SKILL.md missing name frontmatter"
grep -qE "^description: " skills/karpathy-llm-wiki/SKILL.md || fail "SKILL.md missing description frontmatter"

assert_state_phase_pass 2
print_cookie 2
