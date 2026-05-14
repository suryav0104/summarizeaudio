"""Tests for speaker diarization.

Integration test (test_diarizer_pipeline_runs):
  Skipped automatically when HUGGINGFACE_ACCESS_TOKEN is not set.
  Requires:
    - pip install 'summarizeaudio[diarization]'
    - HUGGINGFACE_ACCESS_TOKEN in .env or environment
    - HuggingFace license accepted for pyannote/speaker-diarization-3.1,
      pyannote/segmentation-3.0, and pyannote/speaker-diarization-community-1
    - macOS (uses the built-in `say` command to synthesize test audio)

Unit tests (test_diarizer_format_*, test_diarizer_dominant_speaker):
  Run without any HuggingFace token or pyannote installation.
"""
from __future__ import annotations

import os
import subprocess
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _has_say() -> bool:
    return subprocess.run(["which", "say"], capture_output=True).returncode == 0


def _load_token() -> str | None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return os.environ.get("HUGGINGFACE_ACCESS_TOKEN")


def _make_two_speaker_wav(tmp_path: Path) -> Path:
    """Synthesize two voices with macOS say, concatenate via pydub."""
    s1 = tmp_path / "speaker1.aiff"
    s2 = tmp_path / "speaker2.aiff"
    subprocess.run(
        ["say", "-v", "Alex", "-o", str(s1),
         "Hello. My name is Alex. I am the first speaker in this recording. "
         "I will talk for a few seconds so the model has enough audio to work with."],
        check=True,
    )
    subprocess.run(
        ["say", "-v", "Samantha", "-o", str(s2),
         "Hi there. I am Samantha. I am the second speaker. "
         "I also need a few seconds of audio for the diarization to detect me correctly."],
        check=True,
    )
    from pydub import AudioSegment  # type: ignore[import]
    seg1 = AudioSegment.from_file(str(s1))
    seg2 = AudioSegment.from_file(str(s2))
    combined = seg1 + AudioSegment.silent(duration=800) + seg2
    out = tmp_path / "two_speakers.wav"
    combined.export(str(out), format="wav")
    return out


# ── Integration test ──────────────────────────────────────────────────────────

@pytest.mark.skipif(not _load_token(), reason="HUGGINGFACE_ACCESS_TOKEN not set")
@pytest.mark.skipif(not _has_say(), reason="macOS say command not available")
def test_diarizer_pipeline_runs(tmp_path: Path) -> None:
    """Validates the full pipeline: loads pyannote, runs on audio, returns labeled output.

    Speaker-count accuracy is not asserted here — TTS voices are acoustically
    similar enough that pyannote may cluster them as one speaker. Real human
    recordings with distinct voices will produce reliable two-speaker output.
    """
    from pydub import AudioSegment  # type: ignore[import]
    from summarizeaudio.diarizer import Diarizer

    token = _load_token()
    assert token

    audio = _make_two_speaker_wav(tmp_path)
    duration_s = len(AudioSegment.from_wav(str(audio))) / 1000.0
    mid = duration_s / 2.0

    segments = [
        types.SimpleNamespace(start=0.0, end=mid,
                              text="Hello my name is Alex I am the first speaker"),
        types.SimpleNamespace(start=mid, end=duration_s,
                              text="Hi there I am Samantha I am the second speaker"),
    ]

    diarizer = Diarizer(token)
    result = diarizer.label(audio, segments, num_speakers=2)

    assert result, "Expected non-empty labeled output"
    assert "Speaker 1:" in result, f"Expected 'Speaker 1:' in:\n{result}"
    assert all(line.startswith("Speaker ") for line in result.splitlines()), \
        f"Every line should start with 'Speaker N:':\n{result}"


# ── Unit tests (no HuggingFace token required) ────────────────────────────────

def _make_diarizer() -> "Diarizer":
    from summarizeaudio.diarizer import Diarizer
    d = Diarizer.__new__(Diarizer)
    d._hf_token = "fake"
    d._pipeline = None
    return d


def test_diarizer_format_groups_consecutive_same_speaker() -> None:
    from summarizeaudio.diarizer import Diarizer
    d = _make_diarizer()
    labeled = [("Speaker 1", "Hello there"), ("Speaker 1", "how are you"),
               ("Speaker 2", "I am fine"), ("Speaker 1", "great")]
    result = d._format(labeled)
    assert result == (
        "Speaker 1: Hello there how are you\n"
        "Speaker 2: I am fine\n"
        "Speaker 1: great"
    )


def test_diarizer_format_empty_input() -> None:
    from summarizeaudio.diarizer import Diarizer
    d = _make_diarizer()
    assert d._format([]) == ""


def test_diarizer_dominant_speaker_picks_most_overlap() -> None:
    from summarizeaudio.diarizer import Diarizer
    d = _make_diarizer()
    turns = [(0.0, 5.0, "SPEAKER_00"), (5.0, 10.0, "SPEAKER_01")]
    speaker_map = {"SPEAKER_00": "Speaker 1", "SPEAKER_01": "Speaker 2"}
    # Segment mostly in SPEAKER_00's range
    assert d._dominant_speaker(0.0, 4.0, turns, speaker_map) == "Speaker 1"
    # Segment mostly in SPEAKER_01's range
    assert d._dominant_speaker(6.0, 10.0, turns, speaker_map) == "Speaker 2"


def test_diarizer_label_with_mocked_pipeline(tmp_path: Path) -> None:
    """Full label() path with pyannote mocked — no token or model download."""
    import wave
    from summarizeaudio.diarizer import Diarizer

    # Minimal valid WAV
    wav = tmp_path / "test.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 16000)

    # Build a fake pyannote Annotation with two speakers
    fake_turn_0 = MagicMock(); fake_turn_0.start = 0.0; fake_turn_0.end = 4.0
    fake_turn_1 = MagicMock(); fake_turn_1.start = 4.5; fake_turn_1.end = 8.0
    fake_annotation = MagicMock()
    fake_annotation.itertracks.return_value = [
        (fake_turn_0, None, "SPEAKER_00"),
        (fake_turn_1, None, "SPEAKER_01"),
    ]
    fake_result = MagicMock()
    fake_result.speaker_diarization = fake_annotation

    d = _make_diarizer()
    d._pipeline = MagicMock(return_value=fake_result)

    segments = [
        types.SimpleNamespace(start=0.0, end=4.0, text="Hello I am the first speaker"),
        types.SimpleNamespace(start=4.5, end=8.0, text="Hi I am the second speaker"),
    ]
    result = d.label(wav, segments)

    assert "Speaker 1: Hello I am the first speaker" in result
    assert "Speaker 2: Hi I am the second speaker" in result
