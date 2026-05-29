from __future__ import annotations

import re
import sqlite3
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from summarizeaudio.config import CONFIG_DIR

_DATE_RE = r"(?P<date>\d{2}-\d{2}-\d{2})(?P<suffix>(?:_\d+)?)"
_SESSION_SUMMARY_RE = re.compile(rf"^Summary - (?P<name>.+?) {_DATE_RE}$")
_SESSION_SUMMARY_OLD_RE = re.compile(rf"^Summary - (?P<name>.+?)_(?P<date>\d{{2}}-\d{{2}}-\d{{2}})(?P<suffix>(?:_\d+)?)$")
_SESSION_AUDIO_RE = re.compile(rf"^Audio - (?P<name>.+?) {_DATE_RE}$")
_SESSION_AUDIO_OLD_RE = re.compile(rf"^Audio_(?P<name>.+?)_(?P<date>\d{{2}}-\d{{2}}-\d{{2}})(?P<suffix>(?:_\d+)?)$")
_SESSION_TRANSCRIPT_RE = re.compile(rf"^Transcript - (?P<name>.+?) {_DATE_RE}$")
_SESSION_TRANSCRIPT_OLD_RE = re.compile(rf"^Transcript_(?P<name>.+?)_(?P<date>\d{{2}}-\d{{2}}-\d{{2}})(?P<suffix>(?:_\d+)?)$")
_SESSION_ARTIFACT_RE = re.compile(
    r"^(?P<prefix>.+?)(?: (?P<date>\d{2}-\d{2}-\d{2})(?P<suffix>(?:_\d+)?)|_(?P<legacy_date>\d{2}-\d{2}-\d{2})(?P<legacy_suffix>(?:_\d+)?)?)?$"
)

HISTORY_DB = CONFIG_DIR / "history.sqlite3"
_HISTORY_MIGRATION_KEY = "archive_initial_history_v1"


@dataclass(frozen=True)
class SessionFiles:
    label: str
    date: str
    folder: Path
    summary: Path | None
    transcript: Path | None
    audio: Path | None
    source_path: Path | None = None
    id: str = ""
    created_at: str = ""
    completed_at: str = ""
    status: str = "completed"
    archived: bool = False
    mode: str = "unknown"
    source_key: str = ""


@dataclass(frozen=True)
class ArtifactParts:
    kind: str
    name: str
    date: str
    suffix: str = ""


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
            summary_path TEXT,
            transcript_path TEXT,
            audio_path TEXT,
            source_path TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            archived INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
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
        "summary_path": "TEXT",
        "transcript_path": "TEXT",
        "audio_path": "TEXT",
        "source_path": "TEXT",
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


def _db_path(path: Path | None) -> str:
    return str(path) if path is not None else ""


def _session_id_for_key(source_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"summarizeaudio:{source_key}"))


def _session_key_for_summary(summary: Path) -> str:
    return summary.stem


def _artifact_filename(kind: str, name: str, date: str, suffix: str = "") -> str:
    if kind == "audio":
        return f"Audio - {name} {date}{suffix}.mp3"
    if kind == "transcript":
        return f"Transcript - {name} {date}{suffix}.txt"
    if kind == "summary":
        return f"Summary - {name} {date}{suffix}.md"
    raise ValueError(f"Unsupported artifact kind: {kind}")


def _artifact_path(root: Path, kind: str, name: str, date: str, suffix: str = "") -> Path:
    folder = {
        "audio": "AudioFiles",
        "transcript": "TranscriptionFiles",
        "summary": "SummaryFiles",
    }.get(kind)
    if folder is None:
        raise ValueError(f"Unsupported artifact kind: {kind}")
    return root / folder / _artifact_filename(kind, name, date, suffix)


def _parse_artifact_stem(stem: str) -> ArtifactParts | None:
    patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("summary", _SESSION_SUMMARY_RE),
        ("summary", _SESSION_SUMMARY_OLD_RE),
        ("audio", _SESSION_AUDIO_RE),
        ("audio", _SESSION_AUDIO_OLD_RE),
        ("transcript", _SESSION_TRANSCRIPT_RE),
        ("transcript", _SESSION_TRANSCRIPT_OLD_RE),
    )
    for kind, pattern in patterns:
        match = pattern.match(stem)
        if match:
            return ArtifactParts(
                kind=kind,
                name=match.group("name"),
                date=match.group("date"),
                suffix=match.group("suffix") or "",
            )
    return None


def _rename_artifact_path(path: Path | None, target: Path) -> Path | None:
    if path is None:
        return None
    if path == target:
        return target
    if path.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            try:
                if path.resolve() != target.resolve():
                    path.unlink()
            except FileNotFoundError:
                pass
        else:
            shutil.move(str(path), target)
    return target


def display_artifact_name(path: Path | None) -> str:
    if path is None:
        return ""
    stem = path.stem
    suffix = path.suffix
    match = _SESSION_ARTIFACT_RE.match(stem)
    if match and (match.group("date") or match.group("legacy_date")):
        stem = match.group("prefix")
    return f"{stem}{suffix}"


def display_session_label(label: str) -> str:
    match = re.match(r"^(?P<name>.+?) \((?P<date>\d{2}-\d{2}-\d{2})\)$", label)
    if match:
        return match.group("name")
    return label


def _metadata_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def _metadata_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO metadata (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _is_in_root(folder: str, root: Path) -> bool:
    root_resolved = root.resolve()
    folder_path = Path(folder).resolve()
    return root_resolved == folder_path or root_resolved in folder_path.parents


def _maybe_archive_initial_sessions(conn: sqlite3.Connection, root: Path, keep: int = 10) -> None:
    migration_key = f"{_HISTORY_MIGRATION_KEY}::{root.resolve()}"
    if _metadata_get(conn, migration_key) is not None:
        return

    rows = conn.execute(
        "SELECT id, folder, completed_at, created_at, label FROM sessions WHERE archived = 0"
    ).fetchall()
    scoped = [row for row in rows if _is_in_root(row["folder"], root)]
    scoped.sort(key=lambda row: (row["completed_at"] or "", row["created_at"] or "", row["label"] or ""), reverse=True)
    for row in scoped[keep:]:
        conn.execute("UPDATE sessions SET archived = 1 WHERE id = ?", (row["id"],))
    _metadata_set(conn, migration_key, datetime.now(tz=timezone.utc).isoformat())


def _row_artifact_parts(row: sqlite3.Row, root: Path) -> ArtifactParts | None:
    for field in ("summary_path", "transcript_path", "audio_path", "source_path"):
        raw = row[field]
        if not raw:
            continue
        path = Path(raw)
        if field == "source_path" and not _is_in_root(str(path.parent), root):
            continue
        parts = _parse_artifact_stem(path.stem)
        if parts is not None:
            return parts
    return None


def _migrate_legacy_filenames(conn: sqlite3.Connection, root: Path) -> None:
    rows = conn.execute("SELECT * FROM sessions").fetchall()
    for row in rows:
        if not _is_in_root(row["folder"], root):
            continue
        parts = _row_artifact_parts(row, root)
        if parts is None:
            continue

        summary_target = _artifact_path(root, "summary", parts.name, parts.date, parts.suffix)
        transcript_target = _artifact_path(root, "transcript", parts.name, parts.date, parts.suffix)
        audio_target = _artifact_path(root, "audio", parts.name, parts.date, parts.suffix)

        summary_path = Path(row["summary_path"]) if row["summary_path"] else None
        transcript_path = Path(row["transcript_path"]) if row["transcript_path"] else None
        audio_path = Path(row["audio_path"]) if row["audio_path"] else None
        source_path = Path(row["source_path"]) if row["source_path"] else None

        new_summary = _rename_artifact_path(summary_path, summary_target)
        new_transcript = _rename_artifact_path(transcript_path, transcript_target)
        new_audio = _rename_artifact_path(audio_path, audio_target)
        new_source = source_path
        if source_path is not None and _is_in_root(str(source_path.parent), root):
            source_parts = _parse_artifact_stem(source_path.stem)
            if source_parts is not None:
                source_target = _artifact_path(root, source_parts.kind, source_parts.name, source_parts.date, source_parts.suffix)
                new_source = _rename_artifact_path(source_path, source_target)

        updates = {
            "summary_path": _db_path(new_summary),
            "transcript_path": _db_path(new_transcript),
            "audio_path": _db_path(new_audio),
            "source_path": _db_path(new_source),
        }
        if row["summary_path"]:
            candidate_source_key = summary_target.stem
            conflict = conn.execute(
                "SELECT id FROM sessions WHERE source_key = ? AND id != ? LIMIT 1",
                (candidate_source_key, row["id"]),
            ).fetchone()
            if conflict is None:
                updates["source_key"] = candidate_source_key

        assignments = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(
            f"UPDATE sessions SET {assignments} WHERE id = ?",
            (*updates.values(), row["id"]),
        )


def _migrate_legacy_files_on_disk(root: Path) -> None:
    for folder_name in ("SummaryFiles", "TranscriptionFiles", "AudioFiles"):
        folder = root / folder_name
        if not folder.exists():
            continue
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            parts = _parse_artifact_stem(path.stem)
            if parts is None:
                continue
            target = _artifact_path(root, parts.kind, parts.name, parts.date, parts.suffix)
            _rename_artifact_path(path, target)


def _row_to_session(row: sqlite3.Row) -> SessionFiles:
    summary = Path(row["summary_path"]) if row["summary_path"] else None
    transcript = Path(row["transcript_path"]) if row["transcript_path"] else None
    audio = Path(row["audio_path"]) if row["audio_path"] else None
    source_path = Path(row["source_path"]) if row["source_path"] else None
    status = row["status"] or "completed"
    if status == "in_progress":
        status = "partial"
    return SessionFiles(
        label=row["label"],
        date=row["date"],
        folder=Path(row["folder"]),
        summary=summary if summary is not None and summary.exists() else summary,
        transcript=transcript if transcript is not None and transcript.exists() else None,
        audio=audio if audio is not None and audio.exists() else None,
        source_path=source_path if source_path is not None and source_path.exists() else source_path,
        id=row["id"],
        created_at=row["created_at"],
        completed_at=row["completed_at"] or "",
        status=status,
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
        parts = _parse_artifact_stem(summary.stem)
        if parts is None or parts.kind != "summary":
            continue
        transcript = _artifact_path(root, "transcript", parts.name, parts.date, parts.suffix)
        audio = _artifact_path(root, "audio", parts.name, parts.date, parts.suffix)
        sessions.append(
            SessionFiles(
                label=f"{parts.name} ({parts.date})",
                date=parts.date,
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
    with _connect() as conn:
        _ensure_schema(conn)
        _migrate_legacy_filenames(conn, root)
        _migrate_legacy_files_on_disk(root)
        discovered = _scan_filesystem_sessions(root)
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
                        summary_path, transcript_path, audio_path, source_path, status, archived
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        _db_path(session.summary),
                        _db_path(session.transcript),
                        _db_path(session.audio),
                        _db_path(session.source_path),
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
                    source_path = ?,
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
                    _db_path(session.summary),
                    _db_path(session.transcript),
                    _db_path(session.audio),
                    _db_path(session.source_path),
                    existing["status"] or session.status,
                    session.source_key,
                ),
            )
        _maybe_archive_initial_sessions(conn, root, keep=10)
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
        if include_archived:
            query += " WHERE archived = 1"
        else:
            query += " WHERE archived = 0"
        query += (
            " ORDER BY "
            "CASE WHEN status IN ('partial', 'failed', 'in_progress') THEN 0 ELSE 1 END, "
            "COALESCE(completed_at, created_at) DESC, "
            "created_at DESC, "
            "label ASC"
        )
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
    specs: list[tuple[str, Path]] = []
    if session.summary is not None and session.summary.exists():
        specs.append(("Open Summary", session.summary))
    if session.transcript is not None and session.transcript.exists():
        specs.append(("Open Transcript", session.transcript))
    if session.audio is not None and session.audio.exists():
        specs.append(("Open Recording", session.audio))
    return specs


def session_for_summary_path(root: Path, summary: Path) -> SessionFiles | None:
    summary_resolved = summary.resolve()
    for session in load_sessions(root, limit=None, include_archived=False):
        if session.summary is None:
            continue
        try:
            if session.summary.resolve() == summary_resolved:
                return session
        except OSError:
            continue

    parts = _parse_artifact_stem(summary.stem)
    if parts is None or parts.kind != "summary":
        return None

    transcript = _artifact_path(root, "transcript", parts.name, parts.date, parts.suffix)
    audio = _artifact_path(root, "audio", parts.name, parts.date, parts.suffix)
    return SessionFiles(
        label=f"{parts.name} ({parts.date})",
        date=parts.date,
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


def session_by_id(session_id: str) -> SessionFiles | None:
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    return _row_to_session(row)


def session_source_key_exists(source_key: str) -> bool:
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT 1 FROM sessions WHERE source_key = ? LIMIT 1", (source_key,)).fetchone()
    return row is not None


def create_session_record(
    *,
    root: Path,
    source_key: str,
    label: str,
    date: str,
    mode: str,
    folder: Path,
    status: str = "in_progress",
    summary_path: Path | None = None,
    transcript_path: Path | None = None,
    audio_path: Path | None = None,
    source_path: Path | None = None,
    created_at: str | None = None,
    completed_at: str | None = None,
    archived: bool = False,
) -> SessionFiles:
    now = created_at or datetime.now(tz=timezone.utc).isoformat()
    session = SessionFiles(
        label=label,
        date=date,
        folder=folder,
        summary=summary_path,
        transcript=transcript_path,
        audio=audio_path,
        source_path=source_path,
        id=_session_id_for_key(source_key),
        created_at=now,
        completed_at=completed_at or "",
        status=status,
        archived=archived,
        mode=mode,
        source_key=source_key,
    )
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO sessions (
                id, source_key, created_at, completed_at, mode, label, date, folder,
                summary_path, transcript_path, audio_path, source_path, status, archived
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                created_at = excluded.created_at,
                completed_at = excluded.completed_at,
                mode = excluded.mode,
                label = excluded.label,
                date = excluded.date,
                folder = excluded.folder,
                summary_path = excluded.summary_path,
                transcript_path = excluded.transcript_path,
                audio_path = excluded.audio_path,
                source_path = excluded.source_path,
                status = excluded.status,
                archived = excluded.archived
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
                _db_path(session.summary),
                _db_path(session.transcript),
                _db_path(session.audio),
                _db_path(session.source_path),
                session.status,
                int(session.archived),
            ),
        )
        conn.commit()
    return session


def update_session_record(
    *,
    session_id: str,
    source_key: str | None = None,
    label: str | None = None,
    date: str | None = None,
    folder: Path | None = None,
    summary_path: Path | None | object = ...,
    transcript_path: Path | None | object = ...,
    audio_path: Path | None | object = ...,
    source_path: Path | None | object = ...,
    status: str | None = None,
    completed_at: str | None | object = ...,
    archived: bool | None = None,
    mode: str | None = None,
    created_at: str | None = None,
) -> None:
    assignments: list[str] = []
    params: list[object] = []

    def add(name: str, value: object | None | object) -> None:
        assignments.append(f"{name} = ?")
        params.append(value)

    if label is not None:
        add("label", label)
    if source_key is not None:
        add("source_key", source_key)
    if date is not None:
        add("date", date)
    if folder is not None:
        add("folder", str(folder))
    if summary_path is not ...:
        add("summary_path", _db_path(summary_path if summary_path is not ... else None))
    if transcript_path is not ...:
        add("transcript_path", _db_path(transcript_path if transcript_path is not ... else None))
    if audio_path is not ...:
        add("audio_path", _db_path(audio_path if audio_path is not ... else None))
    if source_path is not ...:
        add("source_path", _db_path(source_path if source_path is not ... else None))
    if status is not None:
        add("status", status)
    if completed_at is not ...:
        add("completed_at", completed_at)
    if archived is not None:
        add("archived", int(archived))
    if mode is not None:
        add("mode", mode)
    if created_at is not None:
        add("created_at", created_at)

    if not assignments:
        return

    params.append(session_id)
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            f"UPDATE sessions SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        conn.commit()


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
