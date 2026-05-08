from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from summarizeaudio import sessions as session_store
from summarizeaudio.sessions import (
    archive_session,
    create_session_record,
    discover_sessions,
    load_sessions,
    session_action_specs,
    session_for_summary_path,
    update_session_record,
)


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


def test_archived_and_active_views_are_disjoint(tmp_path, monkeypatch):
    root = tmp_path / "Output"
    summary_dir = root / "SummaryFiles"
    summary_dir.mkdir(parents=True)
    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setattr(session_store, "HISTORY_DB", db_path)

    active_summary = summary_dir / "Summary - Active_05-08-26.md"
    archived_summary = summary_dir / "Summary - Archived_05-07-26.md"
    active_summary.write_text("active")
    archived_summary.write_text("archived")

    active = create_session_record(
        root=root,
        source_key="active-1",
        label="Active",
        date="05-08-26",
        mode="text",
        folder=root,
        status="completed",
        summary_path=active_summary,
        completed_at="2026-05-08T12:00:00+00:00",
    )
    archived = create_session_record(
        root=root,
        source_key="archived-1",
        label="Archived",
        date="05-07-26",
        mode="text",
        folder=root,
        status="completed",
        summary_path=archived_summary,
        completed_at="2026-05-07T12:00:00+00:00",
        archived=True,
    )

    monkeypatch.setattr(session_store, "sync_sessions_from_filesystem", lambda root: None)
    active_rows = load_sessions(root, include_archived=False)
    archived_rows = load_sessions(root, include_archived=True)

    assert [row.id for row in active_rows] == [active.id]
    assert [row.id for row in archived_rows] == [archived.id]


def test_partial_session_is_saved_before_summary_exists(tmp_path, monkeypatch):
    root = tmp_path / "Output"
    root.mkdir(parents=True)
    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setattr(session_store, "HISTORY_DB", db_path)

    audio = root / "AudioFiles" / "Recording.m4a"
    audio.parent.mkdir(parents=True)
    audio.write_text("audio")

    session = create_session_record(
        root=root,
        source_key="workflow-123",
        label="Recording",
        date="05-10-26",
        mode="record",
        folder=root,
        status="in_progress",
        audio_path=audio,
        source_path=audio,
    )

    sessions = load_sessions(root, include_archived=False)
    assert len(sessions) == 1
    assert sessions[0].label == "Recording"
    assert sessions[0].summary is None
    assert sessions[0].audio == audio
    assert sessions[0].source_path == audio
    assert session_action_specs(sessions[0]) == [("Open Recording", audio)]

    transcript = root / "TranscriptionFiles" / "Transcript_Recording_05-10-26.txt"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("transcript")
    summary = root / "SummaryFiles" / "Summary - Recording_05-10-26.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("summary")
    update_session_record(
        session_id=session.id,
        source_key="Summary - Recording_05-10-26",
        label="Recording",
        summary_path=summary,
        transcript_path=transcript,
        status="completed",
        completed_at="2026-05-10T00:00:00+00:00",
    )

    refreshed = load_sessions(root, include_archived=False)
    assert refreshed[0].summary == summary
    assert refreshed[0].transcript == transcript
    assert refreshed[0].status == "completed"


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


def test_partial_sessions_sort_ahead_of_completed_sessions(tmp_path, monkeypatch):
    root = tmp_path / "Output"
    root.mkdir(parents=True)
    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setattr(session_store, "HISTORY_DB", db_path)

    completed = create_session_record(
        root=root,
        source_key="completed-1",
        label="Completed",
        date="05-08-26",
        mode="audio",
        folder=root,
        status="completed",
        summary_path=root / "SummaryFiles" / "Summary - Completed_05-08-26.md",
        created_at="2026-05-08T20:00:00+00:00",
        completed_at="2026-05-08T20:01:00+00:00",
    )
    partial = create_session_record(
        root=root,
        source_key="partial-1",
        label="Partial",
        date="05-08-26",
        mode="audio",
        folder=root,
        status="partial",
        summary_path=None,
        created_at="2026-05-08T21:00:00+00:00",
    )
    failed = create_session_record(
        root=root,
        source_key="failed-1",
        label="Failed",
        date="05-08-26",
        mode="audio",
        folder=root,
        status="failed",
        summary_path=None,
        created_at="2026-05-08T21:05:00+00:00",
    )

    sessions = load_sessions(root, include_archived=False)
    assert [session.id for session in sessions[:3]] == [failed.id, partial.id, completed.id]
