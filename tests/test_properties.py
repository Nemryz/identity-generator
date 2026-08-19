"""
Property-based tests (Paso 7, issue 5).

Randomized invariants over generate_identity and its helpers using
Hypothesis, targeting exotic Faker locales and arbitrary unicode input
that directed tests would not enumerate by hand.
"""

import random
import re

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from faker.config import AVAILABLE_LOCALES

from email_api import _local_part
from generator import (
    _PASSPORT_FORMATS,
    _build_nickname,
    _build_username,
    _format_address,
    _load_address_dataset,
    _pick_dataset_city,
    _street_number,
    generate_identity,
)

REQUIRED_FIELDS = [
    "first_name",
    "last_name",
    "full_name",
    "address",
    "city",
    "postcode",
    "country",
    "phone",
    "occupation",
    "email",
    "username",
    "nickname",
    "password",
    "passport_number",
]

# Exotic locales are sampled against the installed Faker's available
# set, since not every historically documented locale ships in every
# Faker release.
LOCALE_SAMPLE = [
    loc
    for loc in [
        "es_ES", "es_MX", "es_AR", "es_CL", "es_CO", "en_US", "en_GB",
        "fr_FR", "de_DE", "it_IT", "pt_BR",
        "ar_EG", "bg_BG", "cs_CZ", "da_DK", "el_GR", "fa_IR", "fi_FI",
        "he_IL", "hi_IN", "hu_HU", "id_ID", "ja_JP", "ko_KR", "nl_NL",
        "pl_PL", "pt_PT", "ro_RO", "ru_RU", "sk_SK", "sv_SE", "th_TH",
        "tr_TR", "uk_UA", "vi_VN", "zh_CN", "zh_TW", "en_AU", "es_VE",
    ]
    if loc in AVAILABLE_LOCALES
]


def _fake_email(*_args, **_kwargs):
    return {
        "email": "test@example.com",
        "token": "fake-token",
        "provider": "tempmail",
    }


def test_identity_invariants_across_locales(monkeypatch):
    monkeypatch.setattr("generator.get_temp_email", _fake_email)

    @given(st.sampled_from(LOCALE_SAMPLE))
    @settings(
        max_examples=150,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def _check(locale):
        identity = generate_identity(locale=locale, email_usable=False)

        for field in REQUIRED_FIELDS:
            assert identity[field], f"{locale}: {field} vacío"

        username = identity["username"]
        assert username.isascii()
        assert all(c.isalnum() for c in username)

        assert re.fullmatch(r"[a-z0-9._-]+@[a-z0-9.-]+", identity["email"])

        assert 18 <= identity["age"] <= 60

        passport = identity["passport_number"]
        letters, digits = _PASSPORT_FORMATS.get(locale, (0, 9))
        assert re.fullmatch(rf"^[A-Z]{{{letters}}}\d{{{digits}}}$", passport)

        assert identity["national_id"] is None or isinstance(
            identity["national_id"], str
        )

    _check()


@settings(max_examples=200, deadline=None)
@given(st.text(min_size=0, max_size=50))
def test_username_ascii_safe_for_arbitrary_names(name):
    username = _build_username(name, 1995)
    assert username
    assert username.isascii()
    assert username.isalnum()


@settings(max_examples=200, deadline=None)
@given(
    st.text(min_size=0, max_size=50),
    st.sampled_from(["es_ES", "en_US", "ja_JP", "xx_XX"]),
)
def test_nickname_never_empty_for_arbitrary_names(name, locale):
    nickname = _build_nickname(name, locale)
    assert nickname


@settings(max_examples=200, deadline=None)
@given(st.text(min_size=0, max_size=50), st.text(min_size=0, max_size=50))
def test_local_part_ascii_safe_for_arbitrary_names(first, last):
    local = _local_part(first, last)
    assert local
    assert local.isascii()
    assert all(c.isalnum() or c in "._-" for c in local)


@pytest.mark.parametrize("locale", sorted(_PASSPORT_FORMATS))
def test_dataset_draws_stay_valid(locale):
    dataset = _load_address_dataset(locale)
    postcodes_by_name: dict[str, set[str]] = {}
    for city in dataset["cities"]:
        postcodes_by_name.setdefault(city["name"], set()).add(city["postcode"])

    random.seed(locale)
    for _ in range(100):
        city = _pick_dataset_city(dataset)
        street = random.choice(dataset["streets"])
        address = _format_address(locale, street, _street_number())
        assert city["postcode"] in postcodes_by_name[city["name"]]
        assert street in dataset["streets"]
        assert address