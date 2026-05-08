from __future__ import annotations

import logging
import queue
import traceback
from pathlib import Path

log = logging.getLogger(__name__)

from summarizeaudio.error_handler import friendly_message, post_error


class Transcriber:
    """Wraps faster-whisper for local transcription."""

    def __init__(self, model: str, language: str, ui_queue: queue.Queue) -> None:
        self._model_name = model
        self._language = language
        self._ui_queue = ui_queue
        self._model = None  # lazy-loaded

    def _is_model_cached(self) -> bool:
        """Check if the model is already cached locally by faster-whisper / HuggingFace."""
        import os
        cache_dir = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
        # faster-whisper stores models under hub/models--Systran--faster-whisper-{name}
        model_dir = cache_dir / "hub" / f"models--Systran--faster-whisper-{self._model_name}"
        return model_dir.exists()

    def _load_model(self) -> None:
        from faster_whisper import WhisperModel
        if self._model is None:
            cached = self._is_model_cached()
            log.info("Whisper model '%s' cached=%s — loading", self._model_name, cached)
            try:
                self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")
                log.info("Whisper model '%s' loaded", self._model_name)
            except Exception as exc:
                log.exception("Failed to load Whisper model '%s'", self._model_name)
                message = friendly_message(
                    "transcriber.py → faster_whisper",
                    str(exc),
                    traceback.format_exc(),
                )
                post_error(
                    self._ui_queue,
                    "transcriber.py → faster_whisper",
                    message,
                    traceback.format_exc(),
                )
                raise

    def transcribe(self, audio_path: Path, out_txt: Path) -> None:
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        self._load_model()
        lang = None if self._language == "auto" else self._language
        log.info("Transcribing %s (language=%s)", audio_path.name, lang)
        try:
            segments, info = self._model.transcribe(str(audio_path), language=lang)
            log.info("Transcription detected language=%s duration=%.1fs",
                     getattr(info, "language", "?"), getattr(info, "duration", 0))
            text = " ".join(seg.text.strip() for seg in segments)
            out_txt.write_text(text, encoding="utf-8")
            log.info("Transcription written: %d chars → %s", len(text), out_txt)
        except Exception as exc:
            log.exception("Transcription error for %s", audio_path)
            message = friendly_message(
                "transcriber.py → faster_whisper",
                str(exc),
                traceback.format_exc(),
            )
            post_error(
                self._ui_queue,
                "transcriber.py → faster_whisper",
                message,
                traceback.format_exc(),
            )
            raise
