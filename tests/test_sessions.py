from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from summarizeaudio import sessions as session_store
from summarizeaudio.sessions import archive_session, discover_sessions, load_sessions, session_action_specs, session_for_summary_path


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


def test_archive_session_toggles_visibility_in_sqlite(tmp_path, monkeypatch):
    root = tmp_path / "Output"
    summary_dir = root / "SummaryFiles"
    summary_dir.mkdir(parents=True)
    summary = summary_dir / "Summary - Topic_05-10-26.md"
    summary.write_text("summary")

    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setattr(session_store, "HISTORY_DB", db_path)

    sessions = discover_sessions(root, limit=None)
    assert sessions
    session_id = sessions[0].id

    archive_session(session_id, archived=True)
    assert load_sessions(root, include_archived=False) == []
    archived_sessions = load_sessions(root, include_archived=True)
    assert archived_sessions
    assert archived_sessions[0].archived is True

    archive_session(session_id, archived=False)
    restored_sessions = load_sessions(root, include_archived=False)
    assert restored_sessions
    assert restored_sessions[0].archived is False


def test_initial_history_migration_archives_only_existing_tail_once(tmp_path, monkeypatch):
    root = tmp_path / "Output"
    summary_dir = root / "SummaryFiles"
    transcript_dir = root / "TranscriptionFiles"
    audio_dir = root / "AudioFiles"
    summary_dir.mkdir(parents=True)
    transcript_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)

    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setattr(session_store, "HISTORY_DB", db_path)

    summaries = []
    for idx in range(12):
        day = f"05-{idx + 1:02d}-26"
        summary = summary_dir / f"Summary - Topic{idx}_{day}.md"
        transcript = transcript_dir / f"Transcript_Topic{idx}_{day}.txt"
        audio = audio_dir / f"Audio_Topic{idx}_{day}.mp3"
        summary.write_text(f"summary {idx}")
        transcript.write_text(f"transcript {idx}")
        audio.write_text(f"audio {idx}")
        summaries.append(summary)

    first_pass = discover_sessions(root, limit=None)
    assert len(first_pass) == 10

    with sqlite3.connect(db_path) as conn:
        archived_count = conn.execute("SELECT COUNT(*) FROM sessions WHERE archived = 1").fetchone()[0]
        assert archived_count == 2

    extra_summary = summary_dir / "Summary - Extra_05-20-26.md"
    extra_transcript = transcript_dir / "Transcript_Extra_05-20-26.txt"
    extra_audio = audio_dir / "Audio_Extra_05-20-26.mp3"
    extra_summary.write_text("summary extra")
    extra_transcript.write_text("transcript extra")
    extra_audio.write_text("audio extra")

    second_pass = discover_sessions(root, limit=None)
    assert len(second_pass) == 11

    with sqlite3.connect(db_path) as conn:
        archived_count_after = conn.execute("SELECT COUNT(*) FROM sessions WHERE archived = 1").fetchone()[0]
        assert archived_count_after == 2
