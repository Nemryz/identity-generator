"""
generator.py

Builds a complete synthetic identity using the Faker library.

Each call to generate_identity produces a self-consistent profile: the locale
controls the language and regional conventions for every field (names, addresses,
phone formats), so all data points in a profile belong to the same cultural
context.

Supported locales are listed in LOCALE_COUNTRY_MAP. Any locale supported by
Faker can also be used directly; only the locales in the map get a human-readable
country name in the output.
"""

import random
import secrets
import string
import unicodedata
import uuid
from datetime import date, datetime, timezone

from faker import Faker
from faker.config import AVAILABLE_LOCALES

from email_api import get_temp_email

LOCALE_COUNTRY_MAP = {
    "es_ES": "Espana",
    "es_MX": "Mexico",
    "es_AR": "Argentina",
    "es_CL": "Chile",
    "es_CO": "Colombia",
    "en_US": "United States",
    "en_GB": "United Kingdom",
    "en_AU": "Australia",
    "fr_FR": "France",
    "de_DE": "Germany",
    "it_IT": "Italy",
    "pt_BR": "Brazil",
    "pt_PT": "Portugal",
    "nl_NL": "Netherlands",
    "pl_PL": "Poland",
    "ru_RU": "Russia",
    "ja_JP": "Japan",
    "zh_CN": "China",
    "ko_KR": "South Korea",
    "tr_TR": "Turkey",
    "sv_SE": "Sweden",
    "da_DK": "Denmark",
    "fi_FI": "Finland",
    "cs_CZ": "Czech Republic",
    "ro_RO": "Romania",
    "uk_UA": "Ukraine",
    "hu_HU": "Hungary",
    "el_GR": "Greece",
    "bg_BG": "Bulgaria",
}

DEFAULT_LOCALES = ["es_ES", "es_MX", "en_US"]
_VOWELS = set("aeiou")


def get_supported_locales() -> list[str]:
    """Return the list of locales that have an explicit country name mapping."""
    return sorted(LOCALE_COUNTRY_MAP.keys())


def is_supported_locale(locale: str) -> bool:
    """
    Return True when Faker accepts the given locale code.

    Any locale Faker supports is valid, not only the ones with an explicit
    country name in LOCALE_COUNTRY_MAP (e.g. en_CA, es_PE).
    """
    return locale in AVAILABLE_LOCALES


def _calculate_age(dob, today: date | None = None) -> int:
    """
    Calculate the exact age in whole years for a birth date.

    A year is only counted once the birthday has occurred in the current
    year. Subtracting years alone overstates the age when the birthday is
    still pending (e.g. born Dec 1965, seen in Aug 2026: 60, not 61).

    Accepts a date or datetime; ``today`` is injectable for deterministic
    tests and defaults to the current date.
    """
    dob_date = dob.date() if hasattr(dob, "date") else dob
    if today is None:
        today = datetime.now().date()
    age = today.year - dob_date.year
    if (today.month, today.day) < (dob_date.month, dob_date.day):
        age -= 1
    return age


def generate_identity(locale: str | None = None) -> dict:
    """
    Generate a single synthetic identity.

    If locale is None, a random entry from DEFAULT_LOCALES is used.
    The returned dict contains all profile fields plus metadata (id,
    created_at, locale).
    """
    if locale is None:
        locale = random.choice(DEFAULT_LOCALES)

    fake = Faker(locale)
    gender = random.choice(["male", "female"])
    first = _get_first_name(fake, gender)
    last = fake.last_name()
    dob = fake.date_of_birth(minimum_age=18, maximum_age=60)

    return {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "locale": locale,
        "gender": gender,
        "first_name": first,
        "last_name": last,
        "full_name": f"{first} {last}",
        "date_of_birth": dob.isoformat(),
        "age": _calculate_age(dob),
        "address": _safe(fake.street_address, fake.address),
        "city": _safe(fake.city),
        "postcode": _safe(fake.postcode),
        "country": LOCALE_COUNTRY_MAP.get(locale, locale),
        "phone": _safe(fake.phone_number),
        "occupation": _safe(fake.job),
        "email": get_temp_email(),
        "username": _build_username(first, dob.year),
        "nickname": _build_nickname(first),
        "password": secrets.token_urlsafe(16),
    }


def _get_first_name(fake: Faker, gender: str) -> str:
    """
    Retrieve a gendered first name from Faker.

    Falls back to the generic first_name() method if the locale does not
    provide gender-specific variants.
    """
    try:
        return fake.first_name_male() if gender == "male" else fake.first_name_female()
    except AttributeError:
        return fake.first_name()


def _safe(primary_fn, fallback_fn=None) -> str:
    """
    Call primary_fn and return its result.

    If primary_fn raises any exception, call fallback_fn instead.
    If fallback_fn is also unavailable or raises, return "N/A".
    The broad exception catch is intentional: Faker locale coverage varies
    and some providers raise unexpected errors for unsupported locales.
    """
    try:
        return primary_fn()
    except Exception:
        pass
    if fallback_fn:
        try:
            return fallback_fn().split("\n")[0]
        except Exception:
            pass
    return "N/A"


def _to_ascii(text: str) -> str:
    """Strip diacritics and return an ASCII-only lowercase string."""
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def _build_username(first_name: str, birth_year: int) -> str:
    """
    Build an ASCII-safe username from a first name and birth year.

    Format: <name><two-digit-year><three-digit-suffix>
    Example: carlos85042
    """
    clean = _to_ascii(first_name).lower()
    clean = "".join(c for c in clean if c.isalnum())
    suffix = "".join(random.choices(string.digits, k=3))
    return f"{clean}{birth_year % 100}{suffix}"


def _build_nickname(first_name: str) -> str:
    """
    Derive a short creative nickname from the first name.

    Takes the first syllable-like chunk of the name (up to and including the
    first vowel after position 0) and appends a random informal suffix.
    """
    clean = _to_ascii(first_name).lower()
    syllable = clean[:2]
    for i, char in enumerate(clean[1:], 1):
        if char in _VOWELS:
            syllable = clean[: i + 1]
            break
    suffixes = ["x", "z", "ito", "ita", "99", "xd", "pro", "dark", "neo", "chan"]
    return f"{syllable}{random.choice(suffixes)}"
