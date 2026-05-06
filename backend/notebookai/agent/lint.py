"""Lint engine — orchestrates passive watcher + Haiku-driven checks.

`light_lint` always runs the free passive watcher first; only if the budget
allows does it call Haiku for heuristic checks (contradictions, missing
cross-refs, stale claims). `full_lint` runs the same plus deeper checks.

Each Haiku call is gated by :class:`BudgetTracker.can_spend`; spends are
recorded after the agent reports usage. Denials raise
:class:`BudgetExceeded`.

Accepting a finding with a ``suggested_fix`` triggers a separate
``AgentSession(op="lint-fix")`` constrained to the target file. Before
committing, we verify ``git diff --name-only`` matches the expected target;
if the agent strayed beyond scope we revert.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID

from notebookai.agent.budget import BudgetExceeded, BudgetTracker
from notebookai.agent.events import AgentDone, AgentError
from notebookai.agent.runtime import AgentRuntime
from notebookai.index.schema import LintFinding as LintFindingRow
from notebookai.index.store import IndexStore

log = structlog.get_logger(__name__)


_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_DEFAULT_INPUT_BUDGET = 50_000
_DEFAULT_OUTPUT_BUDGET = 10_000
_HAIKU_LIGHT_INPUT_ESTIMATE = 4_000
_HAIKU_LIGHT_OUTPUT_ESTIMATE = 1_000
_HAIKU_FULL_INPUT_ESTIMATE = 12_000
_HAIKU_FULL_OUTPUT_ESTIMATE = 2_500


FindingStatus = Literal["open", "accepted", "rejected", "auto_fixed"]
FindingSource = Literal["passive", "haiku", "user"]


class Finding(BaseModel):
    """A single lint finding — passive, Haiku-derived, or user-reported."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(ULID()))
    kind: str
    path: str
    message: str
    suggested_fix: str | None = None
    status: FindingStatus = "open"
    source: FindingSource = "passive"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model: str | None = None
    usage: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class LintEngine:
    """Coordinates passive scans and Haiku-driven heuristic checks."""

    def __init__(
        self,
        runtime: AgentRuntime,
        store: IndexStore,
        notebook_id: str,
        *,
        lint_model: str = _HAIKU_MODEL,
        input_limit: int = _DEFAULT_INPUT_BUDGET,
        output_limit: int = _DEFAULT_OUTPUT_BUDGET,
    ) -> None:
        self.runtime = runtime
        self.store = store
        self.notebook_id = notebook_id
        self.lint_model = lint_model
        self.budget = BudgetTracker(
            store,
            notebook_id,
            input_limit=input_limit,
            output_limit=output_limit,
        )

    # ------------------------------------------------------------------
    # Passive sweep wrapper
    # ------------------------------------------------------------------
    def _run_passive(self, notebook_root: Path) -> list[Finding]:
        # Local import to avoid module cycle at import time.
        from notebookai.agent.passive_watcher import PassiveWatcher

        watcher = PassiveWatcher(store=self.store, notebook_id=self.notebook_id)
        return watcher._scan_sync(notebook_root)

    # ------------------------------------------------------------------
    async def light_lint(self, notebook_root: Path) -> list[Finding]:
        """Free passive scan + budget-gated Haiku light checks."""
        findings: list[Finding] = list(self._run_passive(notebook_root))
        try:
            haiku_findings = await self._run_haiku(
                notebook_root,
                mode="light",
                input_estimate=_HAIKU_LIGHT_INPUT_ESTIMATE,
                output_estimate=_HAIKU_LIGHT_OUTPUT_ESTIMATE,
            )
            findings.extend(haiku_findings)
        except BudgetExceeded as exc:
            log.info(
                "lint_budget_exceeded",
                notebook_id=self.notebook_id,
                reason=exc.reason,
            )
        self._persist_findings(findings)
        return findings

    # ------------------------------------------------------------------
    async def full_lint(self, notebook_root: Path) -> list[Finding]:
        findings: list[Finding] = list(self._run_passive(notebook_root))
        try:
            haiku_findings = await self._run_haiku(
                notebook_root,
                mode="full",
                input_estimate=_HAIKU_FULL_INPUT_ESTIMATE,
                output_estimate=_HAIKU_FULL_OUTPUT_ESTIMATE,
            )
            findings.extend(haiku_findings)
        except BudgetExceeded as exc:
            log.info(
                "lint_budget_exceeded",
                notebook_id=self.notebook_id,
                reason=exc.reason,
            )
        self._persist_findings(findings)
        return findings

    # ------------------------------------------------------------------
    async def _run_haiku(
        self,
        notebook_root: Path,
        *,
        mode: Literal["light", "full"],
        input_estimate: int,
        output_estimate: int,
    ) -> list[Finding]:
        ok, reason = self.budget.can_spend(
            estimated_input=input_estimate,
            estimated_output=output_estimate,
        )
        if not ok:
            self.budget.record_denial()
            raise BudgetExceeded(reason, snapshot=self.budget.get_today())

        if mode == "light":
            extra = (
                "Run a *light* scan of wiki/. Look only for: missing 'See also' "
                "cross-references between closely-related articles, and "
                "blatantly stale claims (dates that have passed, version "
                "numbers superseded). Reply with a JSON array of findings. "
                "Each item: {kind, path, message, suggested_fix?}."
            )
        else:
            extra = (
                "Run a *full* scan of wiki/: factual contradictions across "
                "articles, orphan pages with no inbound links, missing "
                "concepts referenced by index.md but not present, and stale "
                "claims. Reply with a JSON array of findings as above."
            )

        # Scope limit: the agent must not write files in this op.
        async with self.runtime.session(
            notebook_root, op="lint", model=self.lint_model
        ) as session:
            usage: dict[str, Any] = {}
            text_out: list[str] = []
            err: AgentError | None = None
            async for ev in session.run(
                "Begin the lint scan. Respond with only the JSON array.",
                system_prompt_extra=extra,
            ):
                if isinstance(ev, AgentDone):
                    usage = dict(ev.usage or {})
                    if ev.summary:
                        text_out.append(ev.summary)
                elif isinstance(ev, AgentError):
                    err = ev

        # Record spend regardless of parse success — the tokens were burned.
        in_tok = int(usage.get("input_tokens") or 0)
        out_tok = int(usage.get("output_tokens") or 0)
        if in_tok or out_tok:
            self.budget.record_spend(input_tokens=in_tok, output_tokens=out_tok)

        if err is not None:
            log.warning(
                "haiku_lint_error",
                notebook_id=self.notebook_id,
                error=err.message,
            )
            return []

        return _parse_findings(
            "\n".join(text_out),
            model=self.lint_model,
            usage=usage,
        )

    # ------------------------------------------------------------------
    async def apply_finding(
        self,
        finding_id: str,
        notebook_root: Path,
    ) -> str:
        """Apply a finding's suggested_fix; returns the resulting commit SHA."""
        with self.store.session() as s:
            row = s.get(LintFindingRow, finding_id)
            if row is None or row.notebook_id != self.notebook_id:
                raise ValueError(f"finding {finding_id!r} not found")
            payload = dict(row.payload or {})
            target_path = str(payload.get("path") or "")
            suggested = payload.get("suggested_fix")
            kind = row.kind

        if not target_path:
            raise ValueError("finding payload missing 'path'")
        if not suggested:
            raise ValueError("finding has no suggested_fix to apply")

        prompt = (
            f"Apply this fix to `{target_path}` and ONLY this file.\n\n"
            f"Finding kind: {kind}\n"
            f"Suggested fix:\n{suggested}\n\n"
            "Make no other changes. After editing, exit; the runner will commit."
        )

        before = _git_head_files(notebook_root)
        async with self.runtime.session(
            notebook_root, op="lint-fix", model=self.lint_model
        ) as session:
            async for _ev in session.run(prompt):
                pass

        # Verify scope: only the target file may have changed.
        changed = _git_changed_paths(notebook_root)
        unexpected = [c for c in changed if c != target_path]
        if unexpected:
            log.warning(
                "lint_fix_scope_violation",
                target=target_path,
                unexpected=unexpected,
            )
            _git_revert_paths(notebook_root, unexpected)
            changed = [c for c in changed if c == target_path]

        # Mark accepted regardless of commit (caller still wants the row updated).
        with self.store.session() as s:
            row = s.get(LintFindingRow, finding_id)
            if row is not None:
                row.status = "auto_fixed"

        _ = before  # placeholder for diff-size logging
        sha = _commit(
            notebook_root,
            f"[lint-fix] {kind} in {target_path}",
            self.lint_model,
        )
        return sha

    # ------------------------------------------------------------------
    def _persist_findings(self, findings: list[Finding]) -> None:
        if not findings:
            return
        with self.store.session() as s:
            for f in findings:
                row = LintFindingRow(
                    id=f.id,
                    notebook_id=self.notebook_id,
                    kind=f.kind,
                    status=f.status,
                    payload={
                        "path": f.path,
                        "message": f.message,
                        "suggested_fix": f.suggested_fix,
                        "source": f.source,
                        "model": f.model,
                        "usage": f.usage,
                    },
                )
                s.add(row)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_findings(
    text: str,
    *,
    model: str,
    usage: dict[str, Any] | None,
) -> list[Finding]:
    """Best-effort JSON-array extraction from the agent's reply.

    The agent is instructed to reply with a JSON array. We tolerate prose
    around it by finding the first ``[`` and the matching ``]``.
    """
    import json
    import re

    if not text:
        return []
    # Try fenced block first.
    fenced = re.search(r"```json\s*(\[.*?\])\s*```", text, flags=re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        candidate = text[start : end + 1]
    try:
        items = json.loads(candidate)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []

    findings: list[Finding] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "").strip()
        path = str(it.get("path") or "").strip()
        message = str(it.get("message") or "").strip()
        if not kind or not message:
            continue
        suggested = it.get("suggested_fix")
        findings.append(
            Finding(
                kind=kind,
                path=path,
                message=message,
                suggested_fix=str(suggested) if suggested else None,
                source="haiku",
                model=model,
                usage=dict(usage) if usage else None,
            )
        )
    return findings


def _git_head_files(notebook_root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=str(notebook_root),
            check=False,
            capture_output=True,
            text=True,
        )
        return [line for line in (out.stdout or "").splitlines() if line.strip()]
    except FileNotFoundError:
        return []


def _git_changed_paths(notebook_root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=str(notebook_root),
            check=False,
            capture_output=True,
            text=True,
        )
        return [line for line in (out.stdout or "").splitlines() if line.strip()]
    except FileNotFoundError:
        return []


def _git_revert_paths(notebook_root: Path, paths: list[str]) -> None:
    if not paths:
        return
    try:
        subprocess.run(
            ["git", "checkout", "--", *paths],
            cwd=str(notebook_root),
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        return


def _commit(notebook_root: Path, subject: str, model: str) -> str:
    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(notebook_root),
            check=False,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=NotebookAI Agent",
                "-c",
                "user.email=agent@notebookai.local",
                "commit",
                "--allow-empty",
                "-m",
                f"{subject}\n\nagent-model: {model}",
            ],
            cwd=str(notebook_root),
            check=False,
            capture_output=True,
        )
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(notebook_root),
            check=False,
            capture_output=True,
            text=True,
        )
        return (rev.stdout or "").strip()
    except FileNotFoundError:
        return ""


__all__ = [
    "Finding",
    "LintEngine",
    "BudgetExceeded",
]
