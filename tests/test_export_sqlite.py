# Tests for the SQLite export in exporter.py: I query the written database with real SQL through the stdlib sqlite3 instead of trusting that a file exists, because the point of the format is that a consumer can run a query against it, and the overwrite, collision and failure semantics are exercised through the same public function the CLI calls.

import os
import sqlite3
from pathlib import Path

import pytest

from identity_generator import exporter
from identity_generator.exporter import EXPORT_FIELDS


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(exporter, "output_dir", lambda: tmp_path)
    return tmp_path


def _identity(index: int) -> dict:
    # I build a complete identity with one deliberately null field, because the SQLite mapping must carry optional values as NULL and not as the string "None".
    return {
        "id": f"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee0{index}",
        "created_at": "2026-08-19T10:15:30.123456+00:00",
        "locale": "es_ES",
        "gender": "female",
        "first_name": "Marta",
        "last_name": "Nunez",
        "full_name": "Marta Nunez",
        "date_of_birth": "1994-03-17",
        "age": 32,
        "address": "Calle Mayor 14",
        "city": "Valladolid",
        "postcode": "47001",
        "country": "Espana",
        "national_id": "12345678Z" if index % 2 else None,
        "passport_number": "TRX040250",
        "phone": "+34 612 34 56 78",
        "occupation": "Arquitecta",
        "email": "marta.nunez@tempmail.lol",
        "email_token": "secret-token",
        "email_provider": "tempmail",
        "username": "marta1234",
        "nickname": "marta94",
        "password": "nV!862XVVuMpmvCo",
    }


def _rows(path):
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM identities")]
    finally:
        conn.close()


def test_sqlite_export_writes_a_queryable_database(out_dir):
    path = exporter.to_sqlite_file([_identity(1), _identity(2)])
    assert path.name == "identities.db"
    rows = _rows(path)
    assert len(rows) == 2
    assert rows[0]["full_name"] == "Marta Nunez"
    assert rows[1]["id"] == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee02"


def test_sqlite_export_excludes_the_email_token(out_dir):
    path = exporter.to_sqlite_file([_identity(1)])
    conn = sqlite3.connect(path)
    try:
        columns = [
            row[1] for row in conn.execute("PRAGMA table_info(identities)")
        ]
    finally:
        conn.close()
    assert "email_token" not in columns
    assert columns == [field for field in EXPORT_FIELDS]
    assert b"secret-token" not in path.read_bytes()


def test_sqlite_export_overwrites_the_previous_database(out_dir):
    # I pin the documented semantics, where every run replaces the file instead of appending, so a pipeline always knows it reads exactly one batch.
    exporter.to_sqlite_file([_identity(1), _identity(2)])
    path = exporter.to_sqlite_file([_identity(3)])
    rows = _rows(path)
    assert len(rows) == 1
    assert rows[0]["id"] == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee03"


def test_sqlite_export_maps_none_to_sql_null(out_dir):
    path = exporter.to_sqlite_file([_identity(2)])
    rows = _rows(path)
    assert rows[0]["national_id"] is None


def test_sqlite_export_stores_every_value_as_text(out_dir):
    # I keep one uniform column type instead of letting SQLite guess, which is what makes the schema stable across locales and runs.
    path = exporter.to_sqlite_file([_identity(1)])
    rows = _rows(path)
    assert rows[0]["age"] == "32"
    assert rows[0]["date_of_birth"] == "1994-03-17"


def test_sqlite_export_pins_the_primary_key_on_the_identity_id(out_dir):
    path = exporter.to_sqlite_file([_identity(1)])
    conn = sqlite3.connect(path)
    try:
        info = list(conn.execute("PRAGMA table_info(identities)"))
    finally:
        conn.close()
    primary = [row[1] for row in info if row[5]]
    assert primary == ["id"]


def test_sqlite_export_failure_leaves_the_previous_database_intact(
    out_dir, monkeypatch
):
    # I simulate a storage failure between the temporary build and the replacement, so a broken run can never destroy a database that was still valid, and no partial temporary file survives.
    path = exporter.to_sqlite_file([_identity(1)])
    before = path.read_bytes()

    class _BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("disk error")

        def executemany(self, *_args, **_kwargs):
            raise RuntimeError("disk error")

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        exporter.sqlite3, "connect", lambda *_a, **_k: _BrokenConnection()
    )
    with pytest.raises(RuntimeError):
        exporter.to_sqlite_file([_identity(2)])
    assert path.read_bytes() == before
    assert list(out_dir.glob("identities.db.tmp*")) == []


def test_sqlite_export_uses_a_unique_temp_file_per_run(out_dir, monkeypatch):
    # I pin the anti-collision rule, where every run stages its database in its own uniquely named sibling of the target so two concurrent exports never fight over one fixed temporary file.
    captured = []
    real_replace = os.replace

    def _spy(src, dst):
        captured.append(Path(src))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _spy)
    exporter.to_sqlite_file([_identity(1)])
    exporter.to_sqlite_file([_identity(2)])
    assert len(captured) == 2
    assert captured[0] != captured[1]
    assert captured[0].parent == out_dir
    assert captured[0].name.startswith("identities.db.tmp-")


def test_sqlite_export_survives_a_leftover_temp_database_from_a_crashed_run(
    out_dir,
):
    # I recreate the wreckage of a hard-killed export, where a stale temporary database already holds an identities table, and a fresh export must still build its own staging file and replace the target cleanly.
    stale_conn = sqlite3.connect(out_dir / "identities.db.tmp-stale")
    stale_conn.execute("CREATE TABLE identities (id TEXT)")
    stale_conn.commit()
    stale_conn.close()
    path = exporter.to_sqlite_file([_identity(1)])
    rows = _rows(path)
    assert len(rows) == 1
    assert rows[0]["id"] == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee01"


def test_sqlite_export_handles_an_empty_batch(out_dir):
    path = exporter.to_sqlite_file([])
    assert _rows(path) == []
