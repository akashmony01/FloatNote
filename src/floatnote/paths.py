"""Where FloatNote keeps its files (XDG base directories)."""

import os
from pathlib import Path


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "floatnote"


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "floatnote"


def config_file() -> Path:
    return config_dir() / "config.toml"


def db_file() -> Path:
    return data_dir() / "floatnote.db"


def todo_export_file() -> Path:
    return data_dir() / "todo.md"


def old_ideas_export_file() -> Path:
    """Where FloatNote before 1.3 wrote the ideas list (removed on upgrade)."""
    return data_dir() / "ideas.md"


def queue_dir() -> Path:
    """Recordings waiting to be transcribed (so none is lost on a crash or restart)."""
    return data_dir() / "queue"


def recordings_dir() -> Path:
    return data_dir() / "recordings"


def ui_state_file() -> Path:
    return data_dir() / "ui.json"


def log_file() -> Path:
    return data_dir() / "floatnote.log"


def socket_file() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "floatnote.sock"
    return _private_tmp_dir() / "floatnote.sock"


def icon_dir() -> Path:
    """Private folder for generated panel icons (the project badge, see tray.py)."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    path = Path(runtime) / "floatnote-icons" if runtime else _private_tmp_dir() / "icons"
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def _private_tmp_dir() -> Path:
    """Fallback when XDG_RUNTIME_DIR is unset: a /tmp folder only we can use.

    Refuses a folder someone else created (or a symlink), so another user
    can't plant a fake FloatNote socket.
    """
    import stat

    path = Path(f"/tmp/floatnote-{os.getuid()}")
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise RuntimeError(f"{path} is not a private folder owned by you; refusing to use it")
    return path


def make_private() -> None:
    """New files only readable by you, and FloatNote's folders closed to others."""
    os.umask(0o077)
    for folder in (data_dir(), config_dir()):
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)
