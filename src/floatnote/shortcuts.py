"""Add or remove FloatNote's GNOME custom keyboard shortcuts (via gsettings)."""

import ast
import subprocess

MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
PATH_PREFIX = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/floatnote-"

# (command, name shown in GNOME Settings, key)
# Recording (hold Ctrl+Super / Super+Alt) and copying (Ctrl+Super+Alt) are
# read straight from the keyboard by hotkeys.py; GNOME only needs this one.
SHORTCUTS = [  # default keys; the real ones come from config (toggle_keys, next_project_keys)
    ("show", "FloatNote: open/close", "<Control><Super><Alt>n"),
    ("next-project", "FloatNote: next project", "<Control><Super><Alt>p"),
]


def _gsettings(*args: str) -> str:
    r = subprocess.run(["gsettings", *args], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _current_paths() -> list[str]:
    raw = _gsettings("get", MEDIA_KEYS, "custom-keybindings")
    if raw.startswith("@as"):
        raw = raw[3:].strip()
    return list(ast.literal_eval(raw))


def _set_paths(items: list[str]) -> None:
    _gsettings("set", MEDIA_KEYS, "custom-keybindings", str(items))


def _schema(path: str) -> str:
    return f"{MEDIA_KEYS}.custom-keybinding:{path}"


def default_launcher() -> str:
    """Command GNOME should run for FloatNote (already shell-quoted)."""
    import os
    import shlex
    import shutil
    import sys

    installed = os.path.expanduser("~/.local/bin/floatnote")
    if os.path.exists(installed):
        return shlex.quote(installed)
    found = shutil.which("floatnote")
    return shlex.quote(found) if found else f"{shlex.quote(sys.executable)} -m floatnote"


def install(launcher: str, toggle: str | None = None, next_project: str | None = None) -> list[str]:
    """Create/update the shortcuts. `launcher` is a shell-quoted command prefix
    (see default_launcher). Keys look like 'ctrl+super+alt+n'.
    Returns human-readable lines describing them."""
    chosen = {"show": toggle, "next-project": next_project}
    wanted = {f"{PATH_PREFIX}{command}/" for command, _, _ in SHORTCUTS}
    paths = []
    for path in _current_paths():  # drop FloatNote shortcuts from older versions
        if path.startswith(PATH_PREFIX) and path not in wanted:
            for key in ("name", "command", "binding"):
                subprocess.run(["gsettings", "reset", _schema(path), key], capture_output=True)
        else:
            paths.append(path)
    lines = []
    for command, name, key in SHORTCUTS:
        if chosen.get(command):
            from .hotkeys import to_accelerator

            key = to_accelerator(chosen[command])
        path = f"{PATH_PREFIX}{command}/"
        _gsettings("set", _schema(path), "name", name)
        _gsettings("set", _schema(path), "command", f"{launcher} {command}")
        _gsettings("set", _schema(path), "binding", key)
        if path not in paths:
            paths.append(path)
        lines.append(f"{pretty_key(key):<16} {name.removeprefix('FloatNote: ')}")
    _set_paths(paths)
    return lines


def pretty_key(key: str) -> str:
    """'<Control><Super>Up' -> 'Ctrl+Super+Up'."""
    import re

    mods = {"Control": "Ctrl", "Primary": "Ctrl", "Super": "Super", "Alt": "Alt", "Shift": "Shift"}
    parts = [mods.get(m, m) for m in re.findall(r"<(\w+)>", key)]
    rest = re.sub(r"<\w+>", "", key)
    return "+".join([*parts, rest.upper() if len(rest) == 1 else rest])


def remove() -> int:
    paths = _current_paths()
    ours = [p for p in paths if p.startswith(PATH_PREFIX)]
    for path in ours:
        for key in ("name", "command", "binding"):
            subprocess.run(["gsettings", "reset", _schema(path), key], capture_output=True)
    _set_paths([p for p in paths if not p.startswith(PATH_PREFIX)])
    return len(ours)


def installed() -> bool:
    """Are FloatNote's GNOME shortcuts set up for this user?"""
    try:
        return any(path.startswith(PATH_PREFIX) for path in _current_paths())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError, SyntaxError):
        return True  # can't tell (no gsettings): don't try to set them up


def ensure_installed(toggle: str, next_project: str) -> bool:
    """First run (e.g. after installing the .deb): set up the shortcuts once.
    Returns True if they were created now."""
    if installed():
        return False
    install(default_launcher(), toggle, next_project)
    return True
