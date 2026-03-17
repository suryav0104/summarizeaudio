from __future__ import annotations

import os
import platform
import queue
import sys
import threading
from datetime import date
from pathlib import Path

import pystray
from PIL import Image

from summarizeaudio.config import load_config
from summarizeaudio.error_handler import format_error, post_error
from summarizeaudio.namer import Namer, default_name
from summarizeaudio.notifier import notify
from summarizeaudio.pipeline import Pipeline, PipelineMode
from summarizeaudio.recorder import Recorder
from summarizeaudio.ui_dispatcher import UIDispatcher

ASSETS = Path(__file__).parent.parent / "assets"
LOCK_FILE = Path.home() / ".summarizeaudio" / "app.lock"


def _load_icon(name: str) -> Image.Image:
    suffix = ".ico" if platform.system() == "Windows" else ".png"
    path = ASSETS / f"{name}{suffix}"
    if path.exists():
        return Image.open(path)
    # Fallback: solid color square
    from PIL import ImageDraw
    img = Image.new("RGBA", (64, 64), (120, 120, 120, 255))
    return img


class TrayApp:
    def __init__(self) -> None:
        self._ui_queue: queue.Queue = queue.Queue()
        self._dispatcher = UIDispatcher(self._ui_queue)
        self._pipeline_running = threading.Event()
        self._recorder: Recorder | None = None
        self._namer: Namer | None = None
        self._cfg = load_config(self._ui_queue)
        self._pipeline = Pipeline(cfg=self._cfg, ui_queue=self._ui_queue)

        # Ensure output folders exist
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

        # Register all ui_queue handlers up front (must happen before run())
        self._dispatcher.register("set_icon", self._on_set_icon)
        self._dispatcher.register("error", self._on_error)
        self._dispatcher.register("name_dialog", self._on_name_dialog)
        self._dispatcher.register("override_dialog", self._on_override_dialog)
        self._dispatcher.register("local_audio_flow", self._run_local_audio_flow)
        self._dispatcher.register("local_text_flow", self._run_local_text_flow)

    # ── Menu actions ──────────────────────────────────────────────────────────

    def _on_start_recording(self, icon, item) -> None:
        if self._pipeline_running.is_set():
            return
        today = date.today().strftime("%m-%d-%y")
        self._namer = Namer(self._ui_queue, default=f"Recording_{today}")
        self._recorder = Recorder(self._cfg.storage.output_folder)
        self._recorder.start()
        self._set_icon("recording")
        self._rebuild_menu()

    def _on_stop_recording(self, icon, item) -> None:
        if self._recorder is None:
            return
        try:
            mp3_path, _start, _end = self._recorder.stop()
        except ValueError as exc:
            notify(str(exc))
            self._set_icon("idle")
            self._rebuild_menu()
            return

        name = self._namer.wait(timeout=30) if self._namer else f"Recording_{date.today().strftime('%m-%d-%y')}"
        self._recorder = None
        self._namer = None
        self._pipeline_running.set()
        self._set_icon("processing")
        self._rebuild_menu()

        def run():
            # pipeline clears pipeline_running via done_event in its own finally block
            self._pipeline.run(
                mode=PipelineMode.RECORD,
                session_name=name,
                mp3_path=mp3_path,
                done_event=self._pipeline_running,
            )
            self._ui_queue.put_nowait(("set_icon", "idle"))

        threading.Thread(target=run, daemon=True).start()

    def _on_local_audio(self, icon, item) -> None:
        if self._pipeline_running.is_set():
            return
        self._ui_queue.put_nowait(("local_audio_flow",))

    def _on_local_text(self, icon, item) -> None:
        if self._pipeline_running.is_set():
            return
        self._ui_queue.put_nowait(("local_text_flow",))

    def _on_quit(self, icon, item) -> None:
        LOCK_FILE.unlink(missing_ok=True)
        icon.stop()

    # ── UI queue handlers (run on main thread) ────────────────────────────────

    def _on_set_icon(self, state: str) -> None:
        self._set_icon(state)

    def _on_error(self, component: str, message: str, tb: str) -> None:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw()
        messagebox.showerror("SummarizeAudio Error", format_error(component, message, tb))
        root.destroy()
        self._pipeline_running.clear()
        self._set_icon("idle")
        self._rebuild_menu()

    def _on_name_dialog(self, namer: Namer) -> None:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk(); root.withdraw()
        result = simpledialog.askstring(
            "Session Name", "Enter a name for this recording:",
            parent=root,
        )
        root.destroy()
        namer._resolve(result)

    def _on_override_dialog(self, override, prompt: str) -> None:
        import tkinter as tk
        from tkinter.scrolledtext import ScrolledText
        root = tk.Tk()
        root.title("Edit Summarization Prompt")
        text = ScrolledText(root, width=80, height=20)
        text.insert("1.0", prompt)
        text.pack(padx=10, pady=10)

        def confirm():
            override._resolve(text.get("1.0", "end-1c"))
            root.destroy()

        def cancel():
            override._resolve(None)
            root.destroy()

        import tkinter.ttk as ttk
        frame = tk.Frame(root)
        ttk.Button(frame, text="Summarize", command=confirm).pack(side="left", padx=5)
        ttk.Button(frame, text="Skip", command=cancel).pack(side="left", padx=5)
        frame.pack(pady=(0, 10))
        root.mainloop()

    def _run_local_audio_flow(self) -> None:
        import tkinter as tk
        from tkinter import filedialog, simpledialog
        root = tk.Tk(); root.withdraw()
        path_str = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[("Audio files", "*.mp3 *.wav *.m4a *.ogg *.flac")],
        )
        root.destroy()
        if not path_str:
            return  # picker cancelled — pipeline_running NOT set yet
        source = Path(path_str)
        today = date.today().strftime("%m-%d-%y")
        root2 = tk.Tk(); root2.withdraw()
        name = simpledialog.askstring(
            "Session Name", "Enter a name for this session:",
            initialvalue=f"{source.stem}_{today}", parent=root2,
        ) or f"{source.stem}_{today}"
        root2.destroy()
        # Set pipeline_running AFTER both dialogs complete with a valid path
        self._pipeline_running.set()
        self._set_icon("processing")
        self._rebuild_menu()

        def run():
            self._pipeline.run(
                mode=PipelineMode.LOCAL_AUDIO,
                session_name=name,
                source_path=source,
                done_event=self._pipeline_running,
            )
            self._ui_queue.put_nowait(("set_icon", "idle"))

        threading.Thread(target=run, daemon=True).start()

    def _run_local_text_flow(self) -> None:
        import tkinter as tk
        from tkinter import filedialog, simpledialog
        root = tk.Tk(); root.withdraw()
        path_str = filedialog.askopenfilename(
            title="Select Text File",
            filetypes=[("Text files", "*.txt *.md")],
        )
        root.destroy()
        if not path_str:
            return  # picker cancelled — pipeline_running NOT set yet
        source = Path(path_str)
        today = date.today().strftime("%m-%d-%y")
        root2 = tk.Tk(); root2.withdraw()
        name = simpledialog.askstring(
            "Session Name", "Enter a name for this session:",
            initialvalue=f"{source.stem}_{today}", parent=root2,
        ) or f"{source.stem}_{today}"
        root2.destroy()
        # Set pipeline_running AFTER both dialogs complete with a valid path
        self._pipeline_running.set()
        self._set_icon("processing")
        self._rebuild_menu()

        def run():
            self._pipeline.run(
                mode=PipelineMode.LOCAL_TEXT,
                session_name=name,
                source_path=source,
                done_event=self._pipeline_running,
            )
            self._ui_queue.put_nowait(("set_icon", "idle"))

        threading.Thread(target=run, daemon=True).start()

    # ── Icon and menu helpers ─────────────────────────────────────────────────

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
        else:
            items.append(pystray.MenuItem("Processing…", None, enabled=False))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit", self._on_quit))
        self._tray.menu = pystray.Menu(*items)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        import time
        self._tray = pystray.Icon(
            "SummarizeAudio",
            icon=self._icons["idle"],
            title="SummarizeAudio",
        )
        self._rebuild_menu()

        def setup(icon: pystray.Icon) -> None:
            """Called by pystray on the main thread after the icon is displayed.
            We drive the drain loop here so all tkinter calls execute on the
            main thread — required by both macOS Cocoa and Windows."""
            icon.visible = True
            while icon.visible:
                time.sleep(0.1)
                self._dispatcher.drain()

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
        return True   # process exists but owned by another user (PID recycled by OS)
    except OSError:
        return False  # process does not exist


def run() -> None:
    _check_single_instance()
    app = TrayApp()
    try:
        app.run()
    finally:
        LOCK_FILE.unlink(missing_ok=True)
