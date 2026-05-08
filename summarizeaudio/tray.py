from __future__ import annotations

import os
import platform
import queue
import signal
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

import pystray
from PIL import Image

from summarizeaudio.config import load_config, save_config
from summarizeaudio.error_handler import format_error, post_error
from summarizeaudio.namer import Namer, default_name
from summarizeaudio.notifier import notify
from summarizeaudio.pipeline import Pipeline, PipelineMode
from summarizeaudio.recorder import Recorder
from summarizeaudio.ui_dispatcher import UIDispatcher

ASSETS = Path(__file__).parent.parent / "assets"
LOCK_FILE = Path.home() / ".summarizeaudio" / "app.lock"


def _osascript(script: str) -> tuple[int, str]:
    """Run an AppleScript snippet; returns (returncode, stdout)."""
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def _as_safe(s: str) -> str:
    """Escape a string for embedding inside an AppleScript double-quoted literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


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
        self._stop_event = threading.Event()
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
        self._dispatcher.register("fatal_error", self._on_fatal_error)
        self._dispatcher.register("name_dialog", self._on_name_dialog)
        self._dispatcher.register("override_dialog", self._on_override_dialog)
        self._dispatcher.register("local_audio_flow", self._run_local_audio_flow)
        self._dispatcher.register("local_text_flow", self._run_local_text_flow)
        self._dispatcher.register("summary_ready", self._on_summary_ready)

    # ── Menu actions ──────────────────────────────────────────────────────────

    def _on_start_recording(self, icon, item) -> None:
        if self._pipeline_running.is_set():
            return
        today = date.today().strftime("%m-%d-%y")
        self._namer = Namer(self._ui_queue, default=f"Recording_{today}")
        self._recorder = Recorder(self._cfg.storage.output_folder, self._cfg.recording.input_device)
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

    def _on_quality_fast(self, icon, item) -> None:
        self._set_model("gemma3:4b", "Fast (4B)")

    def _on_quality_high(self, icon, item) -> None:
        self._set_model("gemma3:12b", "High Quality (12B)")

    def _on_quit(self, icon, item) -> None:
        LOCK_FILE.unlink(missing_ok=True)
        self._stop_event.set()
        icon.stop()

    # ── UI queue handlers (run on main thread) ────────────────────────────────

    def _on_set_icon(self, state: str) -> None:
        self._set_icon(state)
        self._rebuild_menu()

    def _on_error(self, component: str, message: str, tb: str) -> None:
        msg = format_error(component, message, tb)
        if sys.platform == "darwin":
            safe = _as_safe(msg[:800])
            _osascript(
                f'display dialog "{safe}" buttons {{"OK"}} default button "OK" '
                f'with icon stop with title "SummarizeAudio Error"'
            )
        else:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk(); root.withdraw()
            messagebox.showerror("SummarizeAudio Error", msg)
            root.destroy()
        self._pipeline_running.clear()
        self._set_icon("idle")
        self._rebuild_menu()

    def _on_fatal_error(self, message: str, detail: str) -> None:
        msg = f"{message}\n\n{detail}" if detail else message
        if sys.platform == "darwin":
            safe = _as_safe(msg[:800])
            _osascript(
                f'display dialog "{safe}" buttons {{"Quit"}} default button "Quit" '
                f'with icon stop with title "SummarizeAudio — Fatal Error"'
            )
        else:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk(); root.withdraw()
            messagebox.showerror("SummarizeAudio — Fatal Error", msg)
            root.destroy()
        LOCK_FILE.unlink(missing_ok=True)
        self._stop_event.set()
        self._tray.stop()

    def _on_name_dialog(self, namer: Namer) -> None:
        if sys.platform == "darwin":
            default_val = _as_safe(namer._default)
            rc, out = _osascript(
                f'display dialog "Enter a name for this recording:" '
                f'default answer "{default_val}" with title "Session Name"'
            )
            if rc == 0:
                text = out.split("text returned:")[-1].strip()
                namer._resolve(text if text else None)
            else:
                namer._resolve(None)
        else:
            import tkinter as tk
            from tkinter import simpledialog
            root = tk.Tk(); root.withdraw()
            result = simpledialog.askstring(
                "Session Name", "Enter a name for this recording:", parent=root,
            )
            root.destroy()
            namer._resolve(result)

    def _on_override_dialog(self, override, prompt: str) -> None:
        if sys.platform == "darwin":
            # AppleScript dialog has a ~254-char limit on default answer; truncate gracefully
            safe_prompt = _as_safe(prompt[:250])
            rc, out = _osascript(
                f'display dialog "Edit summarization prompt:" '
                f'default answer "{safe_prompt}" '
                f'buttons {{"Skip", "Summarize"}} default button "Summarize" '
                f'with title "SummarizeAudio"'
            )
            if rc == 0 and "button returned:Summarize" in out:
                text = out.split("text returned:")[-1].strip()
                # AppleScript truncates default answer at ~254 chars, which cuts off
                # {transcript}. Restore it from the original prompt if missing.
                if "{transcript}" not in text:
                    idx = prompt.find("{transcript}")
                    text = text + prompt[len(text):] if idx != -1 else text + "\n\nTranscript:\n{transcript}"
                override._resolve(text)
            else:
                override._resolve(None)
        else:
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

    def _on_summary_ready(self, path: Path) -> None:
        if sys.platform == "darwin":
            safe_name = _as_safe(path.name)
            rc, out = _osascript(
                f'display dialog "Summary ready:\\n{safe_name}" '
                f'buttons {{"Dismiss", "Open"}} default button "Open" '
                f'with title "SummarizeAudio"'
            )
            if rc == 0 and "button returned:Open" in out:
                subprocess.run(["open", str(path)], check=False)
        else:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            if messagebox.askyesno("SummarizeAudio", f"Summary ready!\n\n{path.name}\n\nOpen it?"):
                import os
                os.startfile(str(path))
            root.destroy()

    def _set_model(self, model: str, label: str) -> None:
        self._cfg.ollama.model = model
        save_config(self._cfg)
        notify(f"Summarization model set to {label}.")
        self._rebuild_menu()

    def _run_local_audio_flow(self) -> None:
        if sys.platform == "darwin":
            rc, path_str = _osascript(
                'set f to choose file with prompt "Select Audio File" '
                'of type {"mp3", "wav", "m4a", "ogg", "flac", "public.audio"}\n'
                'return POSIX path of f'
            )
            if rc != 0 or not path_str:
                return
            source = Path(path_str)
            today = date.today().strftime("%m-%d-%y")
            default_val = _as_safe(f"{source.stem}_{today}")
            rc2, out = _osascript(
                f'display dialog "Enter a name for this session:" '
                f'default answer "{default_val}" with title "Session Name"'
            )
            name = (out.split("text returned:")[-1].strip()
                    if rc2 == 0 else f"{source.stem}_{today}") or f"{source.stem}_{today}"
        else:
            import tkinter as tk
            from tkinter import filedialog, simpledialog
            root = tk.Tk(); root.withdraw()
            path_str = filedialog.askopenfilename(
                title="Select Audio File",
                filetypes=[("Audio files", "*.mp3 *.wav *.m4a *.ogg *.flac")],
            )
            root.destroy()
            if not path_str:
                return
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
        if sys.platform == "darwin":
            rc, path_str = _osascript(
                'set f to choose file with prompt "Select Text File"\n'
                'return POSIX path of f'
            )
            if rc != 0 or not path_str:
                return
            source = Path(path_str)
            today = date.today().strftime("%m-%d-%y")
            default_val = _as_safe(f"{source.stem}_{today}")
            rc2, out = _osascript(
                f'display dialog "Enter a name for this session:" '
                f'default answer "{default_val}" with title "Session Name"'
            )
            name = (out.split("text returned:")[-1].strip()
                    if rc2 == 0 else f"{source.stem}_{today}") or f"{source.stem}_{today}"
        else:
            import tkinter as tk
            from tkinter import filedialog, simpledialog
            root = tk.Tk(); root.withdraw()
            path_str = filedialog.askopenfilename(
                title="Select Text File",
                filetypes=[("Text files", "*.txt *.md")],
            )
            root.destroy()
            if not path_str:
                return
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
        current_model = self._cfg.ollama.model
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
            items.append(pystray.MenuItem("Summarization Model", None, enabled=False))
            items.append(pystray.MenuItem(
                f"Current Model: {current_model}",
                None,
                enabled=False,
            ))
            items.append(pystray.MenuItem("Fast Mode (gemma3:4b)", self._on_quality_fast))
            items.append(pystray.MenuItem("High Quality Mode (gemma3:12b)", self._on_quality_high))
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
            """Called by pystray after the icon is displayed (background thread on macOS,
            main thread on Windows). Drains the ui_queue; on macOS all dialogs use
            osascript so there is no tkinter main-thread requirement."""
            icon.visible = True
            while not self._stop_event.is_set():
                time.sleep(0.1)
                self._dispatcher.drain()

        def _handle_signal(sig, frame):
            LOCK_FILE.unlink(missing_ok=True)
            self._stop_event.set()
            self._tray.stop()

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
