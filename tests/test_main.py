# CLI tests for main.py: I run the real entry point in a subprocess to verify argument handling, especially the friendly error for unsupported --locale values, and every subprocess points IDENTITY_HISTORY_FILE at a temporary path so the generated identities never pollute the real history.json of the project.

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
        encoding="utf-8",
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

# --- --seed: reproducibility (A1) ----------------------------------------------------

_PROFILE_FIELDS = (
    "Full name",
    "Date of birth",
    "Gender",
    "National ID",
    "Passport",
    "Address",
    "City",
    "Postcode",
    "Phone",
    "Email",
    "Username",
    "Nickname",
    "Password",
)


def _profile(result: subprocess.CompletedProcess) -> dict:
    # I pull the printed profile fields back out of the terminal so a reproducibility check needs no file at all and never pollutes the project directory.
    values = {}
    for line in result.stdout.splitlines():
        stripped = line.strip()
        for field in _PROFILE_FIELDS:
            if stripped.startswith(field):
                _, _, value = stripped.partition(field)
                values[field] = value.strip()
    return values


def test_same_seed_reproduces_the_whole_profile(tmp_path):
    # I run the real CLI twice with the same seed and compare every printed field, which is the end-to-end proof that a seeded run is reproducible.
    first = _run(tmp_path / "h1.json", "--seed", "42", "--email-offline", "--locale", "es_ES")
    second = _run(tmp_path / "h2.json", "--seed", "42", "--email-offline", "--locale", "es_ES")
    assert first.returncode == 0 and second.returncode == 0
    profile_first, profile_second = _profile(first), _profile(second)
    assert len(profile_first) == len(_PROFILE_FIELDS)
    assert profile_first == profile_second


def test_different_seeds_produce_different_profiles(tmp_path):
    # I check a different seed moves the profile, so the flag is really seeding something and not being ignored.
    first = _run(tmp_path / "h1.json", "--seed", "42", "--email-offline", "--locale", "es_ES")
    second = _run(tmp_path / "h3.json", "--seed", "99", "--email-offline", "--locale", "es_ES")
    assert _profile(first) != _profile(second)


def test_unseeded_runs_differ(tmp_path):
    # I check two runs without --seed differ, guarding against the seeding having become unconditional.
    first = _run(tmp_path / "h1.json", "--email-offline", "--locale", "es_ES")
    second = _run(tmp_path / "h2.json", "--email-offline", "--locale", "es_ES")
    assert _profile(first) != _profile(second)


def _batch_lines(result: subprocess.CompletedProcess) -> list[str]:
    # I collect the compact batch lines the CLI prints in batch mode.
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("[") and "] " in line
    ]


def test_seeded_batch_repeats_the_same_sequence(tmp_path):
    # I check a seeded batch is reproducible as a whole sequence, which is what a fixture file for a test suite needs.
    first = _run(tmp_path / "h1.json", "--seed", "7", "--email-offline", "--count", "3")
    second = _run(tmp_path / "h2.json", "--seed", "7", "--email-offline", "--count", "3")
    lines_first, lines_second = _batch_lines(first), _batch_lines(second)
    assert len(lines_first) == 3
    assert lines_first == lines_second


def test_seeded_batch_entries_are_distinct(tmp_path):
    # I check the identities inside one seeded run still differ, because reseeding per identity would have collapsed the batch into duplicates.
    result = _run(tmp_path / "h1.json", "--seed", "7", "--email-offline", "--count", "5")
    names = {line.split("]")[1].split("—")[0].strip() for line in _batch_lines(result)}
    assert len(names) == 5


def test_seed_and_locale_work_together(tmp_path):
    # I check a seeded run with an explicit locale stays reproducible, since --locale also consumes the seeded random stream.
    first = _run(tmp_path / "h1.json", "--seed", "3", "--email-offline", "--locale", "de_DE")
    second = _run(tmp_path / "h2.json", "--seed", "3", "--email-offline", "--locale", "de_DE")
    assert _profile(first) == _profile(second)


def test_seed_without_locale_is_reproducible(tmp_path):
    # I check the default random locale is reproducible too, because random.choice draws from the seeded stream and must not break determinism.
    first = _run(tmp_path / "h1.json", "--seed", "11", "--email-offline")
    second = _run(tmp_path / "h2.json", "--seed", "11", "--email-offline")
    assert _profile(first) == _profile(second)


# --- --schema (A2) -------------------------------------------------------------------


def test_schema_flag_prints_valid_json(tmp_path):
    # I check stdout carries the schema and nothing else, since the flag is meant to be piped into a validator.
    result = _run(tmp_path / "h1.json", "--schema")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["$schema"].endswith("2020-12/schema")
    assert "national_id" in payload["properties"]


def test_schema_flag_exits_without_generating(tmp_path):
    # I check the flag short-circuits, so asking for the schema never creates an identity or touches the providers.
    result = _run(tmp_path / "h1.json", "--schema")
    assert "Generating identity" not in result.stdout
    assert "IDENTITY" not in result.stdout


def test_schema_flag_documents_the_nullable_fields(tmp_path):
    # I check the published schema admits null for the three fields the generator can leave empty, so a consumer does not read it as a bug.
    payload = json.loads(_run(tmp_path / "h1.json", "--schema").stdout)
    for field in ("national_id", "email_token", "email_provider"):
        assert payload["properties"][field]["type"] == ["string", "null"]


# --- --list-locales (A4) -------------------------------------------------------------


def test_list_locales_prints_the_capability_table(tmp_path):
    # I check the flag renders the table with its header instead of a bare list of codes.
    result = _run(tmp_path / "h1.json", "--list-locales")
    assert result.returncode == 0
    for column in ("Locale", "Country", "Document", "Passport", "Address", "Cities/streets"):
        assert column in result.stdout


def test_list_locales_shows_every_supported_locale(tmp_path):
    # I check no locale disappears from the table, which is the whole point of the command.
    result = _run(tmp_path / "h1.json", "--list-locales")
    from identity_generator.generator import get_supported_locales

    for locale in get_supported_locales():
        assert locale in result.stdout


def test_list_locales_shows_documents_and_fallbacks(tmp_path):
    # I check a known document label and the Faker fallback both reach the terminal, which proves the capability values are wired to the table and not only tested in isolation.
    result = _run(tmp_path / "h1.json", "--list-locales")
    assert "NIF/DNI" in result.stdout
    assert "Codice fiscale" in result.stdout
    assert "Faker fallback" in result.stdout
