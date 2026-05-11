"""
history.py

Manages a persistent local history of generated identities.

Each identity is stored as a JSON object in history.json, located in the same
directory as this file. The file is created automatically on first use. There is
no upper limit on the number of entries; the file grows with each generation run.

If the file is missing or corrupted, all read operations return an empty list
and the next write creates a fresh file.
"""

import json
from pathlib import Path

HISTORY_FILE = Path(__file__).parent / "history.json"


def append(identity: dict) -> None:
    """Add a single identity dict to the end of the history file."""
    entries = _load()
    entries.append(identity)
    _save(entries)


def get_all(limit: int | None = None) -> list[dict]:
    """
    Return stored identities, optionally capped at the last N entries.

    When limit is None the full history is returned. When a positive integer
    is provided, only the most recent entries up to that count are returned.
    """
    entries = _load()
    if limit and limit > 0:
        return entries[-limit:]
    return entries


def count() -> int:
    """Return the total number of identities currently stored."""
    return len(_load())


def _load() -> list[dict]:
    """
    Read and deserialize the history file.

    Returns an empty list if the file does not exist or cannot be parsed.
    """
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save(entries: list[dict]) -> None:
    """Serialize and write the full history list to disk."""
    HISTORY_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
