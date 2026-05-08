from __future__ import annotations

import os
from pathlib import Path

from summarizeaudio.sessions import discover_sessions, session_action_specs


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
