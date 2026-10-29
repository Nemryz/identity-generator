# Tests for history.py: I cover persistence, locking, atomic writes and corruption handling.

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from identity_generator import history

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
    # Two independent CLI processes appending at the same time must both succeed, because the lock is exclusive at the filesystem level (O_EXCL), not an in-process flag.
    env = {**os.environ, "IDENTITY_HISTORY_FILE": str(history_file)}
    code = (
        "from identity_generator import history\n"
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

# --- paths: the behaviour that the package move introduced (A7) ----------------------


def test_user_data_dir_follows_identity_home(tmp_path, monkeypatch):
    # I check IDENTITY_HOME wins over the platform default, which is what containers and tests rely on.
    from identity_generator import paths

    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "elsewhere"))
    assert paths.user_data_dir() == tmp_path / "elsewhere"


def test_user_data_dir_is_created_on_demand(tmp_path, monkeypatch):
    # I check the directory appears only when something is written, so importing the package never creates folders as a side effect.
    from identity_generator import paths

    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "fresh"))
    assert paths.user_data_dir().exists() is False
    created = paths.ensure_user_data_dir()
    assert created.is_dir()


def test_environment_override_wins_over_the_data_dir(tmp_path, monkeypatch):
    # I check an explicit IDENTITY_HISTORY_FILE beats both the data directory and the legacy path, because that is the escape hatch every test and script uses.
    from identity_generator import paths

    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "home"))
    monkeypatch.setenv("IDENTITY_HISTORY_FILE", str(tmp_path / "explicit.json"))
    resolved = paths.resolve_state_file("history.json", "IDENTITY_HISTORY_FILE")
    assert resolved == tmp_path / "explicit.json"


def test_a_legacy_file_is_migrated_once(tmp_path, monkeypatch):
    # I check a file left in the old location is moved across and not left behind, so nobody ends up with two diverging histories.
    from identity_generator import paths

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "history.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(paths, "legacy_project_dir", lambda: legacy)
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "home"))

    resolved = paths.resolve_state_file("history.json", "IDENTITY_HISTORY_FILE")
    assert resolved == tmp_path / "home" / "history.json"
    assert resolved.exists()
    assert not (legacy / "history.json").exists()

    # A second run must not move anything, since the file is already home.
    (resolved.parent / "marker").write_text("x", encoding="utf-8")
    paths.resolve_state_file("history.json", "IDENTITY_HISTORY_FILE")
    assert (resolved.parent / "marker").exists()


def test_first_use_on_a_fresh_directory_creates_it(tmp_path, monkeypatch):
    # I check the first write on a directory that does not exist yet succeeds, because creating the lock before the folder is what would otherwise crash a library user on their very first call.
    from identity_generator import email_api, history

    fresh = tmp_path / "brand-new"
    monkeypatch.setenv("IDENTITY_HOME", str(fresh))
    monkeypatch.setattr(email_api, "USAGE_FILE", fresh / "email_usage.json")
    monkeypatch.setattr(history, "HISTORY_FILE", fresh / "history.json")

    email_api._record_usage("offline")
    history.append({"id": "first", "full_name": "First Run"})

    assert (fresh / "email_usage.json").exists()
    assert history.get_by_uuid("first") is not None


def test_output_dir_is_the_working_directory(tmp_path, monkeypatch):
    # I check exports follow where the user is standing, since they are requested output rather than state.
    from identity_generator import paths

    monkeypatch.chdir(tmp_path)
    assert paths.output_dir() == Path.cwd()
