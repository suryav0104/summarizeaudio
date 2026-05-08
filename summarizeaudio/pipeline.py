from __future__ import annotations

import enum
import logging
import queue
import re
import shutil
import tempfile
import threading
import traceback
from pathlib import Path
from uuid import uuid4

log = logging.getLogger(__name__)

from summarizeaudio.config import AppConfig
from summarizeaudio.error_handler import friendly_message, post_error
from summarizeaudio.renamer import Renamer
from summarizeaudio.summarizer import Summarizer, OllamaError
from summarizeaudio.transcriber import Transcriber


class _NameEvent:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._name: str | None = None

    def _resolve(self, name: str | None) -> None:
        self._name = name
        self._event.set()

    def wait(self, timeout: float = 300) -> str | None:
        self._event.wait(timeout=timeout)
        return self._name


_NAME_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was",
    "were", "will", "have", "has", "had", "into", "onto", "about", "after",
    "before", "over", "under", "between", "your", "their", "our", "they",
    "them", "then", "than", "when", "where", "what", "which", "who", "whom",
    "how", "why", "you", "a", "an", "of", "to", "in", "on", "at", "by", "is",
    "it", "as", "be", "or", "if", "we", "i", "not", "no", "yes",
}

_NAME_HEADINGS = {
    "key points",
    "decisions",
    "decisions / action items",
    "action items",
    "notable details",
    "summary",
    "transcript",
    "overview",
    "notes",
}


def _derive_default_name(text: str, fallback: str = "Untitled") -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[#*\-\s]+", "", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = line.replace(":", " ")
        normalized = re.sub(r"\s+", " ", line).strip().lower().rstrip(".")
        if line and normalized not in _NAME_HEADINGS:
            lines.append(line)

    candidate = lines[0] if lines else fallback
    words = re.findall(r"[A-Za-z0-9']+", candidate)
    filtered = [w for w in words if w.lower() not in _NAME_STOPWORDS]
    chosen = filtered or words or [fallback]
    return " ".join(chosen[:6]).strip() or fallback


class PipelineMode(enum.Enum):
    RECORD = "record"
    LOCAL_AUDIO = "local_audio"
    LOCAL_TEXT = "local_text"


class Pipeline:
    def __init__(self, cfg: AppConfig, ui_queue: queue.Queue) -> None:
        self._cfg = cfg
        self._ui_queue = ui_queue
        self._error_posted = False

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
        self._error_posted = False
        try:
            self._run_inner(mode, session_name, mp3_path, source_path)
        except Exception as exc:
            tb = traceback.format_exc()
            log.exception("Pipeline failed: mode=%s session=%r", mode.value, session_name)
            if not self._error_posted:
                self._post_error(
                    "pipeline.py",
                    friendly_message("pipeline.py", str(exc), tb),
                    tb,
                )
            return
        finally:
            log.info("Pipeline finished: mode=%s session=%r", mode.value, session_name)
            if done_event is not None:
                done_event.clear()

    def _request_final_name(self, default_name: str) -> str | None:
        name_event = _NameEvent()
        try:
            self._ui_queue.put_nowait(("name_dialog", name_event, default_name))
        except queue.Full:
            log.warning("ui_queue full — skipping name dialog, using default name")
            return default_name
        log.debug("Waiting for final name response")
        result = name_event.wait(timeout=300)
        if result is None:
            log.info("Name dialog dismissed — using default name")
            return default_name
        result = result.strip()
        return result or default_name

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
            # Mode 3: copy text → summarize → ask for final name
            assert source_path is not None
            log.info("Mode 3: copying text file %s", source_path)
            session_id = str(uuid4())
            tmp_txt = cfg.storage.output_folder / f"{session_id}.txt"
            tmp_md = cfg.storage.output_folder / f"{session_id}.md"
            shutil.copy2(source_path, tmp_txt)
            transcript_text = tmp_txt.read_text(encoding="utf-8-sig", errors="replace")
            log.info("Mode 3: summarizing %d chars", len(transcript_text))
            try:
                summarizer.summarize(transcript_text, tmp_md)
            except OllamaError as exc:
                log.exception("Mode 3: Ollama unavailable")
                self._ui_queue.put_nowait(("fatal_error", "Ollama is not running or has crashed.", str(exc)))
                return
            if not tmp_md.exists():
                self._ui_queue.put_nowait(("info_dialog", "Transcription complete.", "No summary file was created."))
                return
            summary_text = tmp_md.read_text(encoding="utf-8-sig", errors="replace")
            final_name = self._request_final_name(_derive_default_name(summary_text, fallback=session_name))
            if final_name is None:
                return
            session = renamer.rename_session(final_name, mp3_path=None, txt_path=tmp_txt)
            shutil.move(str(tmp_md), session.summary)
            self._ui_queue.put_nowait(("summary_ready", session.summary))
            return

        # Mode 1 or 2: transcribe first
        session_id = str(uuid4())
        tmp_txt = cfg.storage.output_folder / f"{session_id}.txt"
        tmp_md = cfg.storage.output_folder / f"{session_id}.md"

        if mode == PipelineMode.RECORD:
            assert mp3_path is not None
            audio_for_transcription = mp3_path
        else:
            assert source_path is not None
            audio_for_transcription = source_path

        AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".webm"}
        if audio_for_transcription.suffix.lower() not in AUDIO_EXTENSIONS:
            self._post_error(
                "pipeline.py",
                f"'{audio_for_transcription.name}' is not a supported audio file. "
                "Please select an audio file (mp3, wav, m4a, etc.).",
                "",
            )
            return

        log.info("Transcribing %s → %s", audio_for_transcription.name, tmp_txt.name)
        transcription_source = audio_for_transcription
        temp_audio_copy: Path | None = None
        if mode == PipelineMode.LOCAL_AUDIO:
            temp_audio_copy = Path(tempfile.gettempdir()) / f"summarizeaudio-{uuid4()}{audio_for_transcription.suffix}"
            log.info("Copying source audio to local temp file %s", temp_audio_copy.name)
            try:
                shutil.copyfile(audio_for_transcription, temp_audio_copy)
            except Exception as exc:
                tb = traceback.format_exc()
                log.exception("Could not copy source audio to local temp file: %s", audio_for_transcription)
                self._post_error(
                    "pipeline.py",
                    friendly_message("pipeline.py", str(exc), tb),
                    tb,
                )
                return
            transcription_source = temp_audio_copy
        try:
            transcriber.transcribe(transcription_source, tmp_txt)
        except Exception as exc:
            log.exception("Transcription failed for %s", audio_for_transcription)
            self._post_error(
                "pipeline.py → transcriber",
                friendly_message(
                    "pipeline.py → transcriber",
                    str(exc),
                    traceback.format_exc(),
                ),
                traceback.format_exc(),
            )
            if mode == PipelineMode.LOCAL_AUDIO and tmp_txt.exists():
                tmp_txt.unlink()
            raise
        log.info("Transcription complete, output: %s", tmp_txt)

        transcript_text = tmp_txt.read_text(encoding="utf-8-sig", errors="replace").strip()
        if len(transcript_text) < 20:
            log.warning("Transcript too short (%d chars) — skipping summarization", len(transcript_text))
            if mode == PipelineMode.RECORD:
                title = "No usable audio was captured."
                message = "Check your microphone or system audio input, then try recording again."
            else:
                title = "No usable speech was found."
                message = (
                    "The selected audio file did not produce enough transcript text to summarize. "
                    "Make sure the file contains clear speech, then try again."
                )
            self._ui_queue.put_nowait(
                (
                    "info_dialog",
                    title,
                    message,
                )
            )
            return
        log.info("Summarizing %d chars → %s", len(transcript_text), tmp_md)
        try:
            summarizer.summarize(transcript_text, tmp_md)
        except OllamaError as exc:
            log.exception("Ollama unavailable")
            self._ui_queue.put_nowait(("fatal_error", "Ollama is not running or has crashed.", str(exc)))
            return

        if not tmp_md.exists():
            log.warning("Summary file not created")
            self._ui_queue.put_nowait(("info_dialog", "Transcription complete.", "No summary file was created."))
            return

        summary_text = tmp_md.read_text(encoding="utf-8-sig", errors="replace")
        final_name = self._request_final_name(_derive_default_name(summary_text, fallback=session_name))
        if final_name is None:
            return

        if mode == PipelineMode.RECORD:
            session = renamer.rename_session(final_name, mp3_path=mp3_path, txt_path=tmp_txt)
        else:
            assert temp_audio_copy is not None
            session = renamer.rename_session(final_name, mp3_path=temp_audio_copy, txt_path=tmp_txt)
        log.info("Files moved → transcript=%s", session.transcript)
        shutil.move(str(tmp_md), session.summary)
        log.info("Summary written: %s (%d bytes)", session.summary, session.summary.stat().st_size)
        if temp_audio_copy is not None and temp_audio_copy.exists():
            temp_audio_copy.unlink(missing_ok=True)
        self._ui_queue.put_nowait(("summary_ready", session.summary))

    def _post_error(self, component: str, message: str, traceback_str: str) -> None:
        self._error_posted = True
        post_error(self._ui_queue, component, message, traceback_str)
