# tests/test_recorder.py
import time
from pathlib import Path

import pytest

from summarizeaudio.recorder import Recorder


def test_recorder_creates_mp3_and_deletes_wav(tmp_output):
    rec = Recorder(output_folder=tmp_output)
    rec.start()
    time.sleep(2.5)  # must exceed MIN_DURATION_SECONDS (2.0)
    mp3_path, start, end = rec.stop()
    assert mp3_path.exists()
    assert mp3_path.suffix == ".mp3"
    wav_path = mp3_path.with_suffix(".wav")
    assert not wav_path.exists(), "temp .wav should be deleted after conversion"


def test_recorder_returns_correct_timestamps(tmp_output):
    rec = Recorder(output_folder=tmp_output)
    rec.start()
    time.sleep(2.5)  # must exceed MIN_DURATION_SECONDS (2.0)
    _, start, end = rec.stop()
    assert start < end
    duration = (end - start).total_seconds()
    assert 2.0 < duration < 5.0


def test_recorder_short_recording_raises(tmp_output):
    rec = Recorder(output_folder=tmp_output)
    rec.start()
    time.sleep(0.05)
    with pytest.raises(ValueError, match="too short"):
        rec.stop()


def test_recorder_wav_flushed_incrementally(tmp_output):
    """WAV file must exist on disk before stop() is called."""
    rec = Recorder(output_folder=tmp_output)
    rec.start()
    time.sleep(2.5)  # must exceed MIN_DURATION_SECONDS (2.0)
    # Find the WAV temp file while still recording
    wav_files = list(tmp_output.glob("*.wav"))
    assert len(wav_files) == 1, "WAV should be written incrementally during recording"
    rec.stop()  # clean up
