# tests/test_transcriber.py
import queue
import sys
import types
import wave
from pathlib import Path
import pytest

from summarizeaudio.transcriber import Transcriber


def make_silence_wav(path: Path, duration_s: float = 1.0, rate: int = 16000) -> Path:
    n_frames = int(rate * duration_s)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return path


def test_transcriber_creates_txt_file(tmp_path, ui_queue):
    wav = make_silence_wav(tmp_path / "silence.wav")
    t = Transcriber(model="tiny", language="en", ui_queue=ui_queue)
    out_txt = tmp_path / "out.txt"
    t.transcribe(wav, out_txt)
    assert out_txt.exists()


def test_transcriber_output_is_string(tmp_path, ui_queue):
    wav = make_silence_wav(tmp_path / "silence.wav")
    t = Transcriber(model="tiny", language="en", ui_queue=ui_queue)
    out_txt = tmp_path / "out.txt"
    t.transcribe(wav, out_txt)
    content = out_txt.read_text(encoding="utf-8")
    assert isinstance(content, str)


def test_transcriber_nonexistent_file_raises(tmp_path, ui_queue):
    t = Transcriber(model="tiny", language="en", ui_queue=ui_queue)
    with pytest.raises(FileNotFoundError):
        t.transcribe(tmp_path / "nofile.mp3", tmp_path / "out.txt")


def test_transcriber_loads_whisper_without_status_notifications(tmp_path, ui_queue, monkeypatch):
    calls = []

    class FakeWhisperModel:
        def __init__(self, model_name, device=None, compute_type=None):
            self.model_name = model_name
            self.device = device
            self.compute_type = compute_type

        def transcribe(self, audio_path, language=None):
            return [types.SimpleNamespace(text="hello world")], types.SimpleNamespace(language="en", duration=1.0)

    fake_mod = types.ModuleType("faster_whisper")
    fake_mod.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_mod)
    monkeypatch.setattr("summarizeaudio.transcriber.notify", lambda *args, **kwargs: calls.append((args, kwargs)), raising=False)

    wav = make_silence_wav(tmp_path / "silence.wav")
    t = Transcriber(model="tiny", language="en", ui_queue=ui_queue)
    out_txt = tmp_path / "out.txt"
    t.transcribe(wav, out_txt)

    assert out_txt.read_text(encoding="utf-8") == "hello world"
    assert calls == []
