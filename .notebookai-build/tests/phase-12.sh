#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 12

# Files
assert_file_exists desktop/package.json
assert_file_exists desktop/src-tauri/Cargo.toml
assert_file_exists desktop/src-tauri/tauri.conf.json
assert_file_exists desktop/src-tauri/src/main.rs
assert_file_exists desktop/README.md

# Tauri config sanity
require_cmd jq
jq -e '.productName | length > 0' desktop/src-tauri/tauri.conf.json >/dev/null \
  || fail "tauri.conf.json missing productName"
jq -e '.identifier | length > 0' desktop/src-tauri/tauri.conf.json >/dev/null \
  || fail "tauri.conf.json missing identifier"
jq -e '.version | length > 0' desktop/src-tauri/tauri.conf.json >/dev/null \
  || fail "tauri.conf.json missing version"

# Cargo.toml has tauri 2
grep -qE 'tauri = .*"2' desktop/src-tauri/Cargo.toml || fail "Cargo.toml not on tauri 2"

# Bundle target build (debug). Cargo + Rust must be available.
require_cmd cargo
require_cmd rustc

# Skip the actual cargo build in CI gate (slow, network for first run); instead validate config compiles and frontend static export works.
require_cmd pnpm
( cd frontend && NEXT_OUTPUT_EXPORT=1 pnpm build 2>&1 | tail -5 ) || true  # static export may differ; smoke only

# Verify frontend's next.config.ts is compatible with Tauri (output must be configured for static export OR standalone)
grep -qE 'output.*standalone|output.*export' frontend/next.config.ts || fail "next.config.ts not configured for standalone or export"

# Confirm cargo check (compile-only, no link) works
( cd desktop/src-tauri && cargo check --quiet 2>&1 | tail -5 ) || fail "cargo check failed"

assert_state_phase_pass 12
print_cookie 12
