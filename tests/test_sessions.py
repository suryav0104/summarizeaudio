from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from summarizeaudio import sessions as session_store
from summarizeaudio.sessions import discover_sessions, session_action_specs, session_for_summary_path


def test_discover_sessions_orders_newest_first_and_filters_missing_files(tmp_path):
    root = tmp_path / "Output"
    summary_dir = root / "SummaryFiles"
    transcript_dir = root / "TranscriptionFiles"
    audio_dir = root / "AudioFiles"
    summary_dir.mkdir(parents=True)
    transcript_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)

    older_summary = summary_dir / "Summary - Older_05-08-26.md"
    newer_summary = summary_dir / "Summary - Newer_05-09-26.md"
    older_summary.write_text("older")
    newer_summary.write_text("newer")
    transcript = transcript_dir / "Transcript_Newer_05-09-26.txt"
    transcript.write_text("transcript")
    audio = audio_dir / "Audio_Newer_05-09-26.mp3"
    audio.write_text("audio")

    os.utime(older_summary, (1, 1))
    os.utime(newer_summary, (2, 2))

    sessions = discover_sessions(root, limit=None)
    assert [session.label for session in sessions] == ["Newer (05-09-26)", "Older (05-08-26)"]
    assert session_action_specs(sessions[0]) == [
        ("Open Summary", newer_summary),
        ("Open Transcript", transcript),
        ("Open Recording", audio),
    ]
    assert session_action_specs(sessions[1]) == [
        ("Open Summary", older_summary),
    ]


def test_discover_sessions_syncs_filesystem_sessions_into_sqlite(tmp_path, monkeypatch):
    root = tmp_path / "Output"
    summary_dir = root / "SummaryFiles"
    transcript_dir = root / "TranscriptionFiles"
    audio_dir = root / "AudioFiles"
    summary_dir.mkdir(parents=True)
    transcript_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)

    summary = summary_dir / "Summary - Topic_05-10-26.md"
    transcript = transcript_dir / "Transcript_Topic_05-10-26.txt"
    audio = audio_dir / "Audio_Topic_05-10-26.mp3"
    summary.write_text("summary")
    transcript.write_text("transcript")
    audio.write_text("audio")

    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setattr(session_store, "HISTORY_DB", db_path)

    sessions = discover_sessions(root, limit=None)
    assert sessions
    assert db_path.exists()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT label, date, archived, summary_path, transcript_path, audio_path FROM sessions ORDER BY completed_at DESC"
        ).fetchall()

    assert rows == [
        ("Topic (05-10-26)", "05-10-26", 0, str(summary), str(transcript), str(audio)),
    ]


def test_session_for_summary_path_recovers_matching_artifacts(tmp_path):
    root = tmp_path / "Output"
    summary_dir = root / "SummaryFiles"
    transcript_dir = root / "TranscriptionFiles"
    audio_dir = root / "AudioFiles"
    summary_dir.mkdir(parents=True)
    transcript_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)

    summary = summary_dir / "Summary - Topic_05-10-26.md"
    transcript = transcript_dir / "Transcript_Topic_05-10-26.txt"
    audio = audio_dir / "Audio_Topic_05-10-26.mp3"
    summary.write_text("summary")
    transcript.write_text("transcript")
    audio.write_text("audio")

    session = session_for_summary_path(root, summary)

    assert session is not None
    assert session.summary == summary
    assert session.transcript == transcript
    assert session.audio == audio
    assert session_action_specs(session) == [
        ("Open Summary", summary),
        ("Open Transcript", transcript),
        ("Open Recording", audio),
    ]
