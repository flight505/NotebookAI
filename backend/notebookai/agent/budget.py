"""Per-notebook, per-day token budget for lint operations.

The lint engine asks :class:`BudgetTracker` whether a given Haiku call may
proceed; the tracker reads/writes the ``LintBudget`` table on ``index.db``
via :class:`IndexStore`. Budgets are reset by date (UTC) so a new row is
created on the first call each new UTC day.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from ulid import ULID

from notebookai.index.schema import LintBudget
from notebookai.index.store import IndexStore


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


class TokenBudget(BaseModel):
    """Snapshot of a single ``LintBudget`` row for the API surface."""

    model_config = ConfigDict(from_attributes=True)

    notebook_id: str
    day: date
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    input_limit: int = 50_000
    output_limit: int = 10_000
    last_op_at: datetime | None = None
    denied_op_count: int = 0


class BudgetExceeded(RuntimeError):
    """Raised by the lint engine when a planned spend would exceed limits."""

    def __init__(self, reason: str, *, snapshot: TokenBudget | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.snapshot = snapshot


class BudgetTracker:
    """SQLAlchemy-backed accumulator over the ``LintBudget`` table.

    All reads and writes go through ``IndexStore.session()`` so they run in
    the same SQLite database as the rest of the index.
    """

    def __init__(
        self,
        store: IndexStore,
        notebook_id: str,
        *,
        input_limit: int = 50_000,
        output_limit: int = 10_000,
    ) -> None:
        self.store = store
        self.notebook_id = notebook_id
        self.input_limit = int(input_limit)
        self.output_limit = int(output_limit)

    # ------------------------------------------------------------------
    def _row_for(self, day: date) -> dict[str, Any]:
        """Read or create the row for ``day`` and return a dict snapshot."""
        with self.store.session() as s:
            row = s.scalar(
                select(LintBudget).where(
                    LintBudget.notebook_id == self.notebook_id,
                    LintBudget.day == day,
                )
            )
            if row is None:
                row = LintBudget(
                    id=str(ULID()),
                    notebook_id=self.notebook_id,
                    day=day,
                    input_tokens_used=0,
                    output_tokens_used=0,
                    input_limit=self.input_limit,
                    output_limit=self.output_limit,
                    last_op_at=None,
                    denied_op_count=0,
                )
                s.add(row)
            else:
                # Reflect tracker-level limit changes into a stale row.
                row.input_limit = self.input_limit
                row.output_limit = self.output_limit
            return {
                "notebook_id": row.notebook_id,
                "day": row.day,
                "input_tokens_used": row.input_tokens_used,
                "output_tokens_used": row.output_tokens_used,
                "input_limit": row.input_limit,
                "output_limit": row.output_limit,
                "last_op_at": row.last_op_at,
                "denied_op_count": row.denied_op_count,
            }

    # ------------------------------------------------------------------
    def get_today(self) -> TokenBudget:
        return TokenBudget(**self._row_for(_today_utc()))

    # ------------------------------------------------------------------
    def can_spend(
        self,
        *,
        estimated_input: int,
        estimated_output: int,
    ) -> tuple[bool, str]:
        snap = self.get_today()
        if estimated_input < 0 or estimated_output < 0:
            return False, "negative spend not allowed"
        if snap.input_limit <= 0 and estimated_input > 0:
            return False, "input limit is zero"
        if snap.output_limit <= 0 and estimated_output > 0:
            return False, "output limit is zero"
        if snap.input_tokens_used + estimated_input > snap.input_limit:
            return (
                False,
                f"input budget would be exceeded: "
                f"{snap.input_tokens_used}+{estimated_input} > {snap.input_limit}",
            )
        if snap.output_tokens_used + estimated_output > snap.output_limit:
            return (
                False,
                f"output budget would be exceeded: "
                f"{snap.output_tokens_used}+{estimated_output} > {snap.output_limit}",
            )
        return True, "ok"

    # ------------------------------------------------------------------
    def record_spend(self, *, input_tokens: int, output_tokens: int) -> None:
        day = _today_utc()
        with self.store.session() as s:
            row = s.scalar(
                select(LintBudget).where(
                    LintBudget.notebook_id == self.notebook_id,
                    LintBudget.day == day,
                )
            )
            if row is None:
                row = LintBudget(
                    id=str(ULID()),
                    notebook_id=self.notebook_id,
                    day=day,
                    input_tokens_used=int(max(0, input_tokens)),
                    output_tokens_used=int(max(0, output_tokens)),
                    input_limit=self.input_limit,
                    output_limit=self.output_limit,
                    last_op_at=datetime.now(timezone.utc),
                    denied_op_count=0,
                )
                s.add(row)
                return
            row.input_tokens_used = int(row.input_tokens_used) + int(max(0, input_tokens))
            row.output_tokens_used = int(row.output_tokens_used) + int(max(0, output_tokens))
            row.last_op_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    def record_denial(self) -> None:
        day = _today_utc()
        with self.store.session() as s:
            row = s.scalar(
                select(LintBudget).where(
                    LintBudget.notebook_id == self.notebook_id,
                    LintBudget.day == day,
                )
            )
            if row is None:
                row = LintBudget(
                    id=str(ULID()),
                    notebook_id=self.notebook_id,
                    day=day,
                    input_tokens_used=0,
                    output_tokens_used=0,
                    input_limit=self.input_limit,
                    output_limit=self.output_limit,
                    last_op_at=None,
                    denied_op_count=1,
                )
                s.add(row)
                return
            row.denied_op_count = int(row.denied_op_count) + 1

    # ------------------------------------------------------------------
    def update_limits(self, *, input_limit: int | None = None, output_limit: int | None = None) -> TokenBudget:
        if input_limit is not None:
            self.input_limit = int(input_limit)
        if output_limit is not None:
            self.output_limit = int(output_limit)
        # Materialise so the row reflects the new limits immediately.
        return TokenBudget(**self._row_for(_today_utc()))

    # ------------------------------------------------------------------
    def reset(self, day: date | None = None) -> None:
        """Test helper: drop the row for ``day`` (defaults to today)."""
        target = day or _today_utc()
        with self.store.session() as s:
            row = s.scalar(
                select(LintBudget).where(
                    LintBudget.notebook_id == self.notebook_id,
                    LintBudget.day == target,
                )
            )
            if row is not None:
                s.delete(row)


__all__ = [
    "TokenBudget",
    "BudgetTracker",
    "BudgetExceeded",
]
