#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 1
assert_file_exists docs/CONTRACTS.md

for h in "Decisions" "Notebook Directory Schema" "REST API surface" "SSE event types" "Subagent Return Schema" "AgentTool inventory" "FileWatcher events" "GitCommit conventions"; do
  grep -qE "^## .*${h}" docs/CONTRACTS.md || fail "CONTRACTS.md missing section: $h"
done

! grep -q "<TODO>" docs/CONTRACTS.md || fail "TODO token in CONTRACTS.md"
! grep -qi "lorem ipsum" docs/CONTRACTS.md || fail "lorem ipsum in CONTRACTS.md"

assert_state_phase_pass 1
print_cookie 1
