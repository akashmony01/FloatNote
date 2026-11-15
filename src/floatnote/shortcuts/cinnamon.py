"""Cinnamon (Linux Mint): custom keybindings in gsettings org.cinnamon.desktop.keybindings.

Cinnamon lists custom shortcuts by id in `custom-list`; each id has its own
settings at CUSTOM_PATH/<id>/ with `binding` as a list of accelerators. It only
re-reads them when `custom-list` changes, so (like Cinnamon's own settings) we
toggle a '__dummy__' entry to make it notice a changed binding.
"""

from . import _gsettings as gs

KEYBINDINGS = "org.cinnamon.desktop.keybindings"
ITEM_SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding"
CUSTOM_PATH = "/org/cinnamon/desktop/keybindings/custom-keybindings/"
ID_PREFIX = "floatnote-"
DUMMY = "__dummy__"


def _schema(item_id: str) -> str:
    return f"{ITEM_SCHEMA}:{CUSTOM_PATH}{item_id}/"


def _ids() -> list[str]:
    return gs.get_list(KEYBINDINGS, "custom-list")


def _save(ids: list[str]) -> None:
    ids = [i for i in ids if i != DUMMY] if DUMMY in ids else [*ids, DUMMY]
    gs.set_list(KEYBINDINGS, "custom-list", ids)


def _clear(item_id: str) -> None:
    for key in ("name", "command", "binding"):
        gs.reset(_schema(item_id), key)


def install(launcher: str, items: list[tuple[str, str, str]]) -> None:
    from ..hotkeys import to_accelerator

    wanted = {f"{ID_PREFIX}{command}" for command, _, _ in items}
    ids = []
    for item_id in _ids():
        if item_id.startswith(ID_PREFIX) and item_id not in wanted:
            _clear(item_id)
        else:
            ids.append(item_id)
    for command, name, keys in items:
        item_id = f"{ID_PREFIX}{command}"
        gs.run("set", _schema(item_id), "name", name)
        gs.run("set", _schema(item_id), "command", f"{launcher} {command}")
        gs.run("set", _schema(item_id), "binding", str([to_accelerator(keys)]))
        if item_id not in ids:
            ids.append(item_id)
    _save(ids)


def remove() -> int:
    ids = _ids()  # raises without Cinnamon's schema: nothing to remove
    ours = [i for i in ids if i.startswith(ID_PREFIX)]
    if not ours:
        return 0
    for item_id in ours:
        _clear(item_id)
    _save([i for i in ids if not i.startswith(ID_PREFIX)])
    return len(ours)


def installed() -> bool:
    return any(i.startswith(ID_PREFIX) for i in _ids())
