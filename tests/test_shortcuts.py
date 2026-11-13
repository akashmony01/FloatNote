import subprocess

from floatnote import shortcuts


class FakeGSettings:
    """Mimics the gsettings CLI with a dict."""

    def __init__(self, existing):
        self.data = {(shortcuts.MEDIA_KEYS, "custom-keybindings"): existing}

    def __call__(self, cmd, capture_output=True, text=True, check=False):
        _, op, schema, key, *value = cmd
        if op == "get":
            out = self.data.get((schema, key), "")
        elif op == "set":
            self.data[(schema, key)] = value[0]
            out = ""
        else:  # reset
            self.data.pop((schema, key), None)
            out = ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out + "\n", stderr="")


def test_install_keeps_existing_and_remove_cleans_up(monkeypatch):
    mine = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/"
    fake = FakeGSettings(f"['{mine}']")
    monkeypatch.setattr(shortcuts.subprocess, "run", fake)

    lines = shortcuts.install("/home/u/.local/bin/floatnote")
    assert lines[0].startswith("Ctrl+Super+Alt+N")
    paths = shortcuts._current_paths()
    assert paths[0] == mine and len(paths) == 3
    show = shortcuts._schema(f"{shortcuts.PATH_PREFIX}show/")
    assert fake.data[(show, "command")] == "/home/u/.local/bin/floatnote show"
    assert fake.data[(show, "binding")] == "<Control><Super><Alt>n"

    shortcuts.install("/home/u/.local/bin/floatnote")  # idempotent
    assert len(shortcuts._current_paths()) == 3

    assert shortcuts.remove() == 2
    assert shortcuts._current_paths() == [mine]
    assert (show, "command") not in fake.data


def test_empty_list_format(monkeypatch):
    fake = FakeGSettings("@as []")
    monkeypatch.setattr(shortcuts.subprocess, "run", fake)
    assert shortcuts._current_paths() == []


def test_old_shortcuts_are_removed_on_install(monkeypatch):
    old = shortcuts.PATH_PREFIX + "toggle-bug/"
    fake = FakeGSettings(f"['{old}']")
    monkeypatch.setattr(shortcuts.subprocess, "run", fake)
    shortcuts.install("/x/floatnote")
    assert old not in shortcuts._current_paths()


def test_pretty_key():
    assert shortcuts.pretty_key("<Control><Super>Up") == "Ctrl+Super+Up"
    assert shortcuts.pretty_key("<Super><Alt>b") == "Super+Alt+B"


def test_ensure_installed_only_once(monkeypatch):
    fake = FakeGSettings("@as []")
    monkeypatch.setattr(shortcuts.subprocess, "run", fake)
    monkeypatch.setattr(shortcuts, "default_launcher", lambda: "/usr/bin/floatnote")
    assert shortcuts.ensure_installed("ctrl+super+alt+n", "ctrl+super+alt+p") is True
    assert shortcuts.ensure_installed("ctrl+super+alt+n", "ctrl+super+alt+p") is False
    show = shortcuts._schema(f"{shortcuts.PATH_PREFIX}show/")
    assert fake.data[(show, "command")] == "/usr/bin/floatnote show"
