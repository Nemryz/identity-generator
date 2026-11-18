# Tests for paths.py: user data dir resolution, env overrides, legacy migration and output dir.



from identity_generator import paths


def test_user_data_dir_honors_IDENTITY_HOME(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "data"))
    assert paths.user_data_dir() == tmp_path / "data"


def test_output_dir_is_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert paths.output_dir() == tmp_path


def test_resolve_state_file_env_override(tmp_path, monkeypatch):
    target = tmp_path / "custom.json"
    monkeypatch.setenv("IDENTITY_HISTORY_FILE", str(target))
    assert paths.resolve_state_file("history.json", "IDENTITY_HISTORY_FILE") == target


def test_resolve_state_file_returns_user_data_path(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "data"))
    monkeypatch.delenv("IDENTITY_HISTORY_FILE", raising=False)
    result = paths.resolve_state_file("history.json", "IDENTITY_HISTORY_FILE")
    assert result == tmp_path / "data" / "history.json"


def test_legacy_migration_moves_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv(paths.HOME_ENV, str(home))
    monkeypatch.delenv("IDENTITY_HISTORY_FILE", raising=False)
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy_file = legacy_dir / "history.json"
    legacy_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(paths, "legacy_project_dir", lambda: legacy_dir)
    result = paths.resolve_state_file("history.json", "IDENTITY_HISTORY_FILE")
    assert result == home / "history.json"
    assert result.exists()
    assert not legacy_file.exists()


def test_ensure_user_data_dir_creates(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "newdata"))
    d = paths.ensure_user_data_dir()
    assert d.exists() and d.is_dir()