from floatnote import cli, config, env


def test_clean_snap_env_restores_and_unsets():
    e = {
        "GTK_PATH": "/snap/code/usr/lib/gtk-3.0",
        "GTK_PATH_VSCODE_SNAP_ORIG": "",
        "XDG_DATA_DIRS": "/snap/code/share:/usr/share",
        "XDG_DATA_DIRS_VSCODE_SNAP_ORIG": "/usr/share",
        "HOME": "/home/x",
    }
    fixed = env.clean_snap_env(e)
    assert fixed == ["GTK_PATH", "XDG_DATA_DIRS"]
    assert e == {"XDG_DATA_DIRS": "/usr/share", "HOME": "/home/x"}


def test_config_created_with_defaults(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.load(path)
    assert path.exists()
    assert cfg.model == "small.en"
    assert "Tailwind" in cfg.vocabulary


def test_config_rejects_unknown_keys(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('modle = "small.en"\n')
    try:
        config.load(path)
    except ValueError as e:
        assert "modle" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_help_lists_all_commands(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    for name in [*cli.DAEMON_COMMANDS, "list", "daemon", "doctor"]:
        assert name in out


def test_daemon_command_without_daemon(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert cli.main(["status"]) == 1  # status never auto-starts the daemon
    assert "not running" in capsys.readouterr().err


def test_old_paste_intro_still_works(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('paste_intro = "Old intro"\n')
    assert config.load(path).copy_intro == "Old intro"


def test_set_values_keeps_comments(tmp_path):
    path = tmp_path / "config.toml"
    config.load(path)
    config.set_values({"model": "base.en", "beam_size": 1}, path)
    text = path.read_text()
    assert 'model = "base.en"' in text and "beam_size = 1" in text
    assert "# Speech model" in text
    cfg = config.load(path)
    assert (cfg.model, cfg.beam_size) == ("base.en", 1)


def test_paste_all_alias(capsys, monkeypatch, tmp_path):
    parser = cli.build_parser()
    assert parser.parse_args(["paste-all"]).command == "paste-all"
    assert parser.parse_args(["copy-all"]).command == "copy-all"


def test_apply_replacements():
    from floatnote.transcriber import apply_replacements
    fixes = {"white tail": "Wagtail", "whitetail": "Wagtail", "tail wind": "Tailwind"}
    assert apply_replacements("The whitetail admin and the White  tail page", fixes) == \
        "The Wagtail admin and the Wagtail page"
    assert apply_replacements("tail windy weather", fixes) == "tail windy weather"  # whole words only
    assert apply_replacements("nothing here", {}) == "nothing here"


def test_replacements_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    config.load(path)
    config.set_values({"replacements": {"white tail": "Wagtail"}, "vocabulary": ["API", "Wagtail"]}, path)
    cfg = config.load(path)
    assert cfg.replacements == {"white tail": "Wagtail"}
    assert cfg.vocabulary == ["API", "Wagtail"]
    config.set_values({"replacements": {}}, path)
    assert config.load(path).replacements == {}


def test_fix_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))  # no daemon to restart
    assert cli.main(["fix", "White Tail", "Wagtail"]) == 0
    cfg = config.load()
    assert cfg.replacements == {"white tail": "Wagtail"} and "Wagtail" in cfg.vocabulary
    assert cli.main(["fix"]) == 0
    assert "'white tail'" in capsys.readouterr().out
    assert cli.main(["fix", "--remove", "white tail"]) == 0
    assert config.load().replacements == {}
    assert cli.main(["fix", "only-one"]) == 1


def test_reexec_skipped_when_group_already_active(monkeypatch):
    import os
    calls = []
    monkeypatch.setattr(os, "execvp", lambda *a: calls.append(a))
    monkeypatch.delenv("FLOATNOTE_SG", raising=False)
    cli._reexec_with_input_group(["daemon"])
    import grp
    try:
        g = grp.getgrnam("input")
    except KeyError:
        return
    import pwd
    me = pwd.getpwuid(os.getuid()).pw_name
    expected = me in g.gr_mem and g.gr_gid not in os.getgroups()
    assert bool(calls) == expected
    if calls:
        assert calls[0][1][:3] == ["sg", "input", "-c"]
