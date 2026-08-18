"""
CLI tests for main.py.

Runs the real entry point in a subprocess to verify argument handling,
especially the friendly error for unsupported --locale values.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-X", "utf8", str(REPO_ROOT / "main.py"), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_unknown_locale_fails_with_friendly_error():
    result = _run("--locale", "xx_XX")
    assert result.returncode == 2
    assert "unknown locale" in result.stderr
    assert "xx_XX" in result.stderr
    assert "--list-locales" in result.stderr


def test_list_locales_exits_cleanly():
    result = _run("--list-locales")
    assert result.returncode == 0
    assert "es_ES" in result.stdout
    assert "en_US" in result.stdout


def test_faker_only_locale_accepted():
    result = _run("--locale", "en_CA")
    assert result.returncode == 0
    assert "Generating identity" in result.stdout