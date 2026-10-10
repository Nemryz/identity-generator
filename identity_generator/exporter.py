"""
exporter.py

I handle the four output formats an identity can take, writing the full dict as a JSON file named after the username, spilling a batch into identities.csv as one row per identity (used by --count --csv for database seeding), streaming a batch into identities.jsonl as one compact object per line for data pipelines, and finally copying a plain-text rendering of the profile to the system clipboard through pyperclip.
The clipboard route depends on the host offering a clipboard mechanism at all (xclip or xsel on Linux, pbcopy on macOS, clip.exe on Windows), so it stays unavailable inside a Docker container unless a display is forwarded.
"""

import csv
import json
from pathlib import Path

import pyperclip

from identity_generator.schema import IDENTITY_SCHEMA
from identity_generator.paths import output_dir


def _output_dir() -> Path:
    # I resolve the target on every call instead of at import time, so a
    # change of working directory between two exports is respected.
    return output_dir()

_CSV_FIELDS = [
    "full_name",
    "first_name",
    "last_name",
    "gender",
    "date_of_birth",
    "age",
    "address",
    "city",
    "postcode",
    "country",
    "national_id",
    "passport_number",
    "phone",
    "occupation",
    "email",
    "email_provider",
    "username",
    "nickname",
    "password",
    "id",
    "locale",
    "created_at",
]


def to_json_file(identity: dict) -> Path:
    """I write the identity dict to <username>_identity.json in the current directory and, when that name is already taken, append a short id suffix so an earlier export is never silently overwritten."""
    path = _output_dir() / f"{identity['username']}_identity.json"
    if path.exists():
        path = (
            _output_dir()
            / f"{identity['username']}_{identity['id'][:8]}_identity.json"
        )
    path.write_text(
        json.dumps(identity, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def to_clipboard(identity: dict) -> None:
    """I copy the identity to the system clipboard, formatted as the plain-text block below."""
    pyperclip.copy(_format_profile(identity))


def to_csv_file(identities: list[dict]) -> Path:
    """I write one row per identity into identities.csv in the current directory, overwriting it on every run so a pipeline always knows the filename, and leaving out email_token because inbox tokens mean nothing to a database seed."""
    path = _output_dir() / "identities.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for identity in identities:
            writer.writerow(
                {field: identity.get(field, "") for field in _CSV_FIELDS}
            )
    return path


def to_schema_file() -> Path:
    """I dump the identity JSON Schema to identity.schema.json in the current directory, overwriting it each run so the published schema always matches the code that produced the data."""
    path = _output_dir() / "identity.schema.json"
    path.write_text(
        json.dumps(IDENTITY_SCHEMA, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def to_jsonl_file(identities: list[dict]) -> Path:
    """I write the identities to identities.jsonl in the current directory, one compact JSON object per line in generation order, overwriting the file each run so streaming consumers (jq, log shippers, data loaders) can read it incrementally even while a longer batch is still going, and I drop email_token for the same reason the CSV does."""
    path = _output_dir() / "identities.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for identity in identities:
            record = {
                field: value
                for field, value in identity.items()
                if field != "email_token"
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def _format_profile(identity: dict) -> str:
    """I render the identity as a fixed-width plain-text block, using separator lines and aligned labels so it reads well both in the terminal and pasted into a plain-text field."""
    lines = [
        "=" * 48,
        f"  GENERATED IDENTITY  —  {identity.get('country', '')}",
        "=" * 48,
        f"  Full name      : {identity['full_name']}",
        f"  Date of birth  : {identity['date_of_birth']} ({identity['age']} yrs)",
        f"  Gender         : {identity['gender']}",
        f"  Occupation     : {identity['occupation']}",
        f"  National ID    : {identity.get('national_id') or ''}",
        f"  Passport       : {identity.get('passport_number') or ''}",
        "-" * 48,
        f"  Address        : {identity['address']}",
        f"  City           : {identity['city']}",
        f"  Postcode       : {identity['postcode']}",
        f"  Country        : {identity['country']}",
        f"  Phone          : {identity['phone']}",
        "-" * 48,
        f"  Email          : {identity['email']}",
        f"  Username       : {identity['username']}",
        f"  Nickname       : {identity['nickname']}",
        f"  Password       : {identity['password']}",
        "=" * 48,
        f"  ID             : {identity['id']}",
        f"  Generated at   : {identity['created_at']}",
        "=" * 48,
    ]
    return "\n".join(lines)
