"""
email_api.py

Handles temporary email address generation for a synthetic identity.

The preferred path creates a REAL usable inbox whose address is built from
the identity's first and last names (e.g. carlos.garcia@<provider>):

0. Custom    - own catch-all domain (domains.json, e.g. Cloudflare Email
               Routing). Addresses are deliverable to the user's real
               inbox, never rate-limited and never blocked as disposable.
1. tempmail.lol - REST API, no key on the free tier. Custom prefix. The
   creation response includes the inbox token in the same request.
2. mail.tm      - REST API, no key. Custom address + best-effort session
   token (its /token endpoint can lag behind account creation).
3. Offline      - plausible address with a known disposable domain, no inbox.

Rate limits are tracked per provider in email_usage.json (tempmail.lol: 25
inboxes per 5 minutes per IP, mail.tm: 8 requests/second) so the chain
skips a provider before it rejects us, and the user is warned when a limit
is approaching. The returned token lets the --check-inbox command read the
mailbox for verification codes; read operations are also counted so their
usage stays visible.

API references:
- https://docs.mail.tm/
- https://tempmail.lol/en/api
"""

import json
import os
import random
import secrets
import string
import time
import unicodedata
from pathlib import Path

import requests

from applog import get_logger

logger = get_logger("email")

MAILTM_BASE = "https://api.mail.tm"
TEMPMAIL_BASE = "https://api.tempmail.lol"
FALLBACK_DOMAINS = [
    "mailinator.com",
    "guerrillamail.com",
    "trashmail.com",
    "yopmail.com",
]
REQUEST_TIMEOUT = 5

USAGE_FILE = Path(
    os.environ.get("EMAIL_USAGE_FILE", Path(__file__).parent / "email_usage.json")
)

CUSTOM_DOMAINS_FILE = Path(
    os.environ.get("CUSTOM_DOMAINS_FILE", Path(__file__).parent / "domains.json")
)

PROVIDER_LIMITS = {
    "custom": {"window": 0, "max": 0},
    "tempmail": {"window": 300, "max": 25},
    "mailtm": {"window": 1, "max": 8},
    "offline": {"window": 0, "max": 0},
}
_WARNING_THRESHOLD = 0.8
_LOCK_RETRIES = 10
_LOCK_WAIT_SECONDS = 0.05
_LOCK_STALE_SECONDS = 10


def get_temp_email(
    first_name: str, last_name: str, usable: bool = True
) -> dict:
    """
    Create an email address for the identity, returned as
    {"email": str, "token": str | None, "provider": str}.

    When a custom catch-all domain is configured in domains.json it is
    used first: addresses are deliverable to the user's real inbox with
    no API, no rate limit and no blocking risk. Otherwise, with
    usable=True the real-inbox providers are tried in order (tempmail.lol
    then mail.tm), falling back to a plausible address without an inbox
    when both are unreachable or rate-limited. With usable=False only the
    plausible offline address is produced. The token, when present, can
    later be used to read the inbox.
    """
    local = _local_part(first_name, last_name)

    custom = _custom_domains()
    if custom:
        _record_usage("custom")
        return {
            "email": _custom_email(local, custom),
            "token": None,
            "provider": "custom",
        }

    if not usable:
        _record_usage("offline")
        return {
            "email": _offline_email(local),
            "token": None,
            "provider": "offline",
        }

    if _can_use("tempmail"):
        result = _tempmail_email(local.replace(".", "_"))
        if result is not None:
            _record_usage("tempmail")
            address, token = result
            return {
                "email": address,
                "token": token or None,
                "provider": "tempmail",
            }
    _warn_provider("tempmail", "mail.tm")

    if _can_use("mailtm"):
        result = _mailtm_email(local)
        if result is not None:
            _record_usage("mailtm")
            address, token = result
            return {
                "email": address,
                "token": token or None,
                "provider": "mailtm",
            }
    _warn_provider("mailtm", "offline")

    _record_usage("offline")
    return {
        "email": _offline_email(local),
        "token": None,
        "provider": "offline",
    }


def check_inbox(identity: dict, limit: int = 10) -> list[dict]:
    """
    Fetch received emails for an identity's inbox.

    Uses the provider and token stored on the identity. Returns a list of
    message dicts with keys "from", "subject" and "text". Raises ValueError
    when the identity has no inbox to read (offline email or unknown
    provider). An unreachable or rejecting API returns an empty list after
    warning on stderr.
    """
    provider = identity.get("email_provider")
    token = identity.get("email_token")
    if provider == "custom":
        raise ValueError(
            "Esta dirección se reenvía a tu bandeja de correo real "
            "(dominio catch-all) - revisa tu correo."
        )
    if not token:
        raise ValueError("Esta identidad no tiene un inbox usable (correo offline).")
    if provider == "tempmail":
        return _tempmail_read(token, limit)
    if provider == "mailtm":
        return _mailtm_read(token, limit)
    raise ValueError(
        "Proveedor de email desconocido o identidad antigua sin email_provider; "
        "regenera la identidad."
    )


def usage_summary() -> str:
    """Render the per-provider usage counters for --email-usage."""
    lines = []
    usage = _load_usage()
    providers = ["tempmail", "mailtm", "offline"]
    if _custom_domains():
        providers.insert(0, "custom")
    for provider in providers:
        limit = PROVIDER_LIMITS[provider]
        count = _usage_count(provider)
        window = f"ventana {limit['window']}s" if limit["window"] else "sin límite"
        lines.append(f"    {provider:<10} {count} creaciones  ({window})")
        read_key = f"read_{provider}"
        if usage.get(read_key):
            lines.append(f"    {read_key:<9} {len(usage[read_key])} lecturas")
    return "\n".join(lines)


def _local_part(first_name: str, last_name: str) -> str:
    """
    Build an ASCII-safe email local part from the identity names.

    Example: carlos.garcia. Falls back to "user" when no name
    transliterates to ASCII (e.g. CJK names).
    """
    parts = []
    for name in (first_name, last_name):
        ascii_name = (
            unicodedata.normalize("NFKD", name)
            .encode("ascii", "ignore")
            .decode("ascii")
            .lower()
        )
        clean = "".join(c for c in ascii_name if c.isalnum())
        if clean:
            parts.append(clean)
    local = ".".join(parts) if parts else "user"
    if len(local) < 3:
        local = local + "".join(random.choices(string.digits, k=3 - len(local)))
    return local


def _offline_email(local: str) -> str:
    """Plausible address on a known disposable domain, no inbox."""
    domain = random.choice(FALLBACK_DOMAINS)
    return f"{local}@{domain}"


def _custom_domains() -> list[str]:
    """
    Read the user's catch-all domains from domains.json.

    Expected format: {"domains": ["mail.example.com"]}. Returns an empty
    list when the file is missing, invalid or has no usable entries.
    """
    if not CUSTOM_DOMAINS_FILE.exists():
        return []
    try:
        data = json.loads(
            CUSTOM_DOMAINS_FILE.read_text(encoding="utf-8-sig")
        )
        domains = data.get("domains", []) if isinstance(data, dict) else []
        return [d for d in domains if isinstance(d, str) and d]
    except (json.JSONDecodeError, OSError):
        return []


def _custom_email(local: str, domains: list[str]) -> str:
    """
    Build an address on a custom catch-all domain.

    A random 4-digit suffix avoids collisions with earlier addresses in
    the user's own inbox while staying readable.
    """
    suffix = "".join(random.choices(string.digits, k=4))
    return f"{local}.{suffix}@{random.choice(domains)}"


def _mailtm_email(local: str) -> tuple[str, str] | None:
    """
    Create a real inbox at mail.tm with a custom address.

    Returns (address, token) on success or None. Retries with a numeric
    suffix when the address is already taken.
    """
    try:
        response = requests.get(f"{MAILTM_BASE}/domains", timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        members = response.json().get("hydra:member", [])
        domain = members[0]["domain"] if members else "mail.tm"

        for attempt in range(3):
            suffix = str(attempt) if attempt else ""
            address = f"{local}{suffix}@{domain}"
            password = secrets.token_urlsafe(16)
            resp = requests.post(
                f"{MAILTM_BASE}/accounts",
                json={"address": address, "password": password},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 201:
                return address, _mailtm_token(address, password) or ""
            if resp.status_code != 422:
                break
        return None
    except Exception:
        return None


def _mailtm_token(address: str, password: str) -> str | None:
    """
    Exchange mail.tm account credentials for a bearer token.

    The token endpoint can lag behind account creation, so a few short
    retries are attempted. Returns None when it never validates; the
    address itself is still a real inbox in that case.
    """
    for _ in range(3):
        try:
            response = requests.post(
                f"{MAILTM_BASE}/token",
                json={"address": address, "password": password},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                return response.json().get("token")
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None


def _tempmail_email(prefix: str) -> tuple[str, str] | None:
    """
    Create a real inbox at tempmail.lol with a custom prefix.

    Returns (address, token) on success or None.
    """
    try:
        response = requests.post(
            f"{TEMPMAIL_BASE}/v2/inbox/create",
            json={"prefix": prefix},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        address = data.get("address")
        if address:
            return address, data.get("token") or ""
        return None
    except Exception:
        return None


def _tempmail_read(token: str, limit: int) -> list[dict]:
    """
    Read received emails from a tempmail.lol inbox.

    v3 consumes only the emails it returns, so the limit keeps later
    messages intact. Returns an empty list when the API is unreachable
    or rejects the token.
    """
    try:
        response = requests.get(
            f"{TEMPMAIL_BASE}/v3/inboxes/{token}/emails",
            params={"limit": limit},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        messages = data if isinstance(data, list) else []
        _record_usage("read_tempmail")
        return [
            {
                "from": msg.get("from", ""),
                "subject": msg.get("subject", ""),
                "text": msg.get("text") or msg.get("body", ""),
            }
            for msg in messages
        ]
    except Exception:
        logger.warning("no se pudo consultar el inbox de tempmail.lol")
        return []


def _mailtm_read(token: str, limit: int) -> list[dict]:
    """
    Read received emails from a mail.tm inbox.

    The message list is fetched with the bearer token; each message body
    is fetched individually. Returns an empty list when the API is
    unreachable or rejects the token.
    """
    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(
            f"{MAILTM_BASE}/messages",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        messages = data.get("hydra:member", []) if isinstance(data, dict) else []
        result = []
        for msg in messages[:limit]:
            body = ""
            msg_id = msg.get("id")
            if msg_id:
                full = requests.get(
                    f"{MAILTM_BASE}/messages/{msg_id}",
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                if full.status_code == 200:
                    full_data = full.json()
                    body = full_data.get("text") or full_data.get("html") or ""
            sender = ""
            if msg.get("from"):
                sender = msg["from"][0].get("address", "")
            result.append(
                {"from": sender, "subject": msg.get("subject", ""), "text": body}
            )
        _record_usage("read_mailtm")
        return result
    except Exception:
        logger.warning("no se pudo consultar el inbox de mail.tm")
        return []


def _usage_count(provider: str) -> int:
    """Number of creations of a provider inside its rate-limit window."""
    usage = _load_usage()
    window = PROVIDER_LIMITS.get(provider, {}).get("window", 0)
    if window <= 0:
        return len(usage.get(provider, []))
    now = time.time()
    return len([t for t in usage.get(provider, []) if now - t <= window])


def _can_use(provider: str) -> bool:
    """True when the provider still has room inside its rate limit."""
    limit = PROVIDER_LIMITS.get(provider, {})
    if limit.get("max", 0) <= 0:
        return True
    return _usage_count(provider) < limit["max"]


def _warn_provider(provider: str, next_name: str) -> None:
    """Warn on stderr when a provider is at or near its rate limit."""
    limit = PROVIDER_LIMITS.get(provider, {})
    if limit.get("max", 0) <= 0:
        return
    count = _usage_count(provider)
    status = f"{count}/{limit['max']}"
    if count >= limit["max"]:
        logger.warning(f"{provider} en el límite ({status}) - usando {next_name}")
    elif count >= limit["max"] * _WARNING_THRESHOLD:
        logger.warning(f"{provider} cerca del límite ({status})")


def _record_usage(provider: str) -> None:
    """
    Append a timestamp for provider, prune expired entries and persist.

    Writes atomically under an exclusive lock so parallel runs do not
    lose counts. If the lock cannot be acquired the count is dropped
    (benign: the API limit is still caught by the chain fallback).
    """
    lock = USAGE_FILE.with_name(USAGE_FILE.name + ".lock")
    for _ in range(_LOCK_RETRIES):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if _is_stale_lock(lock):
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            time.sleep(_LOCK_WAIT_SECONDS)
    else:
        return

    try:
        usage = _load_usage()
        timestamps = usage.setdefault(provider, [])
        now = time.time()
        timestamps.append(now)
        window = PROVIDER_LIMITS.get(provider, {}).get("window", 0)
        if window > 0:
            usage[provider] = [t for t in timestamps if now - t <= window]
        tmp = USAGE_FILE.with_name(USAGE_FILE.name + ".tmp")
        tmp.write_text(json.dumps(usage, indent=2), encoding="utf-8")
        os.replace(tmp, USAGE_FILE)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _load_usage() -> dict:
    """
    Read the persisted usage counters, or an empty dict on any error.

    A corrupted file is backed up and reported so the counters are not
    reset silently, mirroring the history.json protection.
    """
    if not USAGE_FILE.exists():
        return {}
    try:
        data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _backup_corrupt_usage()
        return {}
    if not isinstance(data, dict):
        _backup_corrupt_usage()
        return {}
    return data


def _backup_corrupt_usage() -> None:
    """Move a corrupted usage file aside so it is not silently reset."""
    backup = USAGE_FILE.with_name(
        f"email_usage.corrupt.{int(time.time())}.bak"
    )
    try:
        os.replace(USAGE_FILE, backup)
        logger.warning(f"corrupt usage file backed up to {backup.name}")
    except OSError:
        pass


def _is_stale_lock(lock: Path) -> bool:
    try:
        return time.time() - lock.stat().st_mtime > _LOCK_STALE_SECONDS
    except OSError:
        return False