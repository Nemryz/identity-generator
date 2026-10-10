"""
tests/conftest.py

I keep the whole suite away from the real per-user data directory.

Since the package move, the default home for history.json, email_usage.json, email_keys.json and domains.json is the per-user data directory instead of the project, which means a test that forgets to redirect one of them would quietly write into the files the user actually relies on. This autouse fixture points every one of them at a throwaway directory for each test, so no test can ever touch the real state even if it forgets to ask.
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    """I redirect every state, secret and config file to a temporary directory."""
    from identity_generator import email_api, history

    monkeypatch.setattr(email_api, "USAGE_FILE", tmp_path / "email_usage.json")
    monkeypatch.setattr(email_api, "KEYS_FILE", tmp_path / "email_keys.json")
    monkeypatch.setattr(
        email_api, "CUSTOM_DOMAINS_FILE", tmp_path / "domains.json"
    )
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "history.json")
    return tmp_path