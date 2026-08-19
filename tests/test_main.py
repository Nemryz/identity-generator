"""
CLI tests for main.py.

Runs the real entry point in a subprocess to verify argument handling,
especially the friendly error for unsupported --locale values.

Every subprocess points IDENTITY_HISTORY_FILE at a temporary path so the
generated identities never pollute the real history.json of the project.
"""

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def _run(history_file: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "IDENTITY_HISTORY_FILE": str(history_file),
        "EMAIL_USAGE_FILE": str(history_file.parent / "email_usage.json"),
        "CUSTOM_DOMAINS_FILE": str(history_file.parent / "domains.json"),
    }
    return subprocess.run(
        [PYTHON, "-X", "utf8", str(REPO_ROOT / "main.py"), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def test_unknown_locale_fails_with_friendly_error(tmp_path):
    result = _run(tmp_path / "history.json", "--locale", "xx_XX")
    assert result.returncode == 2
    assert "unknown locale" in result.stderr
    assert "xx_XX" in result.stderr
    assert "--list-locales" in result.stderr


def test_list_locales_exits_cleanly(tmp_path):
    result = _run(tmp_path / "history.json", "--list-locales")
    assert result.returncode == 0
    assert "es_ES" in result.stdout
    assert "en_US" in result.stdout


def test_faker_only_locale_accepted(tmp_path):
    result = _run(tmp_path / "history.json", "--locale", "en_CA")
    assert result.returncode == 0
    assert "Generating identity" in result.stdout


def test_generated_identity_goes_to_env_history_file(tmp_path):
    repo_history = REPO_ROOT / "history.json"
    before = (
        repo_history.read_text(encoding="utf-8")
        if repo_history.exists()
        else None
    )
    history_file = tmp_path / "custom_history.json"
    result = _run(history_file, "--locale", "en_US")
    assert result.returncode == 0
    entries = json.loads(history_file.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["locale"] == "en_US"
    after = (
        repo_history.read_text(encoding="utf-8")
        if repo_history.exists()
        else None
    )
    assert after == before


def test_email_usage_flag_shows_counters(tmp_path):
    result = _run(tmp_path / "history.json", "--email-usage")
    assert result.returncode == 0
    assert "mailtm" in result.stdout
    assert "tempmail" in result.stdout
    assert "offline" in result.stdout


def _write_history(history_file: Path, entries: list[dict]) -> None:
    history_file.write_text(
        json.dumps(entries, ensure_ascii=False), encoding="utf-8"
    )


def _usable_identity(identity_id="11111111-2222-3333-4444-555555555555"):
    return {
        "id": identity_id,
        "full_name": "Ana López",
        "locale": "es_ES",
        "email": "ana.lopez@tmp.com",
        "email_token": "deadbeef",
        "email_provider": "tempmail",
    }


def test_check_inbox_latest_uses_stored_token(tmp_path):
    history_file = tmp_path / "history.json"
    _write_history(history_file, [_usable_identity()])
    result = _run(history_file, "--check-inbox")
    assert result.returncode == 0
    assert "Checking inbox" in result.stdout
    assert "ana.lopez@tmp.com" in result.stdout


def test_check_inbox_by_uuid(tmp_path):
    history_file = tmp_path / "history.json"
    _write_history(
        history_file,
        [_usable_identity("aaaaaaaa-0000-0000-0000-000000000000")],
    )
    result = _run(
        history_file, "--check-inbox", "aaaaaaaa-0000-0000-0000-000000000000"
    )
    assert result.returncode == 0
    assert "Checking inbox" in result.stdout


def test_check_inbox_unknown_uuid_reports_not_found(tmp_path):
    history_file = tmp_path / "history.json"
    _write_history(history_file, [_usable_identity()])
    result = _run(history_file, "--check-inbox", "no-such-uuid")
    assert result.returncode == 0
    assert "No identity found" in result.stdout


def test_check_inbox_empty_history_reports_none(tmp_path):
    history_file = tmp_path / "history.json"
    _write_history(history_file, [])
    result = _run(history_file, "--check-inbox")
    assert result.returncode == 0
    assert "No identities in history" in result.stdout


def test_reuse_flag_copies_previous_inbox(tmp_path):
    history_file = tmp_path / "history.json"
    _write_history(history_file, [_usable_identity()])
    result = _run(history_file, "--reuse", "--locale", "en_US")
    assert result.returncode == 0
    entries = json.loads(history_file.read_text(encoding="utf-8"))
    assert len(entries) == 2
    assert entries[1]["email"] == "ana.lopez@tmp.com"
    assert entries[1]["email_token"] == "deadbeef"
    assert entries[1]["email_provider"] == "tempmail"


def test_delay_flag_prints_throttle_message(tmp_path):
    history_file = tmp_path / "history.json"
    result = _run(history_file, "--delay", "0.01", "--locale", "en_US")
    assert result.returncode == 0
    assert "[throttle]" in result.stdout


def test_batch_count_writes_history_and_csv(tmp_path):
    history_file = tmp_path / "history.json"
    result = _run(
        history_file,
        "--count",
        "3",
        "--email-offline",
        "--csv",
        "--delay",
        "0.01",
        "--locale",
        "en_US",
    )
    assert result.returncode == 0
    entries = json.loads(history_file.read_text(encoding="utf-8"))
    assert len(entries) == 3
    assert "[3/3]" in result.stdout
    assert "Batch complete: 3 identities" in result.stdout
    assert "[throttle]" in result.stdout

    csv_path = REPO_ROOT / "identities.csv"
    assert csv_path.exists()
    with csv_path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3
    assert "email_token" not in rows[0]
    csv_path.unlink()


def test_batch_count_one_prints_full_profile(tmp_path):
    history_file = tmp_path / "history.json"
    result = _run(
        history_file, "--count", "1", "--email-offline", "--locale", "en_US"
    )
    assert result.returncode == 0
    assert "IDENTITY" in result.stdout
    assert "[1/1]" not in result.stdout


def test_log_file_created_on_generation(tmp_path):
    log_file = tmp_path / "app.log"
    env = {
        **os.environ,
        "IDENTITY_HISTORY_FILE": str(tmp_path / "history.json"),
        "EMAIL_USAGE_FILE": str(tmp_path / "email_usage.json"),
        "CUSTOM_DOMAINS_FILE": str(tmp_path / "domains.json"),
        "IDENTITY_LOG_FILE": str(log_file),
    }
    result = subprocess.run(
        [PYTHON, "-X", "utf8", str(REPO_ROOT / "main.py"),
         "--email-offline", "--locale", "en_US"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0
    assert log_file.exists()