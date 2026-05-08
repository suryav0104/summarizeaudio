# tests/test_renamer.py
import shutil
from datetime import date
from pathlib import Path
import pytest

from summarizeaudio.renamer import Renamer, SessionPaths


def today() -> str:
    return date.today().strftime("%m-%d-%y")


def test_mode1_renames_and_moves_mp3_and_txt(tmp_output):
    mp3 = tmp_output / "abc.mp3"
    txt = tmp_output / "abc.txt"
    mp3.write_bytes(b"audio")
    txt.write_text("transcript")
    r = Renamer(tmp_output)
    paths = r.rename_session("GTC Keynote", mp3_path=mp3, txt_path=txt)
    assert paths.audio.parent.name == "AudioFiles"
    assert paths.audio.name == f"Audio - GTC Keynote {today()}.mp3"
    assert paths.transcript.parent.name == "TranscriptionFiles"
    assert paths.transcript.name == f"Transcript - GTC Keynote {today()}.txt"
    assert not mp3.exists()
    assert not txt.exists()


def test_collision_appends_counter(tmp_output):
    # Pre-create both audio AND transcript so collision is detected across both dirs
    (tmp_output / "AudioFiles" / f"Audio - test {today()}.mp3").write_bytes(b"old_audio")
    (tmp_output / "TranscriptionFiles" / f"Transcript - test {today()}.txt").write_text("old_txt")
    mp3 = tmp_output / "a.mp3"
    txt = tmp_output / "a.txt"
    mp3.write_bytes(b"new")
    txt.write_text("t")
    r = Renamer(tmp_output)
    paths = r.rename_session("test", mp3_path=mp3, txt_path=txt)
    # Both files must use the SAME suffix so they remain correlated
    assert paths.audio.name == f"Audio - test {today()}_2.mp3"
    assert paths.transcript.name == f"Transcript - test {today()}_2.txt"


def test_collision_detected_from_transcript_only(tmp_output):
    """Collision on transcript alone (Mode 2) must bump counter for all files."""
    (tmp_output / "TranscriptionFiles" / f"Transcript - notes {today()}.txt").write_text("x")
    txt = tmp_output / "b.txt"
    txt.write_text("new")
    r = Renamer(tmp_output)
    paths = r.rename_session("notes", txt_path=txt)
    assert paths.transcript.name == f"Transcript - notes {today()}_2.txt"
    assert paths.summary.name == f"Summary - notes {today()}_2.md"


def test_mode3_copies_txt_does_not_move(tmp_output):
    source = tmp_output / "notes.txt"
    source.write_text("original text")
    r = Renamer(tmp_output)
    paths = r.copy_text_session("notes", source)
    assert source.exists(), "source file must not be moved"
    assert paths.transcript.read_text() == "original text"
    assert paths.transcript.name == f"Transcript - notes {today()}.txt"


def test_summary_path_uses_same_stem(tmp_output):
    r = Renamer(tmp_output)
    summary_path = r.summary_path("GTC Keynote")
    assert summary_path.parent.name == "SummaryFiles"
    assert summary_path.name == f"Summary - GTC Keynote {today()}.md"
