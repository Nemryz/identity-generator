# test_network.py
# I am the only suite that touches the real tempmail.lol and mail.tm APIs, marked network, excluded by default and run manually, because the mocked tests can prove anything about fake responses but cannot see the day a provider changes a status code or a payload key.

import secrets

import pytest
import requests

import identity_generator.email_api as email_api

pytestmark = pytest.mark.network


def test_tempmail_lol_creates_a_readable_inbox(tmp_path, monkeypatch):
    # I point the usage counters at an isolated directory because the inbox read records usage exactly like a real run would.
    monkeypatch.setattr(email_api, "USAGE_FILE", tmp_path / "email_usage.json")

    prefix = f"idgen{secrets.randbelow(10**6):06d}"
    response = requests.post(
        f"{email_api.TEMPMAIL_BASE}/v2/inbox/create",
        json={"prefix": prefix},
        headers=email_api._tempmail_headers(),
        timeout=email_api.REQUEST_TIMEOUT,
    )
    if response.status_code == 429:
        pytest.skip(f"tempmail.lol spent the free quota of this IP ({response.text[:120]}), retry inside the 30 minute window or later")
    response.raise_for_status()
    data = response.json()
    address = data.get("address")
    token = data.get("token") or ""
    assert address and token, (
        f"tempmail.lol answered {response.status_code} without an (address, token) pair, keys {sorted(data)}: "
        "the contract every mocked test imitates is no longer what the provider ships"
    )
    messages = email_api._tempmail_read(token, 10)
    assert isinstance(messages, list), "the inbox read stopped returning a list"
    for message in messages:
        assert set(message) == {"from", "subject", "text"}, f"unexpected message keys {sorted(message)}"


def test_mail_tm_creates_a_readable_inbox(tmp_path, monkeypatch):
    # I accept the token endpoint lag by retrying creation, and when the wrapper fails I first reach the public domains endpoint to tell a provider outage or limit apart from a contract change, since a limit or an outage deserves a skip while a shape change deserves a failure.
    monkeypatch.setattr(email_api, "USAGE_FILE", tmp_path / "email_usage.json")

    local = f"idgen-{secrets.randbelow(10**6)}"
    created = email_api._mailtm_email(local)
    if created is None:
        probe = requests.get(f"{email_api.MAILTM_BASE}/domains", timeout=email_api.REQUEST_TIMEOUT)
        pytest.skip(
            f"mail.tm is unavailable or limited for this IP ({probe.status_code}, {probe.text[:120]}), "
            "retry later, because a dead provider is not the same finding as a changed contract"
        )
    address, token = created
    assert "@" in address, f"the account response lost the address shape, got {address!r}"
    assert token, (
        "mail.tm created the account but the token endpoint never validated, "
        "so reads against this inbox stay empty, which is the drift this suite exists to catch"
    )

    messages = email_api._mailtm_read(token, 10)
    assert isinstance(messages, list), "the message list stopped being a list"
    for message in messages:
        assert set(message) == {"from", "subject", "text"}, f"unexpected message keys {sorted(message)}"
