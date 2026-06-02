from __future__ import annotations

import logging
import queue
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import tkinter as tk

from summarizeaudio.config import AppConfig

if TYPE_CHECKING:
    from summarizeaudio.workflow_window import WorkflowWindow
    from summarizeaudio.history_window import HistoryWindow
    from summarizeaudio.settings_window import SettingsWindow

log = logging.getLogger(__name__)


class WindowManager:
    """Owns the Tk root and all visible windows. Must be driven from the main thread."""

    def __init__(
        self,
        cfg: AppConfig,
        ui_queue: queue.Queue,
        on_icon_state: Callable[[str], None] | None = None,
        on_rebuild_tray: Callable[[], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._ui_queue = ui_queue
        self._on_icon_state = on_icon_state
        self._on_rebuild_tray = on_rebuild_tray
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
        self._settings_win: SettingsWindow | None = None
        self._last_pipeline_active: bool = False
        self._error_active: bool = False
        self._prev_any_open: bool = False
        self._dock_icon: Any = None
        # A pipeline error surfaced with no window open can't clear via the
        # window-dismiss path (that needs an open->closed transition that never
        # happens). Auto-revert to idle after this delay so the red icon doesn't
        # stick forever; the macOS notification is the persistent record.
        self._error_auto_clear_ms: int = 12000

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

        # History window open — one window at a time.
        if self._history_win is not None and _win_alive(self._history_win._win):
            self._history_win._focus()
            self._history_win._show_toast("Close this window before starting a new action.")
            return

        if self._workflow_win is not None and _win_alive(self._workflow_win._win):
            if self._workflow_win._step_state == "chooser":
                # Nothing in progress — safe to retarget silently.
                self._workflow_win.retarget(mode, source, resume_session_id)
            else:
                # User is engaged — bring to front and explain.
                self._workflow_win._focus()
                self._workflow_win._show_toast(
                    "Close this window before starting a new action.",
                    duration_ms=6000,
                    color="#dc2626",
                )
            return

        self._workflow_win = WorkflowWindow(
            self._root, self._cfg, self._ui_queue, mode, source, resume_session_id
        )
        self._workflow_win.show()

    def block_for_open_window(self) -> bool:
        """Return True if a workflow/history window is open.

        Safe to call from any thread (pystray menu callbacks fire off the Tk
        main thread). Performs only Python-level reference checks — no Tk
        calls. When a window is detected, posts a `show_blocked_toast`
        message onto the UI queue so the actual focus + toast run on the
        main thread.
        """
        if self._workflow_win is None and self._history_win is None:
            return False
        try:
            self._ui_queue.put_nowait(("show_blocked_toast",))
        except Exception:
            pass
        return True

    def show_history(self) -> None:
        from summarizeaudio.history_window import HistoryWindow

        # Workflow window open — one window at a time.
        if self._workflow_win is not None and _win_alive(self._workflow_win._win):
            self._workflow_win._focus()
            self._workflow_win._show_toast(
                "Close this window before starting a new action.",
                duration_ms=6000,
                color="#dc2626",
            )
            return

        if self._history_win is not None and _win_alive(self._history_win._win):
            self._history_win._focus()  # Already open — just bring to front, no toast.
            return

        self._history_win = HistoryWindow(self._root, self._cfg, self._ui_queue)
        self._history_win.show()

    def show_settings(self, focus_target: str | None = None) -> None:
        """Open the Settings window. Stacks on top of Workflow/History; refocuses
        if already open. Does NOT participate in the Workflow ↔ History block.

        ``focus_target`` may be ``"input"`` or ``"model"`` to direct keyboard
        focus to the corresponding dropdown — used when the user clicks one of
        the inline status items in the tray menu."""
        from summarizeaudio.settings_window import SettingsWindow

        if self._settings_win is not None and _win_alive(self._settings_win._win):
            self._settings_win._focus()
            if focus_target:
                try:
                    self._settings_win.focus_target(focus_target)
                except Exception:
                    pass
            return

        self._settings_win = SettingsWindow(
            self._root,
            self._cfg,
            self._ui_queue,
            pipeline_active=self._last_pipeline_active,
            focus_target=focus_target,
        )
        self._settings_win.show()

    def close_all(self) -> None:
        for win in (self._workflow_win, self._history_win, self._settings_win):
            if win is not None:
                try:
                    win.close()
                except Exception:
                    pass
        self._workflow_win = None
        self._history_win = None
        self._settings_win = None

    def _load_dock_icon(self) -> Any:
        try:
            import AppKit
            assets = Path(__file__).parent.parent / "assets"
            path = assets / "dock_icon.png"
            if not path.exists():
                path = assets / "icon_idle.png"
            if path.exists():
                return AppKit.NSImage.alloc().initWithContentsOfFile_(str(path))
        except Exception:
            pass
        return None

    def _any_window_open(self) -> bool:
        return (
            (self._workflow_win is not None and _win_alive(self._workflow_win._win))
            or (self._history_win is not None and _win_alive(self._history_win._win))
            or (self._settings_win is not None and _win_alive(self._settings_win._win))
        )

    def _emit_icon_state(self, state: str) -> None:
        if self._on_icon_state is not None:
            try:
                self._on_icon_state(state)
            except Exception:
                log.debug("Error in on_icon_state callback", exc_info=True)

    def _clear_error_on_window_dismiss(self) -> None:
        """Clear a persistent error when the last open window closes.

        Only fires on the open->all-closed transition, so a device error that
        surfaced with no window open (cleared instead by health re-probe) is
        not dropped spuriously.
        """
        any_open = self._any_window_open()
        if self._error_active and self._prev_any_open and not any_open:
            self._error_active = False
            self._emit_icon_state("idle")
        self._prev_any_open = any_open

    def _schedule_error_auto_clear(self) -> None:
        """Arm a delayed revert-to-idle for a window-less pipeline error."""
        try:
            self._root.after(self._error_auto_clear_ms, self._auto_clear_error)
        except Exception:
            pass

    def _auto_clear_error(self) -> None:
        """Fired ~12s after a window-less pipeline error. Bail if a window opened
        meanwhile (defer to the dismiss path) or the error was already cleared by
        a new recording/pipeline; otherwise drop the sticky error and go idle."""
        if self._error_active and not self._any_window_open():
            self._error_active = False
            self._emit_icon_state("idle")

    def _update_activation_policy(self) -> None:
        """Show app in Dock + Cmd-Tab when a window is open; hide when all closed."""
        if sys.platform != "darwin":
            return
        try:
            import AppKit
            nsapp = AppKit.NSApplication.sharedApplication()
            any_open = self._any_window_open()
            policy = (
                AppKit.NSApplicationActivationPolicyRegular
                if any_open
                else AppKit.NSApplicationActivationPolicyAccessory
            )
            if nsapp.activationPolicy() != policy:
                nsapp.setActivationPolicy_(policy)
                if any_open:
                    if self._dock_icon is None:
                        self._dock_icon = self._load_dock_icon()
                    if self._dock_icon is not None:
                        nsapp.setApplicationIconImage_(self._dock_icon)
                    nsapp.activateIgnoringOtherApps_(True)
        except Exception:
            pass

    def _show_blocked_toast_main_thread(self) -> None:
        """Focus the open window and surface the 'close before starting' toast.
        Must run on the Tk main thread."""
        if self._workflow_win is not None and _win_alive(self._workflow_win._win):
            self._workflow_win._focus()
            self._workflow_win._show_toast(
                "Close this window before starting a new action.",
                duration_ms=6000,
                color="#dc2626",
            )
            return
        if self._history_win is not None and _win_alive(self._history_win._win):
            self._history_win._focus()
            self._history_win._show_toast("Close this window before starting a new action.")

    def _sweep_stale_window_refs(self) -> None:
        """Clear `_workflow_win` / `_history_win` when the underlying Tk widget
        has been destroyed. Must run on the main thread.

        Required so the thread-safe `block_for_open_window` (which only does
        None checks) doesn't return False positives after the user closes a
        window via its X button.
        """
        if self._workflow_win is not None and not _win_alive(self._workflow_win._win):
            self._workflow_win = None
        if self._history_win is not None and not _win_alive(self._history_win._win):
            self._history_win = None
        if self._settings_win is not None and not _win_alive(self._settings_win._win):
            self._settings_win = None

    def _pump(self) -> None:
        try:
            while True:
                item = self._ui_queue.get_nowait()
                self._handle(item)
        except queue.Empty:
            pass
        self._sweep_stale_window_refs()
        self._clear_error_on_window_dismiss()
        self._update_activation_policy()
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

        elif kind == "show_settings":
            target = item[1] if len(item) > 1 else None
            self.show_settings(focus_target=target)

        elif kind == "rebuild_tray_menu":
            if self._on_rebuild_tray is not None:
                try:
                    self._on_rebuild_tray()
                except Exception:
                    log.debug("Error in on_rebuild_tray callback", exc_info=True)

        elif kind == "show_blocked_toast":
            self._show_blocked_toast_main_thread()

        elif kind == "set_icon":
            _, state = item
            self._last_pipeline_active = state in {"recording", "processing"}
            # A persistent error survives the pipeline worker's auto-idle in
            # `finally`; only an explicit clear trigger may drop it.
            if state == "idle" and self._error_active:
                return
            if state in {"recording", "processing"}:
                self._error_active = False
            elif state == "error":
                self._error_active = True
            self._emit_icon_state(state)

        elif kind == "error":
            _, component, message, tb = item
            notify(format_error(component, message, tb), "SummarizeAudio Error")
            self._error_active = True
            self._emit_icon_state("error")
            self._forward(item)
            # No window to show this in -> no dismiss action will ever clear the
            # sticky error. Schedule a time-based auto-revert. With a window open
            # the error is shown in-window and clears on dismiss, so keep sticky.
            if not self._any_window_open():
                self._schedule_error_auto_clear()

        elif kind == "fatal_error":
            _, message, detail = item
            notify(format_error("fatal", message, detail), "SummarizeAudio — Fatal Error")
            self._error_active = True
            self._emit_icon_state("error")
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
            return
        # No live workflow window to show this. If the item carries a blocking
        # resolver (the pipeline worker is parked on resolver.wait(300) for an
        # override/name dialog), resolve it with None so the worker unblocks,
        # runs its finally, and posts ("set_icon","idle") — stopping the
        # processing pulse. Without this, closing the window before the dialog
        # arrives drops the item and leaves the worker (and the animation)
        # hanging until the 300s timeout.
        if item and item[0] in {"override_dialog", "name_dialog"}:
            resolver = item[1]
            try:
                resolver._resolve(None)
            except Exception:
                log.debug("Failed to resolve undeliverable %s", item[0], exc_info=True)


def _win_alive(win: tk.Toplevel) -> bool:
    try:
        return bool(win.winfo_exists())
    except Exception:
        return False
