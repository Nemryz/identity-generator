# Tests for the Parquet export in exporter.py: I read the file back through pyarrow itself and assert the explicit schema, and I simulate the missing optional dependency at the import level so the controlled error is exercised even on a machine where pyarrow is installed, which is the situation CI and every dev environment live in.

import os
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from identity_generator import exporter
from identity_generator.exporter import EXPORT_FIELDS


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(exporter, "output_dir", lambda: tmp_path)
    return tmp_path


def _identity(index: int) -> dict:
    # I build a complete identity with one deliberately null field, because the Parquet mapping must carry optional values as nulls and not as the string "None".
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


def test_parquet_export_writes_a_readable_table(out_dir):
    path = exporter.to_parquet_file([_identity(1), _identity(2)])
    assert path.name == "identities.parquet"
    table = pq.read_table(path)
    assert table.num_rows == 2
    rows = table.to_pylist()
    assert rows[0]["full_name"] == "Marta Nunez"
    assert rows[1]["id"] == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee02"


def test_parquet_schema_is_explicit_string_columns_over_the_export_fields(out_dir):
    # I pin the declared schema instead of trusting inference, so the file shape stays identical no matter which locale or null fields the first record carries.
    path = exporter.to_parquet_file([_identity(1)])
    schema = pq.read_schema(path)
    assert schema.names == EXPORT_FIELDS
    for name in EXPORT_FIELDS:
        assert str(schema.field(name).type) == "string"


def test_parquet_export_maps_none_to_null(out_dir):
    path = exporter.to_parquet_file([_identity(2)])
    rows = pq.read_table(path).to_pylist()
    assert rows[0]["national_id"] is None


def test_parquet_export_excludes_the_email_token(out_dir):
    path = exporter.to_parquet_file([_identity(1)])
    assert "email_token" not in pq.read_schema(path).names
    assert b"secret-token" not in path.read_bytes()


def test_parquet_export_overwrites_the_previous_file(out_dir):
    # I pin the documented semantics, where every run replaces the file, so an analytics pipeline always reads exactly one batch.
    exporter.to_parquet_file([_identity(1), _identity(2)])
    path = exporter.to_parquet_file([_identity(3)])
    table = pq.read_table(path)
    assert table.num_rows == 1
    assert table.to_pylist()[0]["id"] == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee03"


def test_parquet_export_handles_an_empty_batch(out_dir):
    path = exporter.to_parquet_file([])
    table = pq.read_table(path)
    assert table.num_rows == 0
    assert table.column_names == EXPORT_FIELDS


def test_missing_pyarrow_reports_the_install_hint(out_dir, monkeypatch):
    # I blank the module out of sys.modules, which is exactly what a base install looks like to the import system, and expect the controlled error naming the extra instead of a traceback.
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)
    with pytest.raises(SystemExit) as excinfo:
        exporter.to_parquet_file([_identity(1)])
    assert "identity-generator[parquet]" in str(excinfo.value)


def test_pyarrow_available_is_false_when_the_engine_is_absent(monkeypatch):
    # I keep the CLI preflight probe and the lazy loader reading the same world, so the flag refuses exactly the environments the export would refuse.
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)
    assert exporter.pyarrow_available() is False


def test_pyarrow_available_is_true_when_the_engine_is_installed():
    assert exporter.pyarrow_available() is True


def test_parquet_export_failure_leaves_the_previous_file_intact(
    out_dir, monkeypatch
):
    # I break the engine's write after a first successful export, so the previous file must survive untouched and no partial staging file may be left behind.
    path = exporter.to_parquet_file([_identity(1)])
    before = path.read_bytes()

    def _broken_write(*_args, **_kwargs):
        raise RuntimeError("disk error")

    monkeypatch.setattr(pq, "write_table", _broken_write)
    with pytest.raises(RuntimeError):
        exporter.to_parquet_file([_identity(2)])
    assert path.read_bytes() == before
    assert list(out_dir.glob("identities.parquet.tmp*")) == []


def test_parquet_export_replaces_the_target_through_a_unique_temp_file(
    out_dir, monkeypatch
):
    # I pin the same protection the SQLite export has, where every run stages the file under its own unique name in the target directory before the atomic replacement.
    captured = []
    real_replace = os.replace

    def _spy(src, dst):
        captured.append(Path(src))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _spy)
    exporter.to_parquet_file([_identity(1)])
    exporter.to_parquet_file([_identity(2)])
    assert len(captured) == 2
    assert captured[0] != captured[1]
    assert captured[0].parent == out_dir
    assert captured[0].name.startswith("identities.parquet.tmp-")


def test_parquet_export_survives_a_leftover_temp_file(out_dir):
    # I recreate the wreckage of a hard-killed export, where a stale staging file sits in the target directory, and a fresh export must still write its own staging file and replace the target.
    (out_dir / "identities.parquet.tmp-stale").write_bytes(b"garbage")
    path = exporter.to_parquet_file([_identity(1)])
    assert pq.read_table(path).num_rows == 1
