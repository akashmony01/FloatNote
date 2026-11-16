"""FloatNote: hotkey voice notes for Linux."""

import os

# numpy's bundled OpenBLAS must not start its own thread pool. Next to
# ctranslate2's OpenMP threads it could hang for good: a transcription stuck at
# "Transcribing…" in the spectrogram step (OpenBLAS 0.3.34, Fedora 45), with
# every later note queued behind it. FloatNote's numpy work is tiny; the speech
# model runs in ctranslate2's own threads, which this doesn't affect.
# Set before anything imports numpy (this file runs first).
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

__version__ = "1.3.0"
