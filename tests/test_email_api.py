"""
Tests for email_api.py: provider chain, rate-limit counters and tokens.
"""

import json

import pytest

import email_api
from email_api import (
    _can_use,
    _custom_domains,
    _custom_email,
    _local_part,
    _offline_email,
    _record_usage,
    _usage_count,
    check_inbox,
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


def _with_custom_domains(tmp_path, monkeypatch, content):
    domains_file = tmp_path / "domains.json"
    domains_file.write_text(content, encoding="utf-8")
    monkeypatch.setattr(email_api, "CUSTOM_DOMAINS_FILE", domains_file)
    return domains_file


def test_custom_domains_used_first_without_network(usage_file, tmp_path, monkeypatch):
    _with_custom_domains(
        tmp_path, monkeypatch, '{"domains": ["mail.midominio.com"]}'
    )
    _no_network(monkeypatch)
    result = get_temp_email("Carlos", "García")
    assert result["provider"] == "custom"
    assert result["token"] is None
    assert result["email"].startswith("carlos.garcia.")
    assert result["email"].endswith("@mail.midominio.com")
    assert _usage_count("custom") == 1


def test_custom_domains_used_in_offline_mode(usage_file, tmp_path, monkeypatch):
    _with_custom_domains(
        tmp_path, monkeypatch, '{"domains": ["mail.midominio.com"]}'
    )
    _no_network(monkeypatch)
    result = get_temp_email("Carlos", "García", usable=False)
    assert result["provider"] == "custom"
    assert result["email"].endswith("@mail.midominio.com")


def test_custom_domains_missing_file_falls_back_to_chain(
    usage_file, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        email_api, "CUSTOM_DOMAINS_FILE", tmp_path / "no_such_file.json"
    )
    _no_network(monkeypatch)
    result = get_temp_email("Carlos", "García")
    assert result["provider"] == "offline"
    assert result["email"].startswith("carlos.garcia@")


def test_custom_domains_invalid_file_falls_back_to_chain(
    usage_file, tmp_path, monkeypatch
):
    _with_custom_domains(tmp_path, monkeypatch, "{broken json")
    _no_network(monkeypatch)
    result = get_temp_email("Carlos", "García")
    assert result["provider"] == "offline"


def test_custom_domains_empty_entries_ignored(tmp_path, monkeypatch):
    domains_file = _with_custom_domains(
        tmp_path, monkeypatch, '{"domains": []}'
    )
    assert _custom_domains() == []
    domains_file.write_text('{"domains": [42, ""]}', encoding="utf-8")
    assert _custom_domains() == []


def test_custom_domains_accepts_utf8_bom(tmp_path, monkeypatch):
    _with_custom_domains(tmp_path, monkeypatch, "\ufeff" '{"domains": ["mail.x.com"]}')
    assert _custom_domains() == ["mail.x.com"]


def test_custom_email_has_numeric_suffix(monkeypatch):
    monkeypatch.setattr(email_api.random, "choices", lambda *a, **k: ["1234"])
    monkeypatch.setattr(email_api.random, "choice", lambda seq: seq[0])
    assert _custom_email("carlos.garcia", ["mail.x.com"]) == (
        "carlos.garcia.1234@mail.x.com"
    )


def test_check_inbox_custom_raises_forwarding_message(usage_file):
    with pytest.raises(ValueError, match="tu bandeja"):
        check_inbox(
            {
                "email": "x@mail.midominio.com",
                "email_token": None,
                "email_provider": "custom",
            }
        )


def test_usage_summary_hides_custom_when_not_configured(usage_file):
    summary = usage_summary()
    assert "custom" not in summary


def test_usage_summary_shows_custom_when_configured(
    usage_file, tmp_path, monkeypatch
):
    _with_custom_domains(
        tmp_path, monkeypatch, '{"domains": ["mail.midominio.com"]}'
    )
    summary = usage_summary()
    assert "custom" in summary
    assert "offline" in summary


def test_offline_mode_skips_network(usage_file, monkeypatch):
    _no_network(monkeypatch)
    result = get_temp_email("Carlos", "García", usable=False)
    assert result["token"] is None
    assert result["provider"] == "offline"
    assert result["email"].startswith("carlos.garcia@")
    assert _usage_count("offline") == 1


def test_chain_prefers_tempmail(usage_file, monkeypatch):
    _tempmail_success(monkeypatch)
    result = get_temp_email("Carlos", "García")
    assert result["email"] == "carlos_garcia@tmp.com"
    assert result["token"] == "tok2"
    assert result["provider"] == "tempmail"
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
    assert result["provider"] == "mailtm"
    assert _usage_count("mailtm") == 1


def test_chain_offline_when_all_providers_down(usage_file, monkeypatch):
    _no_network(monkeypatch)
    result = get_temp_email("Carlos", "García")
    assert result["token"] is None
    assert result["provider"] == "offline"
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


def test_tempmail_skipped_at_limit(usage_file, fake_clock, monkeypatch, caplog):
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
    assert "en el límite" in caplog.text
    assert "mail.tm" in caplog.text


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


def test_check_inbox_tempmail_parses_messages(usage_file, monkeypatch):
    def fake_get(url, **kwargs):
        assert "/v3/inboxes/tok2/emails" in url
        return _Resp(
            200,
            [
                {"from": "no-reply@shop.com", "subject": "Verify", "text": "code 123"},
                {"from": "a@b.com", "subject": "Hi", "text": ""},
            ],
        )

    monkeypatch.setattr(email_api.requests, "get", fake_get)

    messages = check_inbox(
        {"email": "x@tmp.com", "email_token": "tok2", "email_provider": "tempmail"}
    )
    assert len(messages) == 2
    assert messages[0]["from"] == "no-reply@shop.com"
    assert messages[0]["subject"] == "Verify"
    assert messages[0]["text"] == "code 123"
    assert _usage_count("read_tempmail") == 1


def test_check_inbox_tempmail_uses_body_fallback(usage_file, monkeypatch):
    def fake_get(url, **kwargs):
        return _Resp(200, [{"from": "x@y.com", "subject": "S", "body": "html body"}])

    monkeypatch.setattr(email_api.requests, "get", fake_get)

    messages = check_inbox(
        {"email": "x@tmp.com", "email_token": "t", "email_provider": "tempmail"}
    )
    assert messages[0]["text"] == "html body"


def test_check_inbox_mailtm_uses_bearer_and_fetches_bodies(usage_file, monkeypatch):
    seen_headers = {}

    def fake_get(url, **kwargs):
        seen_headers.setdefault(url, kwargs.get("headers", {}))
        if url.endswith("/messages/msg1"):
            return _Resp(200, {"id": "msg1", "text": "full body"})
        return _Resp(
            200,
            {
                "hydra:member": [
                    {
                        "id": "msg1",
                        "from": [{"address": "boss@corp.com"}],
                        "subject": "Welcome",
                    }
                ]
            },
        )

    monkeypatch.setattr(email_api.requests, "get", fake_get)

    messages = check_inbox(
        {"email": "x@mail.tm", "email_token": "mtok", "email_provider": "mailtm"}
    )
    assert len(messages) == 1
    assert messages[0]["from"] == "boss@corp.com"
    assert messages[0]["subject"] == "Welcome"
    assert messages[0]["text"] == "full body"
    assert seen_headers["https://api.mail.tm/messages"]["Authorization"] == "Bearer mtok"
    assert _usage_count("read_mailtm") == 1


def test_check_inbox_offline_identity_raises(usage_file):
    with pytest.raises(ValueError):
        check_inbox(
            {"email": "x@yopmail.com", "email_token": None, "email_provider": "offline"}
        )


def test_check_inbox_unknown_provider_raises(usage_file):
    with pytest.raises(ValueError):
        check_inbox({"email": "x@y.com", "email_token": "t", "email_provider": "old"})


def test_check_inbox_fetch_failure_returns_empty(usage_file, monkeypatch, caplog):
    def boom(*_args, **_kwargs):
        raise RuntimeError("api down")

    monkeypatch.setattr(email_api.requests, "get", boom)

    messages = check_inbox(
        {"email": "x@tmp.com", "email_token": "t", "email_provider": "tempmail"}
    )
    assert messages == []
    assert "no se pudo consultar" in caplog.text


def test_corrupt_usage_file_is_backed_up_and_reset(usage_file, caplog):
    usage_file.write_text("{broken", encoding="utf-8")
    assert _usage_count("tempmail") == 0
    backups = list(usage_file.parent.glob("email_usage.corrupt.*.bak"))
    assert len(backups) == 1
    assert not usage_file.exists()
    assert "backed up" in caplog.text


def test_non_dict_usage_file_is_backed_up_and_reset(usage_file):
    usage_file.write_text("[1, 2, 3]", encoding="utf-8")
    assert _usage_count("mailtm") == 0
    assert len(list(usage_file.parent.glob("email_usage.corrupt.*.bak"))) == 1


def test_valid_usage_file_is_untouched(usage_file):
    _record_usage("tempmail")
    assert _usage_count("tempmail") == 1
    assert not list(usage_file.parent.glob("email_usage.corrupt.*.bak"))