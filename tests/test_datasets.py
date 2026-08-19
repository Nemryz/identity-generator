"""
Tests for the committed address datasets in data/addresses/.

These run offline against the generated JSON files: schema shape,
coverage thresholds, per-country postal code formats, and ordering.
The datasets are derived from GeoNames (CC-BY 4.0) and OpenStreetMap
(ODbL); see the "Data sources" section of the README.
"""

import json
import re
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "addresses"

# Cities (population, desc) and their postcode shapes.
# GB codes are outward-only (e.g. "EC1A"), ES codes start 01-52.
POSTCODE_REGEX = {
    "es_ES": r"^(0[1-9]|[1-4]\d|5[0-2])\d{3}$",
    "es_MX": r"^\d{5}$",
    "es_AR": r"^\d{4,5}$",
    "es_CL": r"^\d{7}$",
    "es_CO": r"^\d{6}$",
    "en_US": r"^\d{5}$",
    "en_GB": r"^[A-Z]{1,2}\d[A-Z]?\d?$",
    "fr_FR": r"^\d{5}$",
    "de_DE": r"^\d{5}$",
    "it_IT": r"^\d{5}$",
    "pt_BR": r"^\d{5}-\d{3}$",
}

LOCALES = sorted(POSTCODE_REGEX)


def _load(locale: str) -> dict:
    path = DATA_DIR / f"{locale}.json"
    assert path.exists(), f"missing dataset {path}"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("locale", LOCALES)
def test_dataset_schema(locale):
    dataset = _load(locale)
    assert {"cities", "streets", "sources"} <= set(dataset)
    assert dataset["sources"]["geonames"], "geonames attribution required"
    assert dataset["sources"]["osm"], "osm attribution required"


@pytest.mark.parametrize("locale", LOCALES)
def test_city_volume_and_shape(locale):
    cities = _load(locale)["cities"]
    assert len(cities) >= 100, f"{locale}: only {len(cities)} cities"
    for city in cities:
        assert city["name"].strip()
        assert city["population"] > 0
        assert city["postcode"] is None or isinstance(city["postcode"], str)


@pytest.mark.parametrize("locale", LOCALES)
def test_cities_sorted_by_population_desc(locale):
    cities = _load(locale)["cities"]
    populations = [c["population"] for c in cities]
    assert populations == sorted(populations, reverse=True)


@pytest.mark.parametrize("locale", LOCALES)
def test_postcode_coverage(locale):
    cities = _load(locale)["cities"]
    with_code = sum(1 for c in cities if c["postcode"])
    assert with_code / len(cities) >= 0.5, (
        f"{locale}: only {with_code}/{len(cities)} cities have a postcode"
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_postcode_format(locale):
    cities = _load(locale)["cities"]
    pattern = re.compile(POSTCODE_REGEX[locale])
    bad = [
        c["postcode"]
        for c in cities
        if c["postcode"] and not pattern.match(c["postcode"])
    ]
    assert not bad, f"{locale}: invalid postcodes {bad[:5]}"


@pytest.mark.parametrize("locale", LOCALES)
def test_street_volume_and_uniqueness(locale):
    streets = _load(locale)["streets"]
    assert len(streets) >= 100, f"{locale}: only {len(streets)} streets"
    assert len(streets) == len(set(streets))
    assert all(s.strip() for s in streets)
