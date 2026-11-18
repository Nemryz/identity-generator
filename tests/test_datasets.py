# Tests for the committed address datasets in identity_generator/data/addresses/: I run them offline against the generated JSON files by delegating every check to identity_generator.dataset_check, so the CLI and this suite validate with the exact same code and a dataset that passes here is the dataset --check-datasets accepts. The datasets derive from GeoNames (CC-BY 4.0) and OpenStreetMap (ODbL) as the "Data sources" section of the README explains.

import json
from pathlib import Path

import pytest

from identity_generator.dataset_check import POSTCODE_REGEX, check_dataset

DATA_DIR = Path(__file__).resolve().parents[1] / "identity_generator" / "data" / "addresses"

LOCALES = sorted(POSTCODE_REGEX)


def _load(locale: str) -> dict:
    path = DATA_DIR / f"{locale}.json"
    assert path.exists(), f"missing dataset {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _results(locale: str) -> dict:
    return {result.validator: result for result in check_dataset(_load(locale), locale)}


@pytest.mark.parametrize("locale", LOCALES)
def test_dataset_schema(locale):
    result = _results(locale)["schema"]
    assert result.passed, result.message


@pytest.mark.parametrize("locale", LOCALES)
def test_city_volume_and_shape(locale):
    result = _results(locale)["cities"]
    assert result.passed, result.message


@pytest.mark.parametrize("locale", LOCALES)
def test_cities_sorted_by_population_desc(locale):
    result = _results(locale)["population_order"]
    assert result.passed, result.message


@pytest.mark.parametrize("locale", LOCALES)
def test_postcode_coverage(locale):
    result = _results(locale)["postcode_coverage"]
    assert result.passed, result.message


@pytest.mark.parametrize("locale", LOCALES)
def test_postcode_format(locale):
    result = _results(locale)["postcode_format"]
    assert result.passed, result.message


@pytest.mark.parametrize("locale", LOCALES)
def test_street_volume_and_uniqueness(locale):
    result = _results(locale)["streets"]
    assert result.passed, result.message
