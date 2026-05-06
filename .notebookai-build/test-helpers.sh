#!/usr/bin/env bash
# Assertion helpers shared by every phase test.
# Usage: source ./.notebookai-build/test-helpers.sh

fail() { echo "FAIL: $*" >&2; exit 1; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }

sha256_of() {
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" | awk '{print $1}'
  else
    shasum -a 256 "$f" | awk '{print $1}'
  fi
}

assert_file_exists() { [[ -f "$1" ]] || fail "expected file: $1"; }
assert_dir_exists() { [[ -d "$1" ]] || fail "expected directory: $1"; }

assert_state_phase_pass() {
  local n="$1"
  local status
  status=$(jq -r ".phases.\"$n\".status // \"missing\"" .notebookai-build/state.json)
  [[ "$status" == "pass" ]] || fail "phase $n status: $status"
}

assert_build_md_unchanged() {
  local recorded actual
  recorded=$(jq -r '.checksums."BUILD.md"' .notebookai-build/state.json)
  actual="sha256:$(sha256_of BUILD.md)"
  [[ "$recorded" == "$actual" ]] || fail "BUILD.md sha256 changed since Phase 0 (recorded=$recorded actual=$actual)"
}

run_prior_phase_tests() {
  local upto="$1"
  local i
  for ((i=0; i<upto; i++)); do
    [[ -x ".notebookai-build/tests/phase-$i.sh" ]] || fail "missing prior test: phase-$i.sh"
    bash ".notebookai-build/tests/phase-$i.sh" >/dev/null || fail "prior phase $i regressed"
  done
}

print_cookie() {
  local phase="$1"
  local prefix
  prefix=$(sha256_of BUILD.md | cut -c1-8)
  echo "PHASE-${phase}-OK-${prefix}"
}
