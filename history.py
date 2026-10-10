"""
history.py

I keep a persistent local record of every identity I generate, storing each one as a JSON object inside history.json next to this file, which I create on first use and never cap, so the file simply grows with each run.
Concurrency and corruption safety come down to three things: I take an exclusive lock file on every write so two simultaneous runs cannot lose entries to a read-modify-write race, I save atomically by writing a temporary file and renaming it into place so an interrupted run never leaves truncated JSON behind, and when the file is missing or unreadable I return an empty list, moving a corrupted file aside to history.corrupt.<timestamp>.bak instead of letting the next write destroy it.
"""

import json
import os
import time
from pathlib import Path

from applog import get_logger

logger = get_logger("history")

HISTORY_FILE = Path(
    os.environ.get(
        "IDENTITY_HISTORY_FILE", Path(__file__).parent / "history.json"
    )
)

_LOCK_RETRIES = 10
_LOCK_WAIT_SECONDS = 0.05
_LOCK_STALE_SECONDS = 10


def append(identity: dict) -> None:
    """I push a single identity onto the end of the history file, holding the lock across the whole read-append-write cycle."""
    _acquire_lock()
    try:
        entries = _load()
        entries.append(identity)
        _save(entries)
    finally:
        _release_lock()


def append_many(identities: list[dict]) -> None:
    """I add several identities in one locked write, which is how batch generation (--count N) avoids taking and dropping the lock N times."""
    if not identities:
        return
    _acquire_lock()
    try:
        entries = _load()
        entries.extend(identities)
        _save(entries)
    finally:
        _release_lock()


def get_all(limit: int | None = None) -> list[dict]:
    """I return the stored identities, optionally trimmed to the most recent N entries when a positive limit is given, or the full list when it is None."""
    entries = _load()
    if limit and limit > 0:
        return entries[-limit:]
    return entries


def count() -> int:
    """I report how many identities the file holds right now."""
    return len(_load())


def get_by_uuid(identity_id: str) -> dict | None:
    """I look up the stored identity carrying that UUID and give it back, or None when nothing matches."""
    for entry in _load():
        if entry.get("id") == identity_id:
            return entry
    return None


def find_usable_email() -> dict | None:
    """I walk the history backwards and return the {"email", "token", "provider"} triple of the newest identity that still has a real inbox, which is what --reuse builds on, or None when no entry carries a token."""
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
    """I deserialize the history file and give back an empty list whenever it is absent, unreadable or not a JSON array, backing a corrupted file up so the data is never lost without a trace."""
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
    """I move a corrupted history file aside so the next write cannot overwrite it."""
    backup = HISTORY_FILE.with_name(
        f"history.corrupt.{int(time.time())}.bak"
    )
    try:
        os.replace(HISTORY_FILE, backup)
        logger.warning(f"corrupt file backed up to {backup.name}")
    except OSError:
        pass


def _save(entries: list[dict]) -> None:
    """I serialize the whole list to a temporary file and rename it over the real one, so readers only ever see the previous or the new content."""
    tmp = HISTORY_FILE.with_name(HISTORY_FILE.name + ".tmp")
    tmp.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, HISTORY_FILE)


def _acquire_lock() -> None:
    """I create the lock file with O_CREAT and O_EXCL, which the kernel guarantees is atomic even between processes, retrying briefly while another run holds it and clearing a lock older than _LOCK_STALE_SECONDS; when I still cannot get it I raise RuntimeError rather than risk losing entries."""
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
    """I drop the lock file, ignoring the case where somebody already removed it."""
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