"""Phase 6 — Agent runtime tests.

Mocked tests must pass without Claude credentials. Live tests are tagged
``requires_claude`` and skipped by default.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from notebookai.agent import (
    AgentDone,
    AgentError,
    AgentMessage,
    AgentRuntime,
    AgentToolCall,
    AgentToolResult,
)
from notebookai.agent.events import EVENT_NAMES
from notebookai.agent.operations import (
    _commit_op_result,
    _detect_source_type,
    ingest,
    query,
)
from notebookai.agent.tools import (
    BASH_ALLOWLIST,
    is_bash_allowed,
    is_path_in_notebook,
    is_path_writable,
)
from notebookai.scaffold import create_notebook


# ---------------------------------------------------------------------------
# Bash allowlist
# ---------------------------------------------------------------------------


def test_bash_allowlist_basic():
    assert "ls" in BASH_ALLOWLIST
    assert "git" in BASH_ALLOWLIST

    ok, _ = is_bash_allowed("ls -la")
    assert ok
    ok, _ = is_bash_allowed("cat wiki/index.md")
    assert ok
    ok, _ = is_bash_allowed("git log --oneline -n 5")
    assert ok
    ok, _ = is_bash_allowed("git status")
    assert ok
    ok, _ = is_bash_allowed("git config --get user.email")
    assert ok

    # Denied programs
    ok, reason = is_bash_allowed("rm -rf /")
    assert not ok
    assert "rm" in reason
    ok, _ = is_bash_allowed("curl https://example.com")
    assert not ok
    ok, _ = is_bash_allowed("sudo ls")
    assert not ok

    # Denied git subcommands
    ok, reason = is_bash_allowed("git push origin main")
    assert not ok
    assert "push" in reason
    ok, _ = is_bash_allowed("git pull")
    assert not ok
    ok, _ = is_bash_allowed("git fetch --all")
    assert not ok
    ok, _ = is_bash_allowed("git reset --hard")
    assert not ok
    ok, _ = is_bash_allowed("git checkout other-branch")
    assert not ok

    # `git config` non-read forms denied
    ok, _ = is_bash_allowed("git config user.email new@x")
    assert not ok

    # Chained commands — denied if any segment is denied
    ok, _ = is_bash_allowed("ls && curl example.com")
    assert not ok
    ok, _ = is_bash_allowed("ls; rm bad")
    assert not ok
    ok, _ = is_bash_allowed("cat foo | curl -X POST http://x")
    assert not ok
    # All-allowed pipeline is fine
    ok, _ = is_bash_allowed("git log | head -n 5")
    assert ok

    # Empty / unparsable
    ok, _ = is_bash_allowed("")
    assert not ok
    ok, _ = is_bash_allowed("   ")
    assert not ok


# ---------------------------------------------------------------------------
# Path guards
# ---------------------------------------------------------------------------


def test_path_writable_guards(tmp_path: Path):
    nb = tmp_path / "nb"
    nb.mkdir()
    (nb / ".git").mkdir()
    (nb / ".notebookai").mkdir()
    (nb / "raw").mkdir()
    (nb / "wiki").mkdir()
    (nb / "chats").mkdir()

    # Allowed
    ok, _ = is_path_writable(nb / "wiki" / "x.md", nb)
    assert ok
    ok, _ = is_path_writable(nb / "wiki" / "ml" / "y.md", nb)
    assert ok
    ok, _ = is_path_writable(nb / "chats" / "z.md", nb)
    assert ok
    ok, _ = is_path_writable(nb / "AGENTS.md", nb)
    assert ok
    ok, _ = is_path_writable(nb / "README.md", nb)
    assert ok

    # Denied subtrees
    ok, reason = is_path_writable(nb / ".git" / "foo", nb)
    assert not ok
    assert ".git" in reason
    ok, _ = is_path_writable(nb / ".notebookai" / "embeddings.db", nb)
    assert not ok
    ok, _ = is_path_writable(nb / "raw" / "x.md", nb)
    assert not ok

    # Outside notebook
    ok, _ = is_path_writable(tmp_path / "elsewhere.md", nb)
    assert not ok

    # Unauthorised top-level files
    ok, _ = is_path_writable(nb / "secret.env", nb)
    assert not ok

    # is_path_in_notebook
    assert is_path_in_notebook(nb / "wiki" / "x.md", nb)
    assert not is_path_in_notebook(tmp_path / "outside.md", nb)


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------


def test_event_dataclasses():
    call = AgentToolCall(
        notebook_id="nb", op_id="01HW", tool="Read", input={"path": "wiki/x.md"}
    )
    assert call._event_name == "agent.tool_call"
    assert call.to_dict()["tool"] == "Read"

    res = AgentToolResult(
        notebook_id="nb", op_id="01HW", tool="Read", output_preview="…"
    )
    assert res._event_name == "agent.tool_result"
    assert res.to_dict()["is_error"] is False

    msg = AgentMessage(notebook_id="nb", op_id="01HW", text="hi")
    assert msg._event_name == "agent.message"
    assert msg.to_dict()["kind"] == "user-visible"

    done = AgentDone(
        notebook_id="nb", op_id="01HW", op="ingest", summary="wrote x", commit_sha="abc"
    )
    assert done._event_name == "agent.done"
    assert done.to_dict()["commit_sha"] == "abc"

    err = AgentError(
        notebook_id="nb",
        op_id="01HW",
        error_type="ValueError",
        message="boom",
        retriable=True,
    )
    assert err._event_name == "agent.error"
    assert err.to_dict()["retriable"] is True

    assert EVENT_NAMES[AgentToolCall] == "agent.tool_call"
    assert EVENT_NAMES[AgentDone] == "agent.done"


# ---------------------------------------------------------------------------
# AgentRuntime credential check
# ---------------------------------------------------------------------------


def test_runtime_credentials_available(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    rt = AgentRuntime()
    # No env, no credentials file -> False
    assert rt.credentials_available() is False

    # With env var
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert rt.credentials_available() is True

    # Without env, but with credentials file
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cred_dir = tmp_path / ".claude"
    cred_dir.mkdir()
    (cred_dir / ".credentials.json").write_text("{}", encoding="utf-8")
    assert rt.credentials_available() is True


# ---------------------------------------------------------------------------
# Session op_ids unique
# ---------------------------------------------------------------------------


def test_session_op_id_unique(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    nb = tmp_path / "nb"
    nb.mkdir()
    (nb / ".notebookai").mkdir()
    (nb / ".notebookai" / "notebook.json").write_text(
        json.dumps({"id": "nb-id"}), encoding="utf-8"
    )
    rt = AgentRuntime()
    s1 = rt.session(nb, op="ingest")
    s2 = rt.session(nb, op="ingest")
    assert s1.op_id != s2.op_id
    assert s1.notebook_id == "nb-id"


# ---------------------------------------------------------------------------
# Commit helper
# ---------------------------------------------------------------------------


def _have_git() -> bool:
    try:
        subprocess.run(
            ["git", "--version"], check=True, capture_output=True
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):  # pragma: no cover
        return False


@pytest.mark.skipif(not _have_git(), reason="git not available")
def test_commit_op_result_with_git(tmp_path: Path):
    handle = create_notebook(tmp_path, "Test Book", git_enabled=True)
    nb = handle.root

    # Make an agent-style edit.
    (nb / "wiki" / "new.md").write_text("# new\nbody\n", encoding="utf-8")

    sha = _commit_op_result(
        nb, op="compile", summary="add wiki/new.md", op_id="01HOPID", model="claude-sonnet-4-6"
    )
    assert sha
    assert len(sha) >= 7

    # Inspect the commit
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%an%n%ae%n%B"],
        cwd=str(nb),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "NotebookAI Agent" in log
    assert "agent@notebookai.local" in log
    assert "[compile] add wiki/new.md" in log
    assert "notebook-id:" in log
    assert "op-id: 01HOPID" in log
    assert "agent-model: claude-sonnet-4-6" in log


def test_commit_op_result_disabled_git(tmp_path: Path):
    handle = create_notebook(tmp_path, "No Git Book", git_enabled=False)
    nb = handle.root

    sha = _commit_op_result(
        nb, op="ingest", summary="wrote raw/foo.md", op_id="01HXID", model="claude-haiku-4-5"
    )
    assert sha == "oplog-01HXID"

    oplog = nb / ".notebookai" / "oplog.jsonl"
    assert oplog.is_file()
    lines = [json.loads(line) for line in oplog.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    entry = lines[0]
    assert entry["op"] == "ingest"
    assert entry["op_id"] == "01HXID"
    assert entry["summary"] == "wrote raw/foo.md"
    assert entry["agent_model"] == "claude-haiku-4-5"


# ---------------------------------------------------------------------------
# Source-type detection
# ---------------------------------------------------------------------------


def test_detect_source_type():
    assert _detect_source_type("https://example.com/article") == "url"
    assert _detect_source_type("https://www.youtube.com/watch?v=abc") == "youtube"
    assert _detect_source_type("https://youtu.be/abc") == "youtube"
    assert _detect_source_type("/tmp/file.pdf") == "pdf"
    assert _detect_source_type("paper.PDF") == "pdf"


# ---------------------------------------------------------------------------
# Ingest dispatches the right adapter (mocked SDK + adapters)
# ---------------------------------------------------------------------------


class _FakeSession:
    """Stand-in for AgentSession that yields a synthetic AgentDone."""

    def __init__(self, notebook_root, op, model="claude-sonnet-4-6"):
        self.notebook_root = Path(notebook_root)
        self.op = op
        self.model = model
        self.op_id = "01HFAKEOPID"
        self.notebook_id = self.notebook_root.name

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def run(self, prompt, *, system_prompt_extra=None):
        yield AgentDone(
            notebook_id=self.notebook_id,
            op_id=self.op_id,
            op=self.op,
            summary="mock summary",
            usage={"input_tokens": 0, "output_tokens": 0},
        )


def _make_runtime_with_fake_session():
    rt = AgentRuntime()
    rt.session = lambda root, *, op, model=None: _FakeSession(root, op, model or rt.model)
    return rt


@pytest.mark.asyncio
async def test_ingest_dispatches_url_adapter(tmp_path: Path):
    handle = create_notebook(tmp_path, "Adapter Book", git_enabled=False)
    nb = handle.root

    rt = _make_runtime_with_fake_session()

    fake_doc = MagicMock()
    fake_doc.source_type = "url"
    fake_doc.title = "Hello"
    fake_doc.body = "body"
    fake_doc.published = "2024-01-01"
    fake_doc.collected_at = MagicMock()
    fake_doc.collected_at.isoformat.return_value = "2024-01-01T00:00:00+00:00"

    with patch("notebookai.agent.operations.write_to_notebook") as mock_write, patch(
        "notebookai.agent.operations.URLAdapter"
    ) as mock_url, patch("notebookai.agent.operations.PDFAdapter") as mock_pdf, patch(
        "notebookai.agent.operations.YouTubeAdapter"
    ) as mock_yt:
        mock_url.return_value.fetch.return_value = fake_doc
        mock_write.return_value = nb / "raw" / "url" / "x.md"
        result = await ingest(rt, nb, source="https://example.com/page")

    assert mock_url.return_value.fetch.called
    assert not mock_pdf.called
    assert not mock_yt.called
    assert result.op == "ingest"
    assert result.summary == "mock summary"
    assert result.commit_sha == f"oplog-{result.op_id}"


@pytest.mark.asyncio
async def test_ingest_dispatches_pdf_adapter(tmp_path: Path):
    handle = create_notebook(tmp_path, "PDF Book", git_enabled=False)
    nb = handle.root
    rt = _make_runtime_with_fake_session()

    fake_doc = MagicMock()
    fake_doc.source_type = "pdf"
    fake_doc.collected_at = MagicMock()
    fake_doc.collected_at.isoformat.return_value = "2024-01-01T00:00:00+00:00"

    with patch("notebookai.agent.operations.write_to_notebook") as mock_write, patch(
        "notebookai.agent.operations.URLAdapter"
    ) as mock_url, patch("notebookai.agent.operations.PDFAdapter") as mock_pdf, patch(
        "notebookai.agent.operations.YouTubeAdapter"
    ) as mock_yt:
        mock_pdf.return_value.fetch.return_value = fake_doc
        mock_write.return_value = nb / "raw" / "pdf" / "x.md"
        result = await ingest(rt, nb, source="/tmp/paper.pdf")

    assert mock_pdf.return_value.fetch.called
    assert not mock_url.called
    assert not mock_yt.called
    assert result.op == "ingest"


@pytest.mark.asyncio
async def test_ingest_dispatches_youtube_adapter(tmp_path: Path):
    handle = create_notebook(tmp_path, "YT Book", git_enabled=False)
    nb = handle.root
    rt = _make_runtime_with_fake_session()

    fake_doc = MagicMock()
    fake_doc.source_type = "youtube"
    fake_doc.collected_at = MagicMock()
    fake_doc.collected_at.isoformat.return_value = "2024-01-01T00:00:00+00:00"

    with patch("notebookai.agent.operations.write_to_notebook") as mock_write, patch(
        "notebookai.agent.operations.URLAdapter"
    ) as mock_url, patch("notebookai.agent.operations.PDFAdapter") as mock_pdf, patch(
        "notebookai.agent.operations.YouTubeAdapter"
    ) as mock_yt:
        mock_yt.return_value.fetch.return_value = fake_doc
        mock_write.return_value = nb / "raw" / "video" / "x.md"
        result = await ingest(rt, nb, source="https://youtube.com/watch?v=abc")

    assert mock_yt.return_value.fetch.called
    assert not mock_url.called
    assert not mock_pdf.called
    assert result.op == "ingest"


# ---------------------------------------------------------------------------
# Live tests — gated on requires_claude
# ---------------------------------------------------------------------------


@pytest.mark.requires_claude
@pytest.mark.asyncio
async def test_live_query_lists_wiki(tmp_path: Path):
    runtime = AgentRuntime()
    if not runtime.credentials_available():
        pytest.skip("no Claude credentials available")

    handle = create_notebook(tmp_path, "Live Book", git_enabled=False)
    nb = handle.root
    (nb / "wiki" / "alpha.md").write_text("# Alpha\nFirst article.\n", encoding="utf-8")
    (nb / "wiki" / "beta.md").write_text("# Beta\nSecond article.\n", encoding="utf-8")

    result = await query(runtime, nb, prompt="List the wiki articles in this notebook.")
    text = (result.summary or "").lower()
    assert "alpha" in text
    assert "beta" in text


@pytest.mark.requires_claude
@pytest.mark.asyncio
async def test_live_ingest_url(tmp_path: Path):
    runtime = AgentRuntime()
    if not runtime.credentials_available():
        pytest.skip("no Claude credentials available")

    handle = create_notebook(tmp_path, "Live Ingest", git_enabled=True)
    nb = handle.root

    fake_doc = MagicMock()
    fake_doc.source_type = "url"
    fake_doc.title = "Sample"
    fake_doc.body = "Sample body for ingest."
    fake_doc.source_url = "https://example.com/sample"
    fake_doc.published = "2024-01-01"
    fake_doc.collected_at = MagicMock()
    fake_doc.collected_at.isoformat.return_value = "2024-01-01T00:00:00+00:00"
    fake_doc.metadata = {}

    with patch("notebookai.agent.operations.URLAdapter") as mock_url:
        mock_url.return_value.fetch.return_value = fake_doc
        result = await ingest(runtime, nb, source="https://example.com/sample")

    wiki_files = list((nb / "wiki").rglob("*.md"))
    assert len(wiki_files) >= 1
    assert result.commit_sha
