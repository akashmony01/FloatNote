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


def has_vad() -> bool:
    """Is faster-whisper's silence filter (VAD) available? It needs onnxruntime,
    which isn't built for every Python yet (e.g. 3.15): then notes are
    transcribed without it, which only matters for long silences."""
    import importlib.util

    return importlib.util.find_spec("onnxruntime") is not None


def read_wav(path: str) -> np.ndarray:
    """Load a 16-bit WAV (as FloatNote saves them) as mono float32 at 16 kHz.
    Done here instead of faster-whisper's decoder, which needs a PyAV version
    some Pythons don't have."""
    import wave

    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: only 16-bit WAV files are supported")
        rate, channels = w.getframerate(), w.getnchannels()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != 16000:
        audio = np.interp(np.arange(0, len(audio), rate / 16000), np.arange(len(audio)), audio)
    return audio.astype(np.float32)


class Transcriber:
    def __init__(self, model: str = "base.en", compute_type: str = "int8",
                 beam_size: int = 1, vocabulary: list[str] | None = None,
                 replacements: dict[str, str] | None = None):
        from faster_whisper import WhisperModel

        self.model_name = model
        self.beam_size = beam_size
        self.vad = has_vad()
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
        if isinstance(audio, str):
            audio = read_wav(audio)
        with self._lock:
            segments, info = self._model.transcribe(
                audio,
                language="en",
                beam_size=self.beam_size,
                vad_filter=self.vad,
                initial_prompt=self.prompt,
                condition_on_previous_text=False,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
        text = apply_replacements(text, self.replacements)
        return Result(text=text, audio_seconds=info.duration,
                      elapsed_seconds=time.perf_counter() - start)
