"""Small helpers around the gsettings command (GNOME and Cinnamon)."""

import ast
import subprocess


def run(*args: str) -> str:
    r = subprocess.run(["gsettings", *args], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def reset(schema: str, key: str) -> None:
    subprocess.run(["gsettings", "reset", schema, key], capture_output=True)


def get_list(schema: str, key: str) -> list[str]:
    """Read a string-array setting: "@as []" or "['a', 'b']"."""
    raw = run("get", schema, key)
    if raw.startswith("@as"):
        raw = raw[3:].strip()
    return list(ast.literal_eval(raw))


def set_list(schema: str, key: str, items: list[str]) -> None:
    run("set", schema, key, str(items))
