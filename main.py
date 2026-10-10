"""
main.py

I am the entry point for the identity-generator command-line tool: I parse the arguments, hand the real work over to the generator, history and exporter modules, and print a colour-coded profile to the terminal, where the colours come from colorama so they work on Windows without extra configuration.

Run with: python -X utf8 main.py [options]
"""

import argparse
import sys
import time

from colorama import Fore, Style, init

import exporter
import history as hist
import email_api
from applog import setup_logging
from generator import (
    generate_identity,
    get_supported_locales,
    is_supported_locale,
    locale_capabilities,
    set_seed,
)
from schema import schema_json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

init(autoreset=True)

_SEP_FULL = "=" * 50
_SEP_HALF = "-" * 50
_DIM = Fore.WHITE + Style.DIM
_LABEL = Fore.CYAN + Style.BRIGHT


def _row(label: str, value: str) -> None:
    """I print a single aligned label-value pair."""
    print(f"  {_LABEL}{label:<18}{Style.RESET_ALL} {value}")


def print_identity(identity: dict) -> None:
    """I render a full identity profile to the terminal with colour."""
    country = identity.get("country", identity["locale"])
    print(_DIM + _SEP_FULL)
    print(Fore.GREEN + Style.BRIGHT + f"  IDENTITY  —  {country}")
    print(_DIM + _SEP_FULL)
    _row("Full name", identity["full_name"])
    _row(
        "Date of birth",
        f"{identity['date_of_birth']}  ({identity['age']} yrs)",
    )
    _row("Gender", identity["gender"])
    _row("Occupation", identity["occupation"])
    _row("National ID", identity.get("national_id") or "N/A")
    _row("Passport", identity.get("passport_number") or "N/A")
    print(_DIM + _SEP_HALF)
    _row("Address", identity["address"])
    _row("City", identity["city"])
    _row("Postcode", identity["postcode"])
    _row("Country", identity["country"])
    _row("Phone", identity["phone"])
    print(_DIM + _SEP_HALF)
    _row("Email", Fore.YELLOW + identity["email"])
    _row("Username", Fore.YELLOW + identity["username"])
    _row("Nickname", Fore.YELLOW + identity["nickname"])
    _row("Password", Fore.RED + identity["password"])
    print(_DIM + _SEP_FULL)
    _row("ID", _DIM + identity["id"])
    _row("Generated at", _DIM + identity["created_at"])
    print(_DIM + _SEP_FULL)


def print_history(entries: list[dict]) -> None:
    """I render the history list as a plain table to the terminal."""
    if not entries:
        print(Fore.YELLOW + "  No identities in history yet.")
        return

    header = (
        f"{'#':<4} {'Full name':<24} {'Country':<18} {'Email':<32} {'Date'}"
    )
    print(_DIM + "-" * len(header))
    print(_LABEL + header)
    print(_DIM + "-" * len(header))
    for i, entry in enumerate(entries, 1):
        created = entry.get("created_at", "")[:10]
        print(
            f"  {i:<3} {entry.get('full_name', ''):<24}"
            f" {entry.get('country', ''):<18}"
            f" {entry.get('email', ''):<32} {created}"
        )
    print(_DIM + "-" * len(header))
    print(f"  Total stored: {hist.count()}")


def _print_inbox(selector: str) -> None:
    """I fetch and render the received emails of one identity's inbox."""
    if selector == "_latest":
        entries = hist.get_all(limit=1)
        if not entries:
            print(Fore.YELLOW + "  No identities in history yet.")
            return
        identity = entries[-1]
    else:
        identity = hist.get_by_uuid(selector)
        if identity is None:
            print(Fore.RED + f"  No identity found with UUID {selector}.")
            return

    print(_DIM + "\n  Checking inbox for " + Fore.YELLOW + identity.get("email", ""))
    print(_DIM + "  (emails are consumed when read from tempmail.lol)\n")
    try:
        messages = email_api.check_inbox(identity)
    except ValueError as exc:
        print(Fore.YELLOW + f"  {exc}")
        return
    if not messages:
        print(Fore.YELLOW + "  No messages received yet (or inbox unavailable).")
        return
    for i, msg in enumerate(messages, 1):
        print(f"  {i}. {_LABEL}{msg['subject']}")
        print(f"     from: {msg['from']}")
        body = msg["text"].strip()[:200]
        if body:
            print(f"     {body}")
        print()


def _print_locale_table() -> None:
    """I print one aligned row per supported locale showing what the generator really produces for it (country, official document, passport shape, address convention and dataset sizes), marking with a dash the locales that have no official document or no real-address dataset."""
    widths = (8, 16, 15, 22, 16, 16)
    header = (
        "  "
        + f"{'Locale':<8}{'Country':<16}{'Document':<15}"
        + f"{'Passport':<22}{'Address':<16}{'Cities/streets':<16}"
    )
    print(_DIM + header)
    print(_DIM + "-" * (sum(widths) + 2))
    for locale in get_supported_locales():
        caps = locale_capabilities(locale)
        dataset = (
            f"{caps['cities']} / {caps['streets']}"
            if caps["cities"] is not None
            else "-"
        )
        print(
            f"  {caps['locale']:<8}{caps['country']:<16}"
            f"{caps['national_id'] or '-':<15}{caps['passport']:<22}"
            f"{caps['address_style']:<16}{dataset:<16}"
        )


def _build_parser() -> argparse.ArgumentParser:
    """I define and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="identity-generator",
        description=(
            "Generate coherent synthetic identities"
            " for privacy-conscious registrations."
        ),
    )
    parser.add_argument(
        "--locale",
        metavar="LOCALE",
        help=(
            "Faker locale code (e.g. es_ES, en_US, fr_FR). "
            "Defaults to a random choice among es_ES, es_MX, en_US."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="export_json",
        help="Export the identity to a JSON file in the project directory.",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Export the generated identities to identities.csv.",
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        dest="export_jsonl",
        help=(
            "Export the generated identities to identities.jsonl, one "
            "compact JSON object per line for data pipelines."
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        metavar="N",
        default=1,
        help=(
            "Generate N identities in one run. Batch mode prints one "
            "compact line per identity instead of the full profile."
        ),
    )
    parser.add_argument(
        "--clipboard",
        action="store_true",
        help="Copy the formatted profile to the system clipboard.",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Display the history of previously generated identities.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        default=None,
        help="When showing history, limit output to the last N entries.",
    )
    parser.add_argument(
        "--list-locales",
        action="store_true",
        dest="list_locales",
        help=(
            "Print every supported locale with its country, official "
            "document, passport shape, address convention and dataset "
            "sizes, then exit."
        ),
    )
    parser.add_argument(
        "--email-offline",
        action="store_true",
        dest="email_offline",
        help=(
            "Generate a plausible email address without a real inbox "
            "(no network calls, no token)."
        ),
    )
    parser.add_argument(
        "--email-usage",
        action="store_true",
        dest="email_usage",
        help="Show email provider usage counters and exit.",
    )
    parser.add_argument(
        "--set-key",
        nargs=2,
        metavar=("PROVIDER", "KEY"),
        dest="set_key",
        help=(
            "Store the API key for a provider (tempmail) and exit. "
            "The key is saved to email_keys.json, which is ignored by git."
        ),
    )
    parser.add_argument(
        "--clear-key",
        nargs=1,
        metavar="PROVIDER",
        dest="clear_key",
        help="Remove the stored API key for a provider and exit.",
    )
    parser.add_argument(
        "--email-keys",
        action="store_true",
        dest="email_keys",
        help="Show which providers have an API key configured (masked) and exit.",
    )
    parser.add_argument(
        "--check-inbox",
        nargs="?",
        const="_latest",
        metavar="UUID",
        dest="check_inbox",
        help=(
            "Read the inbox of the latest identity (or of the UUID given) "
            "and print received emails."
        ),
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help=(
            "Reuse the most recent usable inbox from history instead of "
            "creating a new email (no network calls, no provider usage)."
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        metavar="SECONDS",
        default=None,
        help="Wait SECONDS after generating (throttle for script loops).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        metavar="N",
        default=None,
        help=(
            "Seed the random generators so the same N reproduces the same "
            "profile (pair it with --email-offline, the email provider is "
            "not deterministic)."
        ),
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help=(
            "Print the JSON Schema of an identity and exit. "
            "Combined with --json it is also written to identity.schema.json."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Write debug details to the log file and stderr.",
    )
    return parser


def main() -> None:
    """I parse the arguments and execute the action they ask for."""
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    set_seed(args.seed)

    if args.locale and not is_supported_locale(args.locale):
        parser.error(
            f"unknown locale: {args.locale!r}. "
            "Run --list-locales to see the supported codes."
        )

    if args.list_locales:
        print(Fore.GREEN + Style.BRIGHT + "\n  Supported locales:\n")
        _print_locale_table()
        print()
        sys.exit(0)

    if args.schema:
        print(schema_json())
        if args.export_json:
            path = exporter.to_schema_file()
            print(f"Schema written to: {path}", file=sys.stderr)
        sys.exit(0)

    if args.history:
        print_history(hist.get_all(limit=args.limit))
        sys.exit(0)

    if args.email_usage:
        print(_LABEL + "\n  Email provider usage:\n")
        print(email_api.usage_summary())
        print()
        sys.exit(0)

    if args.set_key:
        provider, key = args.set_key
        try:
            email_api.set_api_key(provider, key)
        except ValueError as exc:
            print(Fore.RED + f"  {exc}")
            sys.exit(1)
        print(
            Fore.GREEN
            + f"\n  Clave guardada para {provider.lower()} en "
            + f"{email_api.KEYS_FILE}"
        )
        print(_DIM + "  (visible solo parcialmente, nunca se imprime completa)\n")
        sys.exit(0)

    if args.clear_key:
        provider = args.clear_key[0]
        if email_api.clear_api_key(provider):
            print(
                Fore.GREEN + f"\n  Clave de {provider.lower()} eliminada.\n"
            )
        else:
            print(Fore.YELLOW + f"\n  No habia clave guardada para {provider}.\n")
        sys.exit(0)

    if args.email_keys:
        print(_LABEL + "\n  Claves de API de email:\n")
        print(email_api.keys_summary())
        print()
        sys.exit(0)

    if args.check_inbox:
        _print_inbox(args.check_inbox)
        sys.exit(0)

    print(_DIM + "\n  Generating identity...\n")
    count = max(1, args.count)
    identities = []
    for i in range(count):
        identity = generate_identity(
            locale=args.locale,
            email_usable=not args.email_offline,
            reuse=args.reuse,
        )
        identities.append(identity)
        if count == 1:
            print_identity(identity)
        else:
            print(
                f"  [{i + 1}/{count}] {identity['full_name']}"
                f" — {identity['country']} — {identity['email']}"
            )
        if i < count - 1 and args.delay:
            print(_DIM + f"  [throttle] waiting {args.delay}s...")
            time.sleep(args.delay)

    hist.append_many(identities)
    if count > 1:
        print(Fore.GREEN + f"\n  Batch complete: {count} identities")

    if args.export_json:
        for identity in identities:
            path = exporter.to_json_file(identity)
            print(Fore.GREEN + f"\n  Exported to: {path}")

    if args.csv:
        path = exporter.to_csv_file(identities)
        print(Fore.GREEN + f"\n  CSV written to: {path}")

    if args.export_jsonl:
        path = exporter.to_jsonl_file(identities)
        print(Fore.GREEN + f"\n  JSONL written to: {path}")

    if args.clipboard:
        try:
            exporter.to_clipboard(identities[-1])
            print(Fore.GREEN + "\n  Profile copied to clipboard.")
        except Exception as exc:  # pyperclip raises various types depending on OS
            print(Fore.RED + f"\n  Clipboard unavailable: {exc}")

    if count == 1 and args.delay:
        print(_DIM + f"\n  [throttle] waiting {args.delay}s...")
        time.sleep(args.delay)

    print()


if __name__ == "__main__":
    main()
