# Resilience tests for email_api.py: providers failing, rate limits, token lag, corrupted state.

import json
from unittest.mock import patch

import pytest
import requests

from identity_generator import email_api


def test_tempmail_email_returns_none_on_connection_error(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(email_api.requests, "post", boom)
    assert email_api._tempmail_email("prefix") is None


def test_mailtm_email_returns_none_on_server_error(monkeypatch):
    class Resp:
        status_code = 500
        def raise_for_status(self):
            raise requests.HTTPError("500")
        def json(self):
            return {}
    monkeypatch.setattr(email_api.requests, "get", lambda *a, **k: Resp())
    assert email_api._mailtm_email("local") is None


def test_mailtm_token_retries_and_returns_none(monkeypatch):
    class Resp:
        status_code = 500
        def json(self):
            return {}
    monkeypatch.setattr(email_api.requests, "post", lambda *a, **k: Resp())
    monkeypatch.setattr(email_api.time, "sleep", lambda s: None)
    assert email_api._mailtm_token("a@b.com", "pw") is None


def test_get_temp_email_falls_back_to_offline(monkeypatch):
    monkeypatch.setattr(email_api, "_custom_domains", lambda: [])
    monkeypatch.setattr(email_api, "_can_use", lambda p: True)
    monkeypatch.setattr(email_api, "_tempmail_email", lambda p: None)
    monkeypatch.setattr(email_api, "_mailtm_email", lambda p: None)
    monkeypatch.setattr(email_api, "_record_usage", lambda p: None)
    result = email_api.get_temp_email("Carlos", "Garcia", usable=True)
    assert result["provider"] == "offline"
    assert result["token"] is None


def test_tempmail_read_returns_empty_on_http_error(monkeypatch):
    class Resp:
        status_code = 404
        def raise_for_status(self):
            raise requests.HTTPError("404")
    monkeypatch.setattr(email_api.requests, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(email_api, "_record_usage", lambda p: None)
    assert email_api._tempmail_read("token", 10) == []


def test_mailtm_read_returns_empty_on_http_error(monkeypatch):
    class Resp:
        status_code = 401
        def raise_for_status(self):
            raise requests.HTTPError("401")
    monkeypatch.setattr(email_api.requests, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(email_api, "_record_usage", lambda p: None)
    assert email_api._mailtm_read("token", 10) == []


def test_load_api_keys_backs_up_corrupt(tmp_path, monkeypatch):
    bad = tmp_path / "keys.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(email_api, "KEYS_FILE", bad)
    assert email_api.load_api_keys() == {}
    backups = list(tmp_path.glob("email_keys.corrupt.*.bak"))
    assert backups, "corrupt keys file was not backed up"


def test_custom_domains_invalid_returns_empty(tmp_path, monkeypatch):
    bad = tmp_path / "domains.json"
    bad.write_text("[1,2,3]", encoding="utf-8")
    monkeypatch.setattr(email_api, "CUSTOM_DOMAINS_FILE", bad)
    assert email_api._custom_domains() == []