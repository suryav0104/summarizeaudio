from __future__ import annotations

import queue
import threading
from datetime import date


def default_name(stem: str) -> str:
    today = date.today().strftime("%m-%d-%y")
    if stem.lower() == "recording":
        return f"Recording_{today}"
    return f"{stem}_{today}"


class Namer:
    """Posts a name-input dialog request and provides thread-safe result retrieval."""

    def __init__(self, ui_queue: queue.Queue, default: str) -> None:
        self._default = default
        self._event = threading.Event()
        self._name: str | None = None
        try:
            ui_queue.put_nowait(("name_dialog", self))
        except queue.Full:
            pass

    def _resolve(self, name: str | None) -> None:
        """Called by main thread when user submits or dismisses the dialog."""
        self._name = name
        self._event.set()

    def wait(self, timeout: float = 30) -> str:
        """Block until name is submitted or timeout; returns name or default."""
        self._event.wait(timeout=timeout)
        return self._name if self._name is not None else self._default
