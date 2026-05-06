#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 14

# Final docs + audit
assert_file_exists README.md
assert_file_exists docs/architecture.md
assert_file_exists scripts/audit-notebookai.sh
assert_file_exists .claude/skills/audit-notebookai/SKILL.md

# README has required sections
for h in "Install" "Quick start" "Architecture" "Build status"; do
  grep -qiE "^#{1,3} .*${h}" README.md || fail "README.md missing section: $h"
done

# Audit skill frontmatter
grep -qE '^name:' .claude/skills/audit-notebookai/SKILL.md \
  || fail "audit-notebookai SKILL.md missing name frontmatter"
grep -qE '^description:' .claude/skills/audit-notebookai/SKILL.md \
  || fail "audit-notebookai SKILL.md missing description frontmatter"

# Audit script runs cumulatively
[[ -x scripts/audit-notebookai.sh ]] || fail "audit-notebookai.sh not executable"
bash scripts/audit-notebookai.sh 2>&1 | tail -5 || fail "audit script failed"

# Cumulative — every prior phase test is included via run_prior_phase_tests above

assert_state_phase_pass 14
prefix=$(sha256_of BUILD.md | cut -c1-8)
echo "BUILD-COMPLETE-${prefix}-$(date -u +%Y%m%dT%H%M%SZ)"
