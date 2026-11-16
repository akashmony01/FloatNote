"""`floatnote doctor`: check that this machine has what FloatNote needs."""

import ctypes.util
import os
import platform
import shutil
import subprocess
import sys

from . import client, config, distro, paths

OK, WARN, FAIL = "ok", "warn", "FAIL"


def _check_gtk3() -> tuple[str, str]:
    # Run in a child process with the snap leak cleaned, like the daemon will.
    code = (
        "from floatnote.env import clean_snap_env; clean_snap_env();"
        "import gi; gi.require_version('Gtk', '3.0');"
        "from gi.repository import Gtk; print(Gtk.get_major_version(), Gtk.get_minor_version())"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        return OK, "GTK " + r.stdout.strip().replace(" ", ".")
    return FAIL, (r.stderr.strip().splitlines() or ["unknown error"])[-1]


def _check_audio() -> tuple[str, str]:
    if not ctypes.util.find_library("portaudio"):
        return FAIL, f"PortAudio missing: {distro.install_hint('portaudio')}"
    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="input")
        return OK, f"default mic: {dev['name']}"
    except Exception as e:  # noqa: BLE001 - report anything
        return FAIL, f"sounddevice: {e}"


def _check_whisper() -> tuple[str, str]:
    try:
        import faster_whisper

        from .transcriber import has_vad

        vad = "" if has_vad() else (f" (silence filter off: onnxruntime isn't available for "
                                    f"Python {platform.python_version()} yet)")
        return OK, f"faster-whisper {faster_whisper.__version__}{vad}"
    except Exception as e:  # noqa: BLE001
        return FAIL, f"faster-whisper not importable: {e}"


def _check_model() -> tuple[str, str]:
    from . import models

    try:
        name = config.load().model
    except Exception:  # noqa: BLE001
        return WARN, "config error"
    found = models.where(name)
    if found:
        return OK, f"{name} in {found}"
    return WARN, f"{name} not downloaded yet: run  floatnote download-models  (needs internet)"


def _check_hold_keys() -> tuple[str, str]:
    import glob

    try:
        cfg = config.load()
    except Exception:  # noqa: BLE001
        return WARN, "config error"
    if not cfg.hold_to_record:
        return OK, "off in config"
    combos = f"hold {cfg.hold_bug} = bug"
    if cfg.todo_enabled:
        combos += f", {cfg.hold_todo} = to-do"
    if cfg.dictation_enabled:
        combos += f", {cfg.hold_dictation} = dictation"
    try:  # the running app knows best whether it can read the keyboard
        status = client.send("status")
        if status.get("hold_on"):
            return OK, combos
        if status.get("hold_error"):
            return WARN, status["hold_error"]
    except Exception:  # noqa: BLE001 - daemon not running: check permissions here
        pass
    readable = [p for p in glob.glob("/dev/input/event*") if os.access(p, os.R_OK)]
    if readable:
        return OK, combos
    import grp
    import pwd

    try:
        if pwd.getpwuid(os.getuid()).pw_name in grp.getgrnam("input").gr_mem:
            return OK, combos + " (FloatNote applies the 'input' group itself)"
    except KeyError:
        pass
    return WARN, f"off: run  {distro.input_group_hint()}  then restart FloatNote"


def _check_shortcuts() -> tuple[str, str]:
    """Who handles open/close and next project (see shortcuts.sync)."""
    from . import shortcuts
    from .hotkeys import keyboard_readable

    try:
        method = client.send("status").get("shortcut_method", "?")
    except Exception:  # noqa: BLE001 - daemon not running: work it out here
        method = "keyboard" if keyboard_readable() else ("desktop" if shortcuts.installed() else None)
    if method == "keyboard":
        return OK, "read from the keyboard (any desktop)"
    if method == "desktop":
        return OK, f"registered with {shortcuts.detect_desktop() or 'the desktop'} (no keyboard access)"
    if shortcuts.detect_desktop() is None:
        return WARN, "none: turn on keyboard access (this desktop isn't supported for desktop shortcuts)"
    return WARN, "none yet: start FloatNote, or run  floatnote setup-shortcuts"


def _desktop() -> tuple[str, str]:
    from . import shortcuts

    session = os.environ.get("XDG_SESSION_TYPE", "?")
    raw = os.environ.get("XDG_CURRENT_DESKTOP", "?")
    desktop = shortcuts.detect_desktop()
    if desktop is None:
        return WARN, f"{raw} / {session} (not tested; GNOME, KDE, Cinnamon and XFCE are supported)"
    names = {"gnome": "GNOME", "kde": "KDE Plasma", "cinnamon": "Cinnamon", "xfce": "XFCE"}
    return OK, f"{names[desktop]} / {session}"


def _check_clipboard() -> tuple[str, str]:
    session = os.environ.get("XDG_SESSION_TYPE", "")
    tool = "wl-copy" if session == "wayland" else "xclip"
    if shutil.which(tool):
        return OK, tool
    fallback = shutil.which("xclip") or shutil.which("wl-copy")
    if fallback:
        return WARN, f"{tool} missing, will use {os.path.basename(fallback)}"
    return FAIL, f"no clipboard tool: {distro.install_hint('clipboard')}"


def _check_config() -> tuple[str, str]:
    try:
        cfg = config.load()
        return OK, f"{paths.config_file()} (model {cfg.model})"
    except Exception as e:  # noqa: BLE001
        return FAIL, str(e)


def run() -> int:
    snap_leak = [k for k in os.environ if k.endswith("_VSCODE_SNAP_ORIG")]
    checks = [
        ("Python", (OK, platform.python_version()) if sys.version_info >= (3, 11) else (FAIL, "need 3.11+")),
        ("Desktop", _desktop()),
        ("Snap env", (WARN, "VS Code snap env detected; FloatNote will clean it") if snap_leak else (OK, "clean")),
        ("GTK3", _check_gtk3()),
        ("Audio", _check_audio()),
        ("Whisper", _check_whisper()),
        ("Model", _check_model()),
        ("Hold keys", _check_hold_keys()),
        ("Open/close", _check_shortcuts()),
        ("Clipboard", _check_clipboard()),
        ("Config", _check_config()),
        ("Data dir", (OK, str(paths.data_dir()))),
        ("Daemon", (OK, "running") if client.is_running() else (WARN, "not running")),
    ]
    width = max(len(name) for name, _ in checks)
    for name, (status, detail) in checks:
        print(f"  [{status:^4}] {name:<{width}}  {detail}")
    failed = sum(1 for _, (s, _) in checks if s == FAIL)
    print(f"\n{failed} problem(s) found." if failed else "\nAll required checks passed.")
    return 1 if failed else 0
