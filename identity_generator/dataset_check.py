# dataset_check.py I validate the real-address datasets the generator consumes from identity_generator/data/addresses/, so a broken dataset is reported as a structured result before it can reach a generated identity and turn into an error nobody can trace. The validators are pure functions over the loaded dataset dict, which keeps them free of any test framework and lets the CLI, the test suite and a future diagnostic export share the exact same checks, and check_directory() is the only part that touches the filesystem, turning unreadable or uninterpretable files into a load failure result instead of an exception. Every validator always returns a result, one per check, even when the dataset is missing its cities entirely, because a report with holes is not a report. The checks cover the structure of the file (required keys and the GeoNames and OpenStreetMap attributions both datasets derive from), the volumes (a dataset that cannot fill a realistic locale is worse than no dataset), the population ordering the weighted city pick relies on, the postal code coverage and per-country format, and the street list with its uniqueness rule, where two names differing only in compatible unicode representations, outer whitespace or case count as one street while accents, punctuation and abbreviations stay significant because they distinguish real streets. Format validity is not postal validity: a postcode that matches the country's shape is not guaranteed to exist or belong to its city, and the message text keeps the distinction explicit.

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MIN_CITIES = 100
MIN_STREETS = 100
MIN_POSTCODE_COVERAGE = 0.5

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

VALIDATORS = (
    "schema",
    "cities",
    "population_order",
    "postcode_coverage",
    "postcode_format",
    "streets",
)


@dataclass
class DatasetCheckResult:
    # I carry the outcome of one validator for one locale, so the caller decides how to present it instead of the validators printing anything themselves.
    locale: str
    validator: str
    passed: bool
    message: str


def normalize_street(value: str) -> str:
    # I collapse compatible unicode representations, outer whitespace and case into one comparison key, keeping accents, punctuation and abbreviations intact because two distinct real streets may share everything else.
    return unicodedata.normalize("NFKC", value).strip().casefold()


def check_dataset(data: object, locale: str) -> list[DatasetCheckResult]:
    # I run every validator over one loaded dataset and return exactly one result per validator, in a fixed order the report table can rely on.
    return [
        _check_schema(data, locale),
        _check_cities(data, locale),
        _check_population_order(data, locale),
        _check_postcode_coverage(data, locale),
        _check_postcode_format(data, locale),
        _check_streets(data, locale),
    ]


def check_directory(path: Path) -> dict[str, list[DatasetCheckResult]]:
    # I validate every JSON file in a dataset directory, converting unreadable files into a load failure result so the caller always receives a complete renderable report keyed by locale.
    results: dict[str, list[DatasetCheckResult]] = {}
    for file in sorted(Path(path).glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            results[file.stem] = [
                DatasetCheckResult(
                    file.stem, "load", False, f"{file.stem}: unreadable dataset ({exc})"
                )
            ]
            continue
        results[file.stem] = check_dataset(data, file.stem)
    return results


def _fail(locale: str, validator: str, message: str) -> DatasetCheckResult:
    return DatasetCheckResult(locale, validator, False, message)


def _pass(locale: str, validator: str, message: str) -> DatasetCheckResult:
    return DatasetCheckResult(locale, validator, True, message)


def _cities_of(data: object) -> object:
    if isinstance(data, dict):
        return data.get("cities")
    return None


def _streets_of(data: object) -> object:
    if isinstance(data, dict):
        return data.get("streets")
    return None


def _check_schema(data: object, locale: str) -> DatasetCheckResult:
    if not isinstance(data, dict):
        return _fail(locale, "schema", f"{locale}: dataset is not a JSON object")
    missing = {"cities", "streets", "sources"} - set(data)
    if missing:
        return _fail(locale, "schema", f"{locale}: missing keys {sorted(missing)}")
    sources = data["sources"]
    if not isinstance(sources, dict):
        return _fail(locale, "schema", f"{locale}: sources is not an object")
    unattributed = [key for key in ("geonames", "osm") if not sources.get(key)]
    if unattributed:
        return _fail(
            locale,
            "schema",
            f"{locale}: missing attribution for {unattributed}",
        )
    return _pass(locale, "schema", f"{locale}: structure and attribution ok")


def _check_cities(data: object, locale: str) -> DatasetCheckResult:
    cities = _cities_of(data)
    if not isinstance(cities, list):
        return _fail(locale, "cities", f"{locale}: cities is missing or not a list")
    if len(cities) < MIN_CITIES:
        return _fail(
            locale,
            "cities",
            f"{locale}: only {len(cities)} cities (minimum {MIN_CITIES})",
        )
    problems = []
    for index, city in enumerate(cities):
        if not isinstance(city, dict):
            problems.append(f"city #{index} is not an object")
            continue
        name = city.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"city #{index} has an empty name")
            continue
        population = city.get("population")
        if not isinstance(population, int) or isinstance(population, bool) or population <= 0:
            problems.append(f"city #{index} ({name}) has population {population!r}")
        postcode = city.get("postcode")
        if postcode is not None and not isinstance(postcode, str):
            problems.append(f"city #{index} ({name}) has a non-string postcode")
    if problems:
        return _fail(
            locale,
            "cities",
            f"{locale}: {len(problems)} bad cities, first: {problems[0]}",
        )
    return _pass(locale, "cities", f"{locale}: {len(cities)} cities ok")


def _populations_of(cities: list) -> tuple[list[int], str | None]:
    # I collect the population values in order and stop at the first city whose population is not a positive integer, naming it for the failure message.
    populations = []
    for index, city in enumerate(cities):
        if not isinstance(city, dict):
            return [], f"city #{index} is not an object"
        population = city.get("population")
        if (
            not isinstance(population, int)
            or isinstance(population, bool)
            or population <= 0
        ):
            name = city.get("name")
            return [], f"city #{index} ({name}) has population {population!r}"
        populations.append(population)
    return populations, None


def _check_population_order(data: object, locale: str) -> DatasetCheckResult:
    cities = _cities_of(data)
    if not isinstance(cities, list):
        return _fail(
            locale, "population_order", f"{locale}: cities is missing or not a list"
        )
    populations, problem = _populations_of(cities)
    if problem is not None:
        return _fail(locale, "population_order", f"{locale}: {problem}")
    if populations != sorted(populations, reverse=True):
        violation = next(
            index
            for index in range(1, len(populations))
            if populations[index] > populations[index - 1]
        )
        return _fail(
            locale,
            "population_order",
            f"{locale}: cities are not sorted by population descending, first violation at position {violation}",
        )
    return _pass(
        locale,
        "population_order",
        f"{locale}: {len(populations)} cities sorted by population descending",
    )


def _check_postcode_coverage(data: object, locale: str) -> DatasetCheckResult:
    cities = _cities_of(data)
    if not isinstance(cities, list) or not cities:
        return _fail(
            locale, "postcode_coverage", f"{locale}: no cities to cover with postcodes"
        )
    with_code = sum(
        1
        for city in cities
        if isinstance(city, dict) and city.get("postcode")
    )
    ratio = with_code / len(cities)
    if ratio < MIN_POSTCODE_COVERAGE:
        return _fail(
            locale,
            "postcode_coverage",
            f"{locale}: only {with_code}/{len(cities)} cities have a postcode (minimum {MIN_POSTCODE_COVERAGE:.0%})",
        )
    return _pass(
        locale,
        "postcode_coverage",
        f"{locale}: {with_code}/{len(cities)} cities carry a postcode",
    )


def _check_postcode_format(data: object, locale: str) -> DatasetCheckResult:
    cities = _cities_of(data)
    if not isinstance(cities, list):
        return _fail(
            locale, "postcode_format", f"{locale}: cities is missing or not a list"
        )
    pattern = POSTCODE_REGEX.get(locale)
    if pattern is None:
        return _fail(
            locale,
            "postcode_format",
            f"{locale}: no postcode pattern is defined for this locale",
        )
    regex = re.compile(pattern)
    bad = [
        postcode
        for postcode in (
            city.get("postcode") for city in cities if isinstance(city, dict)
        )
        if isinstance(postcode, str) and postcode and not regex.match(postcode)
    ]
    if bad:
        return _fail(
            locale,
            "postcode_format",
            f"{locale}: {len(bad)} invalid postcodes, first: {bad[:5]}",
        )
    return _pass(locale, "postcode_format", f"{locale}: every postcode matches {pattern}")


def _check_streets(data: object, locale: str) -> DatasetCheckResult:
    streets = _streets_of(data)
    if not isinstance(streets, list):
        return _fail(locale, "streets", f"{locale}: streets is missing or not a list")
    if len(streets) < MIN_STREETS:
        return _fail(
            locale,
            "streets",
            f"{locale}: only {len(streets)} streets (minimum {MIN_STREETS})",
        )
    problems = []
    for index, street in enumerate(streets):
        if not isinstance(street, str) or not street.strip():
            problems.append(f"street #{index} is empty")
    seen: dict[str, str] = {}
    duplicates = []
    for street in streets:
        if not isinstance(street, str):
            continue
        key = normalize_street(street)
        if key in seen:
            duplicates.append((seen[key], street))
        else:
            seen[key] = street
    if duplicates:
        first, second = duplicates[0]
        problems.append(
            f"{len(duplicates)} duplicates after normalization, e.g. {first!r} and {second!r}"
        )
    if problems:
        return _fail(locale, "streets", f"{locale}: " + "; ".join(problems))
    return _pass(
        locale,
        "streets",
        f"{locale}: {len(streets)} streets, all non-empty and unique after normalization",
    )
