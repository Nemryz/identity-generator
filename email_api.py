"""
email_api.py

Handles temporary email address generation using the 1secmail public API.
If the API is unreachable (no internet, timeout, or unexpected response),
the module falls back to generating a plausible-looking address using known
disposable mail domains. No API key or account is required.

API reference: https://www.1secmail.com/api/v1/
"""

import random
import string

import requests

API_URL = "https://www.1secmail.com/api/v1/"
FALLBACK_DOMAINS = [
    "mailinator.com",
    "guerrillamail.com",
    "trashmail.com",
    "yopmail.com",
]
REQUEST_TIMEOUT = 5


def get_temp_email() -> str:
    """
    Request a temporary email address from the 1secmail API.

    Returns a real inbox address on success, or a fallback address generated
    locally if the request fails for any reason.
    """
    try:
        response = requests.get(
            API_URL,
            params={"action": "genRandomMailbox", "count": 1},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list):
            return data[0]
    except Exception:
        pass
    return _fallback_email()


def _fallback_email() -> str:
    """
    Generate a plausible disposable email address locally.

    Used when the 1secmail API cannot be reached. The local part is a random
    alphanumeric string of ten characters appended to a known disposable domain.
    """
    domain = random.choice(FALLBACK_DOMAINS)
    local = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"{local}@{domain}"
