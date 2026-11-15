"""XFCE: custom commands in the xfce4-keyboard-shortcuts xfconf channel.

Each shortcut is a property /commands/custom/<accelerator> whose value is the
command. xfsettingsd picks up changes straight away.
"""

import shutil
import subprocess

from . import is_ours

CHANNEL = "xfce4-keyboard-shortcuts"
CUSTOM = "/commands/custom/"


def _xfconf(*args: str, check: bool = True) -> str:
    r = subprocess.run(["xfconf-query", "-c", CHANNEL, *args], capture_output=True, text=True, check=check)
    return r.stdout


def _ours() -> list[str]:
    """Properties of FloatNote's shortcuts."""
    if not shutil.which("xfconf-query"):
        return []
    try:
        listing = _xfconf("-l", "-v")
    except subprocess.CalledProcessError:
        return []  # no such channel: XFCE never ran here
    props = []
    for line in listing.splitlines():
        prop, _, value = line.strip().partition(" ")
        if prop.startswith(CUSTOM) and is_ours(value):
            props.append(prop)
    return props


def accelerator(keys: str) -> str:
    """'ctrl+super+alt+n' -> '<Primary><Super><Alt>n' (XFCE writes Ctrl as Primary)."""
    from ..hotkeys import to_accelerator

    return to_accelerator(keys).replace("<Control>", "<Primary>")


def install(launcher: str, items: list[tuple[str, str, str]]) -> None:
    for prop in _ours():
        _xfconf("-r", "-p", prop)
    for command, _name, keys in items:
        _xfconf("-n", "-t", "string", "-p", CUSTOM + accelerator(keys), "-s", f"{launcher} {command}")


def remove() -> int:
    ours = _ours()
    for prop in ours:
        _xfconf("-r", "-p", prop, check=False)
    return len(ours)


def installed() -> bool:
    return bool(_ours())
