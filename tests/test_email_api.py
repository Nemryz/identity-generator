"""
Tests for email_api.py: provider chain, rate-limit counters and tokens.
"""

import json

import pytest

import email_api
from email_api import (
    _can_use,
    _local_part,
    _offline_email,
    _record_usage,
    _usage_count,
    get_temp_email,
    usage_summary,
)


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture
def usage_file(tmp_path, monkeypatch):
    monkeypatch.setattr(email_api, "USAGE_FILE", tmp_path / "email_usage.json")
    return tmp_path / "email_usage.json"


@pytest.fixture
def fake_clock(monkeypatch):
    state = {"now": 1000.0}
    monkeypatch.setattr(email_api.time, "time", lambda: state["now"])
    return state


def _no_network(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("no network")

    monkeypatch.setattr(email_api.requests, "get", boom)
    monkeypatch.setattr(email_api.requests, "post", boom)


def _mailtm_success(monkeypatch, token="tok1"):
    def fake_get(url, **kwargs):
        return _Resp(200, {"hydra:member": [{"domain": "mail.tm"}]})

    def fake_post(url, **kwargs):
        if url.endswith("/accounts"):
            return _Resp(201, {})
        return _Resp(200, {"token": token})

    monkeypatch.setattr(email_api.requests, "get", fake_get)
    monkeypatch.setattr(email_api.requests, "post", fake_post)


def _tempmail_success(monkeypatch, address="carlos_garcia@tmp.com", token="tok2"):
    def fake_get(url, **kwargs):
        raise RuntimeError("mailtm down")

    def fake_post(url, **kwargs):
        return _Resp(200, {"address": address, "token": token})

    monkeypatch.setattr(email_api.requests, "get", fake_get)
    monkeypatch.setattr(email_api.requests, "post", fake_post)


def test_local_part_from_names():
    assert _local_part("Carlos", "García") == "carlos.garcia"


def test_local_part_cjk_falls_back_to_user():
    assert _local_part("太郎", "佐藤") == "user"


@pytest.mark.parametrize(
    "first,last", [("José", "Pérez"), ("Åsa", "Öberg"), ("太郎", "佐藤")]
)
def test_local_part_is_ascii_and_non_empty(first, last):
    part = _local_part(first, last)
    assert part.isascii()
    assert len(part) >= 3


def test_offline_email_uses_local_and_disposable_domain(monkeypatch):
    monkeypatch.setattr(email_api.random, "choice", lambda seq: seq[0])
    assert _offline_email("carlos.garcia") == "carlos.garcia@mailinator.com"


def test_offline_mode_skips_network(usage_file, monkeypatch):
    _no_network(monkeypatch)
    result = get_temp_email("Carlos", "García", usable=False)
    assert result["token"] is None
    assert result["email"].startswith("carlos.garcia@")
    assert _usage_count("offline") == 1


def test_chain_prefers_tempmail(usage_file, monkeypatch):
    _tempmail_success(monkeypatch)
    result = get_temp_email("Carlos", "García")
    assert result["email"] == "carlos_garcia@tmp.com"
    assert result["token"] == "tok2"
    assert _usage_count("tempmail") == 1


def test_chain_falls_back_to_mailtm(usage_file, monkeypatch):
    def fake_get(url, **kwargs):
        return _Resp(200, {"hydra:member": [{"domain": "mail.tm"}]})

    def fake_post(url, **kwargs):
        if "tempmail" in url:
            raise RuntimeError("tempmail down")
        if url.endswith("/accounts"):
            return _Resp(201, {})
        return _Resp(200, {"token": "tok1"})

    monkeypatch.setattr(email_api.requests, "get", fake_get)
    monkeypatch.setattr(email_api.requests, "post", fake_post)

    result = get_temp_email("Carlos", "García")
    assert result["email"] == "carlos.garcia@mail.tm"
    assert result["token"] == "tok1"
    assert _usage_count("mailtm") == 1


def test_chain_offline_when_all_providers_down(usage_file, monkeypatch):
    _no_network(monkeypatch)
    result = get_temp_email("Carlos", "García")
    assert result["token"] is None
    assert result["email"].startswith("carlos.garcia@")
    assert _usage_count("offline") == 1


def test_mailtm_retries_when_address_taken(usage_file, monkeypatch):
    calls = {"accounts": 0}

    def fake_get(url, **kwargs):
        return _Resp(200, {"hydra:member": [{"domain": "mail.tm"}]})

    def fake_post(url, **kwargs):
        if url.endswith("/accounts"):
            calls["accounts"] += 1
            return _Resp(201 if calls["accounts"] >= 3 else 422, {})
        return _Resp(200, {"token": "tok1"})

    monkeypatch.setattr(email_api.requests, "get", fake_get)
    monkeypatch.setattr(email_api.requests, "post", fake_post)

    result = get_temp_email("Carlos", "García")
    assert result["email"] == "carlos.garcia2@mail.tm"
    assert result["token"] == "tok1"


def test_counters_within_window(usage_file, fake_clock):
    for _ in range(3):
        _record_usage("tempmail")
    assert _usage_count("tempmail") == 3
    assert _can_use("tempmail")


def test_tempmail_skipped_at_limit(usage_file, fake_clock, monkeypatch, capsys):
    for _ in range(25):
        _record_usage("tempmail")
    assert not _can_use("tempmail")

    def fake_get(url, **kwargs):
        raise RuntimeError("mailtm down")

    def fake_post(url, **kwargs):
        raise AssertionError("tempmail must not be called at limit")

    monkeypatch.setattr(email_api.requests, "get", fake_get)
    monkeypatch.setattr(email_api.requests, "post", fake_post)

    result = get_temp_email("Carlos", "García")
    assert result["token"] is None
    assert result["email"].startswith("carlos.garcia@")
    err = capsys.readouterr().err
    assert "en el límite" in err
    assert "mail.tm" in err


def test_usage_prunes_expired_entries(usage_file, fake_clock):
    _record_usage("tempmail")
    assert _usage_count("tempmail") == 1
    fake_clock["now"] = (
        1000 + email_api.PROVIDER_LIMITS["tempmail"]["window"] + 1
    )
    assert _usage_count("tempmail") == 0


def test_usage_persists_across_runs(usage_file, fake_clock):
    _record_usage("mailtm")
    raw = json.loads(usage_file.read_text(encoding="utf-8"))
    assert "mailtm" in raw
    assert _usage_count("mailtm") == 1


def test_usage_summary_lists_providers(usage_file):
    summary = usage_summary()
    for provider in ("mailtm", "tempmail", "offline"):
        assert provider in summary