"""
Tests for the real-address datasets (Paso 4).

For the 11 locales that ship a dataset in data/addresses/, the generated
address must come entirely from that dataset: a city weighted by
population, the postal code stored for that exact city, and a real
street name, formatted following the locale's convention. Locales
without a dataset keep the Faker fallback.
"""

import json
import re
from pathlib import Path

import pytest

from generator import generate_identity

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "addresses"
DATASET_LOCALES = sorted(p.stem for p in DATA_DIR.glob("*.json"))

ADDRESS_NUMBER_FIRST = {"en_US", "en_GB", "fr_FR"}
ADDRESS_COMMA = {"pt_BR"}


def _fake_email(*_args, **_kwargs):
    return {
        "email": "test@example.com",
        "token": "fake-token",
        "provider": "tempmail",
    }


def _load(locale: str) -> dict:
    return json.loads((DATA_DIR / f"{locale}.json").read_text(encoding="utf-8"))


def _street_from_address(locale: str, address: str) -> str | None:
    """
    Return the street part of an address, or None when the address does
    not follow the locale's format (number-first, comma, or street-first).
    """
    if locale in ADDRESS_NUMBER_FIRST:
        match = re.match(r"^(\d+) (.+)$", address)
        return match.group(2) if match else None
    if locale in ADDRESS_COMMA:
        match = re.match(r"^(.+), (\d+)$", address)
        return match.group(1) if match else None
    match = re.match(r"^(.*) (\d+)$", address)
    return match.group(1) if match else None


@pytest.mark.parametrize("locale", DATASET_LOCALES)
def test_address_components_come_from_dataset(locale, monkeypatch):
    monkeypatch.setattr("generator.get_temp_email", _fake_email)
    dataset = _load(locale)
    streets = dataset["streets"]
    postcodes_by_name: dict[str, set[str]] = {}
    for city in dataset["cities"]:
        postcodes_by_name.setdefault(city["name"], set()).add(city["postcode"])

    identity = generate_identity(locale=locale, email_usable=False)

    assert identity["city"] in postcodes_by_name
    assert identity["postcode"] in postcodes_by_name[identity["city"]]
    assert identity["postcode"]

    street = _street_from_address(locale, identity["address"])
    assert street is not None, f"formato inesperado: {identity['address']!r}"
    assert street in streets


@pytest.mark.parametrize("locale", DATASET_LOCALES)
def test_generated_cities_always_have_postcode(locale, monkeypatch):
    monkeypatch.setattr("generator.get_temp_email", _fake_email)
    dataset = _load(locale)
    streets = set(dataset["streets"])

    for _ in range(50):
        identity = generate_identity(locale=locale, email_usable=False)
        assert identity["postcode"], f"{locale}: postcode vacio"
        street = _street_from_address(locale, identity["address"])
        assert street in streets, f"{locale}: calle fuera del dataset"


def test_city_selection_is_weighted_and_varies(monkeypatch):
    monkeypatch.setattr("generator.get_temp_email", _fake_email)
    cities = {
        generate_identity(locale="es_ES", email_usable=False)["city"]
        for _ in range(30)
    }
    assert len(cities) >= 2


@pytest.mark.parametrize("locale", ["pt_PT", "ja_JP"])
def test_faker_fallback_without_dataset(locale, monkeypatch):
    monkeypatch.setattr("generator.get_temp_email", _fake_email)
    identity = generate_identity(locale=locale, email_usable=False)
    assert identity["city"] not in {"", "N/A"}
    assert identity["postcode"] not in {"", "N/A"}
    assert identity["address"] not in {"", "N/A"}