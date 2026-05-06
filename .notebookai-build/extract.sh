#!/usr/bin/env bash
# Extracts TOOL and TEST blocks from BUILD.md to .notebookai-build/{,tests/}.
set -euo pipefail

SOURCE="${1:-BUILD.md}"
[[ -f "$SOURCE" ]] || { echo "extract.sh: source not found: $SOURCE" >&2; exit 1; }

mkdir -p .notebookai-build/tests

extract_kind() {
  local kind="$1" outdir="$2"
  local current="" in_block=0 line
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^"<!-- ${kind}:"([^[:space:]]+)" -->"$ ]]; then
      current="${BASH_REMATCH[1]}"
      mkdir -p "$(dirname "$outdir/$current")"
      : > "$outdir/$current"
      in_block=1
    elif [[ "$line" == "<!-- /${kind} -->" ]]; then
      in_block=0
      current=""
    elif (( in_block )); then
      printf '%s\n' "$line" >> "$outdir/$current"
    fi
  done < "$SOURCE"
}

extract_kind "TOOL" ".notebookai-build"
extract_kind "TEST" ".notebookai-build/tests"

find .notebookai-build -maxdepth 2 -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
echo "extract.sh: done"
