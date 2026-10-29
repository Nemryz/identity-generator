# applog.py I keep the structured logging that every module shares, so nobody has to print to stderr by hand. main.py calls setup_logging() once at startup and I attach a file handler (identity-generator.log, overridable through IDENTITY_LOG_FILE) plus a stderr handler, while modules grab their own logger with get_logger() and log through it. When setup_logging() has not run yet (inside tests, for example) messages fall back to Python's last-resort handler, so warnings still reach stderr.

import logging
import sys
from pathlib import Path

from identity_generator.paths import ensure_user_data_dir, resolve_state_file

LOG_FILENAME = "identity-generator.log"

_FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_STREAM_FORMAT = "%(levelname)s %(name)s: %(message)s"


def log_file() -> Path:
    # I return the path of the log file, resolving it here instead of at import time. Resolving at import time would close an import cycle, since the paths module logs through me while migrating a file, and it would also freeze a location before the user had a chance to set IDENTITY_HOME or IDENTITY_LOG_FILE for this run.
    return resolve_state_file(LOG_FILENAME, "IDENTITY_LOG_FILE")


def setup_logging(verbose: bool = False) -> None:
    # I wire the shared "identity" logger to a file and to stderr, doing nothing when handlers already exist, which keeps repeated calls harmless; without verbose I pass INFO and above to both, with verbose I let DEBUG through as well.
    root = logging.getLogger("identity")
    if root.handlers:
        return
    root.setLevel(logging.DEBUG)
    ensure_user_data_dir()
    file_handler = logging.FileHandler(log_file(), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(logging.Formatter(_STREAM_FORMAT))
    root.addHandler(stream_handler)


def get_logger(name: str) -> logging.Logger:
    # I hand back a child of the shared "identity" logger, named after the calling module.
    return logging.getLogger(f"identity.{name}")
