"""
CLI tests for main.py.

Runs the real entry point in a subprocess to verify argument handling,
especially the friendly error for unsupported --locale values.

Every subprocess points IDENTITY_HISTORY_FILE at a temporary path so the
generated identities never pollute the real history.json of the project.
"""

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