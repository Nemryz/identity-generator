"""
Tests for the age calculation in generator.py.

Covers the exact-age fix: the age must not be overstated when the
birthday of the current year has not happened yet.
"""

from datetime import date

import pytest

from generator import (
    _PASSWORD_DIGITS,
    _PASSWORD_LENGTH,
    _PASSWORD_LOWER,
    _PASSWORD_SYMBOLS,
    _PASSWORD_UPPER,
    _build_nickname,
    _build_password,
    _build_username,
    _calculate_age,
    _nickname_suffixes,
    generate_identity,
    is_supported_locale,
)

AMBIGUOUS_CHARS = set("Il1O0")
TODAY = date(2026, 8, 18)


def _fake_email(*_args, **_kwargs):
    return {"email": "test@example.com", "token": "fake-token", "provider": "tempmail"}


def test_age_when_birthday_already_passed():
    assert _calculate_age(date(2000, 1, 1), today=TODAY) == 26


def test_age_when_birthday_not_yet_passed():
    assert _calculate_age(date(2000, 12, 31), today=TODAY) == 25


def test_age_regression_birthday_pending_in_december():
    assert _calculate_age(date(1965, 12, 10), today=TODAY) == 60


def test_age_on_exact_birthday():
    assert _calculate_age(date(1996, 8, 18), today=TODAY) == 30


def test_age_leap_day_birthday():
    assert _calculate_age(date(2000, 2, 29), today=TODAY) == 26


def test_age_accepts_datetime():
    from datetime import datetime

    assert _calculate_age(datetime(2000, 12, 31, 23, 59), today=TODAY) == 25


@pytest.mark.parametrize(
    "locale", ["es_ES", "es_MX", "en_US", "fr_FR", "ja_JP"]
)
def test_is_supported_locale_accepts_mapped_locales(locale):
    assert is_supported_locale(locale)


def test_is_supported_locale_accepts_faker_only_locale():
    assert is_supported_locale("en_CA")
    assert is_supported_locale("en_IE")


@pytest.mark.parametrize("locale", ["xx_XX", "en_USS", "", "es_PE", "spanish"])
def test_is_supported_locale_rejects_invalid(locale):
    assert not is_supported_locale(locale)


def test_nickname_suffixes_spanish_locales():
    suffixes = _nickname_suffixes("es_ES")
    assert "ito" in suffixes
    assert "ita" in suffixes
    assert _nickname_suffixes("es_MX") == suffixes


def test_nickname_suffixes_english_locales_have_no_spanish_diminutives():
    suffixes = _nickname_suffixes("en_US")
    assert "ito" not in suffixes
    assert "ita" not in suffixes
    assert "chan" not in suffixes


def test_nickname_suffixes_japanese_locale():
    suffixes = _nickname_suffixes("ja_JP")
    assert "chan" in suffixes
    assert "kun" in suffixes


def test_nickname_suffixes_unknown_language_falls_back_to_default():
    assert _nickname_suffixes("xx_YY") == _nickname_suffixes("default")


def test_nickname_uses_locale_suffixes(monkeypatch):
    monkeypatch.setattr(
        "generator.random.choice", lambda suffixes: suffixes[0]
    )
    assert _build_nickname("Cristian", "es_ES").endswith("ito")
    assert _build_nickname("Joshua", "en_US").endswith("x")
    assert _build_nickname("Yuki", "ja_JP").endswith("chan")


def _assert_password_valid(password: str) -> None:
    assert len(password) == _PASSWORD_LENGTH
    assert any(c in _PASSWORD_LOWER for c in password)
    assert any(c in _PASSWORD_UPPER for c in password)
    assert any(c in _PASSWORD_DIGITS for c in password)
    assert any(c in _PASSWORD_SYMBOLS for c in password)
    assert not AMBIGUOUS_CHARS.intersection(password)


def test_password_has_required_length_and_classes():
    _assert_password_valid(_build_password())


def test_password_avoids_ambiguous_characters():
    for _ in range(100):
        _assert_password_valid(_build_password())


def test_generated_identity_password_is_valid(monkeypatch):
    monkeypatch.setattr("generator.get_temp_email", _fake_email)
    for _ in range(20):
        _assert_password_valid(generate_identity(locale="en_US")["password"])


def test_generated_identity_includes_email_token(monkeypatch):
    monkeypatch.setattr("generator.get_temp_email", _fake_email)
    identity = generate_identity(locale="en_US")
    assert identity["email"] == "test@example.com"
    assert identity["email_token"] == "fake-token"
    assert identity["email_provider"] == "tempmail"


def test_generated_identity_email_offline_passes_flag(monkeypatch):
    def offline_email(*_args, **_kwargs):
        return {"email": "x@yopmail.com", "token": None, "provider": "offline"}

    monkeypatch.setattr("generator.get_temp_email", offline_email)
    identity = generate_identity(locale="en_US", email_usable=False)
    assert identity["email"] == "x@yopmail.com"
    assert identity["email_token"] is None
    assert identity["email_provider"] == "offline"


def test_reuse_copies_previous_inbox_without_network(monkeypatch):
    monkeypatch.setattr(
        "history.find_usable_email",
        lambda: {"email": "reused@tmp.com", "token": "t1", "provider": "tempmail"},
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("get_temp_email must not be called with --reuse")

    monkeypatch.setattr("generator.get_temp_email", boom)

    identity = generate_identity(locale="en_US", reuse=True)
    assert identity["email"] == "reused@tmp.com"
    assert identity["email_token"] == "t1"
    assert identity["email_provider"] == "tempmail"


def test_reuse_falls_back_to_creation_without_previous(monkeypatch, caplog):
    caplog.set_level("INFO")
    monkeypatch.setattr("history.find_usable_email", lambda: None)
    monkeypatch.setattr("generator.get_temp_email", _fake_email)

    identity = generate_identity(locale="en_US", reuse=True)
    assert identity["email"] == "test@example.com"
    assert "no hay inbox previo" in caplog.text


def test_cjk_name_username_falls_back_to_user_prefix(monkeypatch):
    monkeypatch.setattr(
        "generator.random.choices", lambda *a, **k: ["123"]
    )
    username = _build_username("太郎", 1988)
    assert username == "user88123"
    assert username.isascii()


def test_cjk_name_nickname_keeps_original_first_char(monkeypatch):
    monkeypatch.setattr(
        "generator.random.choice", lambda suffixes: suffixes[0]
    )
    nickname = _build_nickname("太郎", "ja_JP")
    assert nickname.startswith("太")
    assert nickname.endswith("chan")


@pytest.mark.parametrize("locale", ["ja_JP", "zh_CN", "ko_KR"])
def test_generated_identity_cjk_username_and_nickname_non_empty(
    locale, monkeypatch
):
    monkeypatch.setattr("generator.get_temp_email", _fake_email)
    identity = generate_identity(locale=locale)
    assert identity["username"].isascii()
    assert len(identity["username"]) >= 4
    assert len(identity["nickname"]) >= 2


@pytest.mark.parametrize("locale", ["es_ES", "en_US", "fr_FR", "ja_JP"])
def test_generated_identity_age_matches_birth_date(locale, monkeypatch):
    monkeypatch.setattr("generator.get_temp_email", _fake_email)
    identity = generate_identity(locale=locale)
    expected = _calculate_age(date.fromisoformat(identity["date_of_birth"]))
    assert identity["age"] == expected


@pytest.mark.parametrize("locale", ["es_ES", "en_US", "fr_FR", "de_DE", "pt_BR"])
def test_generated_identity_age_within_bounds(locale, monkeypatch):
    monkeypatch.setattr("generator.get_temp_email", _fake_email)
    for _ in range(30):
        identity = generate_identity(locale=locale)
        assert 18 <= identity["age"] <= 60