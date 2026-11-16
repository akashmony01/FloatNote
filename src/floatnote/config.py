"""Load ~/.config/floatnote/config.toml, creating it with defaults on first run."""

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from . import paths

DEFAULT_TOML = """\
# FloatNote settings. Restart the daemon after editing.

# Speech model. Change it with: floatnote model <name>
#   base.en   fastest (~0.5 s per 10 s of speech), least accurate, ~350 MB RAM
#   small.en  more accurate (~1.3 s per 10 s), ~800 MB RAM
model = "small.en"
compute_type = "int8"
# 1 = fastest; 5 = a bit more accurate, slower.
beam_size = 5

# First line of the text copied by "Copy all".
copy_intro = "I tested the app and found these issues. Please fix them:"

# Keep this many recent recordings (audio + transcript) on disk so models can
# be compared on your real voice with `floatnote bench run`. 0 = keep none.
keep_recordings = 0

# Hold-to-record: hold these keys to record, let go to stop.
# Needs your user in the "input" group (install.sh offers to do it).
# hold_dictation: the text is copied to the clipboard, ready to paste anywhere.
# copy_keys: press together and let go to copy all bugs.
# toggle_keys: open/close FloatNote; next_project_keys: switch project.
# Easiest to change from the Settings screen (gear button).
hold_to_record = true
hold_bug = "ctrl+super"
hold_todo = "super+alt"
hold_dictation = "ctrl+alt"
copy_keys = "ctrl+super+alt"
toggle_keys = "ctrl+super+alt+n"
next_project_keys = "ctrl+super+alt+p"

# Recording stops by itself after this many seconds.
max_record_seconds = 180

# Optional parts (bugs are always on).
todo_enabled = true
dictation_enabled = false

sounds = true
# Show the active project's name next to the mic in the panel (where the panel supports it).
show_project_in_bar = true
show_panel_on_record = false
home_on_login = true

# Words Whisper should spell correctly (product names, tech terms).
vocabulary = ["Claude Code", "Tailwind", "Supabase", "navbar", "useEffect", "API", "404"]

# Fix words Whisper keeps getting wrong: "what it writes" = "what you said".
# Add one with: floatnote fix "white tail" Wagtail
replacements = {}
"""


@dataclass
class Config:
    model: str = "small.en"
    compute_type: str = "int8"
    beam_size: int = 5
    copy_intro: str = "I tested the app and found these issues. Please fix them:"
    keep_recordings: int = 0
    hold_to_record: bool = True
    hold_bug: str = "ctrl+super"
    hold_todo: str = "super+alt"
    hold_dictation: str = "ctrl+alt"
    copy_keys: str = "ctrl+super+alt"
    toggle_keys: str = "ctrl+super+alt+n"
    next_project_keys: str = "ctrl+super+alt+p"
    max_record_seconds: int = 180
    todo_enabled: bool = True
    dictation_enabled: bool = False
    sounds: bool = True
    show_project_in_bar: bool = True
    show_panel_on_record: bool = False
    home_on_login: bool = True
    vocabulary: list[str] = field(default_factory=list)
    replacements: dict[str, str] = field(default_factory=dict)


def load(path: Path | None = None, create: bool = True) -> Config:
    path = path or paths.config_file()
    if not path.exists():
        if not create:
            return Config()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_TOML)
    if create:
        _rename_old_settings(path)
    with path.open("rb") as f:
        raw = tomllib.load(f)
    for old, new in RENAMED.items():  # read-only load of an old file
        if old in raw:
            raw.setdefault(new, raw.pop(old))
    known = {f.name for f in fields(Config)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"Unknown setting(s) in {path}: {', '.join(sorted(unknown))}")
    cfg = Config(**raw)
    if cfg.model not in MODELS:  # only download models we know about
        raise ValueError(f"Unknown model {cfg.model!r} in {path}. Choose one of: {', '.join(MODELS)}")
    return cfg


# Settings that were renamed: old name -> new name.
RENAMED = {"paste_intro": "copy_intro", "hold_idea": "hold_todo"}


def _rename_old_settings(path: Path) -> None:
    """Rewrite old setting names in config.toml (1.3: ideas became to-dos)."""
    import re

    text = path.read_text()
    new = text
    for old, name in RENAMED.items():
        if re.search(rf"^{name}\s*=", new, re.M):
            continue  # the new one is already there; the old line is ignored on load
        new = re.sub(rf"^{old}(\s*=)", rf"{name}\1", new, flags=re.M)
    if new != text:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(new)
        tmp.replace(path)


MODELS = {
    "base.en": "fastest, least accurate (~350 MB RAM)",
    "small.en": "more accurate, ~2.5x slower (~800 MB RAM)",
    "medium.en": "most accurate, slow on CPU (~3-5 s per 10 s, ~1.8 GB RAM)",
    "distil-small.en": "between base and small; dropped words in tests",
}


def set_values(values: dict, path: Path | None = None) -> None:
    """Change settings in config.toml, keeping comments and layout."""
    path = path or paths.config_file()
    load(path)  # creates the file if needed
    lines = path.read_text().splitlines()
    for key, value in values.items():
        new = f"{key} = {_toml(value)}"
        span = _find_setting(lines, key)
        if span is None:
            lines.append(new)
        else:
            lines[span[0]:span[1]] = [new]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(path)  # atomic: a crash never leaves a half-written config


def _find_setting(lines: list[str], key: str) -> tuple[int, int] | None:
    """Line range [start, end) of `key = value`, including a value that spans
    several lines (a hand-written multi-line list)."""
    import re

    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            depth, end = 0, i
            for j in range(i, len(lines)):
                depth += _bracket_depth(lines[j] if j > i else line.split("=", 1)[1])
                end = j + 1
                if depth <= 0:
                    break
            return i, end
    return None


def _bracket_depth(text: str) -> int:
    """Net [ and { opened on a line, ignoring brackets inside strings and comments."""
    depth, quote, escaped = 0, None, False
    for ch in text:
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            break
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
    return depth


def _toml(value) -> str:
    """Format a value as a one-line TOML value."""
    import json

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # TOML rejects \ud83d-style escapes
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{ " + ", ".join(f"{_toml(k)} = {_toml(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"can't write {value!r} to config")
