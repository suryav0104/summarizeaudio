from __future__ import annotations

import logging
import queue
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import tkinter as tk

from summarizeaudio.config import AppConfig

if TYPE_CHECKING:
    from summarizeaudio.workflow_window import WorkflowWindow
    from summarizeaudio.history_window import HistoryWindow

log = logging.getLogger(__name__)


class WindowManager:
    """Owns the Tk root and all visible windows. Must be driven from the main thread."""

    def __init__(
        self,
        cfg: AppConfig,
        ui_queue: queue.Queue,
        on_icon_state: Callable[[str], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._ui_queue = ui_queue
        self._on_icon_state = on_icon_state
        self._root = tk.Tk()
        # Set accessory policy AFTER tk.Tk() so Tk has already created its
        # TKApplication subclass (which defines macOSVersion and other selectors
        # that newer NSApplication bottles check for). Setting it before Tk
        # initialises creates a plain NSApplication that lacks those selectors
        # and crashes on macOS Tahoe beta.
        if sys.platform == "darwin":
            try:
                import AppKit
                nsapp = AppKit.NSApplication.sharedApplication()
                nsapp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
            except Exception:
                pass
        self._root.withdraw()
        self._root.after(100, self._pump)
        self._workflow_win: WorkflowWindow | None = None
        self._history_win: HistoryWindow | None = None

    @property
    def root(self) -> tk.Tk:
        return self._root

    def show_workflow(
        self,
        mode: str,
        source: Path | None = None,
        resume_session_id: str | None = None,
    ) -> None:
        from summarizeaudio.workflow_window import WorkflowWindow

        if self._workflow_win is not None and _win_alive(self._workflow_win._win):
            if self._workflow_win.pipeline_active:
                self._workflow_win._focus()
                return
            self._workflow_win.retarget(mode, source, resume_session_id)
            return
        self._workflow_win = WorkflowWindow(
            self._root, self._cfg, self._ui_queue, mode, source, resume_session_id
        )
        self._workflow_win.show()

    def show_history(self) -> None:
        from summarizeaudio.history_window import HistoryWindow

        if self._history_win is not None and _win_alive(self._history_win._win):
            self._history_win.refresh()
            return
        self._history_win = HistoryWindow(self._root, self._cfg, self._ui_queue)
        self._history_win.show()

    def close_all(self) -> None:
        for win in (self._workflow_win, self._history_win):
            if win is not None:
                try:
                    win.close()
                except Exception:
                    pass
        self._workflow_win = None
        self._history_win = None

    def _pump(self) -> None:
        try:
            while True:
                item = self._ui_queue.get_nowait()
                self._handle(item)
        except queue.Empty:
            pass
        if self._root.winfo_exists():
            self._root.after(100, self._pump)

    def _handle(self, item: tuple) -> None:
        from summarizeaudio.error_handler import format_error
        from summarizeaudio.notifier import notify

        kind = item[0]

        if kind == "show_workflow":
            mode = item[1]
            source = item[2] if len(item) > 2 else None
            resume_session_id = item[3] if len(item) > 3 else None
            self.show_workflow(mode, source, resume_session_id)

        elif kind == "show_history":
            self.show_history()

        elif kind == "set_icon":
            _, state = item
            if self._on_icon_state is not None:
                try:
                    self._on_icon_state(state)
                except Exception:
                    log.debug("Error in on_icon_state callback", exc_info=True)

        elif kind == "error":
            _, component, message, tb = item
            notify(format_error(component, message, tb), "SummarizeAudio Error")
            self._forward(item)

        elif kind == "fatal_error":
            _, message, detail = item
            notify(format_error("fatal", message, detail), "SummarizeAudio — Fatal Error")
            self._forward(item)
            self._root.after(500, self._root.quit)

        else:
            self._forward(item)

    def _forward(self, item: tuple) -> None:
        if self._workflow_win is not None and _win_alive(self._workflow_win._win):
            try:
                self._workflow_win._handle_item(item)
            except Exception:
                log.debug("Error forwarding queue item %r", item, exc_info=True)


def _win_alive(win: tk.Toplevel) -> bool:
    try:
        return bool(win.winfo_exists())
    except Exception:
        return False
