from __future__ import annotations

import os
import platform
import queue
import signal
import subprocess
import sys
import threading
import traceback
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pystray
from PIL import Image

from summarizeaudio.config import load_config, save_config
from summarizeaudio.error_handler import format_error
from summarizeaudio.notifier import notify
from summarizeaudio.recorder import Recorder

if TYPE_CHECKING:
    from summarizeaudio.window_manager import WindowManager

ASSETS = Path(__file__).parent.parent / "assets"
LOCK_FILE = Path.home() / ".summarizeaudio" / "app.lock"
log = logging.getLogger(__name__)


def _patch_pystray_darwin(icon: "pystray.Icon") -> None:
    """Work around macOS Tahoe (NSSceneStatusItem) click-handling regression.

    pystray calls NSStatusItem.setMenu_(), which on Tahoe may silently fail
    to attach the popup menu to the click target.  The reliable modern path is:
      1. Leave statusItem.menu NIL (so the button's action selector fires).
      2. In the action handler, manually pop up the stored NSMenu.

    We monkey-patch _update_menu to skip setMenu_ and instead store the menu,
    then patch the ObjC delegate to pop it up on click.
    """
    import AppKit
    import objc

    # ── patch _update_menu ──────────────────────────────────────────────────
    original_create_menu = icon._create_menu  # bound method

    def _patched_update_menu(self) -> None:  # type: ignore[override]
        callbacks: list = []
        nsmenu = original_create_menu(self.menu, callbacks)
        if nsmenu is not None:
            # Keep the menu handle so the action handler can reach it.
            self._menu_handle = (nsmenu, callbacks)
            # Try the old path too – harmless if Tahoe ignores it.
            try:
                self._status_item.setMenu_(nsmenu)
            except Exception:
                pass
        else:
            self._menu_handle = None
            try:
                self._status_item.setMenu_(None)
            except Exception:
                pass

    # Bind to the Icon *instance* so we don't break other icons.
    icon._update_menu = _patched_update_menu.__get__(icon, type(icon))  # type: ignore[method-assign]

    # ── patch ObjC delegate to pop up the menu on click ─────────────────────
    # We subclass IconDelegate dynamically (ObjC doesn't allow per-instance
    # method swaps), then swap the delegate on the button.
    existing_delegate = icon._delegate

    class _PatchedDelegate(type(existing_delegate)):  # type: ignore[misc]
        @objc.namedSelector(b"activate:sender")
        def activate_button(self, sender) -> None:  # type: ignore[override]
            icon_ref = getattr(self, "icon", None)
            if icon_ref is None:
                return
            menu_handle = getattr(icon_ref, "_menu_handle", None)
            if menu_handle:
                nsmenu, _callbacks = menu_handle
                btn = icon_ref._status_item.button()
                # Pop the menu up from the bottom-left of the button,
                # which places it just below the menu bar item.
                loc = AppKit.NSPoint(0, btn.bounds().size.height)
                nsmenu.popUpMenuPositioningItem_atLocation_inView_(
                    None, loc, btn
                )
            else:
                # No menu – fall back to the original default action.
                icon_ref()

    new_delegate = _PatchedDelegate.alloc().init()
    new_delegate.icon = existing_delegate.icon  # copy the weak/strong ref
    icon._delegate = new_delegate
    try:
        icon._status_item.button().setTarget_(new_delegate)
    except Exception as exc:
        log.debug("_patch_pystray_darwin: could not swap delegate: %s", exc)


def _load_icon(name: str) -> Image.Image:
    suffix = ".ico" if platform.system() == "Windows" else ".png"
    path = ASSETS / f"{name}{suffix}"
    if path.exists():
        return Image.open(path)
    img = Image.new("RGBA", (64, 64), (120, 120, 120, 255))
    return img


class TrayApp:
    def __init__(self) -> None:
        self._ui_queue: queue.Queue = queue.Queue()
        self._pipeline_running = threading.Event()
        self._stop_event = threading.Event()
        self._recorder: Recorder | None = None
        self._cfg = load_config(self._ui_queue)

        root = self._cfg.storage.output_folder
        for sub in ("AudioFiles", "TranscriptionFiles", "SummaryFiles"):
            (root / sub).mkdir(parents=True, exist_ok=True)

        self._icons = {
            "idle":       _load_icon("icon_idle"),
            "recording":  _load_icon("icon_recording"),
            "processing": _load_icon("icon_processing"),
            "error":      _load_icon("icon_error"),
        }
        self._tray: pystray.Icon | None = None

        # WindowManager owns the Tk root and all visible windows.
        # Imported here to avoid circular imports at module level.
        from summarizeaudio.window_manager import WindowManager
        self._window_manager = WindowManager(
            self._cfg, self._ui_queue, on_icon_state=self._on_icon_state
        )

    @property
    def window_manager(self) -> "WindowManager":
        return self._window_manager

    # ── Menu actions ──────────────────────────────────────────────────────────

    def _on_start_recording(self, icon, item) -> None:
        if self._pipeline_running.is_set():
            return
        recorder = Recorder(self._cfg.storage.output_folder, self._cfg.recording.input_device)
        try:
            recorder.start()
        except Exception as exc:
            recorder.cleanup(delete_wav=True)
            notify(
                format_error("tray.py → recorder", str(exc), traceback.format_exc()),
                "SummarizeAudio Error",
            )
            return
        self._recorder = recorder
        self._set_icon("recording")
        self._rebuild_menu()

    def _on_stop_recording(self, icon, item) -> None:
        recorder = self._recorder
        if recorder is None:
            return
        try:
            mp3_path, _start, _end = recorder.stop()
        except Exception as exc:
            recorder.cleanup(delete_wav=False)
            self._recorder = None
            notify(
                format_error("tray.py → recorder", str(exc), traceback.format_exc()),
                "SummarizeAudio Error",
            )
            self._set_icon("idle")
            self._rebuild_menu()
            return

        self._recorder = None
        self._set_icon("idle")
        self._rebuild_menu()
        self._ui_queue.put(("show_workflow", "record", mp3_path, None))

    def _on_local_audio(self, icon, item) -> None:
        self._ui_queue.put(("show_workflow", "audio", None, None))

    def _on_local_text(self, icon, item) -> None:
        self._ui_queue.put(("show_workflow", "text", None, None))

    def _on_history(self, icon, item) -> None:
        self._ui_queue.put(("show_history",))

    def _on_quality_fast(self, icon, item) -> None:
        self._set_model("gemma3:4b", "Fast (4B)")

    def _on_quality_high(self, icon, item) -> None:
        self._set_model("gemma3:12b", "High Quality (12B)")

    def _model_label(self, model: str, label: str) -> str:
        return f"✓ {label}" if self._cfg.ollama.model == model else label

    def _on_quit(self, icon, item) -> None:
        LOCK_FILE.unlink(missing_ok=True)
        self._stop_event.set()
        # Hide the icon immediately so it vanishes from the menu bar even if
        # the subsequent stop/quit sequence stalls.
        try:
            self._tray.visible = False
        except Exception:
            pass
        # Defer stop + Tk quit to after this menu callback returns.  Calling
        # icon.stop() synchronously from inside a pystray callback can deadlock
        # on macOS because pystray is integrated into Tk's NSApplication loop.
        def _do_quit() -> None:
            try:
                icon.stop()
            except Exception:
                pass
            try:
                self._window_manager.root.quit()
            except Exception:
                pass
        try:
            self._window_manager.root.after(50, _do_quit)
        except Exception:
            _do_quit()
        # Hard-kill safety net: if the process is still alive after 3 s
        # (e.g. a stuck daemon thread), force-exit unconditionally.
        threading.Timer(3.0, lambda: os._exit(0)).start()

    # ── Icon state callback (invoked from WindowManager on main thread) ───────

    def _on_icon_state(self, state: str) -> None:
        if state == "processing":
            self._pipeline_running.set()
        else:
            self._pipeline_running.clear()
        self._set_icon(state)
        self._rebuild_menu()

    # ── Icon and menu helpers ─────────────────────────────────────────────────

    def _set_model(self, model: str, label: str) -> None:
        self._cfg.ollama.model = model
        save_config(self._cfg)
        self._rebuild_menu()

    def _set_icon(self, state: str) -> None:
        if self._tray:
            self._tray.icon = self._icons.get(state, self._icons["idle"])

    def _rebuild_menu(self) -> None:
        if self._tray is None:
            return
        recording = self._recorder is not None
        processing = self._pipeline_running.is_set()
        items = []
        if recording:
            items.append(pystray.MenuItem("Stop Recording", self._on_stop_recording))
        elif not processing:
            items.append(pystray.MenuItem("Start Recording", self._on_start_recording))
            items.append(pystray.MenuItem(
                "Transcribe & Summarize Audio File…", self._on_local_audio))
            items.append(pystray.MenuItem(
                "Summarize Text File…", self._on_local_text))
            items.append(pystray.Menu.SEPARATOR)
            items.append(pystray.MenuItem("History…", self._on_history))
            items.append(pystray.Menu.SEPARATOR)
            items.append(pystray.MenuItem("Summarization Model", None, enabled=False))
            fast_label = self._model_label("gemma3:4b", "Fast Mode (gemma3:4b)")
            high_label = self._model_label("gemma3:12b", "High Quality Mode (gemma3:12b)")
            items.append(pystray.MenuItem(fast_label, self._on_quality_fast))
            items.append(pystray.MenuItem(high_label, self._on_quality_high))
        else:
            items.append(pystray.MenuItem("Processing…", None, enabled=False))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit", self._on_quit))
        self._tray.menu = pystray.Menu(*items)

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            elif hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:
            notify(format_error("tray.py → open", str(exc), traceback.format_exc()), "SummarizeAudio Error")

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _create_icon(self) -> None:
        """Creates the pystray Icon and rebuilds the menu.

        Must be called from the main thread on macOS — NSStatusItem creation
        requires the main thread on Tahoe and later.
        """
        kwargs: dict = {}
        if sys.platform == "darwin":
            try:
                import AppKit
                # By this point tk.Tk() has already created TKApplication
                # (Tk's NSApplication subclass, which defines macOSVersion and
                # other selectors). Passing it here tells pystray to use that
                # existing NSApplication rather than creating a new one.
                kwargs["nsapplication"] = AppKit.NSApplication.sharedApplication()
            except Exception:
                pass
        self._tray = pystray.Icon(
            "SummarizeAudio",
            icon=self._icons["idle"],
            title="SummarizeAudio",
            **kwargs,
        )
        if sys.platform == "darwin":
            _patch_pystray_darwin(self._tray)
        self._rebuild_menu()

    def _setup_signals(self) -> None:
        def _handle_signal(sig, frame) -> None:
            LOCK_FILE.unlink(missing_ok=True)
            self._stop_event.set()
            if self._tray is not None:
                self._tray.stop()
            try:
                self._window_manager.root.after(0, self._window_manager.root.quit)
            except Exception:
                pass

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

    def run(self) -> None:
        """Runs the pystray icon loop (Windows/Linux background thread path)."""
        self._create_icon()
        self._setup_signals()
        self._tray.run(setup=lambda icon: setattr(icon, "visible", True))

    def run_detached(self) -> None:
        """Starts pystray without its own event loop (macOS main-thread path).

        Must be called from the main thread before entering Tk's mainloop.
        Tk drives the shared NSApplication event loop, so pystray status bar
        events are delivered through it automatically.
        """
        self._create_icon()
        self._setup_signals()
        # run_detached with a no-op setup so pystray marks itself ready but
        # doesn't try to set visibility from a background thread (NSView updates
        # must happen on the main thread on macOS).
        self._tray.run_detached(setup=lambda icon: None)
        # Show the icon here, on the main thread, before entering mainloop.
        self._tray.visible = True


def _check_single_instance() -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            if _pid_alive(pid):
                notify("SummarizeAudio is already running.")
                sys.exit(0)
        except (ValueError, OSError):
            pass
    LOCK_FILE.write_text(str(os.getpid()))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def run() -> None:
    try:
        _check_single_instance()
        app = TrayApp()
        if sys.platform == "darwin":
            # On macOS, NSStatusItem must be created on the main thread and
            # pystray must not run its own NSApp event loop (Tk owns it).
            app.run_detached()
        else:
            tray_thread = threading.Thread(target=app.run, daemon=True)
            tray_thread.start()
        app.window_manager.root.mainloop()
    except Exception:
        msg = format_error("startup", "SummarizeAudio could not start.", traceback.format_exc())
        notify(msg, "SummarizeAudio Error")
        raise SystemExit(1)
    finally:
        LOCK_FILE.unlink(missing_ok=True)
        # Force-terminate so daemon threads (Whisper, pyannote, Ollama) can't
        # keep a ghost process — and therefore a ghost menu bar icon — alive.
        os._exit(0)
