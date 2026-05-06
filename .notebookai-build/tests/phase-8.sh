#!/usr/bin/env bash
set -euo pipefail
source ./.notebookai-build/test-helpers.sh

run_prior_phase_tests 8

# Required files
assert_file_exists frontend/package.json
assert_file_exists frontend/tsconfig.json
assert_file_exists frontend/next.config.ts
assert_file_exists frontend/postcss.config.mjs
assert_file_exists frontend/app/layout.tsx
assert_file_exists frontend/app/page.tsx
assert_file_exists frontend/app/globals.css
assert_file_exists frontend/app/read/page.tsx
assert_file_exists frontend/lib/api.ts
assert_file_exists frontend/store/useNotebook.ts
assert_file_exists frontend/components/NotebookSwitcher.tsx
assert_file_exists frontend/components/ArticleTree.tsx
assert_file_exists frontend/components/ArticleReader.tsx
assert_file_exists frontend/components/Backlinks.tsx
assert_file_exists frontend/components/GraphView.tsx

# Package.json has required deps
require_cmd jq
node_deps=$(jq -r '.dependencies | keys | join(",")' frontend/package.json)
echo "$node_deps" | grep -q 'next' || fail "package.json missing next"
echo "$node_deps" | grep -q 'react' || fail "package.json missing react"
echo "$node_deps" | grep -q 'zustand' || fail "package.json missing zustand"
echo "$node_deps" | grep -q 'react-markdown' || fail "package.json missing react-markdown"

# Build succeeds (Turbopack)
require_cmd pnpm
( cd frontend && pnpm install --frozen-lockfile 2>/dev/null || pnpm install 2>&1 | tail -10 )
( cd frontend && pnpm build 2>&1 | tail -20 ) || fail "pnpm build failed"

assert_state_phase_pass 8
print_cookie 8
