# email_api.py I handle temporary email address generation for a synthetic identity, and the preferred path always creates a REAL usable inbox whose address is built from the identity's first and last names (carlos.garcia@<provider>, for example) through this chain: 0. Custom - the user's own catch-all domain (domains.json, Cloudflare Email Routing, and the like), where addresses are deliverable to the user's real inbox, never rate-limited and never blocked as disposable. 1. tempmail.lol - REST API. The free tier needs no key (per-IP limits); a stored API key switches it to per-account limits, longer inbox lifespan and access to custom domains. The creation response includes the inbox token in the same request. 2. mail.tm - REST API, no key. Custom address + best-effort session token (its /token endpoint can lag behind account creation). 3. guerrillamail - session AJAX API, no key. One request pins the identity's local part onto a fresh session (set_email_user starts the session for that user directly) and the sid_token it hands back reads the mailbox later. 4. Offline - plausible address with a known disposable domain, no inbox. The --email-provider flag short-circuits the chain: auto walks it in order, while an explicit provider is tried alone and falls back to offline when it fails, so the flag never returns a different real provider than the one asked for. I track rate limits per provider in email_usage.json (tempmail.lol free tier: 15 inboxes per 30 minutes per IP, mail.tm: 8 requests/second) so the chain skips a provider before it rejects us, warning the user when a limit approaches. The tempmail.lol figures are the free tier ones, since a stored API key moves the provider to per-account limits and a Plus or Ultra plan is unaffected by that change. The returned token lets --check-inbox read the mailbox for verification codes, and I count read operations too so their usage stays visible. API references: - https://docs.mail.tm/ - https://tempmail.lol/en/api - https://www.guerrillamail.com/GuerrillaMailAPI.html

import json
import os
import random
import secrets
import string
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path

import requests

from identity_generator.applog import get_logger
from identity_generator.paths import ensure_user_data_dir, resolve_state_file

logger = get_logger("email")

MAILTM_BASE = "https://api.mail.tm"
TEMPMAIL_BASE = "https://api.tempmail.lol"
GUERRILLA_BASE = "https://api.guerrillamail.com/ajax.php"
FALLBACK_DOMAINS = [
    "mailinator.com",
    "guerrillamail.com",
    "trashmail.com",
    "yopmail.com",
]
REQUEST_TIMEOUT = 5

USAGE_FILE = resolve_state_file("email_usage.json", "EMAIL_USAGE_FILE")

CUSTOM_DOMAINS_FILE = resolve_state_file("domains.json", "CUSTOM_DOMAINS_FILE")

# API keys live in their own file (never in domains.json) so the two
# concerns stay separate and so the keys can be deleted independently.
KEYS_FILE = resolve_state_file("email_keys.json", "EMAIL_KEYS_FILE")

# Providers that accept an API key. mail.tm is deliberately absent: its API
# is completely free with no key, no signup and no paid tiers.
KEY_PROVIDERS = ("tempmail",)

PROVIDER_LIMITS = {
    "custom": {"window": 0, "max": 0},
    "tempmail": {"window": 1800, "max": 15},
    "mailtm": {"window": 1, "max": 8},
    "guerrilla": {"window": 0, "max": 0},
    "offline": {"window": 0, "max": 0},
}
_WARNING_THRESHOLD = 0.8
_LOCK_RETRIES = 10
_LOCK_WAIT_SECONDS = 0.05
_LOCK_STALE_SECONDS = 10


def get_temp_email(
    first_name: str,
    last_name: str,
    usable: bool = True,
    provider: str = "auto",
) -> dict:
    # I create an email address for the identity and return it as {"email": str, "token": str | None, "provider": str}: with provider="auto" I walk the chain (custom catch-all domain first, then tempmail.lol, mail.tm and guerrillamail as real-inbox providers, then offline) and fall back to a plausible address without an inbox when everything is unreachable or rate-limited, while an explicit provider is tried on its own and falls back to offline when it fails so the flag never hands back a different real provider than the one asked for; usable=False keeps only the plausible offline address in auto mode, and an explicit provider takes precedence over it because it is the more specific instruction.
    local = _local_part(first_name, last_name)

    custom = _custom_domains()
    if provider == "custom":
        if not custom:
            raise ValueError(
                "--email-provider custom necesita dominios catch-all en "
                "domains.json y no hay ninguno configurado."
            )
        _record_usage("custom")
        return {
            "email": _custom_email(local, custom),
            "token": None,
            "provider": "custom",
        }

    if provider == "auto" and custom:
        _record_usage("custom")
        return {
            "email": _custom_email(local, custom),
            "token": None,
            "provider": "custom",
        }

    if provider == "offline" or (not usable and provider == "auto"):
        _record_usage("offline")
        return {
            "email": _offline_email(local),
            "token": None,
            "provider": "offline",
        }

    if provider != "auto":
        creator = _FORCED_CREATORS.get(provider)
        if creator is None:
            raise ValueError(f"Proveedor de email desconocido: {provider!r}")
        if _can_use(provider):
            result = creator(local)
            if result is not None:
                _record_usage(provider)
                address, token = result
                return {
                    "email": address,
                    "token": token or None,
                    "provider": provider,
                }
            logger.warning(f"{provider} no disponible - usando correo offline")
        else:
            logger.warning(f"{provider} en el limite - usando correo offline")
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
    _warn_provider("mailtm", "guerrillamail")

    if _can_use("guerrilla"):
        result = _guerrilla_email(local)
        if result is not None:
            _record_usage("guerrilla")
            address, token = result
            return {
                "email": address,
                "token": token or None,
                "provider": "guerrilla",
            }
    _warn_provider("guerrilla", "offline")

    _record_usage("offline")
    return {
        "email": _offline_email(local),
        "token": None,
        "provider": "offline",
    }


def check_inbox(identity: dict, limit: int = 10) -> list[dict]:
    # I fetch the received emails for an identity's inbox by using the provider and token stored on it, returning a list of message dicts with keys "from", "subject" and "text"; I raise ValueError when the identity has no inbox to read (an offline email or an unknown provider), and an unreachable or rejecting API gives back an empty list after warning on stderr.
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
    if provider == "guerrilla":
        return _guerrilla_read(token, limit)
    raise ValueError(
        "Proveedor de email desconocido o identidad antigua sin email_provider; "
        "regenera la identidad."
    )


def usage_summary() -> str:
    # Render the per-provider usage counters for --email-usage.
    lines = []
    usage = _load_usage()
    providers = ["tempmail", "mailtm", "guerrilla", "offline"]
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
    # I build an ASCII-safe email local part from the identity names (carlos.garcia.), falling back to "user" when no name transliterates to ASCII as happens with CJK names.
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
    # I return a plausible address on a known disposable domain, with no inbox behind it.
    domain = random.choice(FALLBACK_DOMAINS)
    return f"{local}@{domain}"


def _custom_domains() -> list[str]:
    # I read the user's catch-all domains from domains.json, expecting the {"domains": ["mail.example.com"]} format, and return an empty list when the file is missing, invalid or has no usable entries.
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
    # I build an address on a custom catch-all domain, adding a random 4-digit suffix to avoid collisions with earlier addresses in the user's own inbox while staying readable.
    suffix = "".join(random.choices(string.digits, k=4))
    return f"{local}.{suffix}@{random.choice(domains)}"


def load_api_keys() -> dict:
    # I read the stored API keys, giving back an empty dict on any error, and I expect the {"tempmail": "tm.1234567890.secret"} format while backing a corrupted file up and reporting it so a key is never lost silently, the same protection the usage counters enjoy.
    if not KEYS_FILE.exists():
        return {}
    try:
        data = json.loads(KEYS_FILE.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        _backup_corrupt_keys()
        return {}
    if not isinstance(data, dict):
        _backup_corrupt_keys()
        return {}
    return {
        provider: key
        for provider, key in data.items()
        if provider in KEY_PROVIDERS and isinstance(key, str) and key
    }


def api_key(provider: str) -> str | None:
    # I return the stored API key for a provider, or None when there is none.
    return load_api_keys().get(provider) or None


def set_api_key(provider: str, key: str) -> None:
    # I store an API key for a provider, replacing any previous key, and I raise ValueError on an unknown provider or an empty key so a typo is reported instead of being written to the file.
    provider = provider.strip().lower()
    key = key.strip()
    if provider not in KEY_PROVIDERS:
        raise ValueError(
            f"Proveedor desconocido: {provider!r}. "
            "Solo tempmail admite claves (mail.tm es gratuito y no las usa)."
        )
    if not key:
        raise ValueError("La clave esta vacia.")
    keys = load_api_keys()
    keys[provider] = key
    _save_keys(keys)


def clear_api_key(provider: str) -> bool:
    # I remove the stored API key for a provider, returning True when a key was actually removed and False when there was none or the provider is unknown.
    provider = provider.strip().lower()
    keys = load_api_keys()
    if provider not in keys:
        return False
    del keys[provider]
    _save_keys(keys)
    return True


def mask_api_key(key: str) -> str:
    # I return a printable preview of a key that reveals only its first and last four characters, so the value can be identified without leaking the secret into the terminal or the log file.
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def keys_summary() -> str:
    # I render the stored API keys (masked) for --email-keys.
    keys = load_api_keys()
    lines = []
    for provider in KEY_PROVIDERS:
        key = keys.get(provider)
        if key:
            lines.append(f"    {provider:<10} {mask_api_key(key)}")
        else:
            lines.append(
                f"    {provider:<10} (sin clave, tier gratuito con limite por IP)"
            )
    lines.append(f"    archivo: {KEYS_FILE}")
    return "\n".join(lines)


def _tempmail_headers() -> dict:
    # I build the auth headers for tempmail.lol, leaving them empty on the free tier and adding an Authorization bearer header once an API key is stored, which moves the limits from per-IP to per-account and extends the inbox lifespan.
    key = api_key("tempmail")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _save_keys(keys: dict) -> None:
    # I write the keys atomically and restrict access where supported.
    ensure_user_data_dir()
    tmp = KEYS_FILE.with_name(KEYS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    os.replace(tmp, KEYS_FILE)
    _restrict_permissions(KEYS_FILE)


def _backup_corrupt_keys() -> None:
    # I move a corrupted keys file aside so it is not silently reset.
    backup = KEYS_FILE.with_name(f"email_keys.corrupt.{int(time.time())}.bak")
    try:
        os.replace(KEYS_FILE, backup)
        logger.warning(f"corrupt keys file backed up to {backup.name}")
    except OSError:
        pass


def _restrict_permissions(path: Path) -> None:
    # I make a best-effort restriction so the keys are not readable by other users: chmod 0600 on POSIX, and on Windows I remove inherited ACLs and grant full control only to the current user via icacls.
    if os.name == "nt":
        user = os.environ.get("USERNAME")
        if user:
            domain = os.environ.get("USERDOMAIN")
            principal = f"{domain}\\{user}" if domain else user
            try:
                import subprocess

                subprocess.run(
                    [
                        "icacls",
                        str(path),
                        "/inheritance:r",
                        "/grant:r",
                        f"{principal}:F",
                    ],
                    check=False,
                    capture_output=True,
                )
            except OSError:
                pass
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _guerrilla_email(local: str) -> tuple[str, str] | None:
    # I create a real inbox at guerrillamail in a single request, because set_email_user without a session starts one for that exact user and hands back both the address and the sid_token that reads the mailbox later.
    try:
        response = requests.get(
            GUERRILLA_BASE,
            params={"f": "set_email_user", "email_user": local, "lang": "en"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        address = data.get("email_addr")
        token = data.get("sid_token")
        if address and token:
            return address, token
        return None
    except Exception as exc:  # noqa: BLE001  # guerrillamail can reject or time out; fall through to the next provider.
        logger.debug("guerrillamail inbox creation failed: %s", exc)
        return None


def _guerrilla_read(token: str, limit: int) -> list[dict]:
    # I read received emails from a guerrillamail inbox with the session token, mapping its mail_* fields into the common from/subject/text shape, and give back an empty list when the API is unreachable or the session expired.
    try:
        response = requests.get(
            GUERRILLA_BASE,
            params={"f": "check_email", "seq": "0", "sid_token": token},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        messages = data.get("list", []) if isinstance(data, dict) else []
        result = [
            {
                "from": msg.get("mail_from", ""),
                "subject": msg.get("mail_subject", ""),
                "text": msg.get("mail_body", "") or msg.get("mail_excerpt", ""),
            }
            for msg in messages[:limit]
        ]
        _record_usage("read_guerrilla")
        return result
    except Exception:  # noqa: BLE001
        logger.warning("no se pudo consultar el inbox de guerrillamail")
        return []


def _mailtm_email(local: str) -> tuple[str, str] | None:
    # I create a real inbox at mail.tm with a custom address, giving back (address, token) on success or None, and retrying with a numeric suffix when the address is already taken.
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
    except Exception as exc:  # noqa: BLE001  # mail.tm can reject or time out; fall through to the next provider.
        logger.debug("mail.tm account creation failed: %s", exc)
        return None


def _mailtm_token(address: str, password: str) -> str | None:
    # I exchange mail.tm account credentials for a bearer token, attempting a few short retries because the token endpoint can lag behind account creation, and giving back None when it never validates even though the address itself is still a real inbox.
    for _ in range(3):
        try:
            response = requests.post(
                f"{MAILTM_BASE}/token",
                json={"address": address, "password": password},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                token: str | None = response.json().get("token")
                if isinstance(token, str):
                    return token
                return None
            time.sleep(1)
        except Exception as exc:  # noqa: BLE001  # token endpoint can lag; retry a few times.
            logger.debug("mail.tm token request failed: %s", exc)
            time.sleep(1)
    return None


def _tempmail_email(prefix: str) -> tuple[str, str] | None:
    # I create a real inbox at tempmail.lol with a custom prefix, giving back (address, token) on success or None.
    try:
        response = requests.post(
            f"{TEMPMAIL_BASE}/v2/inbox/create",
            json={"prefix": prefix},
            headers=_tempmail_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        address = data.get("address")
        if address:
            return address, data.get("token") or ""
        return None
    except Exception as exc:  # noqa: BLE001  # tempmail.lol can reject or time out; fall through to the next provider.
        logger.debug("tempmail.lol inbox creation failed: %s", exc)
        return None


def _tempmail_read(token: str, limit: int) -> list[dict]:
    # I read received emails from a tempmail.lol inbox, keeping in mind that v3 consumes only the emails it returns so the limit keeps later messages intact, and I give back an empty list when the API is unreachable or rejects the token.
    try:
        response = requests.get(
            f"{TEMPMAIL_BASE}/v3/inboxes/{token}/emails",
            params={"limit": limit},
            headers=_tempmail_headers(),
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
    except Exception:  # noqa: BLE001
        logger.warning("no se pudo consultar el inbox de tempmail.lol")
        return []


def _mailtm_read(token: str, limit: int) -> list[dict]:
    # I read received emails from a mail.tm inbox: the message list arrives with the bearer token and then each body is fetched on its own, which gives back an empty list when the API is unreachable or rejects the token.
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
    except Exception:  # noqa: BLE001
        logger.warning("no se pudo consultar el inbox de mail.tm")
        return []


# I map an explicit --email-provider choice onto its creation function, so the
# flag tries that provider alone instead of walking the whole chain.
_FORCED_CREATORS: dict[str, Callable[[str], tuple[str, str] | None]] = {
    "tempmail": lambda local: _tempmail_email(local.replace(".", "_")),
    "mailtm": _mailtm_email,
    "guerrilla": _guerrilla_email,
}


def _usage_count(provider: str) -> int:
    # I count the creations of a provider that fall inside its rate-limit window.
    usage = _load_usage()
    window = PROVIDER_LIMITS.get(provider, {}).get("window", 0)
    if window <= 0:
        return len(usage.get(provider, []))
    now = time.time()
    return len([t for t in usage.get(provider, []) if now - t <= window])


def _can_use(provider: str) -> bool:
    # I tell whether a provider still has room inside its rate limit.
    limit = PROVIDER_LIMITS.get(provider, {})
    if limit.get("max", 0) <= 0:
        return True
    return _usage_count(provider) < limit["max"]


def _warn_provider(provider: str, next_name: str) -> None:
    # I warn on stderr when a provider sits at or near its rate limit.
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
    # I append a timestamp for the provider, prune expired entries and persist, writing atomically under an exclusive lock so parallel runs do not lose counts; if the lock cannot be acquired I drop the count, which is benign since the API limit is still caught by the chain fallback.
    ensure_user_data_dir()
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
        ensure_user_data_dir()
        tmp = USAGE_FILE.with_name(USAGE_FILE.name + ".tmp")
        tmp.write_text(json.dumps(usage, indent=2), encoding="utf-8")
        os.replace(tmp, USAGE_FILE)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _load_usage() -> dict:
    # I read the persisted usage counters, or give back an empty dict on any error, and when the file is corrupted I back it up and report so the counters are not reset silently, mirroring the history.json protection.
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
    # I move a corrupted usage file aside so it is not silently reset.
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
