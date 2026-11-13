"""`floatnote doctor`: check that this machine has what FloatNote needs."""

import ctypes.util
import os
import platform
import shutil
import subprocess
import sys

from . import client, config, paths

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
        return FAIL, "PortAudio missing: sudo apt install libportaudio2"
    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="input")
        return OK, f"default mic: {dev['name']}"
    except Exception as e:  # noqa: BLE001 - report anything
        return FAIL, f"sounddevice: {e}"


def _check_whisper() -> tuple[str, str]:
    try:
        import faster_whisper

        return OK, f"faster-whisper {faster_whisper.__version__}"
    except Exception as e:  # noqa: BLE001
        return FAIL, f"faster-whisper not importable: {e}"


def _check_model() -> tuple[str, str]:
    try:
        from faster_whisper.utils import download_model

        name = config.load().model
        download_model(name, local_files_only=True)
        return OK, f"{name} downloaded"
    except Exception:  # noqa: BLE001
        return WARN, "not downloaded yet (happens on first start, needs internet)"


def _check_hold_keys() -> tuple[str, str]:
    import glob

    try:
        cfg = config.load()
    except Exception:  # noqa: BLE001
        return WARN, "config error"
    if not cfg.hold_to_record:
        return OK, "off in config"
    combos = f"hold {cfg.hold_bug} = bug, {cfg.hold_idea} = idea"
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
    return WARN, "off: run  sudo usermod -aG input $USER  then log out and back in"


def _check_clipboard() -> tuple[str, str]:
    session = os.environ.get("XDG_SESSION_TYPE", "")
    tool = "wl-copy" if session == "wayland" else "xclip"
    if shutil.which(tool):
        return OK, tool
    fallback = shutil.which("xclip") or shutil.which("wl-copy")
    if fallback:
        return WARN, f"{tool} missing, will use {os.path.basename(fallback)}"
    return FAIL, "no clipboard tool: sudo apt install wl-clipboard xclip"


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
        ("Session", (OK if os.environ.get("XDG_SESSION_TYPE") else WARN,
                     f"{os.environ.get('XDG_SESSION_TYPE', '?')} / {os.environ.get('XDG_CURRENT_DESKTOP', '?')}")),
        ("Snap env", (WARN, "VS Code snap env detected; FloatNote will clean it") if snap_leak else (OK, "clean")),
        ("GTK3", _check_gtk3()),
        ("Audio", _check_audio()),
        ("Whisper", _check_whisper()),
        ("Model", _check_model()),
        ("Hold keys", _check_hold_keys()),
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
