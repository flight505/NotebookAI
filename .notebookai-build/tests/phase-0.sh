#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

require_cmd git
require_cmd jq
require_cmd python3
require_cmd node
require_cmd pnpm

assert_file_exists BUILD.md
assert_file_exists .notebookai-build/state.json
assert_file_exists .notebookai-build/extract.sh
assert_file_exists .notebookai-build/test-helpers.sh

assert_dir_exists backend
assert_dir_exists frontend
assert_dir_exists desktop
assert_dir_exists skills
assert_dir_exists docs
assert_dir_exists scripts

assert_build_md_unchanged
assert_state_phase_pass 0

# Working tree clean post-commit
git diff --quiet || fail "working tree dirty"
git diff --cached --quiet || fail "staged changes present"

print_cookie 0
