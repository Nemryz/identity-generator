"""
applog.py

Minimal structured logging shared by all modules.

main.py calls setup_logging() once at startup, attaching a file handler
(identity-generator.log, overridable via IDENTITY_LOG_FILE) and a stderr
handler. Modules obtain their logger with get_logger() instead of
printing to stderr directly. When setup_logging() has not been called
(for example inside tests), messages fall back to Python's last-resort
handler, so warnings still reach stderr.
"""

import logging
import os
import sys
from pathlib import Path

LOG_FILE = Path(
    os.environ.get(
        "IDENTITY_LOG_FILE", Path(__file__).parent / "identity-generator.log"
    )
)

_FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_STREAM_FORMAT = "%(levelname)s %(name)s: %(message)s"


def setup_logging(verbose: bool = False) -> None:
    """
    Configure the shared "identity" logger with file and stderr handlers.

    Without verbose, INFO+ messages go to the log file and stderr.
    With verbose, DEBUG messages are written to both.
    """
    root = logging.getLogger("identity")
    if root.handlers:
        return
    root.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(logging.Formatter(_STREAM_FORMAT))
    root.addHandler(stream_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a child of the shared "identity" logger."""
    return logging.getLogger(f"identity.{name}")
