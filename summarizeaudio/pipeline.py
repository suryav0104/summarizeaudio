from __future__ import annotations

import enum
import logging
import queue
import threading
import traceback
from pathlib import Path
from uuid import uuid4

log = logging.getLogger(__name__)

from summarizeaudio.config import AppConfig
from summarizeaudio.error_handler import post_error
from summarizeaudio.notifier import notify
from summarizeaudio.renamer import Renamer
from summarizeaudio.summarizer import Summarizer
from summarizeaudio.transcriber import Transcriber


class PipelineMode(enum.Enum):
    RECORD = "record"
    LOCAL_AUDIO = "local_audio"
    LOCAL_TEXT = "local_text"


class Pipeline:
    def __init__(self, cfg: AppConfig, ui_queue: queue.Queue) -> None:
        self._cfg = cfg
        self._ui_queue = ui_queue

    def run(
        self,
        mode: PipelineMode,
        session_name: str,
        mp3_path: Path | None = None,
        source_path: Path | None = None,
        done_event: threading.Event | None = None,
    ) -> None:
        """Execute the full pipeline for the given mode.

        done_event: optional threading.Event to clear when the pipeline finishes
        (whether by success or exception). Tray passes pipeline_running here so
        the icon always resets to idle.
        """
        log.info("Pipeline starting: mode=%s session=%r", mode.value, session_name)
        try:
            self._run_inner(mode, session_name, mp3_path, source_path)
        except Exception:
            log.exception("Pipeline failed: mode=%s session=%r", mode.value, session_name)
            raise
        finally:
            log.info("Pipeline finished: mode=%s session=%r", mode.value, session_name)
            if done_event is not None:
                done_event.clear()

    def _run_inner(
        self,
        mode: PipelineMode,
        session_name: str,
        mp3_path: Path | None,
        source_path: Path | None,
    ) -> None:
        cfg = self._cfg
        renamer = Renamer(cfg.storage.output_folder)
        transcriber = Transcriber(
            model=cfg.whisper.model,
            language=cfg.whisper.language,
            ui_queue=self._ui_queue,
        )
        summarizer = Summarizer(
            ollama=cfg.ollama,
            summ_cfg=cfg.summarization,
            beh=cfg.behavior,
            ui_queue=self._ui_queue,
        )

        if mode == PipelineMode.LOCAL_TEXT:
            # Mode 3: copy text → summarize
            assert source_path is not None
            log.info("Mode 3: copying text file %s", source_path)
            session = renamer.copy_text_session(session_name, source_path)
            transcript_text = session.transcript.read_text(encoding="utf-8")
            log.info("Mode 3: summarizing %d chars", len(transcript_text))
            try:
                summarizer.summarize(transcript_text, session.summary)
            except Exception:
                log.exception("Mode 3: summarization failed (continuing)")
            notify(f"Summary ready — {session.summary.read_text()[:200]}"
                   if session.summary.exists() else "Processing complete.")
            return

        # Mode 1 or 2: transcribe first
        session_id = str(uuid4())
        tmp_txt = cfg.storage.output_folder / f"{session_id}.txt"

        if mode == PipelineMode.RECORD:
            assert mp3_path is not None
            audio_for_transcription = mp3_path
        else:
            assert source_path is not None
            audio_for_transcription = source_path

        log.info("Transcribing %s → %s", audio_for_transcription.name, tmp_txt.name)
        try:
            transcriber.transcribe(audio_for_transcription, tmp_txt)
        except Exception as exc:
            log.exception("Transcription failed for %s", audio_for_transcription)
            post_error(self._ui_queue, "pipeline.py → transcriber",
                       str(exc), traceback.format_exc())
            if mode == PipelineMode.LOCAL_AUDIO and tmp_txt.exists():
                tmp_txt.unlink()
            raise
        log.info("Transcription complete, output: %s", tmp_txt)

        # Rename and move
        if mode == PipelineMode.RECORD:
            session = renamer.rename_session(session_name, mp3_path=mp3_path, txt_path=tmp_txt)
        else:
            session = renamer.rename_session(session_name, mp3_path=None, txt_path=tmp_txt)
        log.info("Files moved → transcript=%s", session.transcript)

        transcript_text = session.transcript.read_text(encoding="utf-8")
        log.info("Summarizing %d chars → %s", len(transcript_text), session.summary)
        try:
            summarizer.summarize(transcript_text, session.summary)
        except Exception:
            log.exception("Summarization failed (continuing)")

        if session.summary.exists():
            log.info("Summary written: %s (%d bytes)", session.summary, session.summary.stat().st_size)
            notify(f"Summary ready — {session.summary.read_text()[:200]}")
        else:
            log.warning("Summary file not created")
            notify("Transcription complete.")
