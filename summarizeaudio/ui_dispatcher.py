from __future__ import annotations

import logging
import queue
from typing import Callable


class UIDispatcher:
    """Thread-safe queue drain for main-thread UI operations."""

    def __init__(self, q: queue.Queue) -> None:
        self._queue = q
        self._handlers: dict[str, Callable] = {}

    def register(self, action: str, handler: Callable) -> None:
        self._handlers[action] = handler

    def drain(self) -> None:
        """Call from main thread to execute all pending UI actions."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            action, *args = item
            handler = self._handlers.get(action)
            if handler is not None:
                try:
                    handler(*args)
                except Exception:
                    logging.exception("UIDispatcher: handler %r raised an exception", action)
