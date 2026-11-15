import subprocess

import pytest

from floatnote import shortcuts
from floatnote.shortcuts import cinnamon, gnome, kde, xfce

LAUNCHER = "/home/u/.local/bin/floatnote"


class FakeGSettings:
    """Mimics the gsettings CLI with a dict. Schemas not in `schemas` don't exist."""

    def __init__(self, data, schemas=None):
        self.data = dict(data)
        self.schemas = schemas or {schema for schema, _ in data}

    def __call__(self, cmd, capture_output=True, text=True, check=False):
        _, op, schema, key, *value = cmd
        if schema.split(":")[0].rsplit(".custom-keybinding", 1)[0] not in self.schemas:
            if check:
                raise subprocess.CalledProcessError(1, cmd, stderr="No such schema")
            return subprocess.CompletedProcess(cmd, 1, "", "No such schema")
        if op == "get":
            out = self.data.get((schema, key), "")
        elif op == "set":
            self.data[(schema, key)] = value[0]
            out = ""
        else:  # reset
            self.data.pop((schema, key), None)
            out = ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out + "\n", stderr="")


# ---- desktop detection ------------------------------------------------------

@pytest.mark.parametrize("current, session, expected", [
    ("ubuntu:GNOME", "ubuntu", "gnome"),
    ("GNOME", "gnome", "gnome"),
    ("KDE", "plasma", "kde"),
    ("X-Cinnamon", "cinnamon", "cinnamon"),
    ("XFCE", "xfce", "xfce"),
    ("Budgie:GNOME", "budgie-desktop", "gnome"),
    ("", "plasmawayland", "kde"),
    ("MATE", "mate", None),
    ("", "", None),
])
def test_detect_desktop(current, session, expected):
    env = {"XDG_CURRENT_DESKTOP": current, "DESKTOP_SESSION": session}
    assert shortcuts.detect_desktop(env) == expected


def test_is_ours():
    assert shortcuts.is_ours("/usr/bin/floatnote show")
    assert shortcuts.is_ours("'/home/my user/.local/bin/floatnote' next-project")
    assert not shortcuts.is_ours("xfce4-appfinder")
    assert not shortcuts.is_ours("/usr/bin/floatnote copy-all")


# ---- GNOME ------------------------------------------------------------------

def test_gnome_install_keeps_existing_and_remove_cleans_up(monkeypatch):
    mine = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/"
    fake = FakeGSettings({(gnome.MEDIA_KEYS, "custom-keybindings"): f"['{mine}']"})
    monkeypatch.setattr(subprocess, "run", fake)

    lines = shortcuts.install(LAUNCHER, desktop="gnome")
    assert lines[0].startswith("Ctrl+Super+Alt+N")
    paths = gnome._current_paths()
    assert paths[0] == mine and len(paths) == 3
    show = gnome._schema(f"{gnome.PATH_PREFIX}show/")
    assert fake.data[(show, "command")] == f"{LAUNCHER} show"
    assert fake.data[(show, "binding")] == "<Control><Super><Alt>n"

    shortcuts.install(LAUNCHER, "ctrl+super+alt+m", desktop="gnome")  # idempotent, new key
    assert len(gnome._current_paths()) == 3
    assert fake.data[(show, "binding")] == "<Control><Super><Alt>m"

    assert gnome.remove() == 2
    assert gnome._current_paths() == [mine]
    assert (show, "command") not in fake.data


def test_gnome_empty_list_and_old_shortcuts(monkeypatch):
    old = gnome.PATH_PREFIX + "toggle-bug/"
    fake = FakeGSettings({(gnome.MEDIA_KEYS, "custom-keybindings"): "@as []"})
    monkeypatch.setattr(subprocess, "run", fake)
    assert gnome._current_paths() == []
    fake.data[(gnome.MEDIA_KEYS, "custom-keybindings")] = f"['{old}']"
    shortcuts.install("/x/floatnote", desktop="gnome")
    assert old not in gnome._current_paths()


def test_pretty_key():
    assert shortcuts.pretty_key("<Control><Super>Up") == "Ctrl+Super+Up"
    assert shortcuts.pretty_key("<Super><Alt>b") == "Super+Alt+B"


# ---- Cinnamon ---------------------------------------------------------------

def test_cinnamon_install_and_remove(monkeypatch):
    fake = FakeGSettings({(cinnamon.KEYBINDINGS, "custom-list"): "['custom0']"},
                         schemas={cinnamon.KEYBINDINGS, cinnamon.ITEM_SCHEMA})
    monkeypatch.setattr(subprocess, "run", fake)

    shortcuts.install(LAUNCHER, next_project="ctrl+super+alt+o", desktop="cinnamon")
    ids = cinnamon._ids()
    assert ids[0] == "custom0" and "floatnote-show" in ids and "floatnote-next-project" in ids
    assert cinnamon.DUMMY in ids  # toggled so Cinnamon re-reads the bindings
    nxt = cinnamon._schema("floatnote-next-project")
    assert fake.data[(nxt, "binding")] == "['<Control><Super><Alt>o']"
    assert fake.data[(nxt, "command")] == f"{LAUNCHER} next-project"

    shortcuts.install(LAUNCHER, desktop="cinnamon")  # change: the dummy toggles again
    assert cinnamon.DUMMY not in cinnamon._ids()

    assert cinnamon.remove() == 2
    assert [i for i in cinnamon._ids() if i != cinnamon.DUMMY] == ["custom0"]


# ---- XFCE -------------------------------------------------------------------

class FakeXfconf:
    def __init__(self, props):
        self.props = dict(props)

    def __call__(self, cmd, capture_output=True, text=True, check=False):
        assert cmd[:3] == ["xfconf-query", "-c", xfce.CHANNEL]
        args = cmd[3:]
        if args == ["-l", "-v"]:
            out = "".join(f"{p:<40} {v}\n" for p, v in self.props.items())
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if args[0] == "-r":
            self.props.pop(args[2], None)
        else:  # -n -t string -p PROP -s VALUE
            self.props[args[args.index("-p") + 1]] = args[args.index("-s") + 1]
        return subprocess.CompletedProcess(cmd, 0, "", "")


def test_xfce_install_and_remove(monkeypatch):
    fake = FakeXfconf({"/commands/custom/<Alt>F2": "xfce4-appfinder --collapsed",
                       "/commands/custom/<Primary><Super><Alt>z": "/old/floatnote show"})
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(xfce.shutil, "which", lambda name: "/usr/bin/" + name)

    shortcuts.install(LAUNCHER, desktop="xfce")
    assert fake.props["/commands/custom/<Primary><Super><Alt>n"] == f"{LAUNCHER} show"
    assert fake.props["/commands/custom/<Primary><Super><Alt>p"] == f"{LAUNCHER} next-project"
    assert "/commands/custom/<Primary><Super><Alt>z" not in fake.props  # old key replaced
    assert xfce.installed()

    assert xfce.remove() == 2
    assert fake.props == {"/commands/custom/<Alt>F2": "xfce4-appfinder --collapsed"}


# ---- KDE --------------------------------------------------------------------

def test_qt_key_codes():
    assert kde.qt_key("ctrl+super+alt+n") == 0x04000000 | 0x10000000 | 0x08000000 | ord("N")
    assert kde.qt_key("ctrl+alt+f12") == 0x04000000 | 0x08000000 | 0x0100003B
    assert kde.qt_key("super+shift+left") == 0x10000000 | 0x02000000 | 0x01000012
    assert kde.qt_key("ctrl+1") == 0x04000000 | ord("1")


class FakeKGlobalAccel:
    def __init__(self, taken=(), busy=0):
        self.busy = busy
        self.keys = {}
        self.taken = set(taken)
        self.calls = []

    def __call__(self, cmd, capture_output=True, text=True, check=False):
        method = cmd[cmd.index("--method") + 1].rsplit(".", 1)[1]
        args = cmd[cmd.index("--method") + 2:]
        self.calls.append(method)
        out = "()"
        if method == "setShortcutKeys":
            code = int(args[1].split("[")[2].split(",")[0])
            if self.busy:  # KDE still reloading its app list
                self.busy -= 1
                out = "(@a(ai) [],)"
            elif code in self.taken:
                out = "([],)"
            else:
                self.keys[args[0]] = code
                out = f"([([{code}, 0, 0, 0],)],)"
        elif method == "unregister":
            out = "(true,)"
        elif method == "globalShortcutsByKey":
            code = int(args[0].split("[")[1].split(",")[0])
            out = "([('kwin', 'x', 'KWin', 'X', '', '', [0], [0])],)" if code in self.taken \
                else "(@a(ssssssaiai) [],)"
        return subprocess.CompletedProcess(cmd, 0, out, "")


def test_kde_install_and_remove(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    fake = FakeKGlobalAccel()
    monkeypatch.setattr(subprocess, "run", fake)

    shortcuts.install("'/home/my user/.local/bin/floatnote'", desktop="kde")
    desktop = (tmp_path / "applications" / "floatnote-show.desktop").read_text()
    assert 'Exec="/home/my user/.local/bin/floatnote" show' in desktop
    assert "NoDisplay=true" in desktop
    assert fake.calls == ["doRegister", "setShortcutKeys"] * 2
    assert kde.qt_key("ctrl+super+alt+n") in fake.keys.values()
    assert kde.installed()

    assert kde.remove() == 2
    assert not kde.installed() and fake.calls[-1] == "unregister"


def test_kde_reports_taken_keys_at_once(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    fake = FakeKGlobalAccel(taken={kde.qt_key("ctrl+super+alt+n")})
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(kde.time, "sleep", lambda s: pytest.fail("no retry for a real clash"))
    with pytest.raises(shortcuts.ShortcutError, match="already used"):
        shortcuts.install(LAUNCHER, desktop="kde")


def test_kde_retries_while_kde_reloads(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    fake = FakeKGlobalAccel(busy=3)
    monkeypatch.setattr(subprocess, "run", fake)
    sleeps = []
    monkeypatch.setattr(kde.time, "sleep", sleeps.append)
    shortcuts.install(LAUNCHER, desktop="kde")
    assert len(sleeps) == 3 and len(fake.keys) == 2


def test_kde_exec_line_quotes_for_desktop_files():
    assert kde._exec_line("/usr/bin/floatnote", "show") == "/usr/bin/floatnote show"
    assert kde._exec_line("'/usr/bin/python3' -m floatnote", "show") == "/usr/bin/python3 -m floatnote show"
    assert kde._exec_line("'/a b/$x'", "show") == '"/a b/\\$x" show'


# ---- sync: never both at once -------------------------------------------------

def test_sync_with_keyboard_removes_desktop_shortcuts(monkeypatch):
    removed = []
    monkeypatch.setattr(shortcuts, "remove", lambda desktop=None: removed.append(desktop) or 2)
    monkeypatch.setattr(shortcuts, "install", lambda *a, **k: pytest.fail("must not install"))
    assert shortcuts.sync(True, "ctrl+super+alt+n", "ctrl+super+alt+p") == "keyboard"
    assert removed == [None]  # from every desktop


def test_sync_without_keyboard_installs_for_this_desktop(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    installed = []
    monkeypatch.setattr(shortcuts, "install", lambda launcher, t, n, desktop: installed.append((t, desktop)))
    assert shortcuts.sync(False, "ctrl+super+alt+n", "ctrl+super+alt+p", "/x") == "desktop"
    assert installed == [("ctrl+super+alt+n", "kde")]


def test_sync_without_keyboard_on_unknown_desktop(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "MATE")
    monkeypatch.setenv("DESKTOP_SESSION", "mate")
    assert shortcuts.sync(False, "ctrl+super+alt+n", "ctrl+super+alt+p", "/x") is None


def test_sync_reports_refused_install(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")

    def refuse(*a, **k):
        raise shortcuts.ShortcutError("taken")

    monkeypatch.setattr(shortcuts, "install", refuse)
    assert shortcuts.sync(False, "ctrl+super+alt+n", "ctrl+super+alt+p", "/x") is None


def test_remove_everywhere_survives_missing_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    def no_tools(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(subprocess, "run", no_tools)
    monkeypatch.setattr(xfce.shutil, "which", lambda name: None)
    assert shortcuts.remove() == 0
