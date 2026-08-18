"""
history.py

Manages a persistent local history of generated identities.

Each identity is stored as a JSON object in history.json, located in the same
directory as this file. The file is created automatically on first use. There is
no upper limit on the number of entries; the file grows with each generation run.

Concurrency and corruption safety:
- Writes take an exclusive lock file so two concurrent runs cannot lose entries
  (read-modify-write race).
- Saves are atomic: content is written to a temporary file and renamed into
  place, so an interrupted write never leaves a truncated history.
- If the file is missing or corrupted, all read operations return an empty
  list. A corrupted file is backed up to history.corrupt.<timestamp>.bak and
  announced on stderr instead of being silently destroyed by the next write.
"""

import json
import os
import sys
import time
from pathlib import Path

HISTORY_FILE = Path(
    os.environ.get(
        "IDENTITY_HISTORY_FILE", Path(__file__).parent / "history.json"
    )
)

_LOCK_RETRIES = 10
_LOCK_WAIT_SECONDS = 0.05
_LOCK_STALE_SECONDS = 10


def append(identity: dict) -> None:
    """Add a single identity dict to the end of the history file."""
    _acquire_lock()
    try:
        entries = _load()
        entries.append(identity)
        _save(entries)
    finally:
        _release_lock()


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


def get_by_uuid(identity_id: str) -> dict | None:
    """Return the stored identity with the given UUID, or None."""
    for entry in _load():
        if entry.get("id") == identity_id:
            return entry
    return None


def find_usable_email() -> dict | None:
    """
    Return the most recent identity email that has a real inbox.

    Returns {"email", "token", "provider"} from the newest identity with a
    stored token, or None when there is none. Used by --reuse.
    """
    for entry in reversed(_load()):
        token = entry.get("email_token")
        if token:
            return {
                "email": entry.get("email", ""),
                "token": token,
                "provider": entry.get("email_provider"),
            }
    return None


def _load() -> list[dict]:
    """
    Read and deserialize the history file.

    Returns an empty list if the file does not exist or cannot be parsed.
    A corrupted file is backed up and reported so the data is not lost
    silently.
    """
    if not HISTORY_FILE.exists():
        return []
    try:
        entries = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _backup_corrupt()
        return []
    if not isinstance(entries, list):
        _backup_corrupt()
        return []
    return entries


def _backup_corrupt() -> None:
    """Move a corrupted history file aside so it is not overwritten."""
    backup = HISTORY_FILE.with_name(
        f"history.corrupt.{int(time.time())}.bak"
    )
    try:
        os.replace(HISTORY_FILE, backup)
        print(
            f"[history] corrupt file backed up to {backup.name}",
            file=sys.stderr,
        )
    except OSError:
        pass


def _save(entries: list[dict]) -> None:
    """Serialize and atomically write the full history list to disk."""
    tmp = HISTORY_FILE.with_name(HISTORY_FILE.name + ".tmp")
    tmp.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, HISTORY_FILE)


def _acquire_lock() -> None:
    """
    Create the lock file exclusively, retrying briefly.

    A stale lock (older than _LOCK_STALE_SECONDS) is removed and retried.
    Raises RuntimeError if the lock cannot be obtained.
    """
    lock = _lock_file()
    for _ in range(_LOCK_RETRIES):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            if _is_stale_lock(lock):
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            time.sleep(_LOCK_WAIT_SECONDS)
    raise RuntimeError(
        f"Could not acquire history lock {lock.name}; "
        "another identity-generator run may still be writing."
    )


def _release_lock() -> None:
    """Remove the lock file if it exists."""
    try:
        _lock_file().unlink()
    except OSError:
        pass


def _is_stale_lock(lock: Path) -> bool:
    try:
        return time.time() - lock.stat().st_mtime > _LOCK_STALE_SECONDS
    except OSError:
        return False


def _lock_file() -> Path:
    return HISTORY_FILE.with_name(HISTORY_FILE.name + ".lock")