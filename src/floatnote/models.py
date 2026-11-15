"""Where the speech models live, and downloading them.

Installing FloatNote downloads both English models up front, so they're ready
on first start:
  .deb / .rpm   /usr/lib/floatnote/models/<name>        (shared, removed on uninstall)
  install.sh    ~/.local/share/floatnote/models/<name>

FloatNote looks there first, then in the Hugging Face cache (FloatNote 1.0
downloaded models there). A model that is in neither is downloaded into the
user folder on first use.
"""

import os
from pathlib import Path

from . import paths

DEFAULT_MODELS = ["small.en", "base.en"]  # the two offered in Settings > Speech
SYSTEM_DIR = Path("/usr/lib/floatnote/models")


def system_dir() -> Path:
    return Path(os.environ.get("FLOATNOTE_SYSTEM_MODELS", SYSTEM_DIR))


def user_dir() -> Path:
    return paths.data_dir() / "models"


COMPLETE = ".floatnote-complete"  # written after a download finished


def is_complete(folder: Path) -> bool:
    return (folder / COMPLETE).is_file() and (folder / "model.bin").is_file()


def local_path(name: str) -> Path | None:
    """Folder of an installed model, or None."""
    for base in (system_dir(), user_dir()):
        if is_complete(base / name):
            return base / name
    return None


def _in_hf_cache(name: str) -> str | None:
    try:
        from faster_whisper.utils import download_model

        return download_model(name, local_files_only=True)
    except Exception:  # noqa: BLE001 - not cached (or faster-whisper missing)
        return None


def is_downloaded(name: str) -> bool:
    return local_path(name) is not None or _in_hf_cache(name) is not None


def where(name: str) -> str | None:
    """Human-readable location of a model, or None if it isn't downloaded."""
    found = local_path(name)
    if found:
        return str(found)
    return "Hugging Face cache" if _in_hf_cache(name) else None


def resolve(name: str) -> str:
    """What to hand WhisperModel: a local folder, downloading the model into the
    user folder first if it's nowhere yet."""
    found = local_path(name) or _in_hf_cache(name)
    if found:
        return str(found)
    return str(download(name, user_dir()))


def download(name: str, dest: Path) -> Path:
    """Download one model into dest/<name> (with a progress bar on a terminal)."""
    from faster_whisper.utils import download_model

    target = dest / name
    target.mkdir(parents=True, exist_ok=True)
    download_model(name, output_dir=str(target))
    (target / COMPLETE).write_text(name + "\n")
    return target
