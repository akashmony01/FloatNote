"""Undo environment leaks from snap-packaged apps (e.g. the VS Code snap).

The VS Code snap sets GTK_PATH, GSETTINGS_SCHEMA_DIR, XDG_DATA_DIRS and others
to its own bundled copies. GTK apps started from its terminal then crash. The
snap saves the original values as <NAME>_VSCODE_SNAP_ORIG, so we restore them.
Must run before `gi` is imported.
"""

import os

_SUFFIX = "_VSCODE_SNAP_ORIG"


def clean_snap_env(environ: dict[str, str] | None = None) -> list[str]:
    """Restore variables overridden by the VS Code snap. Returns the names fixed."""
    env = os.environ if environ is None else environ
    fixed = []
    for key in [k for k in env if k.endswith(_SUFFIX)]:
        name = key[: -len(_SUFFIX)]
        original = env.pop(key)
        if original:
            env[name] = original
        else:
            env.pop(name, None)
        fixed.append(name)
    return sorted(fixed)
