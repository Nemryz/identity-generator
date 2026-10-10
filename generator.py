"""
generator.py (use alt+z to toggle word wrap in VS Code)

I build a complete synthetic identity on top of the Faker library, and every call to generate_identity() returns a self-consistent profile because the locale drives the language and the regional conventions for all the fields at once (names, addresses, phone formats), so each data point in a profile belongs to the same cultural context.
The locales I list explicitly in LOCALE_COUNTRY_MAP get a human-readable country name in the output, though any locale supported by Faker can still be passed in directly and will simply show its own code as the country.
The identity dict I return holds all the profile fields plus some metadata (id, created_at, locale), where date_of_birth is a date object, age is computed from it, and the email is generated through a temporary email service.
"""

import json
import random
import secrets
import string
import unicodedata
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

from faker import Faker
from faker.config import AVAILABLE_LOCALES

from email_api import get_temp_email
from applog import get_logger
import history as hist

logger = get_logger("generator")

# I flip this on while a seed set through set_seed() is active, which swaps the password generator over to the seeded random module so a seeded run reproduces the whole profile.

_SEEDED = False

# I map locale codes to human-readable country names here, so only the locales present in this table get a proper country name in the output and every other Faker-supported locale falls back to showing its own code.

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

# I default to this set of locales when the caller passes none, and I chose them for the cultural variety they add to the output, since Spanish (Spain and Mexico) and English (United States) are the most widely used and instantly recognisable.

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

# Real-address datasets (Paso 3/4): a locale that has a dataset in data/addresses/ gets a city weighted by population, its real postal code and a real street name, while every other locale falls back to Faker.

DATASETS_DIR = Path(__file__).resolve().parent / "data" / "addresses"

# I track which locales put the house number before the street name, and the single one that separates the two with a comma (the Portuguese convention).

ADDRESS_NUMBER_FIRST = {"en_US", "en_GB", "fr_FR"}
ADDRESS_COMMA = {"pt_BR"}

# Official national ID providers per locale (Paso 5): a locale missing from this table (es_AR, ja_JP, ...) has no official Faker provider so I leave its national_id out, and since de_DE rvnr embeds the birth date I hand the identity's own date of birth to it.

_NATIONAL_ID_PROVIDERS = {
    "es_ES": "nif",
    "es_MX": "curp",
    "es_CL": "rut",
    "es_CO": "nuip",
    "en_US": "ssn",
    "en_GB": "ssn",
    "fr_FR": "ssn",
    "de_DE": "rvnr",
    "it_IT": "ssn",
    "pt_BR": "cpf",
}

# I hold the plausible passport serial shapes as (letters, digits) per locale: since Faker ships no passport provider I generate these locally, following each country's official length conventions.

_PASSPORT_FORMATS = {
    "es_ES": (3, 6),
    "es_MX": (3, 6),
    "es_AR": (3, 6),
    "es_CL": (2, 6),
    "es_CO": (2, 7),
    "en_US": (0, 9),
    "en_GB": (0, 9),
    "fr_FR": (2, 7),
    "de_DE": (4, 5),
    "it_IT": (2, 7),
    "pt_BR": (2, 6),
}


# Display names for the official document each locale gets. I keep them apart from _NATIONAL_ID_PROVIDERS because three locales (en_GB, fr_FR, it_IT) draw on Faker's "ssn" provider while standing for three different documents, so a lookup by method name would label all of them "SSN" and be wrong.

_NATIONAL_ID_LABELS = {
    "es_ES": "NIF/DNI",
    "es_MX": "CURP",
    "es_CL": "RUT",
    "es_CO": "NUIP",
    "en_US": "SSN",
    "en_GB": "NIN",
    "fr_FR": "NIR",
    "de_DE": "RVNR",
    "it_IT": "Codice fiscale",
    "pt_BR": "CPF",
}


def _passport_shape(locale: str) -> str:
    """I describe a locale's passport serial as a readable shape, so 3 letters plus 6 digits reads as "3 letters + 6 digits" and a digits-only locale as "9 digits"."""
    letters, digits = _PASSPORT_FORMATS.get(locale, (0, 9))
    parts = []
    if letters:
        parts.append(f"{letters} letters")
    parts.append(f"{digits} digits")
    return " + ".join(parts)


def _address_style(locale: str) -> str:
    """I name the convention used to write the house number and the street together for a locale: number first in the US, the UK and France, comma separated in Brazil and street first everywhere else."""
    if locale in ADDRESS_COMMA:
        return "street, number"
    if locale in ADDRESS_NUMBER_FIRST:
        return "number first"
    return "street first"


def locale_capabilities(locale: str) -> dict:
    """I describe what the generator can actually produce for one locale (country, official document, passport shape, address convention and dataset sizes) so --list-locales can show real capabilities instead of bare codes, returning None for the dataset sizes when the locale has no real-address data and therefore falls back to Faker for its address."""
    dataset = _load_address_dataset(locale)
    return {
        "locale": locale,
        "country": LOCALE_COUNTRY_MAP.get(locale, locale),
        "national_id": _NATIONAL_ID_LABELS.get(locale),
        "passport": _passport_shape(locale),
        "address_style": _address_style(locale) if dataset else "Faker fallback",
        "cities": len(dataset["cities"]) if dataset else None,
        "streets": len(dataset["streets"]) if dataset else None,
    }


def get_supported_locales() -> list[str]:
    """I return the sorted list of locales that carry an explicit country name mapping."""
    return sorted(LOCALE_COUNTRY_MAP.keys())


def is_supported_locale(locale: str) -> bool:
    """I check whether Faker accepts this locale code, and because Faker drives the generation I accept anything it supports rather than only the locales named in LOCALE_COUNTRY_MAP (en_CA or es_PE, for example)."""
    return locale in AVAILABLE_LOCALES


def _calculate_age(dob, today: date | None = None) -> int:
    """I work out the exact age in whole years for a birth date, counting a year only once the birthday has actually happened this year so that subtracting years alone never overstates it (born December 1965, seen in August 2026 is 60, not 61), and I take either a date or a datetime while letting ``today`` be injected for deterministic tests and defaulting to the current date otherwise."""
    dob_date = dob.date() if hasattr(dob, "date") else dob
    if today is None:
        today = datetime.now().date()
    age = today.year - dob_date.year
    if (today.month, today.day) < (dob_date.month, dob_date.day):
        age -= 1
    return age


@lru_cache(maxsize=None)
def _load_address_dataset(locale: str) -> dict | None:
    """I return the real-address dataset for a locale, or None when it has none or the file is missing or unreadable so the caller can fall back to Faker."""
    path = DATASETS_DIR / f"{locale}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cities = data.get("cities") or []
    streets = data.get("streets") or []
    if not cities or not streets:
        return None
    return {"cities": cities, "streets": streets}


def _pick_dataset_city(dataset: dict) -> dict:
    """I pick a city out of a dataset weighted by population, letting only the cities that carry a real postal code take part so the one I hand back always has a usable postcode."""
    pool = [city for city in dataset["cities"] if city.get("postcode")]
    return random.choices(pool, weights=[c["population"] for c in pool])[0]


def _street_number() -> int:
    # I return a plausible house number.
    return random.randint(1, 9999)


def _format_address(locale: str, street: str, number: int) -> str:
    """
    I format a street address following the locale's convention: number-first for US/GB/French ("123 Main Street", "12 rue de la Paix"), comma-separated for Brazilian Portuguese ("Rua Augusta, 123") and street-first for the rest ("Calle X 123", "Hauptstraße 12").
    """
    if locale in ADDRESS_NUMBER_FIRST:
        return f"{number} {street}"
    if locale in ADDRESS_COMMA:
        return f"{street}, {number}"
    return f"{street} {number}"


def _national_id(locale: str, fake: Faker, dob: date) -> str | None:
    """I return the official national ID for a locale by asking its Faker provider (DNI/NIF for Spain, CURP for Mexico, RUT for Chile, cédula NUIP for Colombia, SSN for the US, National Insurance Number for the UK, NIR for France, German pension number for Germany, codice fiscale for Italy, CPF for Brazil), give back None when the locale has no provider, and swallow any provider exception so a missing document never breaks the whole profile."""
    method = _NATIONAL_ID_PROVIDERS.get(locale)
    if method is None:
        return None
    try:
        if method == "rvnr":
            return fake.rvnr(birthdate=dob)
        return getattr(fake, method)()
    except Exception:
        return None


def _passport_number(locale: str) -> str:
    """I return a plausible passport serial for the locale, assembling it locally out of the letter and digit shape used by that country's official passports because Faker ships no passport provider."""
    letters, digits = _PASSPORT_FORMATS.get(locale, (0, 9))
    part_letters = "".join(random.choices(string.ascii_uppercase, k=letters))
    part_digits = "".join(random.choices(string.digits, k=digits))
    return f"{part_letters}{part_digits}"


def generate_identity(
    locale: str | None = None, email_usable: bool = True, reuse: bool = False
) -> dict:
    """I generate one synthetic identity and return a dict with all the profile fields plus metadata (id, created_at, locale): when locale is None I pick a random entry from DEFAULT_LOCALES, email_usable=False asks for a plausible email without a real inbox (no network calls), and reuse=True copies the most recent usable inbox from history instead of creating a new one (no network calls, no provider usage recorded)."""
    if locale is None:
        locale = random.choice(DEFAULT_LOCALES)

    fake = Faker(locale)
    gender = random.choice(["male", "female"])
    first = _get_first_name(fake, gender)
    last = fake.last_name()
    dob = fake.date_of_birth(minimum_age=18, maximum_age=60)

    dataset = _load_address_dataset(locale)
    if dataset is not None:
        city = _pick_dataset_city(dataset)
        street = random.choice(dataset["streets"])
        address = _format_address(locale, street, _street_number())
        city_name = city["name"]
        postcode = city["postcode"]
    else:
        address = _safe(fake.street_address, fake.address)
        city_name = _safe(fake.city)
        postcode = _safe(fake.postcode)

    email_info = None
    if reuse:
        email_info = hist.find_usable_email()
        if email_info is None:
            logger.info("no hay inbox previo reutilizable - creando uno nuevo")
    if email_info is None:
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
        "address": address,
        "city": city_name,
        "postcode": postcode,
        "country": LOCALE_COUNTRY_MAP.get(locale, locale),
        "national_id": _national_id(locale, fake, dob),
        "passport_number": _passport_number(locale),
        "phone": _safe(fake.phone_number),
        "occupation": _safe(fake.job),
        "email": email_info["email"],
        "email_token": email_info["token"],
        "email_provider": email_info.get("provider"),
        "username": _build_username(first, dob.year),
        "nickname": _build_nickname(first, locale),
        "password": _build_password(),
    }


def _get_first_name(fake: Faker, gender: str) -> str:
    """I retrieve a gendered first name from Faker and fall back to the generic first_name() method when the locale offers no gender-specific variants."""
    try:
        return fake.first_name_male() if gender == "male" else fake.first_name_female()
    except AttributeError:
        return fake.first_name()


def _safe(primary_fn, fallback_fn=None) -> str:
    """
    I call primary_fn and hand back its result, falling through to fallback_fn whenever primary_fn raises, and giving up with "N/A" when there is no fallback or it fails too, keeping the broad exception catch on purpose because Faker's locale coverage varies and some providers blow up in unexpected ways on unsupported locales.
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
    # I strip the diacritics off a name and give back a lowercase ASCII-only string.
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def _build_username(first_name: str, birth_year: int) -> str:
    """I build an ASCII-safe username out of a first name and a birth year, following the <name><two-digit-year><three-digit-suffix> format (carlos85042)."""
    clean = _to_ascii(first_name).lower()
    clean = "".join(c for c in clean if c.isalnum())
    suffix = "".join(random.choices(string.digits, k=3))
    if not clean:
        clean = "user"
    return f"{clean}{birth_year % 100}{suffix}"


def set_seed(seed: int | None) -> None:
    """I seed every random source the generator draws from so a whole run reproduces: the standard `random` module (locale, gender, street, house number, passport serial) and the Faker generator (names, dates of birth, national IDs, phone, job), which needs its own because Faker runs on a separate random instance, and while a seed is active I also pull the password over to `random` so the entire profile repeats, whereas passing None restores the default behaviour."""
    global _SEEDED
    if seed is None:
        _SEEDED = False
        return
    random.seed(seed)
    Faker.seed(seed)
    _SEEDED = True


def _build_password() -> str:
    """I generate a 16-character password that satisfies common validators by guaranteeing at least one lowercase, one uppercase, one digit and one symbol while steering clear of ambiguous characters (I, l, 1, O, 0), and every character comes from the operating system's secure random source unless a seed was set with set_seed(), in which case I use the seeded random module so the password is reproducible too."""
    pools = [_PASSWORD_LOWER, _PASSWORD_UPPER,
             _PASSWORD_DIGITS, _PASSWORD_SYMBOLS]
    if _SEEDED:
        choice = random.choice
        randbelow = random.randrange
    else:
        choice = secrets.choice
        randbelow = secrets.randbelow
    chars = [choice(pool) for pool in pools]
    charset = "".join(pools)
    chars.extend(
        choice(charset) for _ in range(_PASSWORD_LENGTH - len(chars))
    )
    for i in range(len(chars) - 1, 0, -1):
        j = randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def _nickname_suffixes(locale: str) -> list[str]:
    """I return the nickname suffixes that suit the locale's language, reserving the language-specific ones (Spanish diminutives, Japanese honorifics) for locales of that language and falling back to a universal set of informal handles for everything else."""
    return _NICKNAME_SUFFIXES.get(locale.split("_")[0], _NICKNAME_SUFFIXES["default"])


def _build_nickname(first_name: str, locale: str) -> str:
    """I derive a short creative nickname from the first name by taking the first syllable-like chunk of it (everything up to and including the first vowel after position 0) and tacking on a random informal suffix from the locale's language set."""
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
