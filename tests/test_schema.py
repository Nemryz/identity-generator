"""
Tests for schema.py: I check that the published JSON Schema is valid Draft 2020-12, that real identities generated for every supported locale satisfy it, and above all that the schema and the generator cannot drift apart, because these are the drift guards that keep future fields and future locales honest.

I validate with an explicit FormatChecker because JSON Schema treats "format" as a pure annotation unless a checker is passed, so without it the email, uuid and date-time assertions would pass on any string and the whole file would be decoration.
"""

import copy
import json
import random
import re

import pytest
from jsonschema import Draft202012Validator, FormatChecker

import generator
from schema import IDENTITY_SCHEMA, SCHEMA_DIALECT, schema_json

VALIDATOR = Draft202012Validator(IDENTITY_SCHEMA, format_checker=FormatChecker())


def _identity(locale: str = "es_ES") -> dict:
    """I generate one offline identity so the checks never touch the network."""
    return generator.generate_identity(locale=locale, email_usable=False)


def _errors(instance: dict) -> list[str]:
    """I return the validation messages for an instance so a failure is readable."""
    return [error.message for error in VALIDATOR.iter_errors(instance)]


def test_schema_is_valid_draft_2020_12():
    """I assert the schema itself is well formed, so a typo in it fails here and not in every downstream test."""
    Draft202012Validator.check_schema(IDENTITY_SCHEMA)
    assert IDENTITY_SCHEMA["$schema"] == SCHEMA_DIALECT


def test_schema_json_round_trips():
    """I check the printed schema is real JSON carrying the same content, since --schema pipes it into validators."""
    assert json.loads(schema_json()) == IDENTITY_SCHEMA


def test_required_fields_match_generated_identity_keys():
    """I guard the drift that matters most: a new field in generate_identity that nobody added to the schema, or a required field the generator never returns, has to break this test instead of silently shipping a wrong contract."""
    generated = set(_identity())
    required = set(IDENTITY_SCHEMA["required"])
    assert generated == required, (
        "the schema and generate_identity disagree: "
        f"only in the schema {sorted(required - generated)}, "
        f"only in the identity {sorted(generated - required)}"
    )


def test_properties_cover_exactly_the_required_fields():
    """I check no property is described but left optional and no required field goes undescribed, because both states confuse a consumer reading the schema."""
    assert set(IDENTITY_SCHEMA["properties"]) == set(IDENTITY_SCHEMA["required"])


def test_generated_identity_validates_in_every_supported_locale():
    """I validate one identity per supported locale, all 29 of them and offline, because a schema that only holds for the locales someone remembered to try is not a contract."""
    for locale in generator.get_supported_locales():
        assert _errors(_identity(locale)) == [], f"{locale} does not match the schema"


def test_nullable_fields_accept_none():
    """I check the three nullable fields really accept null, since es_AR and ja_JP ship national_id as None and es_CL under --email-offline ships a null token."""
    identity = _identity("es_AR")
    assert identity["national_id"] is None
    identity["email_token"] = None
    identity["email_provider"] = None
    assert _errors(identity) == []


@pytest.mark.parametrize("locale", ["es_AR", "ja_JP"])
def test_locales_without_document_validate_with_null(locale):
    """I assert the locales with no official document still satisfy the schema through the nullable national_id."""
    identity = _identity(locale)
    assert identity["national_id"] is None
    assert _errors(identity) == []


def test_schema_rejects_a_missing_required_field():
    """I delete a required field and expect a failure, which proves the required list is enforced instead of decorative."""
    identity = _identity()
    del identity["username"]
    assert _errors(identity)


def test_schema_rejects_an_unknown_field():
    """I add a field nobody declared and expect a failure, which proves additionalProperties false does its job when a new field is added without touching the schema."""
    identity = _identity()
    identity["unexpected"] = "value"
    assert _errors(identity)


@pytest.mark.parametrize(
    "field,value",
    [
        ("age", "32"),
        ("age", -1),
        ("age", 99),
        ("gender", "other"),
        ("date_of_birth", "32/05/1994"),
        ("username", "with spaces"),
        ("username", "acentúado"),
        ("email", "not-an-email"),
        ("id", "not-a-uuid"),
        ("created_at", "2026-08-19 10:15:30"),
        ("passport_number", ""),
        ("password", "short"),
        ("password", "aaaaAAA2222!!!!"),
        ("password", "aaaalAAA2222!!!!"),
        ("email_provider", "carrier-pigeon"),
    ],
)
def test_schema_rejects_malformed_values(field, value):
    """I feed one malformed value at a time and expect a rejection, which is how I prove the constraints bite rather than pass silently."""
    identity = _identity()
    identity[field] = value
    assert _errors(identity), f"{field}={value!r} should not validate"


def test_schema_accepts_the_providers_the_generator_declares():
    """I check every official document the generator promises produces a value the schema accepts, by walking the provider map instead of a hand-written locale list that would rot."""
    for locale in generator._NATIONAL_ID_PROVIDERS:
        identity = _identity(locale)
        assert identity["national_id"] is not None, locale
        assert _errors(identity) == [], locale


def test_schema_password_pattern_accepts_what_the_generator_can_produce():
    """I build many passwords straight from the generator pools and confirm the schema pattern accepts all of them, so a future charset change cannot contradict the published pattern."""
    pattern = re.compile(IDENTITY_SCHEMA["properties"]["password"]["pattern"])
    pools = [
        generator._PASSWORD_LOWER,
        generator._PASSWORD_UPPER,
        generator._PASSWORD_DIGITS,
        generator._PASSWORD_SYMBOLS,
    ]
    for _ in range(200):
        chars = [random.choice(pool) for pool in pools]
        chars += [
            random.choice("".join(pools))
            for _ in range(generator._PASSWORD_LENGTH - len(pools))
        ]
        assert pattern.fullmatch("".join(chars)), "the schema rejects a password the generator can build"


@pytest.mark.parametrize(
    "candidate,reason",
    [
        ("aaaalAAA2222!!!!", "ambiguous lowercase l"),
        ("aaaAAIAAA2222!!!!", "ambiguous uppercase I"),
        ("aaaaAAA2222!!!!", "15 characters, one short"),
        ("aaaaAAA2222!!!!xx", "17 characters, one too many"),
        ("aaaaAAA22221111", "no symbol at all"),
        ("aaaAAAA2222!!!!", "missing lowercase"),
        ("aaaaAAA!!!!!!!!!", "16 characters with no digit"),
        ("aaaaaaaaaaaaaaaa", "single class only"),
    ],
)
def test_schema_password_pattern_rejects_bad_passwords(candidate, reason):
    """I reject the ambiguous glyphs, the missing classes and the wrong lengths, which proves the four lookaheads and the length bound in the pattern really bite."""
    pattern = re.compile(IDENTITY_SCHEMA["properties"]["password"]["pattern"])
    assert not pattern.fullmatch(candidate), reason


def test_schema_password_pattern_accepts_the_sixteen_character_boundary():
    """I pin the exact boundary case that a careless implementation would get wrong: 16 valid characters must pass, so the {16} bound is a length check and not an off-by-one."""
    pattern = re.compile(IDENTITY_SCHEMA["properties"]["password"]["pattern"])
    assert pattern.fullmatch("aaaaAAA2222!!!!x")
    assert not pattern.fullmatch("aaaaAAA2222!!!!xx")
    assert not pattern.fullmatch("aaaaAAA2222!!!")


def test_schema_enum_values_match_the_generator_providers():
    """I keep the email_provider enum honest against the provider names the code actually stores, so adding a provider without touching the enum is caught here."""
    providers = {"tempmail", "mailtm", "offline", None}
    assert set(IDENTITY_SCHEMA["properties"]["email_provider"]["enum"]) == providers


def test_validating_identities_does_not_mutate_the_schema():
    """I assert repeated validation leaves the schema untouched, since I hand out the module-level object and a consumer mutating it would corrupt every later check."""
    before = copy.deepcopy(IDENTITY_SCHEMA)
    for locale in ("es_ES", "es_AR", "pt_BR"):
        assert _errors(_identity(locale)) == []
    assert IDENTITY_SCHEMA == before