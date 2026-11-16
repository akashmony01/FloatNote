import wave

import numpy as np
import pytest

from floatnote import transcriber
from floatnote.recorder import save_wav


def test_read_wav_round_trip(tmp_path):
    audio = np.sin(np.linspace(0, 100, 16000)).astype(np.float32) * 0.5
    path = tmp_path / "note.wav"
    save_wav(path, audio)
    back = transcriber.read_wav(str(path))
    assert back.dtype == np.float32 and len(back) == 16000
    assert np.abs(back - audio).max() < 1e-3


def test_read_wav_resamples_and_mixes_down(tmp_path):
    path = tmp_path / "stereo.wav"
    frames = np.zeros((22050, 2), dtype=np.int16)
    frames[:, 0] = 16384  # left channel at half volume, right silent
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(frames.tobytes())
    back = transcriber.read_wav(str(path))
    assert abs(len(back) - 16000) <= 1  # one second at 16 kHz
    assert np.allclose(back, 0.25, atol=1e-3)  # mono = average of both channels


def test_read_wav_rejects_other_sample_sizes(tmp_path):
    path = tmp_path / "8bit.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(16000)
        w.writeframes(b"\x80" * 100)
    with pytest.raises(ValueError):
        transcriber.read_wav(str(path))


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kw):
        self.calls.append((audio, kw))

        class Info:
            duration = len(audio) / 16000

        class Segment:
            text = " hello "

        return [Segment()], Info()


@pytest.mark.parametrize("vad", [True, False])
def test_silence_filter_only_with_onnxruntime(monkeypatch, tmp_path, vad):
    monkeypatch.setattr(transcriber, "has_vad", lambda: vad)
    t = transcriber.Transcriber.__new__(transcriber.Transcriber)
    t.beam_size, t.vad, t.prompt, t.replacements = 1, transcriber.has_vad(), None, {}
    t._model, t._lock = FakeModel(), __import__("threading").Lock()
    path = tmp_path / "x.wav"
    save_wav(path, np.zeros(8000, dtype=np.float32))
    result = t.transcribe(str(path))  # a file goes through read_wav, never through PyAV
    audio, kw = t._model.calls[0]
    assert isinstance(audio, np.ndarray) and kw["vad_filter"] is vad
    assert result.text == "hello" and result.audio_seconds == 0.5
