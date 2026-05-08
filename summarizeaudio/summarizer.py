from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

log = logging.getLogger(__name__)

import requests

from summarizeaudio.config import BehaviorConfig, OllamaConfig, SummarizationConfig
from summarizeaudio.error_handler import friendly_message

_CHUNK_TRIGGER_CHARS = 8000
_CHUNK_TARGET_CHARS = 6000
_CHUNK_OVERLAP_CHARS = 500


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable or returns an unexpected error."""


class _OverrideEvent:
    """Holds prompt override result from ui_queue dialog."""
    def __init__(self) -> None:
        self._event = threading.Event()
        self._prompt: str | None = None

    def _resolve(self, prompt: str | None) -> None:
        self._prompt = prompt
        self._event.set()

    def wait(self, timeout: float = 300) -> str | None:
        self._event.wait(timeout=timeout)
        return self._prompt


class Summarizer:
    def __init__(
        self,
        ollama: OllamaConfig,
        summ_cfg: SummarizationConfig,
        beh: BehaviorConfig,
        ui_queue: queue.Queue,
    ) -> None:
        self._ollama = ollama
        self._summ_cfg = summ_cfg
        self._beh = beh
        self._ui_queue = ui_queue

    def summarize(self, transcript: str, out_md: Path) -> None:
        template = self._summ_cfg.default_prompt
        log.info("Summarize: %d-char transcript → %s (model=%s)", len(transcript), out_md.name, self._ollama.model)

        if self._beh.show_override_dialog:
            # Show the template (with {transcript} placeholder, not the full expanded prompt)
            # so it fits within AppleScript's ~254-char default-answer limit.
            # The transcript is injected after the user confirms.
            override = _OverrideEvent()
            posted = False
            try:
                self._ui_queue.put_nowait(("override_dialog", override, template))
                posted = True
                log.debug("Override dialog posted to ui_queue")
            except queue.Full:
                log.warning("ui_queue full — skipping override dialog, using default prompt")
            if posted:
                log.debug("Waiting for override dialog response (timeout=300s)")
                result = override.wait(timeout=300)
                if result is None:
                    log.info("Override dialog dismissed — skipping summarization")
                    return
                log.debug("Override dialog resolved, template length=%d", len(result))
                template = result

        transcript_chunks = _chunk_transcript(transcript)
        if len(transcript_chunks) <= 1:
            summary = self._summarize_prompt(template.replace("{transcript}", transcript))
        else:
            log.info(
                "Transcript exceeds chunk threshold (%d chars) — summarizing in %d chunks",
                len(transcript),
                len(transcript_chunks),
            )
            chunk_summaries: list[str] = []
            for idx, chunk_text in enumerate(transcript_chunks, start=1):
                log.info("Summarizing chunk %d/%d (%d chars)", idx, len(transcript_chunks), len(chunk_text))
                chunk_summary = self._summarize_prompt(template.replace("{transcript}", chunk_text))
                chunk_summaries.append(chunk_summary)
            combined_input = (
                "These are summaries of chunks from one longer transcript. "
                "Combine them into one final summary. Keep the same important sections, "
                "preserve key facts, and remove duplicated wording.\n\n"
                + "\n\n---\n\n".join(
                    f"Chunk {idx} summary:\n{chunk_summary}"
                    for idx, chunk_summary in enumerate(chunk_summaries, start=1)
                )
            )
            summary = self._summarize_prompt(template.replace("{transcript}", combined_input))

        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(summary, encoding="utf-8")
        log.info("Summary written: %d chars → %s", len(summary), out_md)

        if self._beh.auto_open_summary:
            _open_file(out_md)

    def _summarize_prompt(self, prompt: str) -> str:
        log.info("POSTing to Ollama %s/api/generate (model=%s)", self._ollama.host, self._ollama.model)
        try:
            response = requests.post(
                f"{self._ollama.host}/api/generate",
                json={"model": self._ollama.model, "prompt": prompt},
                stream=True,
                timeout=120,
            )
            response.raise_for_status()
            log.info("Ollama responded HTTP %d — streaming tokens", response.status_code)
        except Exception as exc:
            log.exception("Ollama request failed")
            detail = str(exc)
            response_obj = getattr(exc, "response", None)
            if response_obj is not None:
                body = getattr(response_obj, "text", "")
                if body:
                    detail = f"{detail}\n{body}"
            raise OllamaError(
                friendly_message(
                    "summarizer.py → ollama",
                    detail,
                    traceback.format_exc(),
                )
            ) from exc

        text_parts: list[str] = []
        for line in response.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                text_parts.append(chunk.get("response", ""))
                if chunk.get("done"):
                    log.info("Ollama stream complete — %d chars generated", sum(len(p) for p in text_parts))
                    break
            except json.JSONDecodeError:
                continue

        return "".join(text_parts).strip()


def _chunk_transcript(transcript: str) -> list[str]:
    if len(transcript) <= _CHUNK_TRIGGER_CHARS:
        return [transcript]

    chunks: list[str] = []
    start = 0
    total = len(transcript)
    while start < total:
        window_end = min(start + _CHUNK_TARGET_CHARS, total)
        end = window_end
        if window_end < total:
            boundary = _find_chunk_boundary(transcript, start, window_end)
            if boundary > start + (_CHUNK_TARGET_CHARS // 2):
                end = boundary
        if end <= start:
            end = min(start + _CHUNK_TARGET_CHARS, total)
        chunk = transcript[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= total:
            break
        next_start = max(end - _CHUNK_OVERLAP_CHARS, start + 1)
        if next_start <= start:
            next_start = end
        start = next_start
    return chunks


def _find_chunk_boundary(text: str, start: int, end: int) -> int:
    window = text[start:end]
    for separator in ("\n\n", "\n", ". ", "! ", "? "):
        idx = window.rfind(separator)
        if idx > 0:
            return start + idx + len(separator)
    idx = window.rfind(" ")
    if idx > 0:
        return start + idx + 1


def _open_file(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        import os
        os.startfile(str(path))
