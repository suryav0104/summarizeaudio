from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path


def _today() -> str:
    return date.today().strftime("%m-%d-%y")


@dataclass
class SessionPaths:
    audio: Path | None
    transcript: Path
    summary: Path


class Renamer:
    def __init__(self, output_folder: Path) -> None:
        self._root = output_folder

    def rename_session(
        self,
        name: str,
        mp3_path: Path | None = None,
        txt_path: Path | None = None,
    ) -> SessionPaths:
        """Move MP3 and TXT to subfolders with prefixed names. Resolves collisions.

        The same collision suffix is applied to all three output files (audio,
        transcript, summary) so they remain correlated.

        Note: SessionPaths.transcript is always set to the computed destination path.
        It may point to a non-existent file if txt_path was not provided.
        """
        today = _today()
        # Determine a single suffix that avoids collisions across all three subfolders.
        # Using one authoritative suffix prevents audio and transcript from landing
        # in different "slots" (which would break their correlation).
        suffix = _find_collision_suffix(name, today, self._root, has_audio=mp3_path is not None)

        audio_dest: Path | None = None
        if mp3_path is not None:
            audio_dest = self._root / "AudioFiles" / f"Audio_{name}_{today}{suffix}.mp3"
            audio_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(mp3_path), audio_dest)

        txt_dest = self._root / "TranscriptionFiles" / f"Transcript_{name}_{today}{suffix}.txt"
        if txt_path is not None:
            txt_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(txt_path), txt_dest)

        summary_dest = self._root / "SummaryFiles" / f"Summary - {name}_{today}{suffix}.md"
        summary_dest.parent.mkdir(parents=True, exist_ok=True)

        return SessionPaths(audio=audio_dest, transcript=txt_dest, summary=summary_dest)

    def copy_text_session(self, name: str, source_txt: Path) -> SessionPaths:
        """Copy source text to TranscriptionFiles without moving the original."""
        today = _today()
        suffix = _find_collision_suffix(name, today, self._root, has_audio=False)
        txt_dest = self._root / "TranscriptionFiles" / f"Transcript_{name}_{today}{suffix}.txt"
        txt_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source_txt), txt_dest)
        summary_dest = self._root / "SummaryFiles" / f"Summary - {name}_{today}{suffix}.md"
        summary_dest.parent.mkdir(parents=True, exist_ok=True)
        return SessionPaths(audio=None, transcript=txt_dest, summary=summary_dest)

    def summary_path(self, name: str) -> Path:
        today = _today()
        return self._root / "SummaryFiles" / f"Summary - {name}_{today}.md"


def _find_collision_suffix(
    name: str, today: str, root: Path, has_audio: bool
) -> str:
    """Find the lowest suffix ("", "_2", "_3", …) such that no output file collides
    across AudioFiles, TranscriptionFiles, and SummaryFiles.
    """
    audio_dir = root / "AudioFiles"
    trans_dir = root / "TranscriptionFiles"
    summ_dir = root / "SummaryFiles"

    def _collides(sfx: str) -> bool:
        if has_audio and (audio_dir / f"Audio_{name}_{today}{sfx}.mp3").exists():
            return True
        if (trans_dir / f"Transcript_{name}_{today}{sfx}.txt").exists():
            return True
        if (summ_dir / f"Summary - {name}_{today}{sfx}.md").exists():
            return True
        return False

    if not _collides(""):
        return ""
    counter = 2
    while True:
        sfx = f"_{counter}"
        if not _collides(sfx):
            return sfx
        counter += 1
