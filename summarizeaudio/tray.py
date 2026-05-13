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
        icon.stop()
        try:
            self._window_manager.root.after(0, self._window_manager.root.quit)
        except Exception:
            pass

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

    def run(self) -> None:
        """Runs the pystray icon loop. Blocks until the icon is stopped.

        On macOS this is called from a background daemon thread (started in
        __main__.py), leaving the main thread free for tk.mainloop().
        On Windows/Linux it is also called from a background thread.
        """
        self._tray = pystray.Icon(
            "SummarizeAudio",
            icon=self._icons["idle"],
            title="SummarizeAudio",
        )
        self._rebuild_menu()

        def setup(icon: pystray.Icon) -> None:
            icon.visible = True

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
        self._tray.run(setup=setup)


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
        tray_thread = threading.Thread(target=app.run, daemon=True)
        tray_thread.start()
        app.window_manager.root.mainloop()
    except Exception:
        msg = format_error("startup", "SummarizeAudio could not start.", traceback.format_exc())
        notify(msg, "SummarizeAudio Error")
        raise SystemExit(1)
    finally:
        LOCK_FILE.unlink(missing_ok=True)
