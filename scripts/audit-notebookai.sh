#!/usr/bin/env bash
#
# audit-notebookai.sh — full repo audit.
#
# Re-runs every phase gate test (phase-0..phase-13) cumulatively, then runs
# the backend pytest suite, the backend ruff lint, the frontend build, and
# (if cargo is available) `cargo check` on the Tauri shell. Prints a summary
# with phase cookies, total tests passed, and total LOC. Exits 0 on success.
#
# Usage:  bash scripts/audit-notebookai.sh

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

C_RESET="$(printf '\033[0m')"
C_BOLD="$(printf '\033[1m')"
C_OK="$(printf '\033[32m')"
C_WARN="$(printf '\033[33m')"
C_ERR="$(printf '\033[31m')"
C_DIM="$(printf '\033[2m')"

step() { printf '\n%s== %s ==%s\n' "${C_BOLD}" "$1" "${C_RESET}"; }
ok()   { printf '%s  pass%s  %s\n' "${C_OK}" "${C_RESET}" "$1"; }
warn() { printf '%s  warn%s  %s\n' "${C_WARN}" "${C_RESET}" "$1"; }
fail() { printf '%s  fail%s  %s\n' "${C_ERR}" "${C_RESET}" "$1"; exit 1; }

PHASE_COOKIES=()
PHASES_RUN=0

step "Phase gate tests (cumulative)"
for i in $(seq 0 13); do
  test="${REPO_ROOT}/.notebookai-build/tests/phase-${i}.sh"
  if [[ ! -x "${test}" ]]; then
    fail "missing gate test: phase-${i}.sh"
  fi
  cookie=$(bash "${test}" 2>/dev/null | tail -1 || true)
  if [[ "${cookie}" == PHASE-${i}-OK-* ]]; then
    ok "phase-${i}  ${cookie}"
    PHASE_COOKIES+=("${cookie}")
    PHASES_RUN=$((PHASES_RUN + 1))
  else
    fail "phase-${i} did not emit a cookie (got: ${cookie:-<empty>})"
  fi
done

step "Backend pytest"
PYTEST_OUTPUT_FILE="$(mktemp)"
trap 'rm -f "${PYTEST_OUTPUT_FILE}"' EXIT
if ( cd backend && uv run pytest tests/ -q -m "not requires_claude" ) | tee "${PYTEST_OUTPUT_FILE}"; then
  ok "pytest passed"
else
  fail "pytest failed"
fi
PYTEST_SUMMARY=$(grep -E '[0-9]+ passed' "${PYTEST_OUTPUT_FILE}" | tail -1 || echo "no summary line")

step "Backend ruff lint"
if ( cd backend && uv run ruff check ); then
  ok "ruff clean"
else
  fail "ruff reported issues"
fi

step "Frontend build"
if ! command -v pnpm >/dev/null 2>&1; then
  fail "pnpm not found in PATH"
fi
if ( cd frontend && pnpm build ); then
  ok "frontend build succeeded"
else
  fail "frontend build failed"
fi

step "Tauri (cargo check)"
if command -v cargo >/dev/null 2>&1; then
  if ( cd desktop/src-tauri && cargo check --quiet ); then
    ok "cargo check succeeded"
  else
    fail "cargo check failed"
  fi
else
  warn "cargo not installed, skipping Tauri build check"
fi

step "Repo metrics"
LOC_PY=$(find backend/notebookai -type f -name '*.py' -print0 | xargs -0 cat 2>/dev/null | wc -l | tr -d ' ')
LOC_TS=$(find frontend/app frontend/components frontend/lib frontend/store -type f \( -name '*.ts' -o -name '*.tsx' \) -print0 2>/dev/null | xargs -0 cat 2>/dev/null | wc -l | tr -d ' ')
LOC_RS=$(find desktop/src-tauri/src -type f -name '*.rs' -print0 2>/dev/null | xargs -0 cat 2>/dev/null | wc -l | tr -d ' ')
LOC_TOTAL=$(( LOC_PY + LOC_TS + LOC_RS ))

printf '  %sBackend Python%s   %s lines\n' "${C_DIM}" "${C_RESET}" "${LOC_PY}"
printf '  %sFrontend TS/TSX%s  %s lines\n' "${C_DIM}" "${C_RESET}" "${LOC_TS}"
printf '  %sTauri Rust%s       %s lines\n' "${C_DIM}" "${C_RESET}" "${LOC_RS}"
printf '  %sTotal LOC%s        %s lines\n' "${C_DIM}" "${C_RESET}" "${LOC_TOTAL}"

step "Summary"
printf '  Phases verified : %d / 14\n' "${PHASES_RUN}"
printf '  Pytest          : %s\n' "${PYTEST_SUMMARY}"
printf '  Total LOC       : %s\n' "${LOC_TOTAL}"
printf '  Phase cookies   :\n'
for c in "${PHASE_COOKIES[@]}"; do
  printf '    %s\n' "${c}"
done

printf '\n%sNotebookAI audit: PASS%s\n' "${C_OK}" "${C_RESET}"
exit 0
