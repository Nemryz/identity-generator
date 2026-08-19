"""
tools/build_datasets.py

One-time builder for the real-address datasets (Paso 3).

For each of the 11 supported locales it downloads:
- GeoNames cities15000 (top cities by population per country),
- GeoNames postal codes per country (<CC>.zip),
- OpenStreetMap street names via the Overpass API. The country is
  split into a 2x2 grid of cells and each cell is queried separately
  (50 streets per query), so every request stays light even for large
  countries and a failing cell is skipped instead of aborting.

The result is written to data/addresses/<locale>.json and committed to
the repository, so the generator never needs network access at runtime.
Re-running the script refreshes the datasets.

Data sources and licenses:
- GeoNames: https://www.geonames.org/export/  (CC-BY 4.0)
  - cities15000:  https://download.geonames.org/export/dump/cities15000.zip
  - postal codes: https://download.geonames.org/export/zip/<CC>.zip
- OpenStreetMap via Overpass API (https://overpass-api.de/)
  - (c) OpenStreetMap contributors, ODbL https://www.openstreetmap.org/copyright

Run: python -X utf8 tools/build_datasets.py
"""

import argparse
import io
import json
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path

import requests

GEONAMES_BASE = "https://download.geonames.org/export"
CITIES_URL = f"{GEONAMES_BASE}/dump/cities15000.zip"
ZIP_URL = f"{GEONAMES_BASE}/zip/{{cc}}.zip"
OVERPASS_DEFAULT = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
DOWNLOAD_TIMEOUT = 120

LOCALE_COUNTRIES = {
    "es_ES": "ES",
    "es_MX": "MX",
    "es_AR": "AR",
    "es_CL": "CL",
    "es_CO": "CO",
    "en_US": "US",
    "en_GB": "GB",
    "fr_FR": "FR",
    "de_DE": "DE",
    "it_IT": "IT",
    "pt_BR": "BR",
}

CITIES_FIELDS = [
    "geonameid", "name", "asciiname", "alternatenames", "latitude",
    "longitude", "feature_class", "feature_code", "country_code", "cc2",
    "admin1_code", "admin2_code", "admin3_code", "admin4_code", "population",
    "elevation", "dem", "timezone", "modification_date",
]

ZIP_FIELDS = [
    "country_code", "postal_code", "place_name", "admin_name1",
    "admin_code1", "admin_name2", "admin_code2", "admin_name3",
    "admin_code3", "latitude", "longitude", "accuracy",
]

STREET_HIGHWAYS = "^(primary|secondary|tertiary|residential|unclassified)$"
STREETS_PER_CELL = 50
CELL_FETCH_LIMIT = 100
MIRROR_RETRY_SLEEP = 2.0
GRID_ROWS = 2
GRID_COLS = 2


def _normalize(text: str) -> str:
    """Casefold without diacritics for tolerant name matching."""
    ascii_text = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return ascii_text.casefold().strip()


def _download(session: requests.Session, url: str) -> bytes:
    response = session.get(url, timeout=DOWNLOAD_TIMEOUT)
    response.raise_for_status()
    return response.content


def _read_cached(
    session: requests.Session, cache_dir: Path, url: str, name: str
) -> bytes:
    """Download url into a persistent cache, reusing it on later runs."""
    cached = cache_dir / name
    if cached.exists():
        return cached.read_bytes()
    data = _download(session, url)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def load_cities(
    session: requests.Session, cache_dir: Path, cc: str, max_cities: int
) -> list[dict]:
    """
    Return the top cities by population for a country code.

    Uses the GeoNames cities15000 dump (populated places with at least
    15000 inhabitants), filtered by country and sorted by population.
    """
    data = _read_cached(session, cache_dir, CITIES_URL, "cities15000.zip")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        text = archive.read("cities15000.txt").decode("utf-8")

    cities = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < len(CITIES_FIELDS):
            continue
        record = dict(zip(CITIES_FIELDS, fields))
        if record["feature_class"] != "P" or record["country_code"] != cc:
            continue
        try:
            population = int(record["population"])
            latitude = float(record["latitude"])
            longitude = float(record["longitude"])
        except ValueError:
            continue
        if population <= 0:
            continue
        cities.append(
            {
                "name": record["name"],
                "population": population,
                "latitude": latitude,
                "longitude": longitude,
                "admin1_code": record["admin1_code"],
                "alternate_names": _alternate_names(record["alternatenames"]),
            }
        )

    cities.sort(key=lambda city: city["population"], reverse=True)
    return cities[:max_cities]


def _alternate_names(field: str) -> list[str]:
    """Normalized alias list from the cities15000 alternatenames column."""
    names = []
    for raw in field.split(",")[:30]:
        name = _normalize(raw)
        if name and name not in names:
            names.append(name)
    return names


def load_postcodes(
    session: requests.Session, cache_dir: Path, cc: str
) -> dict[str, dict[str, str]]:
    """
    Return postal codes keyed by place and admin1.

    Each place maps admin1 code to the first real postal code, with ""
    holding the first code regardless of region (the plain first-match
    fallback). The zip admin codes differ from the cities15000 admin1
    codes (e.g. "MD" vs "29" for Madrid), so they are bridged per country
    via a learned map in _learn_admin_map.
    """
    data = _read_cached(
        session, cache_dir, ZIP_URL.format(cc=cc), f"zip_{cc}.zip"
    )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member = _postcode_member(archive, cc)
        text = archive.read(member).decode("utf-8")

    codes: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < len(ZIP_FIELDS):
            continue
        record = dict(zip(ZIP_FIELDS, fields))
        place = _normalize(record["place_name"])
        if not place:
            continue
        code = record["postal_code"]
        if "CEDEX" in code:
            code = code.split()[0]
        entry = codes.setdefault(place, {})
        admin = record["admin_code1"]
        if admin and admin not in entry:
            entry[admin] = code
        if "" not in entry:
            entry[""] = code
    return codes


def _learn_admin_map(
    codes: dict[str, dict[str, str]], cities: list[dict]
) -> dict[str, str]:
    """
    Bridge zip admin1 codes to cities15000 admin1 codes.

    For every city whose name appears under exactly one zip region, that
    region is the city's own; this pins zip_admin -> cities_admin for the
    whole country. Used to prefer the correct region when a name collides
    with a same-name district elsewhere.
    """
    admin_map: dict[str, str] = {}
    for city in cities:
        entry = codes.get(_normalize(city["name"]))
        if not entry:
            continue
        admins = [admin for admin in entry if admin != ""]
        if len(admins) != 1:
            continue
        admin_map.setdefault(admins[0], city.get("admin1_code", ""))
    return admin_map


def _postcode_for(
    codes: dict[str, dict[str, str]],
    place: str,
    admin1: str,
    admin_map: dict[str, str],
) -> str | None:
    """
    Best postcode for a place: prefer the zip region that maps to the
    city's own region, otherwise the plain first match.
    """
    entry = codes.get(place)
    if not entry:
        return None
    for admin, postcode in entry.items():
        if admin != "" and admin_map.get(admin) == admin1:
            return postcode
    return entry.get("")


def _postcode_member(archive: zipfile.ZipFile, cc: str) -> str:
    """Pick the <CC>.txt member, ignoring readme.txt and other extras."""
    names = archive.namelist()
    for name in names:
        if name.casefold() == f"{cc}.txt":
            return name
    text_members = [
        name for name in names
        if name.casefold().endswith(".txt") and "readme" not in name.casefold()
    ]
    if text_members:
        return text_members[0]
    raise RuntimeError(f"no postcode table found in zip for {cc}")


def _bbox_cells(cities: list[dict]) -> list[tuple[float, float, float, float]]:
    """
    Split the country into a GRID_ROWS x GRID_COLS grid of cells.

    The bounding box comes from the loaded cities, so each cell is a
    fraction of the country and every street query stays light. Returns
    (south, west, north, east) tuples, or an empty list when the cities
    have no usable coordinates (caller falls back to the area query).
    """
    latitudes = [city["latitude"] for city in cities if "latitude" in city]
    longitudes = [city["longitude"] for city in cities if "longitude" in city]
    if not latitudes or not longitudes:
        return []
    south, north = min(latitudes), max(latitudes)
    west, east = min(longitudes), max(longitudes)
    cells = []
    for row in range(GRID_ROWS):
        cell_south = south + (north - south) * row / GRID_ROWS
        cell_north = south + (north - south) * (row + 1) / GRID_ROWS
        for col in range(GRID_COLS):
            cell_west = west + (east - west) * col / GRID_COLS
            cell_east = west + (east - west) * (col + 1) / GRID_COLS
            cells.append((cell_south, cell_west, cell_north, cell_east))
    return cells


def _match_postcode(
    codes: dict[str, dict[str, str]],
    city: dict,
    admin_map: dict[str, str],
) -> str | None:
    """
    Find the best real postcode for a city.

    Tries the city name and its alternate names (normalized), preferring
    the zip region that maps to the city's own region (via the learned
    admin map) and falling back to the plain first match. Then tries
    prefix matches (e.g. "Bogotá" matching the zip place "Bogotá, D.C.").
    Returns None when the country dataset has no entry at all.
    """
    admin1 = city.get("admin1_code", "")
    candidates = [city["name"], *city.get("alternate_names", [])]
    for name in candidates:
        normalized = _normalize(name)
        if not normalized:
            continue
        postcode = _postcode_for(codes, normalized, admin1, admin_map)
        if postcode:
            return postcode

    primary = _normalize(city["name"])
    if len(primary) >= 5:
        for place, entry in codes.items():
            if place.startswith(primary):
                for admin, postcode in entry.items():
                    if admin != "" and admin_map.get(admin) == admin1:
                        return postcode
                return entry.get("")
    return None


def _query_cell(
    session: requests.Session,
    bbox: tuple[float, float, float, float] | None,
    cc: str,
    mirror: str,
) -> list[str] | None:
    """
    Run one Overpass query and return the named streets found.

    With a bbox the query targets a fraction of the country (small and
    fast); without one it falls back to the whole-country area query.
    Returns None when every mirror fails.
    """
    if bbox is None:
        where = f'area["ISO3166-1"="{cc}"][admin_level=2]->.search;\n(way["highway"~"' + STREET_HIGHWAYS + '"]["name"](area.search););'
    else:
        south, west, north, east = bbox
        where = (
            f'(way["highway"~"' + STREET_HIGHWAYS
            + f'"]["name"]({south:.4f},{west:.4f},{north:.4f},{east:.4f}););'
        )
    query = (
        "[out:json][timeout:120];\n"
        + where
        + f"\nout tags qt {CELL_FETCH_LIMIT};"
    )

    mirrors = [mirror]
    for candidate in OVERPASS_MIRRORS:
        if candidate != mirror:
            mirrors.append(candidate)

    for endpoint in mirrors:
        try:
            response = session.post(
                endpoint, data={"data": query}, timeout=DOWNLOAD_TIMEOUT
            )
            response.raise_for_status()
            payload = response.json()
            streets = []
            for element in payload.get("elements", []):
                name = (element.get("tags") or {}).get("name", "")
                clean = name.strip()
                if clean and len(clean) <= 80:
                    streets.append(clean)
            return streets
        except (requests.RequestException, ValueError):
            print(f"  [osm] {endpoint} fallo, probando siguiente mirror...")
            time.sleep(MIRROR_RETRY_SLEEP)
    return None


def fetch_streets(
    session: requests.Session,
    cc: str,
    cells: list[tuple[float, float, float, float]],
    max_streets: int,
    mirror: str,
    sleep: float,
) -> list[str]:
    """
    Collect up to max_streets named streets of a country.

    The country is queried cell by cell (default 50 streets per cell,
    requested as 100 to compensate for unnamed ways), so every query is
    light enough not to time out even for large countries. A failing
    cell is skipped with a log line instead of aborting the country.
    """
    streets: list[str] = []
    seen: set[str] = set()
    queries = cells if cells else [None]

    for index, bbox in enumerate(queries):
        if len(streets) >= max_streets:
            break
        result = _query_cell(session, bbox, cc, mirror)
        if result is None:
            cell_label = f"celda {index + 1}/{len(queries)}" if bbox else "pais"
            print(f"  [osm] {cell_label} omitida para {cc} (mirrors agotados)")
            continue
        for name in result:
            if len(streets) >= max_streets:
                break
            if name not in seen:
                seen.add(name)
                streets.append(name)
        if index < len(queries) - 1:
            time.sleep(sleep)
    return streets[:max_streets]


def build_locale(
    session: requests.Session,
    cache_dir: Path,
    locale: str,
    max_cities: int,
    max_streets: int,
    mirror: str,
    sleep: float,
    skip_osm: bool = False,
    existing_path: Path | None = None,
) -> dict:
    """Assemble the dataset dict for one locale."""
    cc = LOCALE_COUNTRIES[locale]
    cities = load_cities(session, cache_dir, cc, max_cities)
    postcodes = load_postcodes(session, cache_dir, cc)
    admin_map = _learn_admin_map(postcodes, cities)
    cells = _bbox_cells(cities)

    matched = 0
    for city in cities:
        city["postcode"] = _match_postcode(postcodes, city, admin_map)
        if city["postcode"]:
            matched += 1
        city.pop("latitude", None)
        city.pop("longitude", None)
        city.pop("admin1_code", None)
        city.pop("alternate_names", None)

    if skip_osm and existing_path is not None and existing_path.exists():
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
        streets = existing.get("streets", [])
    else:
        streets = fetch_streets(session, cc, cells, max_streets, mirror, sleep)
    print(
        f"  {locale}: {len(cities)} ciudades "
        f"({matched} con postcode, {matched * 100 // max(len(cities), 1)}%)"
        f", {len(streets)} calles"
    )
    return {
        "locale": locale,
        "country_code": cc,
        "cities": cities,
        "streets": streets,
        "sources": {
            "geonames": "GeoNames, CC-BY 4.0 (https://www.geonames.org/export/)",
            "osm": "(c) OpenStreetMap contributors, ODbL "
            "(https://www.openstreetmap.org/copyright)",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--locales",
        default=",".join(LOCALE_COUNTRIES),
        help="Comma-separated locale codes (default: all 11).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "addresses",
        help="Output directory for the JSON datasets.",
    )
    parser.add_argument(
        "--max-cities", type=int, default=300,
        help="Maximum number of cities per locale (default: 300).",
    )
    parser.add_argument(
        "--max-streets", type=int, default=250,
        help="Maximum number of streets per locale (default: 250).",
    )
    parser.add_argument(
        "--osm-mirror", default=OVERPASS_DEFAULT,
        help="Overpass API endpoint (default: overpass-api.de).",
    )
    parser.add_argument(
        "--sleep", type=float, default=3.0,
        help="Seconds between Overpass queries (default: 3).",
    )
    parser.add_argument(
        "--skip-osm", action="store_true",
        help="Reuse the streets already present in the existing datasets "
        "and skip Overpass entirely (GeoNames-only refresh).",
    )
    args = parser.parse_args()

    locales = [loc for loc in args.locales.split(",") if loc]
    unknown = [loc for loc in locales if loc not in LOCALE_COUNTRIES]
    if unknown:
        parser.error(f"unknown locale(s): {', '.join(unknown)}")

    cache_dir = Path(tempfile.gettempdir()) / "identity-generator-datasets"
    session = requests.Session()
    session.headers["User-Agent"] = "identity-generator dataset builder"

    args.out.mkdir(parents=True, exist_ok=True)
    for index, locale in enumerate(locales):
        print(f"[{index + 1}/{len(locales)}] {locale}")
        target = args.out / f"{locale}.json"
        dataset = build_locale(
            session,
            cache_dir,
            locale,
            args.max_cities,
            args.max_streets,
            args.osm_mirror,
            args.sleep,
            skip_osm=args.skip_osm,
            existing_path=target,
        )
        target.write_text(
            json.dumps(dataset, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if index < len(locales) - 1:
            time.sleep(args.sleep)

    print(f"\nDatasets written to {args.out}")


if __name__ == "__main__":
    main()
