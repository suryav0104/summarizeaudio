from __future__ import annotations

import os
import platform
import queue
import signal
import subprocess
import sys
import threading
import traceback
from datetime import date
from pathlib import Path

import pystray
from PIL import Image

from summarizeaudio.config import load_config, save_config
from summarizeaudio.error_handler import format_error
from summarizeaudio.namer import Namer, default_name
from summarizeaudio.notifier import notify
from summarizeaudio.pipeline import Pipeline, PipelineMode
from summarizeaudio.recorder import Recorder
from summarizeaudio.ui_dispatcher import UIDispatcher

ASSETS = Path(__file__).parent.parent / "assets"
LOCK_FILE = Path.home() / ".summarizeaudio" / "app.lock"
EMOJI_ICONS = {"idle": "🎙", "recording": "🔴", "processing": "💭", "error": "⚠️"}


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
        self._use_rumps = False

        # Register all ui_queue handlers up front (must happen before run())
        self._dispatcher.register("set_icon", self._on_set_icon)
        self._dispatcher.register("error", self._on_error)
        self._dispatcher.register("fatal_error", self._on_fatal_error)
        self._dispatcher.register("info_dialog", self._on_info_dialog)
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
        namer = Namer(self._ui_queue, default=f"Recording_{today}")
        recorder = Recorder(self._cfg.storage.output_folder, self._cfg.recording.input_device)
        try:
            recorder.start()
        except Exception as exc:
            recorder.cleanup(delete_wav=True)
            self._on_error("tray.py → recorder", str(exc), traceback.format_exc())
            return
        self._namer = namer
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
            self._namer = None
            self._on_error("tray.py → recorder", str(exc), traceback.format_exc())
            self._set_icon("idle")
            self._rebuild_menu()
            return

        name = self._namer.wait(timeout=30) if self._namer else f"Recording_{date.today().strftime('%m-%d-%y')}"
        self._recorder = None
        self._namer = None
        if name is None:
            mp3_path.unlink(missing_ok=True)
            self._set_icon("idle")
            self._rebuild_menu()
            return
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

    def _model_label(self, model: str, label: str) -> str:
        return f"✓ {label}" if self._cfg.ollama.model == model else label

    def _on_quit(self, icon, item) -> None:
        LOCK_FILE.unlink(missing_ok=True)
        self._stop_event.set()
        if self._use_rumps:
            import rumps
            rumps.quit_application()
        else:
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
        msg = format_error("fatal", message, detail)
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

    def _on_info_dialog(self, title: str, message: str) -> None:
        if sys.platform == "darwin":
            safe_title = _as_safe(title[:120])
            safe_message = _as_safe(message[:800])
            _osascript(
                f'display dialog "{safe_message}" buttons {{"OK"}} default button "OK" '
                f'with icon note with title "{safe_title}"'
            )
        else:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo(title, message)
            root.destroy()

    def _on_name_dialog(self, namer: Namer) -> None:
        if sys.platform == "darwin":
            default_val = _as_safe(namer._default)
            rc, out = _osascript(
                f'display dialog "Enter a name for this recording:" '
                f'default answer "{default_val}" with title "Session Name"'
            )
            if rc == 0:
                text = out.split("text returned:")[-1].strip()
                if text:
                    namer._resolve(text)
                else:
                    namer._resolve(None)
                    self._cancel_recording_if_naming(namer)
            else:
                namer._resolve(None)
                self._cancel_recording_if_naming(namer)
        else:
            import tkinter as tk
            from tkinter import simpledialog
            root = tk.Tk(); root.withdraw()
            result = simpledialog.askstring(
                "Session Name", "Enter a name for this recording:", parent=root,
            )
            root.destroy()
            namer._resolve(result)
            if result is None:
                self._cancel_recording_if_naming(namer)

    def _cancel_recording_if_naming(self, namer: Namer) -> None:
        if self._namer is not namer or self._recorder is None:
            return
        self._recorder.cleanup(delete_wav=True)
        self._recorder = None
        self._namer = None
        self._set_icon("idle")
        self._rebuild_menu()

    def _on_override_dialog(self, override, prompt: str) -> None:
        def launch() -> None:
            cmd = [sys.executable, "-m", "summarizeaudio.prompt_editor", "--title", "SummarizeAudio"]
            try:
                proc = subprocess.run(
                    cmd,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except Exception as exc:
                log.exception("Prompt editor helper failed to launch")
                override._resolve(None)
                self._ui_queue.put_nowait(
                    (
                        "info_dialog",
                        "Prompt editor could not open.",
                        f"SummarizeAudio could not show the prompt editor.\n\n{exc}",
                    )
                )
                return

            if proc.returncode == 0:
                override._resolve(proc.stdout or prompt)
            else:
                override._resolve(None)

        threading.Thread(target=launch, daemon=True).start()

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
            if self._use_rumps:
                self._tray.title = EMOJI_ICONS.get(state, EMOJI_ICONS["idle"])
            else:
                self._tray.icon = self._icons.get(state, self._icons["idle"])

    def _rebuild_menu(self) -> None:
        if self._tray is None:
            return
        if self._use_rumps:
            self._rebuild_rumps_menu()
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
            fast_label = self._model_label("gemma3:4b", "Fast Mode (gemma3:4b)")
            high_label = self._model_label("gemma3:12b", "High Quality Mode (gemma3:12b)")
            items.append(pystray.MenuItem(fast_label, self._on_quality_fast))
            items.append(pystray.MenuItem(high_label, self._on_quality_high))
        else:
            items.append(pystray.MenuItem("Processing…", None, enabled=False))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit", self._on_quit))
        self._tray.menu = pystray.Menu(*items)

    def _rebuild_rumps_menu(self) -> None:
        import rumps

        recording = self._recorder is not None
        processing = self._pipeline_running.is_set()
        items = []

        if recording:
            items.append(rumps.MenuItem("Stop Recording", callback=lambda _: self._on_stop_recording(None, None)))
        elif not processing:
            items.append(rumps.MenuItem("Start Recording", callback=lambda _: self._on_start_recording(None, None)))
            items.append(rumps.MenuItem(
                "Transcribe & Summarize Audio File…",
                callback=lambda _: self._on_local_audio(None, None),
            ))
            items.append(rumps.MenuItem(
                "Summarize Text File…",
                callback=lambda _: self._on_local_text(None, None),
            ))
            items.append(None)
            items.append(rumps.MenuItem("Summarization Model"))
            fast_item = rumps.MenuItem(
                "Fast Mode (gemma3:4b)",
                callback=lambda _: self._on_quality_fast(None, None),
            )
            high_item = rumps.MenuItem(
                "High Quality Mode (gemma3:12b)",
                callback=lambda _: self._on_quality_high(None, None),
            )
            fast_item.state = 1 if self._cfg.ollama.model == "gemma3:4b" else 0
            high_item.state = 1 if self._cfg.ollama.model == "gemma3:12b" else 0
            items.extend([fast_item, high_item])
        else:
            items.append(rumps.MenuItem("Processing…"))

        items.append(None)
        items.append(rumps.MenuItem("Quit", callback=lambda _: self._on_quit(self._tray, None)))
        self._tray.menu.clear()
        self._tray.menu.update(items)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        if sys.platform == "darwin":
            self._run_rumps()
            return

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

    def _run_rumps(self) -> None:
        import rumps

        self._use_rumps = True
        self._tray = rumps.App(
            "SummarizeAudio",
            title=EMOJI_ICONS["idle"],
            menu=[],
            quit_button=None,
        )
        self._rebuild_menu()

        @rumps.timer(0.1)
        def drain_queue(_):
            self._dispatcher.drain()

        def _handle_signal(sig, frame):
            LOCK_FILE.unlink(missing_ok=True)
            self._stop_event.set()
            rumps.quit_application()

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        self._tray.run()


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
    try:
        _check_single_instance()
        app = TrayApp()
        app.run()
    except Exception:
        msg = format_error("startup", "SummarizeAudio could not start.", traceback.format_exc())
        if sys.platform == "darwin":
            safe = _as_safe(msg[:800])
            _osascript(
                f'display dialog "{safe}" buttons {{"Quit"}} default button "Quit" '
                f'with icon stop with title "SummarizeAudio Error"'
            )
        else:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("SummarizeAudio Error", msg)
            root.destroy()
        raise SystemExit(1)
    finally:
        LOCK_FILE.unlink(missing_ok=True)
