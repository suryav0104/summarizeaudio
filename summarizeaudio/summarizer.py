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
from summarizeaudio.error_handler import post_error


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

        prompt = template.replace("{transcript}", transcript)

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
            post_error(self._ui_queue, "summarizer.py → Ollama",
                       str(exc), traceback.format_exc())
            raise

        # Accumulate streamed response
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

        summary = "".join(text_parts).strip()
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(summary, encoding="utf-8")
        log.info("Summary written: %d chars → %s", len(summary), out_md)

        if self._beh.auto_open_summary:
            _open_file(out_md)


def _open_file(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        import os
        os.startfile(str(path))
