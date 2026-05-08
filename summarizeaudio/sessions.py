from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from summarizeaudio.config import CONFIG_DIR

_SESSION_SUMMARY_RE = re.compile(
    r"^Summary - (?P<name>.+?)_(?P<date>\d{2}-\d{2}-\d{2})(?P<suffix>(?:_\d+)?)$"
)

HISTORY_DB = CONFIG_DIR / "history.sqlite3"


@dataclass(frozen=True)
class SessionFiles:
    label: str
    date: str
    folder: Path
    summary: Path
    transcript: Path | None
    audio: Path | None
    id: str = ""
    created_at: str = ""
    completed_at: str = ""
    status: str = "completed"
    archived: bool = False
    mode: str = "unknown"
    source_key: str = ""


def _connect() -> sqlite3.Connection:
    HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "title" in existing_cols:
        conn.execute("DROP TABLE IF EXISTS sessions")
        conn.commit()
        existing_cols = set()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            source_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            mode TEXT NOT NULL DEFAULT 'unknown',
            label TEXT NOT NULL,
            date TEXT NOT NULL,
            folder TEXT NOT NULL,
            summary_path TEXT NOT NULL,
            transcript_path TEXT,
            audio_path TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            archived INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    required_columns = {
        "id": "TEXT",
        "source_key": "TEXT",
        "created_at": "TEXT",
        "completed_at": "TEXT",
        "mode": "TEXT NOT NULL DEFAULT 'unknown'",
        "label": "TEXT NOT NULL DEFAULT ''",
        "date": "TEXT NOT NULL DEFAULT ''",
        "folder": "TEXT NOT NULL DEFAULT ''",
        "summary_path": "TEXT NOT NULL DEFAULT ''",
        "transcript_path": "TEXT",
        "audio_path": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'completed'",
        "archived": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, ddl in required_columns.items():
        if column not in existing_cols:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_completed_at ON sessions(completed_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_archived ON sessions(archived)")
    conn.commit()


def _iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _session_id_for_key(source_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"summarizeaudio:{source_key}"))


def _session_key_for_summary(summary: Path) -> str:
    return summary.stem


def _row_to_session(row: sqlite3.Row) -> SessionFiles:
    summary = Path(row["summary_path"])
    transcript = Path(row["transcript_path"]) if row["transcript_path"] else None
    audio = Path(row["audio_path"]) if row["audio_path"] else None
    return SessionFiles(
        label=row["label"],
        date=row["date"],
        folder=Path(row["folder"]),
        summary=summary,
        transcript=transcript if transcript is not None and transcript.exists() else None,
        audio=audio if audio is not None and audio.exists() else None,
        id=row["id"],
        created_at=row["created_at"],
        completed_at=row["completed_at"] or "",
        status=row["status"],
        archived=bool(row["archived"]),
        mode=row["mode"],
        source_key=row["source_key"],
    )


def _scan_filesystem_sessions(root: Path) -> list[SessionFiles]:
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
                id=_session_id_for_key(_session_key_for_summary(summary)),
                created_at=_iso_from_timestamp(summary.stat().st_mtime),
                completed_at=_iso_from_timestamp(summary.stat().st_mtime),
                status="completed",
                archived=False,
                mode="audio" if audio.exists() else "text",
                source_key=_session_key_for_summary(summary),
            )
        )
    return sessions


def sync_sessions_from_filesystem(root: Path) -> None:
    discovered = _scan_filesystem_sessions(root)
    if not discovered:
        return

    with _connect() as conn:
        _ensure_schema(conn)
        for session in discovered:
            existing = conn.execute(
                "SELECT id, created_at, status, archived FROM sessions WHERE source_key = ?",
                (session.source_key,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO sessions (
                        id, source_key, created_at, completed_at, mode, label, date, folder,
                        summary_path, transcript_path, audio_path, status, archived
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.id,
                        session.source_key,
                        session.created_at,
                        session.completed_at,
                        session.mode,
                        session.label,
                        session.date,
                        str(session.folder),
                        str(session.summary),
                        str(session.transcript) if session.transcript is not None else None,
                        str(session.audio) if session.audio is not None else None,
                        session.status,
                        int(session.archived),
                    ),
                )
                continue

            conn.execute(
                """
                UPDATE sessions
                SET
                    completed_at = ?,
                    mode = ?,
                    label = ?,
                    date = ?,
                    folder = ?,
                    summary_path = ?,
                    transcript_path = ?,
                    audio_path = ?,
                    status = ?,
                    archived = archived
                WHERE source_key = ?
                """,
                (
                    session.completed_at,
                    session.mode,
                    session.label,
                    session.date,
                    str(session.folder),
                    str(session.summary),
                    str(session.transcript) if session.transcript is not None else None,
                    str(session.audio) if session.audio is not None else None,
                    existing["status"] or session.status,
                    session.source_key,
                ),
            )
        conn.commit()


def load_sessions(
    root: Path,
    limit: int | None = None,
    include_archived: bool = False,
) -> list[SessionFiles]:
    sync_sessions_from_filesystem(root)
    with _connect() as conn:
        _ensure_schema(conn)
        query = "SELECT * FROM sessions"
        params: list[object] = []
        if not include_archived:
            query += " WHERE archived = 0"
        query += " ORDER BY completed_at DESC, created_at DESC, label ASC"
        rows = conn.execute(query, params).fetchall()
        root_resolved = root.resolve()
        filtered = [
            _row_to_session(row)
            for row in rows
            if root_resolved in Path(row["folder"]).resolve().parents or Path(row["folder"]).resolve() == root_resolved
        ]
        if limit is not None:
            filtered = filtered[:limit]
        return filtered


def discover_sessions(root: Path, limit: int | None = None) -> list[SessionFiles]:
    return load_sessions(root, limit=limit, include_archived=False)


def session_action_specs(session: SessionFiles) -> list[tuple[str, Path]]:
    specs = [("Open Summary", session.summary)]
    if session.transcript is not None:
        specs.append(("Open Transcript", session.transcript))
    if session.audio is not None:
        specs.append(("Open Recording", session.audio))
    return specs


def session_for_summary_path(root: Path, summary: Path) -> SessionFiles | None:
    summary_resolved = summary.resolve()
    for session in load_sessions(root, limit=None, include_archived=False):
        if session.summary.resolve() == summary_resolved:
            return session

    match = _SESSION_SUMMARY_RE.match(summary.stem)
    if not match:
        return None

    name = match.group("name")
    date = match.group("date")
    suffix = match.group("suffix")
    transcript = root / "TranscriptionFiles" / f"Transcript_{name}_{date}{suffix}.txt"
    audio = root / "AudioFiles" / f"Audio_{name}_{date}{suffix}.mp3"
    return SessionFiles(
        label=f"{name} ({date})",
        date=date,
        folder=summary.parent,
        summary=summary,
        transcript=transcript if transcript.exists() else None,
        audio=audio if audio.exists() else None,
        id=_session_id_for_key(_session_key_for_summary(summary)),
        created_at=_iso_from_timestamp(summary.stat().st_mtime) if summary.exists() else "",
        completed_at=_iso_from_timestamp(summary.stat().st_mtime) if summary.exists() else "",
        status="completed",
        archived=False,
        mode="audio" if audio.exists() else "text",
        source_key=_session_key_for_summary(summary),
    )


def archive_session(session_id: str, archived: bool = True) -> None:
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            "UPDATE sessions SET archived = ? WHERE id = ?",
            (1 if archived else 0, session_id),
        )
        conn.commit()


def delete_session(session_id: str) -> None:
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
