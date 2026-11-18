# exporter.py I handle every output format an identity can take, writing the full dict as a JSON file named after the username, spilling a batch into identities.csv as one row per identity (used by --count --csv for database seeding), streaming a batch into identities.jsonl as one compact object per line for data pipelines, landing the same batch in identities.db as a SQLite table for anything that would rather query than parse, and copying a plain-text rendering of the profile to the system clipboard through pyperclip. The tabular formats share one ordered field list that excludes the inbox token, because a token is a credential and those formats target pipelines and database seeds, so a field added to the schema reaches every export through a single definition instead of four private copies. The clipboard route depends on the host offering a clipboard mechanism at all (xclip or xsel on Linux, pbcopy on macOS, clip.exe on Windows), so it stays unavailable inside a Docker container unless a display is forwarded.

import csv
import json
import os
import sqlite3
from pathlib import Path

import pyperclip

from identity_generator.paths import output_dir
from identity_generator.schema import IDENTITY_SCHEMA


def _output_dir() -> Path:
    # I resolve the target on every call instead of at import time, so a
    # change of working directory between two exports is respected.
    return output_dir()


_CREDENTIAL_FIELDS = frozenset({"email_token"})

# The single ordered definition of the fields every tabular export carries,
# so the CSV header, the JSONL objects, the SQLite columns and the Parquet
# schema can never disagree about what the pipeline receives. The order is
# the one the CSV shipped with, and a test keeps the list in step with the
# schema properties minus the credential fields.
EXPORT_FIELDS = [
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
    # I write the identity dict to <username>_identity.json in the current directory and, when that name is already taken, append a short id suffix so an earlier export is never silently overwritten. I sanitise the username so a crafted value cannot escape the output directory.
    safe_username = "".join(
        c for c in str(identity.get("username", "identity"))
        if c.isalnum() or c in "_-"
    ) or "identity"
    path = _output_dir() / f"{safe_username}_identity.json"
    if path.exists():
        path = (
            _output_dir()
            / f"{safe_username}_{identity['id'][:8]}_identity.json"
        )
    path.write_text(
        json.dumps(identity, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def to_clipboard(identity: dict) -> None:
    # I copy the identity to the system clipboard, formatted as the plain-text block below.
    pyperclip.copy(_format_profile(identity))


def to_csv_file(identities: list[dict]) -> Path:
    # I write one row per identity into identities.csv in the current directory, overwriting it on every run so a pipeline always knows the filename, carrying the shared export fields that already leave the inbox token out.
    path = _output_dir() / "identities.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        for identity in identities:
            writer.writerow(
                {field: identity.get(field, "") for field in EXPORT_FIELDS}
            )
    return path


def to_schema_file() -> Path:
    # I dump the identity JSON Schema to identity.schema.json in the current directory, overwriting it each run so the published schema always matches the code that produced the data.
    path = _output_dir() / "identity.schema.json"
    path.write_text(
        json.dumps(IDENTITY_SCHEMA, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def to_jsonl_file(identities: list[dict]) -> Path:
    # I write the identities to identities.jsonl in the current directory, one compact JSON object per line in generation order, overwriting the file each run so streaming consumers (jq, log shippers, data loaders) can read it incrementally even while a longer batch is still going, keeping the generator's field order on purpose and excluding the shared credential fields the other tabular exports leave out.
    path = _output_dir() / "identities.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for identity in identities:
            record = {
                field: value
                for field, value in identity.items()
                if field not in _CREDENTIAL_FIELDS
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def _sql_value(value: object) -> str | None:
    # I map None to SQL NULL and everything else to text, so every column reads uniformly no matter which locale produced it or which optional field stayed empty.
    if value is None:
        return None
    return str(value)


def to_sqlite_file(identities: list[dict]) -> Path:
    # I build identities.db in a temporary file next to the target, create the table with the primary key on the identity id, insert every identity through one executemany inside a single transaction, and only after a clean commit and close replace the target with os.replace, so an interrupted export can never destroy a database that was still valid. The replacement discards the previous content entirely, including any extra table the user had added to that file.
    directory = _output_dir()
    target = directory / "identities.db"
    tmp = directory / "identities.db.tmp"
    columns = ", ".join(
        '"id" TEXT NOT NULL PRIMARY KEY'
        if field == "id"
        else f'"{field}" TEXT'
        for field in EXPORT_FIELDS
    )
    placeholders = ", ".join("?" for _ in EXPORT_FIELDS)
    rows = [
        tuple(_sql_value(identity.get(field)) for field in EXPORT_FIELDS)
        for identity in identities
    ]
    conn = sqlite3.connect(tmp)
    try:
        conn.execute(f"CREATE TABLE identities ({columns})")
        conn.executemany(f"INSERT INTO identities VALUES ({placeholders})", rows)
        conn.commit()
    except BaseException:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    conn.close()
    os.replace(tmp, target)
    return target


def _format_profile(identity: dict) -> str:
    # I render the identity as a fixed-width plain-text block, using separator lines and aligned labels so it reads well both in the terminal and pasted into a plain-text field.
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
