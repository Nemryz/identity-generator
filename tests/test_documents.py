"""
Tests for the official document fields (Paso 5).

Every locale with a Faker provider gets an official national_id that
must pass the country's own validation rules (control letters, check
digits, official regexes). Locales without a provider (es_AR, ja_JP)
omit the field. passport_number is always present and must match the
locale's plausible serial shape.
"""

import re
from datetime import date

import pytest

from generator import _PASSPORT_FORMATS, generate_identity
import exporter

PROVIDER_LOCALES = [
    "es_ES",
    "es_MX",
    "es_CL",
    "es_CO",
    "en_US",
    "en_GB",
    "fr_FR",
    "de_DE",
    "it_IT",
    "pt_BR",
]
NO_PROVIDER_LOCALES = ["es_AR", "ja_JP"]


def _fake_email(*_args, **_kwargs):
    return {
        "email": "test@example.com",
        "token": "fake-token",
        "provider": "tempmail",
    }


def _identity(locale: str, monkeypatch) -> dict:
    monkeypatch.setattr("generator.get_temp_email", _fake_email)
    return generate_identity(locale=locale, email_usable=False)


def _rut_check_digit(body: str) -> str:
    total = sum(
        int(d) * (2 + ((len(body) - 1 - i) % 6)) for i, d in enumerate(body)
    )
    dv = 11 - (total % 11)
    return {11: "0", 10: "K"}.get(dv, str(dv))


def _nir_key(nir: str) -> str:
    return f"{97 - (int(nir[:13]) % 97):02d}"


_CF_ODD = {
    **{str(i): v for i, v in enumerate([1, 0, 5, 7, 9, 13, 15, 17, 19, 21])},
    **{c: v for c, v in zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23],
    )},
}


def _cf_control_char(cf: str) -> str:
    total = 0
    for i, ch in enumerate(cf[:15]):
        value = _CF_ODD[ch] if i % 2 == 0 else (int(ch) if ch.isdigit() else ord(ch) - 65)
        total += value
    return chr(65 + total % 26)


def _cpf_check_digit(partial: str) -> str:
    total = sum(int(d) * w for d, w in zip(partial, range(len(partial) + 1, 1, -1)))
    rest = (total * 10) % 11
    return "0" if rest == 10 else str(rest)


def test_nif_es_ES(monkeypatch):
    control = "TRWAGMYFPDXBNJZSQVHLCKE"
    for _ in range(3):
        nif = _identity("es_ES", monkeypatch)["national_id"]
        assert re.fullmatch(r"\d{8}[A-Z]", nif)
        assert control[int(nif[:8]) % 23] == nif[-1]


def test_curp_es_MX(monkeypatch):
    # Official RENAPO state codes (same list Faker samples from). The
    # two internal consonants after the state must exclude vowels; the
    # next letter may be any uppercase letter (Faker deviation).
    states = "AS|BC|BS|CC|CS|CH|DF|CL|CM|DG|GT|GR|HG|JC|MC|MN|MS|NT|NL|OC|PL|QO|QR|SP|SL|SR|TC|TS|TL|VZ|YN|ZS|NE"
    regex = (
        rf"^[A-Z][AEIOUX][A-Z]{{2}}\d{{6}}[HM]({states})"
        r"[B-DF-HJ-NP-TV-Z]{2}[A-Z][0A]\d$"
    )
    for _ in range(3):
        curp = _identity("es_MX", monkeypatch)["national_id"]
        assert len(curp) == 18
        assert re.fullmatch(regex, curp)


def test_rut_es_CL(monkeypatch):
    # Faker's es_CL range spans person RUTs from 10 to 99,999,999, so the
    # thousands separator may produce 2..8 digits ("79.899-1", "85.076.113-2").
    for _ in range(3):
        rut = _identity("es_CL", monkeypatch)["national_id"]
        assert re.fullmatch(r"^\d{1,3}(\.\d{3})*-[\dK]$", rut)
        body, check = rut[:-2].replace(".", ""), rut[-1]
        assert _rut_check_digit(body) == check


def test_rut_es_CL_short_form(monkeypatch):
    # Regression: a draw below 100,000 produces one dot group only
    # ("79.899-1"), which the old two-group regex rejected (CI caught it).
    from faker import Faker
    from faker.providers.ssn.es_CL import Provider as CLSsnProvider

    fake = Faker("es_CL")
    provider = next(p for p in fake.get_providers() if isinstance(p, CLSsnProvider))
    monkeypatch.setattr(provider, "random_int", lambda min, max: 79899)
    rut = fake.rut()
    assert rut == "79.899-1"
    assert re.fullmatch(r"^\d{1,3}(\.\d{3})*-[\dK]$", rut)
    body, check = rut[:-2].replace(".", ""), rut[-1]
    assert _rut_check_digit(body) == check


def test_nuip_es_CO(monkeypatch):
    for _ in range(3):
        nuip = _identity("es_CO", monkeypatch)["national_id"]
        assert re.fullmatch(r"\d{7,10}", nuip)


def test_ssn_en_US(monkeypatch):
    for _ in range(3):
        ssn = _identity("en_US", monkeypatch)["national_id"]
        assert re.fullmatch(r"\d{3}-\d{2}-\d{4}", ssn)
        area = int(ssn[:3])
        assert 1 <= area <= 899 and area != 666


def test_nin_en_GB(monkeypatch):
    # Faker uses the HMRC-reserved prefix "ZZ" and check letter "T".
    for _ in range(3):
        nin = _identity("en_GB", monkeypatch)["national_id"].replace(" ", "")
        assert re.fullmatch(r"ZZ\d{6}T", nin)


def test_nir_fr_FR(monkeypatch):
    for _ in range(3):
        nir = _identity("fr_FR", monkeypatch)["national_id"]
        assert re.fullmatch(r"\d{15}", nir)
        assert nir[-2:] == _nir_key(nir)


def test_rvnr_de_DE(monkeypatch):
    for _ in range(3):
        identity = _identity("de_DE", monkeypatch)
        rvnr = identity["national_id"]
        assert re.fullmatch(r"\d{2}\d{6}[A-Z]\d{3}", rvnr)
        dob = date.fromisoformat(identity["date_of_birth"])
        assert rvnr[2:8] == f"{dob:%d%m%y}"


def test_codice_fiscale_it_IT(monkeypatch):
    for _ in range(3):
        cf = _identity("it_IT", monkeypatch)["national_id"]
        assert re.fullmatch(r"[A-Z]{6}\d{2}[A-EHLMPR-T]\d{2}[A-Z]\d{3}[A-Z]", cf)
        assert cf[-1] == _cf_control_char(cf)


def test_cpf_pt_BR(monkeypatch):
    for _ in range(3):
        cpf = _identity("pt_BR", monkeypatch)["national_id"]
        assert re.fullmatch(r"\d{3}\.\d{3}\.\d{3}-\d{2}", cpf)
        digits = [c for c in cpf if c.isdigit()]
        assert _cpf_check_digit("".join(digits[:9])) == digits[9]
        assert _cpf_check_digit("".join(digits[:10])) == digits[10]


@pytest.mark.parametrize("locale", PROVIDER_LOCALES)
def test_national_id_present_with_provider(locale, monkeypatch):
    assert _identity(locale, monkeypatch)["national_id"]


@pytest.mark.parametrize("locale", NO_PROVIDER_LOCALES)
def test_national_id_omitted_without_provider(locale, monkeypatch):
    assert _identity(locale, monkeypatch)["national_id"] is None


def test_passport_shape_per_locale(monkeypatch):
    for locale, (letters, digits) in _PASSPORT_FORMATS.items():
        regex = rf"^[A-Z]{{{letters}}}\d{{{digits}}}$"
        for _ in range(2):
            number = _identity(locale, monkeypatch)["passport_number"]
            assert re.fullmatch(regex, number), f"{locale}: {number!r}"


def test_passport_fallback_shape(monkeypatch):
    number = _identity("ja_JP", monkeypatch)["passport_number"]
    assert re.fullmatch(r"^\d{9}$", number)


def test_document_fields_in_csv():
    assert "national_id" in exporter._CSV_FIELDS
    assert "passport_number" in exporter._CSV_FIELDS
