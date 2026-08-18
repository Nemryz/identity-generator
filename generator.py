"""
generator.py (use alt+z to toggle word wrap in VS Code)

Builds a complete synthetic identity using the Faker library.

Each call to generate_identity produces a self-consistent profile: the locale controls the language and regional conventions for every field (names, addresses, phone formats), so all data points in a profile belong to the same cultural context.

Supported locales are listed in LOCALE_COUNTRY_MAP. Any locale supported by Faker can also be used directly; only the locales in the map get a human-readable country name in the output.

The returned identity dict contains all profile fields plus metadata (id, created_at, locale). The date_of_birth is a date object, and age is calculated from it. The email is generated using a temporary email service.
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

# Mapping of locale codes to human-readable country names. Only locales in this map get a country name in the output, other Faker-supported locales will return the locale code itself. LOCALE_COUNTRY_MAP is used to provide a more user-friendly country name in the generated identity profiles.

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
_PASSWORD_LENGTH = 16
_PASSWORD_LOWER = "abcdefghijkmnopqrstuvwxyz"
_PASSWORD_UPPER = "ABCDEFGHJKMNPQRSTUVWXYZ"
_PASSWORD_DIGITS = "23456789"
_PASSWORD_SYMBOLS = "!@#$%^&*+=?"
_NICKNAME_SUFFIXES = {
    "es": ["ito", "ita", "in", "ina", "z", "x", "99", "pro", "dark"],
    "ja": ["chan", "kun", "tan", "z", "x", "99", "pro", "dark"],
    "default": ["x", "z", "99", "pro", "dark", "neo", "star", "king", "queen"],
}
# DEFAULT_LOCALES is a list of locale codes that are used as defaults when generating synthetic identities. These locales are chosen to provide a diverse set of cultural contexts for the generated profiles. The list includes Spanish (Spain and Mexico) and English (United States) locales, which are commonly used and widely recognized.


def get_supported_locales() -> list[str]:
    """Return the list of locales that have an explicit country name mapping."""
    return sorted(LOCALE_COUNTRY_MAP.keys())


def is_supported_locale(locale: str) -> bool:
    """
    Return True when Faker accepts the given locale code.
    Any locale Faker supports is valid, not only the ones with an explicit country name in LOCALE_COUNTRY_MAP (e.g. en_CA, es_PE).
    """
    return locale in AVAILABLE_LOCALES


def _calculate_age(dob, today: date | None = None) -> int:
    """
    Calculate the exact age in whole years for a birth date.

    A year is only counted once the birthday has occurred in the current year. Subtracting years alone overstates the age when the birthday is still pending (e.g. born Dec 1965, seen in Aug 2026: 60, not 61).

    Accepts a date or datetime; ``today`` is injectable for deterministic tests and defaults to the current date.
    """
    dob_date = dob.date() if hasattr(dob, "date") else dob
    if today is None:
        today = datetime.now().date()
    age = today.year - dob_date.year
    if (today.month, today.day) < (dob_date.month, dob_date.day):
        age -= 1
    return age
def generate_identity(
    locale: str | None = None, email_usable: bool = True
) -> dict:
    """
    Generate a single synthetic identity.

    If locale is None, a random entry from DEFAULT_LOCALES is used.
    The returned dict contains all profile fields plus metadata (id,
    created_at, locale). email_usable=False requests a plausible email
    without a real inbox (no network calls).
    """
    if locale is None:
        locale = random.choice(DEFAULT_LOCALES)

    fake = Faker(locale)
    gender = random.choice(["male", "female"])
    first = _get_first_name(fake, gender)
    last = fake.last_name()
    dob = fake.date_of_birth(minimum_age=18, maximum_age=60)
    email_info = get_temp_email(first, last, usable=email_usable)
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
        "email": email_info["email"],
        "email_token": email_info["token"],
        "username": _build_username(first, dob.year),
        "nickname": _build_nickname(first, locale),
        "password": _build_password(),
    }


def _get_first_name(fake: Faker, gender: str) -> str:
    """
    Retrieve a gendered first name from Faker.

    Falls back to the generic first_name() method if the locale does not provide gender-specific variants.
    """
    try:
        return fake.first_name_male() if gender == "male" else fake.first_name_female()
    except AttributeError:
        return fake.first_name()


def _safe(primary_fn, fallback_fn=None) -> str:
    """
    Call primary_fn and return its result.

    If primary_fn raises any exception, call fallback_fn instead. If fallback_fn is also unavailable or raises, return "N/A". The broad exception catch is intentional: Faker locale coverage varies and some providers raise unexpected errors for unsupported locales.
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
    if not clean:
        clean = "user"
    return f"{clean}{birth_year % 100}{suffix}"


def _build_password() -> str:
    """
    Generate a 16-character password that passes common validators.

    Guarantees at least one lowercase, one uppercase, one digit and one symbol, and avoids ambiguous characters (I, l, 1, O, 0). Every character comes from the operating system's secure random source.
    """
    pools = [_PASSWORD_LOWER, _PASSWORD_UPPER,
             _PASSWORD_DIGITS, _PASSWORD_SYMBOLS]
    chars = [secrets.choice(pool) for pool in pools]
    charset = "".join(pools)
    chars.extend(
        secrets.choice(charset) for _ in range(_PASSWORD_LENGTH - len(chars))
    )
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def _nickname_suffixes(locale: str) -> list[str]:
    """
    Return the nickname suffixes appropriate for the locale's language.

    Language-specific suffixes (Spanish diminutives, Japanese honorifics) are only used for locales of that language, everything else falls back to a universal set of informal handles.
    """
    return _NICKNAME_SUFFIXES.get(locale.split("_")[0], _NICKNAME_SUFFIXES["default"])


def _build_nickname(first_name: str, locale: str) -> str:
    """
    Derive a short creative nickname from the first name.

    Takes the first syllable-like chunk of the name (up to and including the first vowel after position 0) and appends a random informal suffix from the locale's language set.
    """
    clean = _to_ascii(first_name).lower()
    syllable = clean[:2]
    for i, char in enumerate(clean[1:], 1):
        if char in _VOWELS:
            syllable = clean[: i + 1]
            break
    if not syllable:
        syllable = first_name[:1]
    suffixes = _nickname_suffixes(locale)
    return f"{syllable}{random.choice(suffixes)}"
