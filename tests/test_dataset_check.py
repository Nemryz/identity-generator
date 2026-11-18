# Tests for dataset_check.py: I build synthetic datasets in a temporary directory, break one rule at a time, and assert the structured result each validator hands back, so the CLI report and the exit code rest on behaviour that never changed underneath them. The valid fixture meets every minimum on purpose, because a validator that cannot pass a good dataset proves nothing.

import json
import sys
from pathlib import Path

from identity_generator.dataset_check import (
    MIN_CITIES,
    MIN_POSTCODE_COVERAGE,
    MIN_STREETS,
    DatasetCheckResult,
    check_dataset,
    check_directory,
    normalize_street,
)

LOCALE = "es_ES"


def _valid_dataset(city_count: int = MIN_CITIES, street_count: int = MIN_STREETS) -> dict:
    # I build the smallest dataset every validator accepts: enough cities in descending population order with postcodes above the coverage floor, and enough unique streets.
    half = city_count // 2 + 1
    return {
        "cities": [
            {
                "name": f"City {index:03d}",
                "population": 10_000_000 - index,
                "postcode": f"1{index:04d}" if index < half else None,
            }
            for index in range(city_count)
        ],
        "streets": [f"Calle Mayor {index:03d}" for index in range(street_count)],
        "sources": {"geonames": "CC-BY 4.0", "osm": "ODbL"},
    }


def _by_validator(data: object, locale: str = LOCALE) -> dict:
    return {result.validator: result for result in check_dataset(data, locale)}


def test_valid_dataset_passes_every_validator():
    results = check_dataset(_valid_dataset(), LOCALE)
    assert [result.validator for result in results] == [
        "schema",
        "cities",
        "population_order",
        "postcode_coverage",
        "postcode_format",
        "streets",
    ]
    for result in results:
        assert result.passed, result.message
        assert result.locale == LOCALE


def test_missing_top_level_keys_fail_schema_and_dependents():
    data = _valid_dataset()
    del data["cities"]
    results = _by_validator(data)
    assert not results["schema"].passed, results["schema"].message
    assert "missing keys" in results["schema"].message
    for validator in ("cities", "population_order", "postcode_coverage", "postcode_format"):
        assert not results[validator].passed, results[validator].message


def test_missing_attribution_fails_schema():
    data = _valid_dataset()
    data["sources"] = {"geonames": "CC-BY 4.0"}
    result = _by_validator(data)["schema"]
    assert not result.passed
    assert "osm" in result.message


def test_dataset_not_an_object_fails_every_validator():
    for broken in ([], "text", None):
        results = check_dataset(broken, LOCALE)
        assert len(results) == 6
        for result in results:
            assert not result.passed, (broken, result.validator)


def test_city_volume_below_minimum_fails():
    data = _valid_dataset(city_count=MIN_CITIES - 1)
    result = _by_validator(data)["cities"]
    assert not result.passed
    assert str(MIN_CITIES - 1) in result.message


def test_street_volume_below_minimum_fails():
    data = _valid_dataset(street_count=MIN_STREETS - 1)
    result = _by_validator(data)["streets"]
    assert not result.passed
    assert str(MIN_STREETS - 1) in result.message


def test_city_with_empty_name_fails():
    data = _valid_dataset()
    data["cities"][7]["name"] = "   "
    result = _by_validator(data)["cities"]
    assert not result.passed
    assert "empty name" in result.message


def test_city_with_bad_population_fails():
    data = _valid_dataset()
    data["cities"][3]["population"] = 0
    result = _by_validator(data)["cities"]
    assert not result.passed
    assert "population" in result.message


def test_city_with_non_string_postcode_fails():
    data = _valid_dataset()
    data["cities"][2]["postcode"] = 28939
    result = _by_validator(data)["cities"]
    assert not result.passed
    assert "non-string postcode" in result.message


def test_unsorted_population_fails_with_first_violation():
    data = _valid_dataset()
    data["cities"][5], data["cities"][6] = data["cities"][6], data["cities"][5]
    result = _by_validator(data)["population_order"]
    assert not result.passed
    assert "position 6" in result.message


def test_postcode_coverage_below_threshold_fails():
    data = _valid_dataset()
    for city in data["cities"]:
        city["postcode"] = None
    result = _by_validator(data)["postcode_coverage"]
    assert not result.passed
    assert "0/" in result.message
    assert MIN_POSTCODE_COVERAGE <= 0.5


def test_postcode_format_violations_are_listed():
    data = _valid_dataset()
    data["cities"][0]["postcode"] = "999"
    result = _by_validator(data)["postcode_format"]
    assert not result.passed
    assert "999" in result.message


def test_unknown_locale_has_no_postcode_pattern():
    data = _valid_dataset()
    result = _by_validator(data, "xx_XX")["postcode_format"]
    assert not result.passed
    assert "no postcode pattern" in result.message


def test_duplicate_streets_differing_in_case_fail():
    # I rely on the normalization rule the packaged datasets were audited against, so a case-only twin is reported as the duplicate it is.
    data = _valid_dataset()
    data["streets"][9] = "calle mayor 008"
    result = _by_validator(data)["streets"]
    assert not result.passed
    assert "duplicates after normalization" in result.message
    assert "calle mayor 008" in result.message and "Calle Mayor 008" in result.message


def test_street_uniqueness_keeps_accents_and_punctuation_significant():
    # I keep two streets that differ only by an accent or a trailing abbreviation, because merging them would hide real places.
    data = _valid_dataset()
    data["streets"][9] = "Calle Ángel"
    data["streets"][10] = "Calle Angel"
    data["streets"][11] = "Calle Angel St."
    data["streets"][12] = "Calle Angel."
    result = _by_validator(data)["streets"]
    assert result.passed, result.message


def test_empty_street_name_fails():
    data = _valid_dataset()
    data["streets"][4] = ""
    result = _by_validator(data)["streets"]
    assert not result.passed
    assert "empty" in result.message


def test_normalize_street_causes_only_case_and_whitespace_folding():
    assert normalize_street("  Calle MAYOR ") == "calle mayor"
    assert normalize_street("Calle Ángel") != normalize_street("Calle Angel")
    # I let casefold do its more aggressive job, where the sharp s folds together with a written ss so the two spellings of one street compare equal.
    assert normalize_street("Straße") == normalize_street("STRASSE")


def test_check_directory_reports_load_errors_without_raising(tmp_path):
    (tmp_path / "es_ES.json").write_text("{not json", encoding="utf-8")
    reports = check_directory(tmp_path)
    assert set(reports) == {"es_ES"}
    (load_result,) = reports["es_ES"]
    assert load_result.validator == "load"
    assert not load_result.passed
    assert "unreadable" in load_result.message


def test_check_directory_skips_non_json_files(tmp_path):
    (tmp_path / "es_ES.json").write_text(
        json.dumps(_valid_dataset()), encoding="utf-8"
    )
    (tmp_path / "ATTRIBUTION.md").write_text("credits", encoding="utf-8")
    reports = check_directory(tmp_path)
    assert set(reports) == {"es_ES"}
    assert all(result.passed for result in reports["es_ES"])


def test_check_directory_on_missing_directory_returns_empty(tmp_path):
    assert check_directory(tmp_path / "nope") == {}


def test_check_directory_results_are_renderable_dataclass_results(tmp_path):
    (tmp_path / "es_ES.json").write_text(
        json.dumps(_valid_dataset()), encoding="utf-8"
    )
    reports = check_directory(tmp_path)
    assert all(
        isinstance(result, DatasetCheckResult) for result in reports["es_ES"]
    )


def test_module_never_imports_the_test_framework():
    # I keep the validators free of pytest, since the CLI and a diagnostic export run where no test runner exists.
    source = Path(sys.modules["identity_generator.dataset_check"].__file__).read_text(
        encoding="utf-8"
    )
    assert "pytest" not in source
