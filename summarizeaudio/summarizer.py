from __future__ import annotations

import json
import queue
import subprocess
import sys
import traceback
from pathlib import Path

import requests

from summarizeaudio.config import BehaviorConfig, OllamaConfig, SummarizationConfig
from summarizeaudio.error_handler import post_error


class _OverrideEvent:
    """Holds prompt override result from ui_queue dialog."""
    def __init__(self) -> None:
        import threading
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
        prompt = self._summ_cfg.default_prompt.replace("{transcript}", transcript)

        if self._beh.show_override_dialog:
            override = _OverrideEvent()
            try:
                self._ui_queue.put_nowait(("override_dialog", override, prompt))
            except queue.Full:
                pass
            result = override.wait(timeout=300)
            if result is None:
                return  # user dismissed — skip summarization
            prompt = result

        try:
            response = requests.post(
                f"{self._ollama.host}/api/generate",
                json={"model": self._ollama.model, "prompt": prompt},
                stream=True,
                timeout=120,
            )
            response.raise_for_status()
        except Exception as exc:
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
                    break
            except json.JSONDecodeError:
                continue

        summary = "".join(text_parts).strip()
        out_md.write_text(summary, encoding="utf-8")

        if self._beh.auto_open_summary:
            _open_file(out_md)


def _open_file(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        import os
        os.startfile(str(path))
