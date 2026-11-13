import os

import pytest

from floatnote import config, paths


def test_config_writer_keeps_special_characters(tmp_path):
    path = tmp_path / "config.toml"
    config.load(path)
    tricky = {"x": "café ☕", "back\\slash": "C:\\path", "quote": 'say "hi"', "a\\nb": "line"}
    config.set_values({"replacements": tricky, "copy_intro": "Line one\nLine two"}, path)
    cfg = config.load(path)
    assert cfg.replacements == tricky
    assert cfg.copy_intro == "Line one\nLine two"
    assert not (tmp_path / "config.tmp").exists()  # atomic write cleaned up


def test_unknown_model_is_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('model = "someone/evil-repo"\n')
    with pytest.raises(ValueError, match="Unknown model"):
        config.load(path)


def test_recordings_off_by_default(tmp_path):
    assert config.load(tmp_path / "config.toml").keep_recordings == 0


def test_tmp_fallback_refuses_foreign_or_open_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    target = f"/tmp/floatnote-{os.getuid()}"
    if os.path.exists(target):
        pytest.skip("fallback folder already exists on this machine")
    try:
        sock = paths.socket_file()
        assert str(sock).startswith(target)
        assert os.stat(target).st_mode & 0o777 == 0o700
        os.chmod(target, 0o777)  # someone opened it up: refuse
        with pytest.raises(RuntimeError):
            paths.socket_file()
    finally:
        os.chmod(target, 0o700)
        os.rmdir(target)


def test_launcher_is_quoted_for_paths_with_spaces(monkeypatch):
    from floatnote import shortcuts
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os.path, "expanduser", lambda p: "/home/my user/.local/bin/floatnote")
    assert shortcuts.default_launcher() == "'/home/my user/.local/bin/floatnote'"


def test_config_writer_handles_emoji(tmp_path):
    path = tmp_path / "config.toml"
    config.load(path)
    config.set_values({"copy_intro": "Fix these 🐛:"}, path)
    assert config.load(path).copy_intro == "Fix these 🐛:"


def test_config_writer_replaces_multiline_lists(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('model = "small.en"\nvocabulary = [\n  "API",  # tech\n  "a]b",\n]\nsounds = true\n')
    config.set_values({"vocabulary": ["Wagtail"]}, path)
    cfg = config.load(path)
    assert cfg.vocabulary == ["Wagtail"] and cfg.sounds is True
    assert path.read_text().count("vocabulary") == 1
