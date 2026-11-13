"""Copy text to the desktop clipboard (wl-copy on Wayland, xclip on X11)."""

import os
import shutil
import subprocess


class ClipboardError(Exception):
    pass


def _commands() -> list[list[str]]:
    wl = ["wl-copy"]
    x = ["xclip", "-selection", "clipboard"]
    order = [wl, x] if os.environ.get("WAYLAND_DISPLAY") else [x, wl]
    return [c for c in order if shutil.which(c[0])]


def copy(text: str) -> None:
    cmds = _commands()
    if not cmds:
        raise ClipboardError("no clipboard tool found (sudo apt install wl-clipboard xclip)")
    errors = []
    for cmd in cmds:
        try:
            # wl-copy / xclip fork a helper that keeps serving the clipboard,
            # so close their output pipes or run() would wait on that helper.
            subprocess.run(cmd, input=text.encode(), check=True, timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except (subprocess.SubprocessError, OSError) as e:
            errors.append(f"{cmd[0]}: {e}")
    raise ClipboardError("; ".join(errors))
