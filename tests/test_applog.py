# Tests for applog.py: shared logger wiring and idempotency.

import logging

from identity_generator import applog


def test_get_logger_returns_child():
    logger = applog.get_logger("testmod")
    assert logger.name == "identity.testmod"


def test_setup_logging_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("IDENTITY_HOME", str(tmp_path / "data"))
    applog.setup_logging(verbose=False)
    handlers_before = len(logging.getLogger("identity").handlers)
    applog.setup_logging(verbose=True)
    handlers_after = len(logging.getLogger("identity").handlers)
    assert handlers_before == handlers_after


def test_setup_logging_creates_log_file(tmp_path, monkeypatch):
    monkeypatch.setenv("IDENTITY_HOME", str(tmp_path / "data"))
    # reset handlers to force wiring
    root = logging.getLogger("identity")
    for h in list(root.handlers):
        root.removeHandler(h)
    applog.setup_logging(verbose=False)
    assert applog.log_file().exists()
