"""KDE Plasma: command shortcuts through kglobalaccel.

This is what System Settings > Shortcuts > "Add Command" does: a hidden
.desktop file per command in ~/.local/share/applications, registered with
kglobalaccel as component "<file>.desktop", action "_launch". kglobalaccel then
runs the file's Exec when the keys are pressed, and saves the keys in
kglobalshortcutsrc. Takes effect immediately, no logout.
"""

import os
import subprocess
import time
from pathlib import Path

DEST, OBJECT, IFACE = "org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel"
FILE_PREFIX = "floatnote-"
ACTION = "_launch"
SET_PRESENT = 2  # KGlobalAccel::SetPresent
RETRIES, RETRY_SECONDS = 12, 0.5

# Qt key codes (QKeyCombination as int).
_QT_MODS = {"shift": 0x02000000, "ctrl": 0x04000000, "alt": 0x08000000, "super": 0x10000000}
_QT_KEYS = {"left": 0x01000012, "up": 0x01000013, "right": 0x01000014, "down": 0x01000015, "space": 0x20,
            **{f"f{i}": 0x01000030 + i - 1 for i in range(1, 13)}}


def qt_key(keys: str) -> int:
    """'ctrl+super+alt+n' -> Qt key code (modifier bits | key)."""
    code = 0
    for name in keys.split("+"):
        if name in _QT_MODS:
            code |= _QT_MODS[name]
        elif name in _QT_KEYS:
            code |= _QT_KEYS[name]
        elif len(name) == 1 and name.isalnum():
            code |= ord(name.upper())
        else:
            raise ValueError(f"key {name!r} can't be used in a KDE shortcut")
    return code


def _apps_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "applications"


def _file(command: str) -> Path:
    return _apps_dir() / f"{FILE_PREFIX}{command}.desktop"


def _action_id(command: str, name: str) -> str:
    """GVariant text of kglobalaccel's actionId: [component, action, friendly names]."""
    parts = [f"{FILE_PREFIX}{command}.desktop", ACTION, name, name.removeprefix("FloatNote: ").capitalize()]
    return "[" + ", ".join(_gvariant_str(p) for p in parts) + "]"


def _gvariant_str(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _call(method: str, *args: str) -> str:
    r = subprocess.run(["gdbus", "call", "--session", "--dest", DEST, "--object-path", OBJECT,
                        "--method", f"{IFACE}.{method}", *args], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _exec_line(launcher: str, command: str) -> str:
    """Exec= value. Desktop files quote with double quotes, not shell single quotes."""
    import shlex

    def quote(arg: str) -> str:
        if arg and all(c.isalnum() or c in "/._-+=:@" for c in arg):
            return arg
        return '"' + "".join("\\" + c if c in '"`$\\' else c for c in arg) + '"'

    return " ".join(quote(a) for a in [*shlex.split(launcher), command])


def _owned_by_others(code: int) -> bool:
    """Does another shortcut already use this key?"""
    out = _call("globalShortcutsByKey", f"([{code}, 0, 0, 0],)", "(0,)")  # 0: exact match
    return "[]" not in out and f"{FILE_PREFIX}" not in out


def _desktop_file(launcher: str, command: str, name: str) -> str:
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={name}\n"
            f"Exec={_exec_line(launcher, command)}\n"
            "Icon=audio-input-microphone\n"
            "NoDisplay=true\n"
            "StartupNotify=false\n"
            "X-KDE-GlobalAccel-CommandShortcut=true\n")


def _current_keys(action: str) -> str:
    try:
        return _call("shortcutKeys", action)
    except (subprocess.CalledProcessError, OSError):
        return ""


def install(launcher: str, items: list[tuple[str, str, str]]) -> None:
    """Register the shortcuts. Changes nothing that is already right: every
    rewritten file and every registration makes KDE reload its shortcut
    owners, which KWin 6.8 didn't always survive."""
    from . import ShortcutError

    _apps_dir().mkdir(parents=True, exist_ok=True)
    for command, name, _keys in items:  # all files first: KDE reloads its app list after each
        text = _desktop_file(launcher, command, name)
        path = _file(command)
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
    for command, name, keys in items:
        code = qt_key(keys)
        action = _action_id(command, name)
        if str(code) in _current_keys(action):
            continue  # already registered with these keys
        # While KDE is still reloading after a new .desktop file it refuses
        # shortcuts for a moment (an empty answer); a real clash fails at once.
        for attempt in range(RETRIES):
            _call("doRegister", action)
            got = _call("setShortcutKeys", action, f"[([{code}, 0, 0, 0],)]", str(SET_PRESENT))
            if str(code) in got:  # kglobalaccel hands back what it really set
                break
            if _owned_by_others(code) or attempt == RETRIES - 1:
                from ..hotkeys import pretty_combo

                raise ShortcutError(f"{pretty_combo(keys)} is already used by another KDE shortcut")
            time.sleep(RETRY_SECONDS)


def remove() -> int:
    removed = 0
    for path in sorted(_apps_dir().glob(f"{FILE_PREFIX}*.desktop")):
        try:
            _call("unregister", path.name, ACTION)
        except (subprocess.CalledProcessError, OSError):
            pass  # not running KDE right now: the file is all that's left
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def installed() -> bool:
    return any(_apps_dir().glob(f"{FILE_PREFIX}*.desktop"))
