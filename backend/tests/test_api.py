"""API tests — exercise routers via FastAPI TestClient.

Mocks ``notebookai.agent.operations.{ingest, query, lint}`` so tests don't
require Claude credentials.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notebookai.agent import operations as agent_operations
from notebookai.agent.events import AgentDone
from notebookai.api.app import create_app
from notebookai.api.dependencies import AppConfig
from notebookai.api.sse import broadcaster

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    library_root = tmp_path / "NotebookAI" / "notebooks"
    library_root.mkdir(parents=True, exist_ok=True)
    cfg = AppConfig(
        library_root=library_root,
        config_file=tmp_path / "NotebookAI" / "config.json",
    )
    return cfg


@pytest.fixture
def client(app_config: AppConfig):
    app = create_app(config=app_config)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_notebook(client: TestClient):
    """Helper: POST /api/notebooks and return its meta."""

    def _make(name: str = "Test Notebook", **kw):
        body = {"name": name}
        body.update(kw)
        r = client.post("/api/notebooks", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    return _make


@pytest.fixture(autouse=True)
def _cleanup_broadcaster():
    yield
    # Drop any test-created subscribers between tests.
    broadcaster._channels.clear()


# ---------------------------------------------------------------------------
# Notebooks
# ---------------------------------------------------------------------------


def test_create_notebook(client: TestClient):
    r = client.post("/api/notebooks", json={"name": "ML Research"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["id"] == "ml-research"
    assert data["name"] == "ML Research"

    g = client.get(f"/api/notebooks/{data['id']}")
    assert g.status_code == 200
    assert g.json()["id"] == "ml-research"


def test_notebook_get_includes_agent_status(
    client: TestClient, make_notebook, monkeypatch: pytest.MonkeyPatch
):
    nb = make_notebook("Agent Status NB")

    # Available case.
    monkeypatch.setattr(
        "notebookai.agent.runtime.AgentRuntime.credentials_available",
        lambda self: True,
    )
    r = client.get(f"/api/notebooks/{nb['id']}")
    assert r.status_code == 200
    body = r.json()
    assert "agent_status" in body
    assert body["agent_status"]["available"] is True
    assert body["agent_status"]["reason"] in (None, "")

    # Unavailable case.
    monkeypatch.setattr(
        "notebookai.agent.runtime.AgentRuntime.credentials_available",
        lambda self: False,
    )
    r2 = client.get(f"/api/notebooks/{nb['id']}")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["agent_status"]["available"] is False
    assert body2["agent_status"]["reason"]
    assert "wiki-only" in body2["agent_status"]["reason"].lower()


def test_ingest_in_degraded_mode(
    client: TestClient, make_notebook, monkeypatch: pytest.MonkeyPatch
):
    nb = make_notebook("Degraded Ingest")

    monkeypatch.setattr(
        "notebookai.agent.runtime.AgentRuntime.credentials_available",
        lambda self: False,
    )

    async def fake_smart_ingest(runtime, root, *, source, source_type=None):
        return agent_operations.OperationResult(
            op="ingest",
            op_id="00000000000000000000000050",
            notebook_id=nb["id"],
            summary="degraded ingest",
            usage={"degraded": True},
        )

    monkeypatch.setattr(
        "notebookai.api.routers.ingest.agent_operations.smart_ingest",
        fake_smart_ingest,
    )
    r = client.post(
        f"/api/notebooks/{nb['id']}/ingest",
        json={"source": "https://example.com/y", "source_type": "url"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["degraded"] is True
    assert "op_id" in body


def test_create_notebook_duplicate_409(client: TestClient):
    r1 = client.post("/api/notebooks", json={"name": "Dup"})
    assert r1.status_code == 201
    r2 = client.post("/api/notebooks", json={"name": "Dup"})
    assert r2.status_code == 409


def test_get_notebook_404(client: TestClient):
    r = client.get("/api/notebooks/nonexistent-xyz")
    assert r.status_code == 404


def test_delete_notebook(client: TestClient, app_config: AppConfig, make_notebook):
    nb = make_notebook("Toss Me")
    r = client.delete(f"/api/notebooks/{nb['id']}")
    assert r.status_code == 204
    assert client.get(f"/api/notebooks/{nb['id']}").status_code == 404
    trash = app_config.trash_dir()
    matches = list(trash.glob(f"{nb['id']}-*"))
    assert matches, "notebook not moved to trash"


def test_patch_notebook_name(client: TestClient, make_notebook):
    nb = make_notebook("Old Name")
    r = client.patch(f"/api/notebooks/{nb['id']}", json={"name": "New Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"
    assert client.get(f"/api/notebooks/{nb['id']}").json()["name"] == "New Name"


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------


def test_library_lists_notebooks(client: TestClient, make_notebook):
    make_notebook("Alpha")
    make_notebook("Beta")
    r = client.get("/api/library")
    assert r.status_code == 200
    ids = sorted(e["id"] for e in r.json())
    assert ids == ["alpha", "beta"]


def test_library_register_external(
    client: TestClient, app_config: AppConfig, tmp_path: Path
):
    # Create an external notebook.
    from notebookai.scaffold import create_notebook

    ext_root = tmp_path / "Elsewhere"
    ext_root.mkdir()
    handle = create_notebook(ext_root, "External NB", git_enabled=False)
    r = client.post("/api/library/register", json={"path": str(handle.root)})
    assert r.status_code == 200, r.text
    entry = r.json()
    assert entry["is_external"] is True
    listing = client.get("/api/library").json()
    assert any(e["path"] == str(handle.root.resolve()) for e in listing)


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def test_ingest_returns_202_with_op_id(
    client: TestClient, make_notebook, monkeypatch: pytest.MonkeyPatch
):
    nb = make_notebook("Ingest Target")
    captured: dict = {"called": False}

    async def fake_ingest(runtime, root, *, source, source_type=None):
        captured["called"] = True
        captured["source"] = source
        return agent_operations.OperationResult(
            op="ingest",
            op_id="00000000000000000000000001",
            notebook_id=nb["id"],
            summary="ingested fake",
            commit_sha=None,
        )

    monkeypatch.setattr(
        "notebookai.api.routers.ingest.agent_operations.smart_ingest", fake_ingest
    )

    r = client.post(
        f"/api/notebooks/{nb['id']}/ingest",
        json={"source": "https://example.com/x", "source_type": "url"},
    )
    assert r.status_code == 202, r.text
    assert "op_id" in r.json()


def test_ingest_file_upload(
    client: TestClient, make_notebook, monkeypatch: pytest.MonkeyPatch
):
    nb = make_notebook("File Ingest")
    spawned = asyncio.Event()

    async def fake_ingest(runtime, root, *, source, source_type=None):
        spawned.set()
        return agent_operations.OperationResult(
            op="ingest",
            op_id="00000000000000000000000002",
            notebook_id=nb["id"],
            summary="ok",
        )

    monkeypatch.setattr(
        "notebookai.api.routers.ingest.agent_operations.smart_ingest", fake_ingest
    )

    pdf_bytes = b"%PDF-1.4\n%minimal pdf\n"
    r = client.post(
        f"/api/notebooks/{nb['id']}/ingest/file",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 202, r.text
    assert "op_id" in r.json()


# ---------------------------------------------------------------------------
# Ask
# ---------------------------------------------------------------------------


def test_ask_non_stream_returns_answer(
    client: TestClient, make_notebook, monkeypatch: pytest.MonkeyPatch
):
    nb = make_notebook("Ask NB")

    async def fake_query(runtime, root, *, prompt, archive=False):
        return agent_operations.OperationResult(
            op="query",
            op_id="00000000000000000000000010",
            notebook_id=nb["id"],
            summary="42 is the answer",
            commit_sha=None,
            usage={"input_tokens": 10, "output_tokens": 5},
        )

    monkeypatch.setattr(
        "notebookai.api.routers.ask.agent_operations.smart_query", fake_query
    )
    r = client.post(
        f"/api/notebooks/{nb['id']}/ask",
        json={"prompt": "what is the meaning of life?"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["answer"] == "42 is the answer"
    assert data["op_id"] == "00000000000000000000000010"
    assert data["chat_id"]


# ---------------------------------------------------------------------------
# Chats CRUD
# ---------------------------------------------------------------------------


def test_chats_listed_after_ask(
    client: TestClient, make_notebook, monkeypatch: pytest.MonkeyPatch
):
    nb = make_notebook("Chat NB")

    async def fake_query(runtime, root, *, prompt, archive=False):
        return agent_operations.OperationResult(
            op="query",
            op_id="00000000000000000000000030",
            notebook_id=nb["id"],
            summary="answer body",
        )

    monkeypatch.setattr(
        "notebookai.api.routers.ask.agent_operations.smart_query", fake_query
    )
    # Ask without chat_id => fresh chat created.
    r = client.post(
        f"/api/notebooks/{nb['id']}/ask",
        json={"prompt": "first question"},
    )
    assert r.status_code == 200, r.text
    chat_id = r.json()["chat_id"]
    assert chat_id

    # Ask again with the same chat_id.
    r2 = client.post(
        f"/api/notebooks/{nb['id']}/ask",
        json={"prompt": "follow up", "chat_id": chat_id},
    )
    assert r2.status_code == 200
    assert r2.json()["chat_id"] == chat_id

    # List chats.
    r3 = client.get(f"/api/notebooks/{nb['id']}/chats")
    assert r3.status_code == 200
    chats = r3.json()
    assert len(chats) == 1
    assert chats[0]["id"] == chat_id
    assert chats[0]["message_count"] == 4

    # Load the full chat.
    r4 = client.get(f"/api/notebooks/{nb['id']}/chats/{chat_id}")
    assert r4.status_code == 200
    full = r4.json()
    assert len(full["messages"]) == 4
    roles = [m["role"] for m in full["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_chat_rename(
    client: TestClient, make_notebook, monkeypatch: pytest.MonkeyPatch
):
    nb = make_notebook("Rename NB")

    async def fake_query(runtime, root, *, prompt, archive=False):
        return agent_operations.OperationResult(
            op="query",
            op_id="00000000000000000000000031",
            notebook_id=nb["id"],
            summary="ok",
        )

    monkeypatch.setattr(
        "notebookai.api.routers.ask.agent_operations.smart_query", fake_query
    )
    r = client.post(
        f"/api/notebooks/{nb['id']}/ask",
        json={"prompt": "hi"},
    )
    chat_id = r.json()["chat_id"]
    r2 = client.patch(
        f"/api/notebooks/{nb['id']}/chats/{chat_id}",
        json={"title": "Renamed"},
    )
    assert r2.status_code == 200
    assert r2.json()["title"] == "Renamed"


def test_chat_delete(
    client: TestClient, make_notebook, monkeypatch: pytest.MonkeyPatch
):
    nb = make_notebook("Delete NB")

    async def fake_query(runtime, root, *, prompt, archive=False):
        return agent_operations.OperationResult(
            op="query",
            op_id="00000000000000000000000032",
            notebook_id=nb["id"],
            summary="ok",
        )

    monkeypatch.setattr(
        "notebookai.api.routers.ask.agent_operations.smart_query", fake_query
    )
    r = client.post(f"/api/notebooks/{nb['id']}/ask", json={"prompt": "x"})
    chat_id = r.json()["chat_id"]
    r2 = client.delete(f"/api/notebooks/{nb['id']}/chats/{chat_id}")
    assert r2.status_code == 204
    r3 = client.get(f"/api/notebooks/{nb['id']}/chats/{chat_id}")
    assert r3.status_code == 404


def test_chat_get_404(client: TestClient, make_notebook):
    nb = make_notebook("404 NB")
    r = client.get(f"/api/notebooks/{nb['id']}/chats/no-such-chat")
    assert r.status_code == 404


def test_ask_stream_returns_sse(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
):
    """Stream test runs against a real uvicorn server (TestClient buffers
    the response and would deadlock on an open SSE stream)."""
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    from notebookai.scaffold import create_notebook as _scaffold

    handle = _scaffold(app_config.library_root, "Ask Stream", git_enabled=False)
    nb_id = handle.meta.id

    async def fake_query(runtime, root, *, prompt, archive=False):
        return agent_operations.OperationResult(
            op="query",
            op_id="00000000000000000000000011",
            notebook_id=nb_id,
            summary="streamed",
            events=[
                AgentDone(
                    notebook_id=nb_id,
                    op_id="00000000000000000000000011",
                    op="query",
                    summary="streamed",
                )
            ],
        )

    monkeypatch.setattr(
        "notebookai.api.routers.ask.agent_operations.smart_query", fake_query
    )

    app = create_app(config=app_config)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(40):
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1.0) as c:
                if c.get("/healthz").status_code == 200:
                    break
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=10.0
        ) as c:
            with c.stream(
                "POST",
                f"/api/notebooks/{nb_id}/ask",
                json={"prompt": "stream me", "stream": True},
            ) as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")
                seen = False
                deadline = time.time() + 5.0
                for line in resp.iter_lines():
                    if "agent.done" in line:
                        seen = True
                        break
                    if time.time() > deadline:
                        break
        assert seen, "did not see agent.done"
    finally:
        server.should_exit = True
        thread.join(timeout=2)


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------


def test_lint_returns_202(client: TestClient, make_notebook, monkeypatch):
    nb = make_notebook("Lint NB")

    async def fake_lint(runtime, root, *, mode):
        return agent_operations.OperationResult(
            op="lint-fix",
            op_id="00000000000000000000000020",
            notebook_id=nb["id"],
            summary="no findings",
        )

    monkeypatch.setattr(
        "notebookai.api.routers.lint.agent_operations.smart_lint", fake_lint
    )
    r = client.post(f"/api/notebooks/{nb['id']}/lint", json={"mode": "light"})
    assert r.status_code == 202
    assert "op_id" in r.json()


def test_lint_findings_empty(client: TestClient, make_notebook):
    nb = make_notebook("Findings NB")
    r = client.get(f"/api/notebooks/{nb['id']}/lint/findings")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------


def test_articles_list(client: TestClient, app_config: AppConfig, make_notebook):
    nb = make_notebook("Articles NB")
    root = app_config.library_root / nb["id"]
    (root / "wiki" / "foo.md").write_text("# Foo\n\nBody.\n", encoding="utf-8")
    (root / "wiki" / "sub").mkdir()
    (root / "wiki" / "sub" / "bar.md").write_text("# Bar\n\nBody.\n", encoding="utf-8")

    r = client.get(f"/api/notebooks/{nb['id']}/articles")
    assert r.status_code == 200
    data = r.json()
    titles = {item["path"]: item["title"] for item in data}
    assert "foo.md" in titles and titles["foo.md"] == "Foo"
    assert "sub/bar.md" in titles and titles["sub/bar.md"] == "Bar"


def test_article_get_raw(client: TestClient, app_config: AppConfig, make_notebook):
    nb = make_notebook("Read One")
    root = app_config.library_root / nb["id"]
    (root / "wiki" / "alpha.md").write_text("# Alpha\n\nbody\n", encoding="utf-8")
    r = client.get(f"/api/notebooks/{nb['id']}/articles/alpha.md")
    assert r.status_code == 200
    assert r.json()["content"].startswith("# Alpha")


def test_article_put_creates_human_edit_commit(
    client: TestClient, app_config: AppConfig, make_notebook
):
    nb = make_notebook("Edit NB")
    root = app_config.library_root / nb["id"]
    if not (root / ".git").is_dir():
        pytest.skip("git not available")

    r = client.put(
        f"/api/notebooks/{nb['id']}/articles/edited.md",
        json={"content": "# Edited\n\nNew content.\n"},
    )
    assert r.status_code == 200, r.text

    # Look for the human-edit commit.
    out = subprocess.run(
        ["git", "log", "--pretty=%s"],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )
    assert "[human-edit]" in out.stdout


def test_article_path_traversal_denied(client: TestClient, make_notebook):
    nb = make_notebook("Traversal NB")
    r = client.get(f"/api/notebooks/{nb['id']}/articles/../../etc/passwd")
    assert r.status_code in (400, 404)
    if r.status_code == 400:
        assert "wiki" in r.text.lower() or "path" in r.text.lower()


def test_backlinks(client: TestClient, app_config: AppConfig, make_notebook):
    nb = make_notebook("Backlinks NB")
    root = app_config.library_root / nb["id"]
    (root / "wiki" / "foo.md").write_text("# Foo\n", encoding="utf-8")
    (root / "wiki" / "a.md").write_text("# A\n\nSee [[foo]]\n", encoding="utf-8")
    (root / "wiki" / "b.md").write_text("# B\n\nAlso [[foo]]\n", encoding="utf-8")
    (root / "wiki" / "c.md").write_text("# C\n\nAnd [[foo]]\n", encoding="utf-8")

    r = client.get(f"/api/notebooks/{nb['id']}/articles/foo.md/backlinks")
    assert r.status_code == 200, r.text
    out = r.json()
    assert sorted(out["backlinks"]) == ["a.md", "b.md", "c.md"]


# ---------------------------------------------------------------------------
# Log / history
# ---------------------------------------------------------------------------


def test_history_lists_commits(
    client: TestClient, app_config: AppConfig, make_notebook
):
    nb = make_notebook("History NB")
    root = app_config.library_root / nb["id"]
    if not (root / ".git").is_dir():
        pytest.skip("git not available")
    # Trigger one human-edit commit.
    r = client.put(
        f"/api/notebooks/{nb['id']}/articles/x.md",
        json={"content": "# X\n"},
    )
    assert r.status_code == 200, r.text

    r = client.get(f"/api/notebooks/{nb['id']}/history")
    assert r.status_code == 200
    entries = r.json()
    assert len(entries) >= 1


def test_history_disabled_git_uses_oplog(
    client: TestClient, app_config: AppConfig, make_notebook
):
    nb = make_notebook("Oplog NB", git_enabled=False)
    root = app_config.library_root / nb["id"]
    oplog = root / ".notebookai" / "oplog.jsonl"
    oplog.parent.mkdir(parents=True, exist_ok=True)
    oplog.write_text(
        json.dumps(
            {
                "sha": "01HW000000000000000000000A",
                "op": "compile",
                "op_id": "01HW000000000000000000000A",
                "summary": "fake compile",
                "subject": "[compile] fake compile",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    r = client.get(f"/api/notebooks/{nb['id']}/history")
    assert r.status_code == 200, r.text
    entries = r.json()
    assert any("fake compile" in e["subject"] for e in entries)


# ---------------------------------------------------------------------------
# Events SSE
# ---------------------------------------------------------------------------


def test_events_stream_keepalive(app_config: AppConfig):
    """Open the SSE stream against a real uvicorn server and verify
    a published event is delivered on the wire."""
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    from notebookai.scaffold import create_notebook as _scaffold

    handle = _scaffold(app_config.library_root, "Events NB", git_enabled=False)
    nb_id = handle.meta.id

    app = create_app(config=app_config)

    # Find a free port.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the server to come up.
    for _ in range(40):
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1.0) as c:
                if c.get("/healthz").status_code == 200:
                    break
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    else:  # pragma: no cover
        server.should_exit = True
        thread.join(timeout=2)
        pytest.fail("uvicorn never came up")

    try:
        seen = False
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=10.0
        ) as c:
            with c.stream("GET", f"/api/notebooks/{nb_id}/events") as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")

                def _publish_later():
                    time.sleep(0.3)
                    broadcaster.publish(
                        nb_id,
                        AgentDone(
                            notebook_id=nb_id,
                            op_id="01HW00000000000000000000FF",
                            op="query",
                            summary="ok",
                        ),
                    )

                threading.Thread(target=_publish_later, daemon=True).start()

                deadline = time.time() + 5.0
                for line in resp.iter_lines():
                    if "agent.done" in line:
                        seen = True
                        break
                    if time.time() > deadline:
                        break
        assert seen, "did not see the published event"
    finally:
        server.should_exit = True
        thread.join(timeout=2)
