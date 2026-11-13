"""Microphone recording into memory (16 kHz mono float32, what Whisper wants)."""

import threading
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


class Recorder:
    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._device_rate = sample_rate
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        import sounddevice as sd  # imported lazily: needs PortAudio

        if self._stream is not None:
            return
        self._chunks = []
        try:
            stream = sd.InputStream(samplerate=self.sample_rate, channels=1,
                                    dtype="float32", callback=self._callback)
            self._device_rate = self.sample_rate
        except sd.PortAudioError:
            # Some mics refuse 16 kHz: record at their own rate, resample on stop.
            rate = int(sd.query_devices(kind="input")["default_samplerate"])
            stream = sd.InputStream(samplerate=rate, channels=1,
                                    dtype="float32", callback=self._callback)
            self._device_rate = rate
        stream.start()
        self._stream = stream

    def _callback(self, indata, frames, time_info, status) -> None:
        with self._lock:
            self._chunks.append(indata[:, 0].copy())

    def stop(self) -> np.ndarray:
        """Stop recording and return the audio (empty array if nothing was recorded)."""
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return resample(np.concatenate(chunks), self._device_rate, self.sample_rate)


def resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear-interpolation resample; plenty for speech recognition."""
    if src_rate == dst_rate or len(audio) == 0:
        return audio
    n = int(round(len(audio) * dst_rate / src_rate))
    x_old = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def save_wav(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
