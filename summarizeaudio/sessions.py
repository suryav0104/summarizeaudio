from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SESSION_SUMMARY_RE = re.compile(
    r"^Summary - (?P<name>.+?)_(?P<date>\d{2}-\d{2}-\d{2})(?P<suffix>(?:_\d+)?)$"
)


@dataclass(frozen=True)
class SessionFiles:
    label: str
    date: str
    folder: Path
    summary: Path
    transcript: Path | None
    audio: Path | None


def discover_sessions(root: Path, limit: int | None = None) -> list[SessionFiles]:
    summary_dir = root / "SummaryFiles"
    if not summary_dir.exists():
        return []

    candidates = sorted(
        summary_dir.glob("Summary - *.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    sessions: list[SessionFiles] = []
    for summary in candidates:
        match = _SESSION_SUMMARY_RE.match(summary.stem)
        if not match:
            continue
        name = match.group("name")
        date = match.group("date")
        suffix = match.group("suffix")
        transcript = root / "TranscriptionFiles" / f"Transcript_{name}_{date}{suffix}.txt"
        audio = root / "AudioFiles" / f"Audio_{name}_{date}{suffix}.mp3"
        sessions.append(
            SessionFiles(
                label=f"{name} ({date})",
                date=date,
                folder=summary.parent,
                summary=summary,
                transcript=transcript if transcript.exists() else None,
                audio=audio if audio.exists() else None,
            )
        )
        if limit is not None and len(sessions) >= limit:
            break
    return sessions


def session_action_specs(session: SessionFiles) -> list[tuple[str, Path]]:
    specs = [("Open Summary", session.summary)]
    if session.transcript is not None:
        specs.append(("Open Transcript", session.transcript))
    if session.audio is not None:
        specs.append(("Open Recording", session.audio))
    return specs
