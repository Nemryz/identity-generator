"""
Tests for exporter.py, focusing on JSON export collision handling.
"""

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