"""Tests for :mod:`notebookai.git.notebook_repo`.

Each test scaffolds a real notebook via :func:`create_notebook` so the
git invariants live alongside the directory schema invariants.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest
from ulid import ULID

from notebookai.git import NotebookRepo
from notebookai.scaffold import create_notebook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_wiki(nb_root: Path, name: str, content: str) -> Path:
    p = nb_root / "wiki" / name
    p.write_text(content, encoding="utf-8")
    return p


def _set_local_git_user(nb_root: Path, name: str, email: str) -> None:
    subprocess.run(
        ["git", "config", "user.name", name],
        cwd=nb_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", email],
        cwd=nb_root,
        check=True,
        capture_output=True,
    )


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


# ---------------------------------------------------------------------------
# commit_op
# ---------------------------------------------------------------------------


def test_commit_op_basic(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "GitBasic")
    nb = handle.root
    _set_local_git_user(nb, "Local Dev", "dev@local")

    _write_wiki(nb, "transformers.md", "# Transformers\nbody.\n")

    repo = NotebookRepo(nb)
    op_id = str(ULID())
    sha = repo.commit_op(
        op="compile",
        summary="add wiki/transformers.md",
        op_id=op_id,
        agent_model="claude-sonnet-4-6",
        body="- wiki/transformers.md: new article",
    )
    assert sha and len(sha) == 40

    msg = _git(["show", "-s", "--format=%s%n%b", sha], nb)
    assert msg.splitlines()[0] == "[compile] add wiki/transformers.md"
    assert f"op-id: {op_id}" in msg
    assert "agent-model: claude-sonnet-4-6" in msg
    assert f"notebook-id: {handle.meta.id}" in msg

    # Author = NotebookAI Agent; committer = local git user.
    author = _git(["show", "-s", "--format=%an <%ae>", sha], nb).strip()
    committer = _git(["show", "-s", "--format=%cn <%ce>", sha], nb).strip()
    assert author == "NotebookAI Agent <agent@notebookai.local>"
    assert committer == "Local Dev <dev@local>"


def test_commit_op_human_edit_uses_git_user(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "GitHuman")
    nb = handle.root
    _set_local_git_user(nb, "Jesper", "jesper@example.com")

    _write_wiki(nb, "note.md", "edited by hand\n")
    repo = NotebookRepo(nb)
    sha = repo.commit_op(
        op="human-edit",
        summary="update wiki/note.md",
        op_id=str(ULID()),
        agent_model="",
    )
    assert sha
    author = _git(["show", "-s", "--format=%an <%ae>", sha], nb).strip()
    assert author == "Jesper <jesper@example.com>"


def test_commit_op_no_changes_returns_head(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "GitNoChange")
    nb = handle.root
    _set_local_git_user(nb, "Dev", "dev@local")

    repo = NotebookRepo(nb)
    head_before = _git(["rev-parse", "HEAD"], nb).strip()
    sha = repo.commit_op(
        op="compile",
        summary="no work",
        op_id=str(ULID()),
        agent_model="claude-sonnet-4-6",
    )
    assert sha == head_before
    # No new commit was added.
    log = _git(["log", "--oneline"], nb).splitlines()
    assert len(log) == 1


def test_commit_op_summary_truncation(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "GitTrunc")
    nb = handle.root
    _set_local_git_user(nb, "Dev", "dev@local")
    _write_wiki(nb, "long.md", "x")

    long_summary = "this is a very long summary " + ("blah " * 30)
    assert len(long_summary) > 72

    repo = NotebookRepo(nb)
    sha = repo.commit_op(
        op="compile",
        summary=long_summary,
        op_id=str(ULID()),
        agent_model="claude-sonnet-4-6",
    )
    subject = _git(["show", "-s", "--format=%s", sha], nb).strip()
    assert len(subject) <= 72
    assert subject.startswith("[compile]")
    full_msg = _git(["show", "-s", "--format=%B", sha], nb)
    # The full (un-truncated) summary should appear somewhere in the body.
    # We check a unique chunk near the tail since the subject was clipped.
    tail = long_summary.strip().split()[-2:]
    assert " ".join(tail) in full_msg


# ---------------------------------------------------------------------------
# get_history / get_commit
# ---------------------------------------------------------------------------


def _three_commits(nb: Path) -> list[str]:
    repo = NotebookRepo(nb)
    shas = []
    for i, op in enumerate(("compile", "lint-fix", "compile")):
        _write_wiki(nb, f"a{i}.md", f"v{i}\n")
        shas.append(
            repo.commit_op(
                op=op,
                summary=f"op {i}",
                op_id=str(ULID()),
                agent_model="claude-sonnet-4-6",
            )
        )
    return shas


def test_get_history_lists_commits_in_order(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "GitHistory")
    nb = handle.root
    _set_local_git_user(nb, "Dev", "dev@local")
    shas = _three_commits(nb)

    repo = NotebookRepo(nb)
    commits = repo.get_history(limit=10)
    # Includes the initial scaffold commit plus the three new ones.
    assert len(commits) >= 4
    # Newest first: the last sha we created should come first.
    assert commits[0].sha == shas[-1]
    assert commits[1].sha == shas[-2]
    assert commits[2].sha == shas[-3]


def test_get_history_filter_by_op(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "GitFilter")
    nb = handle.root
    _set_local_git_user(nb, "Dev", "dev@local")
    _three_commits(nb)

    repo = NotebookRepo(nb)
    lint = repo.get_history(limit=20, op_filter="lint-fix")
    assert len(lint) == 1
    assert lint[0].op == "lint-fix"


def test_get_commit_detail(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "GitDetail")
    nb = handle.root
    _set_local_git_user(nb, "Dev", "dev@local")
    _write_wiki(nb, "detail.md", "hi\n")
    repo = NotebookRepo(nb)
    op_id = str(ULID())
    sha = repo.commit_op(
        op="compile",
        summary="detail commit",
        op_id=op_id,
        agent_model="claude-sonnet-4-6",
        body="- wiki/detail.md: new",
    )
    c = repo.get_commit(sha)
    assert c is not None
    assert c.op == "compile"
    assert c.op_id == op_id
    assert "wiki/detail.md" in c.files_changed
    assert "- wiki/detail.md: new" in c.body


def test_revert_op(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "GitRevert")
    nb = handle.root
    _set_local_git_user(nb, "Dev", "dev@local")
    _write_wiki(nb, "rev.md", "original\n")
    repo = NotebookRepo(nb)
    sha = repo.commit_op(
        op="compile",
        summary="add rev.md",
        op_id=str(ULID()),
        agent_model="claude-sonnet-4-6",
    )

    new_sha = repo.revert_op(sha)
    assert new_sha and new_sha != sha
    history = repo.get_history(limit=10)
    shas = [c.sha for c in history]
    assert new_sha in shas
    assert sha in shas


# ---------------------------------------------------------------------------
# Disabled-git mode
# ---------------------------------------------------------------------------


def test_disabled_git_writes_oplog(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "GitDisabled", git_enabled=False)
    nb = handle.root
    repo = NotebookRepo(nb)
    assert repo.is_enabled() is False

    op_id = str(ULID())
    sha = repo.commit_op(
        op="compile",
        summary="disabled mode commit",
        op_id=op_id,
        agent_model="claude-sonnet-4-6",
        paths_to_stage=["wiki/index.md"],
    )
    assert sha and len(sha) >= 20  # ULID-shaped

    oplog = nb / ".notebookai" / "oplog.jsonl"
    assert oplog.is_file()
    lines = oplog.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["op"] == "compile"
    assert obj["op_id"] == op_id
    assert obj["sha"] == sha

    history = repo.get_history(limit=10)
    assert len(history) == 1
    assert history[0].sha == sha
    assert history[0].op == "compile"
    assert history[0].op_id == op_id


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------


def test_lock_serializes_writers(tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, "GitLock")
    nb = handle.root
    _set_local_git_user(nb, "Dev", "dev@local")
    repo = NotebookRepo(nb)

    results: list[str] = []
    errors: list[BaseException] = []

    def worker(idx: int) -> None:
        try:
            path = nb / "wiki" / f"t{idx}.md"
            path.write_text(f"thread {idx}\n", encoding="utf-8")
            # Pin staging to *this* thread's path so `git add -A` from the
            # other worker doesn't accidentally pull both into one commit.
            sha = repo.commit_op(
                op="compile",
                summary=f"thread {idx}",
                op_id=str(ULID()),
                agent_model="claude-sonnet-4-6",
                paths_to_stage=[f"wiki/t{idx}.md"],
            )
            results.append(sha)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=(1,))
    t2 = threading.Thread(target=worker, args=(2,))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not errors, f"thread errors: {errors!r}"
    assert len(results) == 2
    assert len(set(results)) == 2  # distinct SHAs
    history = repo.get_history(limit=10)
    shas = {c.sha for c in history}
    assert results[0] in shas
    assert results[1] in shas


@pytest.mark.parametrize("op", ["ingest", "compile", "lint-fix"])
def test_op_round_trips_through_history(op: str, tmp_path: Path) -> None:
    handle = create_notebook(tmp_path, f"OpRT-{op}")
    nb = handle.root
    _set_local_git_user(nb, "Dev", "dev@local")
    _write_wiki(nb, "x.md", op)
    repo = NotebookRepo(nb)
    op_id = str(ULID())
    sha = repo.commit_op(
        op=op,
        summary=f"{op} change",
        op_id=op_id,
        agent_model="claude-sonnet-4-6",
    )
    c = repo.get_commit(sha)
    assert c is not None
    assert c.op == op
    assert c.op_id == op_id
