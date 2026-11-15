"""GNOME (also Ubuntu, Budgie, Unity): custom keybindings in gsettings media-keys."""

from . import _gsettings as gs

MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
PATH_PREFIX = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/floatnote-"


def _schema(path: str) -> str:
    return f"{MEDIA_KEYS}.custom-keybinding:{path}"


def _current_paths() -> list[str]:
    return gs.get_list(MEDIA_KEYS, "custom-keybindings")


def _clear(path: str) -> None:
    for key in ("name", "command", "binding"):
        gs.reset(_schema(path), key)


def install(launcher: str, items: list[tuple[str, str, str]]) -> None:
    from ..hotkeys import to_accelerator

    wanted = {f"{PATH_PREFIX}{command}/" for command, _, _ in items}
    paths = []
    for path in _current_paths():  # drop FloatNote shortcuts from older versions
        if path.startswith(PATH_PREFIX) and path not in wanted:
            _clear(path)
        else:
            paths.append(path)
    for command, name, keys in items:
        path = f"{PATH_PREFIX}{command}/"
        gs.run("set", _schema(path), "name", name)
        gs.run("set", _schema(path), "command", f"{launcher} {command}")
        gs.run("set", _schema(path), "binding", to_accelerator(keys))
        if path not in paths:
            paths.append(path)
    gs.set_list(MEDIA_KEYS, "custom-keybindings", paths)


def remove() -> int:
    paths = _current_paths()  # raises without GNOME's schema: nothing to remove
    ours = [p for p in paths if p.startswith(PATH_PREFIX)]
    if not ours:
        return 0
    for path in ours:
        _clear(path)
    gs.set_list(MEDIA_KEYS, "custom-keybindings", [p for p in paths if not p.startswith(PATH_PREFIX)])
    return len(ours)


def installed() -> bool:
    return any(path.startswith(PATH_PREFIX) for path in _current_paths())
