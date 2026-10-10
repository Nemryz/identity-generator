"""
Tests for exporter.py, focusing on the JSON export collision handling and the CSV and JSONL batch exports.
"""

import csv
import json

import pytest

import exporter


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(exporter, "_OUTPUT_DIR", tmp_path)
    return tmp_path


def _identity(username: str, identity_id: str) -> dict:
    return {
        "id": identity_id,
        "username": username,
        "full_name": "Test User",
        "email": "test@example.com",
    }


def test_export_uses_username_filename(out_dir):
    path = exporter.to_json_file(_identity("carlos85042", "abc123456789"))
    assert path.name == "carlos85042_identity.json"
    assert path.exists()


def test_export_does_not_overwrite_existing_file(out_dir):
    first = _identity("carlos85042", "aaaaaaaaaaaaaaaa")
    second = _identity("carlos85042", "bbbbbbbbbbbbbbbb")

    path1 = exporter.to_json_file(first)
    path2 = exporter.to_json_file(second)

    assert path1 != path2
    assert path1.name == "carlos85042_identity.json"
    assert path2.name == "carlos85042_bbbbbbbb_identity.json"
    assert json.loads(path1.read_text(encoding="utf-8"))["id"] == first["id"]
    assert json.loads(path2.read_text(encoding="utf-8"))["id"] == second["id"]


def test_export_roundtrip_content(out_dir):
    identity = _identity("maria77521", "cccccccccccccccc")
    path = exporter.to_json_file(identity)
    assert json.loads(path.read_text(encoding="utf-8")) == identity


def test_csv_export_rows_and_columns(out_dir):
    identities = [
        _identity("carlos85042", "aaaaaaaa"),
        _identity("maria77521", "bbbbbbbb"),
    ]
    path = exporter.to_csv_file(identities)
    assert path.name == "identities.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["username"] == "carlos85042"
    assert rows[0]["full_name"] == "Test User"
    assert rows[0]["email"] == "test@example.com"
    assert "email_token" not in rows[0]


def test_csv_export_overwrites_previous_file(out_dir):
    exporter.to_csv_file([_identity("first", "1")])
    path = exporter.to_csv_file([_identity("second", "2")])
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["username"] == "second"

# --- to_jsonl_file: newline-delimited export (A3) -------------------------------------


def _full_identity(**overrides) -> dict:
    """I build a complete identity so the export tests see the same field set the generator produces."""
    identity = {
        "id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
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
        "national_id": "12345678Z",
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
    identity.update(overrides)
    return identity


def test_jsonl_writes_one_line_per_identity(out_dir):
    """I check the line count matches the batch size, which is what makes the file streamable."""
    identities = [_full_identity(username=f"user{n}") for n in range(4)]
    path = exporter.to_jsonl_file(identities)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4


def test_jsonl_lines_are_individually_valid_json(out_dir):
    """I parse every line on its own, since a malformed line would break any consumer reading incrementally."""
    path = exporter.to_jsonl_file([_full_identity()])
    for line in path.read_text(encoding="utf-8").splitlines():
        assert isinstance(json.loads(line), dict)


def test_jsonl_never_includes_the_email_token(out_dir):
    """I assert the inbox token never reaches the export, the same decision the CSV makes, because the token reads someone else's mailbox."""
    path = exporter.to_jsonl_file([_full_identity()])
    assert "secret-token" not in path.read_text(encoding="utf-8")
    assert "email_token" not in json.loads(path.read_text(encoding="utf-8"))


def test_jsonl_record_equals_the_identity_minus_the_token(out_dir):
    """I check the round trip loses exactly the token and nothing else, which catches a silently dropped field."""
    identity = _full_identity()
    path = exporter.to_jsonl_file([identity])
    expected = {k: v for k, v in identity.items() if k != "email_token"}
    assert json.loads(path.read_text(encoding="utf-8")) == expected


def test_jsonl_keeps_the_field_order_stable_across_lines(out_dir):
    """I check the key order is identical on every line, so diffs between two runs stay readable and a fixed-schema consumer can rely on it."""
    identities = [_full_identity(username=f"user{n}") for n in range(3)]
    path = exporter.to_jsonl_file(identities)
    orders = [list(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(order == orders[0] for order in orders)


def test_jsonl_is_overwritten_on_every_run(out_dir):
    """I check a second smaller batch replaces the file instead of appending, so a pipeline never reads stale identities."""
    exporter.to_jsonl_file([_full_identity(username=f"user{n}") for n in range(5)])
    exporter.to_jsonl_file([_full_identity(username="only")])
    lines = out_dir.joinpath("identities.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_jsonl_is_written_as_utf8_without_escapes(out_dir):
    """I check accented names stay readable in the file, because escaped unicode is technically valid but useless to a human opening it."""
    identity = _full_identity(first_name="Mónica", full_name="Mónica Núñez")
    path = exporter.to_jsonl_file([identity])
    raw = path.read_text(encoding="utf-8")
    assert "Mónica Núñez" in raw
    assert "\\u" not in raw


def test_jsonl_filename_is_the_documented_one(out_dir):
    """I pin the filename so a pipeline can rely on it, matching identities.csv."""
    path = exporter.to_jsonl_file([_full_identity()])
    assert path.name == "identities.jsonl"


def test_csv_and_jsonl_export_the_same_fields(out_dir):
    """I guard the drift that a new identity field reaches one export but not the other, since both drop email_token for the same reason."""
    identity = _full_identity()
    csv_path = exporter.to_csv_file([identity])
    jsonl_path = exporter.to_jsonl_file([identity])
    with csv_path.open(encoding="utf-8", newline="") as handle:
        csv_fields = next(csv.reader(handle))
    jsonl_fields = list(json.loads(jsonl_path.read_text(encoding="utf-8")))
    assert set(csv_fields) == set(jsonl_fields)
    assert set(identity) - {"email_token"} == set(jsonl_fields)


def test_csv_and_jsonl_order_differently_on_purpose(out_dir):
    """I pin that the CSV leads with full_name for a spreadsheet reader while the JSONL keeps the generator order, so nobody "fixes" one of them into the other by accident."""
    identity = _full_identity()
    with exporter.to_csv_file([identity]).open(encoding="utf-8", newline="") as fh:
        csv_fields = next(csv.reader(fh))
    jsonl_fields = list(json.loads(exporter.to_jsonl_file([identity]).read_text(encoding="utf-8")))
    assert csv_fields[0] == "full_name"
    assert jsonl_fields[0] == "id"
    assert jsonl_fields == [k for k in identity if k != "email_token"]
    assert csv_fields != jsonl_fields


def test_jsonl_handles_an_empty_batch(out_dir):
    """I check an empty list produces an empty file and not a stray newline, which keeps line counts honest."""
    path = exporter.to_jsonl_file([])
    assert path.read_text(encoding="utf-8") == ""


def test_to_schema_file_writes_the_schema(out_dir):
    """I check the schema file lands where --schema and --json promise, and that it parses back to the same object."""
    import schema as schema_module

    path = exporter.to_schema_file()
    assert path.name == "identity.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == schema_module.IDENTITY_SCHEMA
