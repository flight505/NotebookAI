"""Phase 10 — lint engine + budget tests.

All Haiku calls are mocked; no real Claude credentials needed.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from notebookai.agent.budget import BudgetExceeded, BudgetTracker, TokenBudget
from notebookai.agent.events import AgentDone
from notebookai.agent.lint import Finding, LintEngine
from notebookai.agent.runtime import AgentRuntime
from notebookai.index.store import IndexStore


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_notebook(root: Path, *, nb_id: str = "nb") -> Path:
    nb = root / nb_id
    (nb / ".notebookai").mkdir(parents=True)
    (nb / "wiki").mkdir()
    (nb / "raw").mkdir()
    (nb / "chats").mkdir()
    (nb / ".notebookai" / "notebook.json").write_text(
        json.dumps(
            {
                "id": nb_id,
                "name": nb_id,
                "created_at": "2026-01-01T00:00:00Z",
                "schema_version": 1,
                "git_enabled": False,
                "embeddings": {"model": "fake", "dim": 32},
            }
        ),
        encoding="utf-8",
    )
    return nb


def _store(nb_root: Path) -> IndexStore:
    s = IndexStore(nb_root)
    s.bootstrap()
    return s


class _FakeSession:
    """Stand-in AgentSession that yields a synthetic AgentDone."""

    def __init__(
        self,
        *,
        notebook_root: Path,
        op: str,
        model: str,
        summary: str = "[]",
        usage: dict | None = None,
    ) -> None:
        self.notebook_root = Path(notebook_root)
        self.op = op
        self.model = model
        self.op_id = "01HFAKEOP"
        self.notebook_id = self.notebook_root.name
        self._summary = summary
        self._usage = usage or {"input_tokens": 0, "output_tokens": 0}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def run(self, prompt, *, system_prompt_extra=None):
        yield AgentDone(
            notebook_id=self.notebook_id,
            op_id=self.op_id,
            op=self.op,
            summary=self._summary,
            usage=self._usage,
        )


def _runtime_with_session(summary: str = "[]", usage: dict | None = None) -> AgentRuntime:
    rt = AgentRuntime()
    rt.session = lambda root, *, op, model=None: _FakeSession(  # type: ignore[assignment]
        notebook_root=root,
        op=op,
        model=model or rt.model,
        summary=summary,
        usage=usage or {"input_tokens": 0, "output_tokens": 0},
    )
    return rt


# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------


def test_finding_dataclass() -> None:
    f = Finding(
        kind="orphan_raw",
        path="raw/ml/foo.md",
        message="not cited",
        suggested_fix=None,
        source="passive",
    )
    assert f.id
    assert f.status == "open"
    assert f.source == "passive"
    d = f.model_dump()
    assert d["kind"] == "orphan_raw"
    f2 = Finding.model_validate(d)
    assert f2.id == f.id
    assert f2.message == f.message


# ---------------------------------------------------------------------------
# Budget tracker
# ---------------------------------------------------------------------------


def test_budget_tracker_basic(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    store = _store(nb)
    try:
        bt = BudgetTracker(store, "nb", input_limit=1000, output_limit=200)
        snap = bt.get_today()
        assert snap.input_tokens_used == 0
        assert snap.input_limit == 1000

        ok, _ = bt.can_spend(estimated_input=500, estimated_output=100)
        assert ok

        bt.record_spend(input_tokens=500, output_tokens=100)
        snap = bt.get_today()
        assert snap.input_tokens_used == 500
        assert snap.output_tokens_used == 100

        # Now overdraft.
        ok, reason = bt.can_spend(estimated_input=600, estimated_output=10)
        assert not ok
        assert "input" in reason
    finally:
        store.close()


def test_budget_tracker_resets_daily(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    store = _store(nb)
    try:
        bt = BudgetTracker(store, "nb", input_limit=1000, output_limit=200)
        # Inject a fake row dated yesterday — should not count for today's budget.
        from notebookai.index.schema import LintBudget
        from ulid import ULID as _ULID

        yesterday = date.today() - timedelta(days=1)
        with store.session() as s:
            s.add(
                LintBudget(
                    id=str(_ULID()),
                    notebook_id="nb",
                    day=yesterday,
                    input_tokens_used=999,
                    output_tokens_used=199,
                    input_limit=1000,
                    output_limit=200,
                    last_op_at=None,
                    denied_op_count=0,
                )
            )

        snap = bt.get_today()
        assert snap.input_tokens_used == 0
        ok, _ = bt.can_spend(estimated_input=900, estimated_output=150)
        assert ok
    finally:
        store.close()


# ---------------------------------------------------------------------------
# LintEngine — light + budget gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lint_engine_light_uses_passive_only_when_budget_zero(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    # Create one passive finding (orphan_raw).
    (nb / "raw" / "ml").mkdir(parents=True)
    (nb / "raw" / "ml" / "foo.md").write_text("body\n", encoding="utf-8")

    store = _store(nb)
    try:
        rt = _runtime_with_session(summary="[]")  # would be called only if budget allows
        # Track session calls.
        session_calls: list = []
        original = rt.session

        def _spy(root, *, op, model=None):
            session_calls.append((op, model))
            return original(root, op=op, model=model)

        rt.session = _spy  # type: ignore[assignment]

        engine = LintEngine(rt, store, "nb", input_limit=0, output_limit=0)
        findings = await engine.light_lint(nb)

        # Passive finding should be returned
        assert any(f.source == "passive" and f.kind == "orphan_raw" for f in findings)
        # No Haiku session should have been opened (budget zero).
        assert session_calls == [], f"unexpected sessions: {session_calls}"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_lint_engine_records_usage(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    store = _store(nb)
    try:
        # Mock the agent reply: well-formed JSON array of one finding.
        reply = json.dumps(
            [
                {
                    "kind": "missing_xref",
                    "path": "wiki/topic.md",
                    "message": "no See also block",
                    "suggested_fix": "Add a See also: [[other]]",
                }
            ]
        )
        usage = {"input_tokens": 100, "output_tokens": 50}
        rt = _runtime_with_session(summary=reply, usage=usage)

        engine = LintEngine(rt, store, "nb", input_limit=50_000, output_limit=10_000)
        findings = await engine.light_lint(nb)

        haiku = [f for f in findings if f.source == "haiku"]
        assert len(haiku) == 1
        assert haiku[0].kind == "missing_xref"

        snap = engine.budget.get_today()
        assert snap.input_tokens_used == 100
        assert snap.output_tokens_used == 50
    finally:
        store.close()


@pytest.mark.asyncio
async def test_lint_engine_apply_finding_with_suggested_fix(tmp_path: Path) -> None:
    nb = _make_notebook(tmp_path)
    store = _store(nb)
    try:
        # Seed a finding with a suggested fix.
        from notebookai.index.schema import LintFinding as LFRow
        from ulid import ULID as _ULID

        fid = str(_ULID())
        with store.session() as s:
            s.add(
                LFRow(
                    id=fid,
                    notebook_id="nb",
                    kind="broken_wikilink",
                    status="open",
                    payload={
                        "path": "wiki/topic.md",
                        "message": "broken [[ghost]]",
                        "suggested_fix": "Replace [[ghost]] with [[index]]",
                    },
                )
            )

        # Stub session to track invocation.
        captured: list = []

        class _CaptureSession(_FakeSession):
            async def run(self, prompt, *, system_prompt_extra=None):
                captured.append((prompt, system_prompt_extra))
                async for ev in super().run(prompt, system_prompt_extra=system_prompt_extra):
                    yield ev

        rt = AgentRuntime()
        rt.session = lambda root, *, op, model=None: _CaptureSession(  # type: ignore[assignment]
            notebook_root=root, op=op, model=model or rt.model
        )

        engine = LintEngine(rt, store, "nb")
        # Patch git helpers so we don't need a real git repo.
        with patch("notebookai.agent.lint._git_changed_paths", return_value=[]), patch(
            "notebookai.agent.lint._git_head_files", return_value=[]
        ), patch("notebookai.agent.lint._commit", return_value="abc1234"):
            sha = await engine.apply_finding(fid, nb)

        assert sha == "abc1234"
        assert captured, "AgentSession.run was not invoked"
        prompt, _extra = captured[0]
        assert "wiki/topic.md" in prompt
        assert "Replace [[ghost]] with [[index]]" in prompt

        # Finding row updated to auto_fixed.
        with store.session() as s:
            row = s.get(LFRow, fid)
            assert row is not None
            assert row.status == "auto_fixed"
    finally:
        store.close()
