"""Speech to text with faster-whisper. The model is loaded once and reused."""

import os
import threading
import time
from dataclasses import dataclass

import numpy as np


@dataclass
class Result:
    text: str
    audio_seconds: float
    elapsed_seconds: float


def apply_replacements(text: str, replacements: dict[str, str]) -> str:
    """Replace whole words/phrases, ignoring case: {"white tail": "Wagtail"}."""
    import re

    # Longest first, so "white tail admin" wins over "white tail".
    for wrong in sorted(replacements, key=len, reverse=True):
        pattern = r"(?<![\w-])" + r"\s+".join(map(re.escape, wrong.split())) + r"(?![\w-])"
        text = re.sub(pattern, lambda _m, right=replacements[wrong]: right, text, flags=re.IGNORECASE)
    return text


def build_prompt(vocabulary: list[str]) -> str | None:
    """Hint prompt that nudges Whisper to spell these words correctly."""
    if not vocabulary:
        return None
    return "Glossary: " + ", ".join(vocabulary) + "."


class Transcriber:
    def __init__(self, model: str = "base.en", compute_type: str = "int8",
                 beam_size: int = 1, vocabulary: list[str] | None = None,
                 replacements: dict[str, str] | None = None):
        from faster_whisper import WhisperModel

        self.model_name = model
        self.beam_size = beam_size
        self.set_words(vocabulary or [], replacements or {})
        # Physical cores only; hyperthreads don't help CTranslate2 much.
        threads = max(1, (os.cpu_count() or 2) // 2)
        from .models import resolve

        self._model = WhisperModel(resolve(model), device="cpu", compute_type=compute_type,
                                   cpu_threads=threads)
        self._lock = threading.Lock()  # one transcription at a time

    def set_words(self, vocabulary: list[str], replacements: dict[str, str]) -> None:
        """Change hint words and fixes; takes effect from the next note."""
        self.replacements = dict(replacements)
        # The right spellings also go in the hint prompt.
        words = list(dict.fromkeys([*vocabulary, *self.replacements.values()]))
        self.prompt = build_prompt(words)

    def transcribe(self, audio: np.ndarray | str, sample_rate: int = 16000) -> Result:
        start = time.perf_counter()
        with self._lock:
            segments, info = self._model.transcribe(
                audio,
                language="en",
                beam_size=self.beam_size,
                vad_filter=True,
                initial_prompt=self.prompt,
                condition_on_previous_text=False,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
        text = apply_replacements(text, self.replacements)
        return Result(text=text, audio_seconds=info.duration,
                      elapsed_seconds=time.perf_counter() - start)
