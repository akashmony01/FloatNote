"""Short audio cues using the desktop's standard sound theme."""

import shutil
import subprocess
from pathlib import Path

_THEME = Path("/usr/share/sounds/freedesktop/stereo")
CUES = {
    "start": "device-added.oga",
    "stop": "device-removed.oga",
    "cancel": "bell.oga",
    "error": "dialog-error.oga",
    "switch": "message.oga",
}


def _player() -> list[str] | None:
    for cmd in ("pw-play", "paplay", "canberra-gtk-play"):
        if shutil.which(cmd):
            return [cmd, "-f"] if cmd == "canberra-gtk-play" else [cmd]
    return None


class Sounds:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._cmd = _player()

    def play(self, cue: str) -> None:
        if not self.enabled or self._cmd is None:
            return
        path = _THEME / CUES[cue]
        if path.exists():
            # Fire and forget; never block the daemon on audio playback.
            subprocess.Popen([*self._cmd, str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
