"""
exporter.py

Handles output of a generated identity in three formats.

JSON export writes the full identity dict to a file named after the username
in the project directory. CSV export writes one row per identity to
identities.csv (used by --count --csv for database seeding). Clipboard
export formats the identity as a plain-text block and copies it to the
system clipboard using pyperclip.

The clipboard feature relies on the host system having a clipboard mechanism
available (xclip or xsel on Linux, pbcopy on macOS, clip.exe on Windows).
It will not work inside a Docker container unless a display is forwarded.
"""

import csv
import json
from pathlib import Path

import pyperclip

_OUTPUT_DIR = Path(__file__).parent

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
    """
    Write the identity dict to a JSON file.

    The file is named <username>_identity.json and is placed in the same
    directory as the project. If that name is already taken, a short id
    suffix is appended so existing exports are never silently overwritten.
    Returns the resolved file path.
    """
    path = _OUTPUT_DIR / f"{identity['username']}_identity.json"
    if path.exists():
        path = (
            _OUTPUT_DIR
            / f"{identity['username']}_{identity['id'][:8]}_identity.json"
        )
    path.write_text(
        json.dumps(identity, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def to_clipboard(identity: dict) -> None:
    """Copy the identity formatted as plain text to the system clipboard."""
    pyperclip.copy(_format_profile(identity))


def to_csv_file(identities: list[dict]) -> Path:
    """
    Write the identities as rows to identities.csv in the project directory.

    The file is overwritten on every run so pipelines always know the
    name. email_token is intentionally excluded: the CSV targets database
    seeding, where inbox tokens are meaningless.
    Returns the resolved file path.
    """
    path = _OUTPUT_DIR / "identities.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for identity in identities:
            writer.writerow(
                {field: identity.get(field, "") for field in _CSV_FIELDS}
            )
    return path


def _format_profile(identity: dict) -> str:
    """
    Render an identity dict as a fixed-width plain-text block.

    The layout uses separator lines and aligned labels so the output is
    readable both in the terminal and when pasted into a plain-text field.
    """
    lines = [
        "=" * 48,
        f"  GENERATED IDENTITY  —  {identity.get('country', '')}",
        "=" * 48,
        f"  Full name      : {identity['full_name']}",
        f"  Date of birth  : {identity['date_of_birth']} ({identity['age']} yrs)",
        f"  Gender         : {identity['gender']}",
        f"  Occupation     : {identity['occupation']}",
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
