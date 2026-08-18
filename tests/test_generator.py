"""
Tests for the age calculation in generator.py.

Covers the exact-age fix: the age must not be overstated when the
birthday of the current year has not happened yet.
"""

from datetime import date

import pytest

from generator import (
    _calculate_age,
    generate_identity,
    is_supported_locale,
)

TODAY = date(2026, 8, 18)


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


@pytest.mark.parametrize("locale", ["es_ES", "en_US", "fr_FR", "ja_JP"])
def test_generated_identity_age_matches_birth_date(locale, monkeypatch):
    monkeypatch.setattr("generator.get_temp_email", lambda: "test@example.com")
    identity = generate_identity(locale=locale)
    expected = _calculate_age(date.fromisoformat(identity["date_of_birth"]))
    assert identity["age"] == expected


@pytest.mark.parametrize("locale", ["es_ES", "en_US", "fr_FR", "de_DE", "pt_BR"])
def test_generated_identity_age_within_bounds(locale, monkeypatch):
    monkeypatch.setattr("generator.get_temp_email", lambda: "test@example.com")
    for _ in range(30):
        identity = generate_identity(locale=locale)
        assert 18 <= identity["age"] <= 60