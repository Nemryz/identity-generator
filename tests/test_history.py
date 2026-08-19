"""
Tests for history.py: persistence, locking, atomic writes, and
corruption handling.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import history

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def history_file(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "history.json")
    return tmp_path / "history.json"


def _identity(identity_id: str) -> dict:
    return {"id": identity_id, "username": "test_user"}


def test_append_and_get_all_roundtrip(history_file):
    history.append(_identity("one"))
    history.append(_identity("two"))
    assert [e["id"] for e in history.get_all()] == ["one", "two"]


def test_append_many_writes_all_in_one_call(history_file):
    history.append_many([_identity("one"), _identity("two"), _identity("three")])
    assert [e["id"] for e in history.get_all()] == ["one", "two", "three"]
    assert not history._lock_file().exists()


def test_append_many_empty_is_noop(history_file):
    history.append_many([])
    assert history.count() == 0


def test_append_many_extends_existing_entries(history_file):
    history.append(_identity("first"))
    history.append_many([_identity("a"), _identity("b")])
    assert history.count() == 3


def test_get_all_limit_returns_most_recent(history_file):
    for i in range(5):
        history.append(_identity(str(i)))
    assert [e["id"] for e in history.get_all(limit=2)] == ["3", "4"]


def test_count(history_file):
    assert history.count() == 0
    history.append(_identity("one"))
    history.append(_identity("two"))
    assert history.count() == 2


def test_no_tmp_file_left_after_save(history_file):
    history.append(_identity("one"))
    leftovers = list(history_file.parent.glob("*.tmp"))
    assert leftovers == []


def test_lock_is_released_after_append(history_file):
    history.append(_identity("one"))
    assert not history._lock_file().exists()


def test_append_fails_while_lock_held(history_file):
    lock = history._lock_file()
    lock.write_text("held", encoding="utf-8")
    with pytest.raises(RuntimeError, match="lock"):
        history.append(_identity("one"))


def test_stale_lock_is_ignored(history_file):
    lock = history._lock_file()
    lock.write_text("stale", encoding="utf-8")
    old = time.time() - history._LOCK_STALE_SECONDS - 1
    os.utime(lock, (old, old))
    history.append(_identity("one"))
    assert not lock.exists()
    assert history.count() == 1


def test_corrupt_file_returns_empty_and_is_backed_up(
    history_file, caplog
):
    history_file.write_text("{not valid json", encoding="utf-8")
    assert history.get_all() == []
    backups = list(history_file.parent.glob("history.corrupt.*.bak"))
    assert len(backups) == 1
    assert not history_file.exists()
    assert "backed up" in caplog.text


def test_non_list_json_is_treated_as_corrupt(history_file):
    history_file.write_text('{"not": "a list"}', encoding="utf-8")
    assert history.get_all() == []
    assert len(list(history_file.parent.glob("history.corrupt.*.bak"))) == 1


def test_append_after_corruption_starts_fresh(history_file):
    history_file.write_text("{broken", encoding="utf-8")
    history.append(_identity("fresh"))
    assert [e["id"] for e in history.get_all()] == ["fresh"]


def test_missing_file_returns_empty(history_file):
    assert history.get_all() == []
    assert history.count() == 0


def test_concurrent_processes_do_not_lose_entries(history_file):
    """
    Two independent CLI processes appending at the same time must both
    succeed, because the lock is exclusive at the filesystem level
    (O_EXCL), not an in-process flag.
    """
    env = {**os.environ, "IDENTITY_HISTORY_FILE": str(history_file)}
    code = (
        "import history\n"
        "history.append_many([{'id': 'x', 'n': i} for i in range(20)])\n"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(2)
    ]
    for process in processes:
        assert process.wait(timeout=60) == 0
    assert len(history.get_all()) == 40