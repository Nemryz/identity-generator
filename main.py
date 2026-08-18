"""
main.py

Entry point for the identity-generator command-line tool.

Parses arguments, delegates work to the generator, history, and exporter
modules, and prints a colour-coded profile to the terminal. Colour output
uses colorama so it works on Windows without additional configuration.

Run with: python -X utf8 main.py [options]
"""

import argparse
import sys
import time

from colorama import Fore, Style, init

import exporter
import history as hist
import email_api
from generator import generate_identity, get_supported_locales, is_supported_locale

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

init(autoreset=True)

_SEP_FULL = "=" * 50
_SEP_HALF = "-" * 50
_DIM = Fore.WHITE + Style.DIM
_LABEL = Fore.CYAN + Style.BRIGHT


def _row(label: str, value: str) -> None:
    """Print a single aligned label-value pair."""
    print(f"  {_LABEL}{label:<18}{Style.RESET_ALL} {value}")


def print_identity(identity: dict) -> None:
    """Render a full identity profile to the terminal with colour."""
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
    """Render the history list as a plain table to the terminal."""
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
    """Fetch and render the received emails of one identity's inbox."""
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


def _build_parser() -> argparse.ArgumentParser:
    """Define and return the CLI argument parser."""
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
        help="Print all supported locale codes and exit.",
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
    return parser


def main() -> None:
    """Parse arguments and execute the requested action."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.locale and not is_supported_locale(args.locale):
        parser.error(
            f"unknown locale: {args.locale!r}. "
            "Run --list-locales to see the supported codes."
        )

    if args.list_locales:
        print(Fore.GREEN + Style.BRIGHT + "\n  Supported locales:\n")
        for loc in get_supported_locales():
            print(f"    {loc}")
        print()
        sys.exit(0)

    if args.history:
        print_history(hist.get_all(limit=args.limit))
        sys.exit(0)

    if args.email_usage:
        print(_LABEL + "\n  Email provider usage:\n")
        print(email_api.usage_summary())
        print()
        sys.exit(0)

    if args.check_inbox:
        _print_inbox(args.check_inbox)
        sys.exit(0)

    print(_DIM + "\n  Generating identity...\n")
    identity = generate_identity(
        locale=args.locale,
        email_usable=not args.email_offline,
        reuse=args.reuse,
    )

    print_identity(identity)
    hist.append(identity)

    if args.export_json:
        path = exporter.to_json_file(identity)
        print(Fore.GREEN + f"\n  Exported to: {path}")

    if args.clipboard:
        try:
            exporter.to_clipboard(identity)
            print(Fore.GREEN + "\n  Profile copied to clipboard.")
        except Exception as exc:  # pyperclip raises various types depending on OS
            print(Fore.RED + f"\n  Clipboard unavailable: {exc}")

    if args.delay:
        print(_DIM + f"\n  [throttle] waiting {args.delay}s...")
        time.sleep(args.delay)

    print()


if __name__ == "__main__":
    main()
