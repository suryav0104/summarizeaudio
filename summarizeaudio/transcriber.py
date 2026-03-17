from __future__ import annotations

import queue
import traceback
from pathlib import Path

from summarizeaudio.error_handler import post_error
from summarizeaudio.notifier import notify


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
            if not self._is_model_cached():
                notify(f"Downloading Whisper '{self._model_name}' model, this may take a few minutes…")
            else:
                notify(f"Loading Whisper '{self._model_name}' model…")
            try:
                self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")
                notify("Whisper model ready.")
            except Exception as exc:
                post_error(self._ui_queue, "transcriber.py → faster_whisper",
                           str(exc), traceback.format_exc())
                raise

    def transcribe(self, audio_path: Path, out_txt: Path) -> None:
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        self._load_model()
        # faster-whisper expects language=None for auto-detection, not the string "auto"
        lang = None if self._language == "auto" else self._language
        try:
            segments, _ = self._model.transcribe(str(audio_path), language=lang)
            text = " ".join(seg.text.strip() for seg in segments)
            out_txt.write_text(text, encoding="utf-8")
        except Exception as exc:
            post_error(self._ui_queue, "transcriber.py → faster_whisper",
                       str(exc), traceback.format_exc())
            raise
