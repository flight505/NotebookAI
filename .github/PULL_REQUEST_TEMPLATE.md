## Summary

<!-- 1-3 bullets on the user-visible change -->

## Why

<!-- Reference the VISION.md / CONTRACTS.md sections this satisfies, if applicable -->

## CONTRACTS.md impact

- [ ] No CONTRACTS.md change needed
- [ ] CONTRACTS.md amended in this PR (cite section)

## Test plan

- [ ] `cd backend && uv run pytest tests/ -m "not requires_claude"` passes
- [ ] `cd backend && uv run ruff check` passes
- [ ] `cd frontend && pnpm build` passes (if frontend touched)
- [ ] `cd desktop/src-tauri && cargo check` passes (if desktop touched)
- [ ] Manual verification of changed flows

## Screenshots / GIF

<!-- Optional, especially helpful for frontend changes -->
