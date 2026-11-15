"""FloatNote's open/close and next-project shortcuts.

Normally FloatNote reads these keys straight from the keyboard (hotkeys.py),
which works on every desktop. Without keyboard access (the user isn't in the
'input' group) it falls back to the desktop's own shortcut settings:

  GNOME     gsettings media-keys custom keybindings   (gnome.py)
  Cinnamon  gsettings org.cinnamon.desktop.keybindings  (cinnamon.py)
  KDE       kglobalaccel over D-Bus + .desktop files    (kde.py)
  XFCE      xfconf xfce4-keyboard-shortcuts             (xfce.py)

Never both at once, or every press would fire twice: see sync().
"""

import logging
import os
import re
import shlex
import shutil
import subprocess
import sys

log = logging.getLogger("floatnote")

# (command, name shown in the desktop's settings, default key)
SHORTCUTS = [  # default keys; the real ones come from config (toggle_keys, next_project_keys)
    ("show", "FloatNote: open/close", "ctrl+super+alt+n"),
    ("next-project", "FloatNote: next project", "ctrl+super+alt+p"),
]

DESKTOPS = ("gnome", "kde", "cinnamon", "xfce")


class ShortcutError(Exception):
    """The desktop refused a shortcut (e.g. the keys are already taken)."""


def detect_desktop(environ: dict[str, str] | None = None) -> str | None:
    """'gnome', 'kde', 'cinnamon', 'xfce' or None (unknown / unsupported)."""
    env = os.environ if environ is None else environ
    names = [n.strip().lower() for n in env.get("XDG_CURRENT_DESKTOP", "").split(":") if n.strip()]
    session = env.get("DESKTOP_SESSION", "").lower()
    for desktop, aliases in (("kde", {"kde", "plasma"}), ("cinnamon", {"x-cinnamon", "cinnamon"}),
                             ("xfce", {"xfce", "xfce4"}),
                             ("gnome", {"gnome", "gnome-classic", "gnome-flashback", "unity", "budgie"})):
        if aliases & set(names):
            return desktop
    for desktop, hint in (("kde", "plasma"), ("cinnamon", "cinnamon"), ("xfce", "xfce"), ("gnome", "gnome")):
        if hint in session:
            return desktop
    return None


def backend(desktop: str):
    """The module that handles shortcuts for this desktop."""
    from . import cinnamon, gnome, kde, xfce

    return {"gnome": gnome, "kde": kde, "cinnamon": cinnamon, "xfce": xfce}[desktop]


def default_launcher() -> str:
    """Command the desktop should run for FloatNote (already shell-quoted)."""
    installed = os.path.expanduser("~/.local/bin/floatnote")
    if os.path.exists(installed):
        return shlex.quote(installed)
    found = shutil.which("floatnote")
    return shlex.quote(found) if found else f"{shlex.quote(sys.executable)} -m floatnote"


def wanted(toggle: str | None = None, next_project: str | None = None) -> list[tuple[str, str, str]]:
    """[(command, name, keys)] with the configured keys, e.g. ('show', '…', 'ctrl+super+alt+n')."""
    chosen = {"show": toggle, "next-project": next_project}
    return [(command, name, chosen.get(command) or key) for command, name, key in SHORTCUTS]


def is_ours(command: str) -> bool:
    """Is this a command FloatNote's shortcuts run? ('/usr/bin/floatnote show', …)"""
    return re.search(r"floatnote['\"]? (show|next-project)$", command.strip()) is not None


def install(launcher: str, toggle: str | None = None, next_project: str | None = None,
            desktop: str | None = None) -> list[str]:
    """Register the shortcuts with the desktop. `launcher` is a shell-quoted
    command prefix (see default_launcher). Keys look like 'ctrl+super+alt+n'.
    Returns human-readable lines describing them."""
    from ..hotkeys import pretty_combo

    desktop = desktop or detect_desktop()
    if desktop is None:
        raise ShortcutError("this desktop isn't supported (GNOME, KDE, Cinnamon or XFCE)")
    items = wanted(toggle, next_project)
    backend(desktop).install(launcher, items)
    return [f"{pretty_combo(keys):<16} {name.removeprefix('FloatNote: ')}" for _, name, keys in items]


def remove(desktop: str | None = None) -> int:
    """Remove FloatNote's desktop shortcuts. Without `desktop`: from every desktop
    whose settings exist here (also cleans up after switching desktops)."""
    total = 0
    for name in [desktop] if desktop else DESKTOPS:
        try:
            total += backend(name).remove()
        except (subprocess.CalledProcessError, OSError, ShortcutError) as e:
            log.debug("removing %s shortcuts failed: %s", name, e)
    return total


def installed(desktop: str | None = None) -> bool:
    desktop = desktop or detect_desktop()
    if desktop is None:
        return False
    try:
        return backend(desktop).installed()
    except (subprocess.CalledProcessError, OSError, ShortcutError):
        return False


def sync(keyboard: bool, toggle: str, next_project: str, launcher: str | None = None) -> str | None:
    """Make sure exactly one thing handles open/close and next project.

    keyboard=True: FloatNote reads the keys itself, so remove any desktop
    shortcuts (also the GNOME ones from FloatNote 1.0). Returns "keyboard".
    keyboard=False: register them with the desktop. Returns "desktop", or None
    when that isn't possible (unknown desktop or it refused)."""
    if keyboard:
        if removed := remove():
            log.info("removed %d desktop shortcut(s): FloatNote reads the keys itself now", removed)
        return "keyboard"
    desktop = detect_desktop()
    if desktop is None:
        log.warning("no keyboard access and unknown desktop: open/close and next project have no shortcut")
        return None
    try:
        install(launcher or default_launcher(), toggle, next_project, desktop)
    except (subprocess.CalledProcessError, OSError, ShortcutError) as e:
        log.warning("could not set up %s shortcuts: %s", desktop, e)
        return None
    log.info("open/close and next project registered with %s", desktop)
    return "desktop"


def pretty_key(key: str) -> str:
    """'<Control><Super>Up' -> 'Ctrl+Super+Up'."""
    mods = {"Control": "Ctrl", "Primary": "Ctrl", "Super": "Super", "Alt": "Alt", "Shift": "Shift"}
    parts = [mods.get(m, m) for m in re.findall(r"<(\w+)>", key)]
    rest = re.sub(r"<\w+>", "", key)
    return "+".join([*parts, rest.upper() if len(rest) == 1 else rest])
