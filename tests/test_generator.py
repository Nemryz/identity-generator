# Tests for the age calculation in generator.py, covering the exact-age fix where the age must not be overstated when the birthday of the current year has not happened yet.

from datetime import date

import pytest

from identity_generator.generator import (
    _NATIONAL_ID_LABELS,
    _NATIONAL_ID_PROVIDERS,
    _PASSPORT_FORMATS,
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
    get_supported_locales,
    is_supported_locale,
    locale_capabilities,
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
        "identity_generator.generator.random.choice", lambda suffixes: suffixes[0]
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
    monkeypatch.setattr("identity_generator.generator.get_temp_email", _fake_email)
    for _ in range(20):
        _assert_password_valid(generate_identity(locale="en_US")["password"])


def test_generated_identity_includes_email_token(monkeypatch):
    monkeypatch.setattr("identity_generator.generator.get_temp_email", _fake_email)
    identity = generate_identity(locale="en_US")
    assert identity["email"] == "test@example.com"
    assert identity["email_token"] == "fake-token"
    assert identity["email_provider"] == "tempmail"


def test_generated_identity_email_offline_passes_flag(monkeypatch):
    def offline_email(*_args, **_kwargs):
        return {"email": "x@yopmail.com", "token": None, "provider": "offline"}

    monkeypatch.setattr("identity_generator.generator.get_temp_email", offline_email)
    identity = generate_identity(locale="en_US", email_usable=False)
    assert identity["email"] == "x@yopmail.com"
    assert identity["email_token"] is None
    assert identity["email_provider"] == "offline"


def test_reuse_copies_previous_inbox_without_network(monkeypatch):
    monkeypatch.setattr(
        "identity_generator.history.find_usable_email",
        lambda: {"email": "reused@tmp.com", "token": "t1", "provider": "tempmail"},
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("get_temp_email must not be called with --reuse")

    monkeypatch.setattr("identity_generator.generator.get_temp_email", boom)

    identity = generate_identity(locale="en_US", reuse=True)
    assert identity["email"] == "reused@tmp.com"
    assert identity["email_token"] == "t1"
    assert identity["email_provider"] == "tempmail"


def test_reuse_falls_back_to_creation_without_previous(monkeypatch, caplog):
    caplog.set_level("INFO")
    monkeypatch.setattr("identity_generator.history.find_usable_email", lambda: None)
    monkeypatch.setattr("identity_generator.generator.get_temp_email", _fake_email)

    identity = generate_identity(locale="en_US", reuse=True)
    assert identity["email"] == "test@example.com"
    assert "no hay inbox previo" in caplog.text


def test_cjk_name_username_falls_back_to_user_prefix(monkeypatch):
    monkeypatch.setattr(
        "identity_generator.generator.random.choices", lambda *a, **k: ["123"]
    )
    username = _build_username("太郎", 1988)
    assert username == "user88123"
    assert username.isascii()


def test_cjk_name_nickname_keeps_original_first_char(monkeypatch):
    monkeypatch.setattr(
        "identity_generator.generator.random.choice", lambda suffixes: suffixes[0]
    )
    nickname = _build_nickname("太郎", "ja_JP")
    assert nickname.startswith("太")
    assert nickname.endswith("chan")


@pytest.mark.parametrize("locale", ["ja_JP", "zh_CN", "ko_KR"])
def test_generated_identity_cjk_username_and_nickname_non_empty(
    locale, monkeypatch
):
    monkeypatch.setattr("identity_generator.generator.get_temp_email", _fake_email)
    identity = generate_identity(locale=locale)
    assert identity["username"].isascii()
    assert len(identity["username"]) >= 4
    assert len(identity["nickname"]) >= 2


@pytest.mark.parametrize("locale", ["es_ES", "en_US", "fr_FR", "ja_JP"])
def test_generated_identity_age_matches_birth_date(locale, monkeypatch):
    monkeypatch.setattr("identity_generator.generator.get_temp_email", _fake_email)
    identity = generate_identity(locale=locale)
    expected = _calculate_age(date.fromisoformat(identity["date_of_birth"]))
    assert identity["age"] == expected


@pytest.mark.parametrize("locale", ["es_ES", "en_US", "fr_FR", "de_DE", "pt_BR"])
def test_generated_identity_age_within_bounds(locale, monkeypatch):
    monkeypatch.setattr("identity_generator.generator.get_temp_email", _fake_email)
    for _ in range(30):
        identity = generate_identity(locale=locale)
        assert 18 <= identity["age"] <= 60

# --- locale_capabilities: what --list-locales shows (A4) ----------------------------


def test_locale_capabilities_returns_the_documented_keys():
    # I check the capability dict carries exactly the keys the CLI table reads, so renaming one breaks here instead of rendering a blank column.
    caps = locale_capabilities("es_ES")
    assert set(caps) == {
        "locale",
        "country",
        "national_id",
        "passport",
        "address_style",
        "cities",
        "streets",
    }


@pytest.mark.parametrize("locale", get_supported_locales())
def test_locale_capabilities_is_complete_for_every_locale(locale):
    # I walk all supported locales and require a country, a passport shape and a dataset verdict, because a table with an empty cell is a table nobody trusts.
    caps = locale_capabilities(locale)
    assert caps["locale"] == locale
    assert caps["country"]
    assert caps["passport"]
    assert caps["address_style"]
    assert (caps["cities"] is None) == (caps["streets"] is None)


def test_locale_capabilities_country_matches_the_country_map():
    # I tie the displayed country back to LOCALE_COUNTRY_MAP, since that map is what actually reaches the identity.
    for locale in get_supported_locales():
        from identity_generator.generator import LOCALE_COUNTRY_MAP

        assert locale_capabilities(locale)["country"] == LOCALE_COUNTRY_MAP[locale]


def test_every_locale_with_a_provider_shows_a_document():
    # I guard the drift that a new national_id provider arrives without a display label, which would render a dash for a locale that does have a document.
    for locale in _NATIONAL_ID_PROVIDERS:
        caps = locale_capabilities(locale)
        assert caps["national_id"], f"{locale} has a provider but no label"
        assert caps["national_id"] != caps["locale"]


def test_no_label_without_a_provider():
    # I reject orphan labels, so a stale entry cannot advertise a document for a locale that no longer generates one.
    assert set(_NATIONAL_ID_LABELS) == set(_NATIONAL_ID_PROVIDERS)


def test_locales_without_a_provider_report_no_document():
    # I check the locales Faker has no official provider for report None, which is what --list-locales renders as a dash and what the schema allows as null.
    for locale in ("es_AR", "ja_JP"):
        assert locale not in _NATIONAL_ID_PROVIDERS
        assert locale_capabilities(locale)["national_id"] is None


def test_ssn_providers_show_their_own_document_names():
    # I pin the trap that three locales share Faker's ssn provider while shipping three different documents, so nobody collapses them back into one label.
    labels = {
        locale: locale_capabilities(locale)["national_id"]
        for locale in ("en_GB", "fr_FR", "it_IT")
    }
    assert _NATIONAL_ID_PROVIDERS["en_GB"] == "ssn"
    assert _NATIONAL_ID_PROVIDERS["fr_FR"] == "ssn"
    assert _NATIONAL_ID_PROVIDERS["it_IT"] == "ssn"
    assert labels == {"en_GB": "NIN", "fr_FR": "NIR", "it_IT": "Codice fiscale"}
    assert len(set(labels.values())) == 3


@pytest.mark.parametrize(
    "locale,expected",
    [
        ("es_ES", "3 letters + 6 digits"),
        ("en_US", "9 digits"),
        ("de_DE", "4 letters + 5 digits"),
        ("fr_FR", "2 letters + 7 digits"),
        ("es_CO", "2 letters + 7 digits"),
    ],
)
def test_passport_shape_renders_the_configured_format(locale, expected):
    # I check the shape string is derived from _PASSPORT_FORMATS instead of being written by hand, so editing the format map updates the table.
    assert locale_capabilities(locale)["passport"] == expected


def test_passport_shape_falls_back_to_nine_digits():
    # I check an unknown locale gets the generator default, which is the same (0, 9) _passport_number itself uses.
    letters, digits = _PASSPORT_FORMATS.get("xx_XX", (0, 9))
    assert (letters, digits) == (0, 9)
    assert locale_capabilities("xx_XX")["passport"] == "9 digits"


@pytest.mark.parametrize(
    "locale,expected",
    [
        ("en_US", "number first"),
        ("en_GB", "number first"),
        ("fr_FR", "number first"),
        ("pt_BR", "street, number"),
        ("es_ES", "street first"),
        ("de_DE", "street first"),
    ],
)
def test_address_style_names_the_convention_of_dataset_locales(locale, expected):
    # I check the convention reported matches the one _format_address actually applies, which only matters for the locales that carry a dataset.
    caps = locale_capabilities(locale)
    assert caps["cities"] is not None
    assert caps["address_style"] == expected


def test_locales_without_a_dataset_report_the_faker_fallback():
    # I check the table says Faker fallback where the address really comes from Faker, instead of claiming a convention the code never applies.
    for locale in ("ja_JP", "bg_BG", "zh_CN"):
        caps = locale_capabilities(locale)
        assert caps["cities"] is None
        assert caps["streets"] is None
        assert caps["address_style"] == "Faker fallback"


def test_dataset_sizes_are_positive_when_present():
    # I check the reported city and street counts are real numbers, since the table prints them and a zero would read as a broken dataset.
    for locale in get_supported_locales():
        caps = locale_capabilities(locale)
        if caps["cities"] is not None:
            assert caps["cities"] > 0
            assert caps["streets"] > 0
