# identity_generator/paths.py I decide where this tool keeps its files, because that question changes completely depending on how you installed it: from a git checkout the natural home is the project directory, while from a pip install inside a virtualenv the project directory is site-packages, where writing a history file or a log would either fail for lack of permissions or pollute every other package in the environment. So I split the files by nature and resolve each one independently: state, secrets and the log belong to the user and live in a per-user data directory, exports belong to the task and are written to the current working directory, and the datasets travel with the package since they are read-only data. Resolution order for a state file is always the same: the environment variable wins when it is set, then a file already present in the user data directory, then the legacy location next to the project (which I migrate once and announce), and finally the user data directory itself for the first run that has not written anything yet.

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "identity-generator"

# Environment variable that overrides the whole user data directory.
HOME_ENV = "IDENTITY_HOME"


def _windows_data_dir() -> Path:
    # I return the roaming-free application data folder on Windows.
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / "AppData" / "Local" / APP_NAME


def _macos_data_dir() -> Path:
    # I return the Application Support folder on macOS.
    return Path.home() / "Library" / "Application Support" / APP_NAME


def _linux_data_dir() -> Path:
    # I follow the XDG base directory specification on Linux, falling back to ~/.local/share.
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def user_data_dir() -> Path:
    # I return the per-user directory where state, secrets and the log live. The IDENTITY_HOME environment variable overrides the platform default, which is handy for containers and for tests that want a throwaway directory without touching the real one.
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        return _windows_data_dir()
    if sys.platform == "darwin":
        return _macos_data_dir()
    return _linux_data_dir()


def ensure_user_data_dir() -> Path:
    # I create the user data directory when it is missing and hand it back.
    directory = user_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def legacy_project_dir() -> Path:
    # I return the directory the tool used before the package move, which is the parent of the package itself when running from a checkout and the current directory otherwise.
    return Path(__file__).resolve().parent.parent


def resolve_state_file(
    filename: str,
    env_var: str | None = None,
    legacy_name: str | None = None,
) -> Path:
    # I work out where a state file belongs and return that path without touching the disk. An explicit environment variable always wins, which keeps the existing IDENTITY_HISTORY_FILE, EMAIL_USAGE_FILE, EMAIL_KEYS_FILE, CUSTOM_DOMAINS_FILE and IDENTITY_LOG_FILE overrides working exactly as before. When the user data directory holds no file yet but the legacy location still has one, I migrate it once and log it, so nobody ends up with two diverging histories.
    if env_var:
        override = os.environ.get(env_var)
        if override:
            return Path(override).expanduser()

    target = user_data_dir() / filename

    if not target.exists():
        legacy = legacy_project_dir() / (legacy_name or filename)
        if legacy.exists():
            # I import the logger lazily because applog resolves the log
            # path through this module, and a module-level import here
            # would close the cycle.
            from identity_generator.applog import get_logger

            logger = get_logger("paths")
            try:
                ensure_user_data_dir()
                shutil.move(str(legacy), str(target))
                logger.info(
                    f"migrated {legacy.name} to {target} "
                    f"(set {HOME_ENV} to keep it somewhere else)"
                )
            except OSError as error:
                logger.warning(
                    f"could not migrate {legacy.name}: {error}. "
                    f"It stays there and this run uses {target}."
                )
    return target


def output_dir() -> Path:
    # I return the directory exports are written to, which is the current working directory. Exports are something the user asked for right now, so they belong where the user is standing rather than in a hidden per-user directory.
    return Path.cwd()


def describe() -> str:
    # I render where this run keeps its files, for the --verbose log.
    return (
        f"state and secrets: {user_data_dir()}\n"
        f"exports: {output_dir()}"
    )
