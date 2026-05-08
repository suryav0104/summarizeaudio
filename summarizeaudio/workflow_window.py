from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
import tkinter.ttk as ttk
from tkinter.scrolledtext import ScrolledText

from summarizeaudio.config import load_config
from summarizeaudio.pipeline import Pipeline, PipelineMode
from summarizeaudio.chooser_window import _native_audio_picker, _native_text_picker


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SummarizeAudio workflow window.")
    parser.add_argument("--mode", choices=("record", "audio", "text"), required=True)
    parser.add_argument("--source", default="", help="Optional source path for record mode")
    return parser


class WorkflowWindow:
    def __init__(self, mode: str, source: str | None = None) -> None:
        self._mode = mode
        self._source = Path(source) if source else None
        self._ui_queue: queue.Queue = queue.Queue()
        self._cfg = load_config(self._ui_queue)
        self._pipeline = Pipeline(cfg=self._cfg, ui_queue=self._ui_queue)
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("SummarizeAudio")
        self._window_width = 1440
        self._window_height = 900
        self._root.geometry(f"{self._window_width}x{self._window_height}")
        self._root.minsize(1180, 700)
        self._root.resizable(True, True)
        self._root.configure(bg="#f5f7fb")
        self._root.protocol("WM_DELETE_WINDOW", self._close)

        self._state = "chooser" if self._mode in {"audio", "text"} and self._source is None else "processing"
        self._step_text = "Choose a file to begin" if self._state == "chooser" else "Working…"
        self._detail_text = ""
        self._resolver: object | None = None
        self._resolver_kind: str | None = None
        self._prompt_text = ""
        self._default_name = ""
        self._summary_path: Path | None = None
        self._summary_preview = ""
        self._active_source: Path | None = self._source
        self._pipeline_started = False
        self._processing_started = False
        self._step_state = "chooser"

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("SummarizeAudio.TFrame", background="#f5f7fb")
        style.configure("Card.TFrame", background="white")
        style.configure("Title.TLabel", background="#f5f7fb", foreground="#162033", font=("Helvetica Neue", 24, "bold"))
        style.configure("Sub.TLabel", background="#f5f7fb", foreground="#52607a", font=("Helvetica Neue", 12))
        style.configure("Step.TLabel", background="white", foreground="#162033", font=("Helvetica Neue", 15, "bold"))
        style.configure("Detail.TLabel", background="white", foreground="#60708a", font=("Helvetica Neue", 11))
        style.configure("Progress.Horizontal.TProgressbar", troughcolor="#e7ebf2", background="#222222", thickness=16)

        self._title = tk.StringVar(value="Prepare your workflow")
        self._subtitle = tk.StringVar(value="Pick a file, review the prompt, and finish with a final name.")
        self._status = tk.StringVar(value=self._step_text)
        self._content = None
        self._body = None
        self._progress = None
        self._text_font = ("Helvetica Neue", 14)
        self._button_font = ("Helvetica Neue", 13, "bold")
        self._button_bg = "#f6f8fb"
        self._button_fg = "#000000"
        self._button_secondary_bg = "#edf2f9"
        self._button_secondary_fg = "#000000"
        self._button_border = "#d4dce8"
        self._button_accent_bg = "#2e72ff"
        self._button_accent_fg = "#000000"

    def run(self) -> int:
        self._render()
        self._root.deiconify()
        self._center()
        self._root.lift()
        self._root.attributes("-topmost", True)
        self._root.after(250, lambda: self._root.attributes("-topmost", False))
        self._root.focus_force()
        self._root.grab_set()
        self._root.after(100, self._pump_queue)

        if self._state == "processing":
            self._start_pipeline()

        self._root.mainloop()
        return 0

    def _center(self) -> None:
        self._root.update_idletasks()
        w = self._window_width
        h = self._window_height
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = max((sw - w) // 2, 0)
        y = max((sh - h) // 2, 0)
        self._root.geometry(f"{w}x{h}+{x}+{y}")

    def _clear_body(self) -> ttk.Frame:
        if self._content is not None:
            self._content.destroy()
        self._content = ttk.Frame(self._root, style="SummarizeAudio.TFrame", padding=18)
        self._content.pack(fill="both", expand=True)
        card = ttk.Frame(self._content, style="Card.TFrame", padding=24)
        card.pack(fill="both", expand=True)
        self._body = card
        return card

    def _button(self, parent: tk.Misc, *, text: str, command, primary: bool = True) -> tk.Button:
        if primary:
            return tk.Button(
                parent,
                text=text,
                command=command,
                bg=self._button_accent_bg,
                fg=self._button_accent_fg,
                activebackground="#245fe0",
                activeforeground="#000000",
                relief="flat",
                bd=0,
                padx=16,
                pady=10,
                font=self._button_font,
                highlightthickness=0,
            )
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=self._button_secondary_bg,
            fg=self._button_secondary_fg,
            activebackground="#dde6f4",
            activeforeground=self._button_secondary_fg,
            relief="flat",
            bd=0,
            padx=16,
            pady=10,
            font=self._button_font,
            highlightthickness=1,
            highlightbackground=self._button_border,
        )

    def _text_widget(self, parent: tk.Misc, *, width: int, height: int) -> ScrolledText:
        text = ScrolledText(
            parent,
            width=width,
            height=height,
            wrap="word",
            undo=True,
            bg="white",
            fg="#162033",
            insertbackground="#162033",
            borderwidth=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground="#d4dce8",
            highlightcolor="#2e72ff",
            font=self._text_font,
        )
        text.configure(padx=12, pady=10)
        return text

    def _entry_widget(self, parent: tk.Misc, *, textvariable: tk.StringVar) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=textvariable,
            bg="white",
            fg="#162033",
            insertbackground="#162033",
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground="#d4dce8",
            highlightcolor="#2e72ff",
            font=self._text_font,
        )

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            elif hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception:
            pass

    def _raise_window(self) -> None:
        try:
            self._root.deiconify()
            self._root.lift()
            self._root.focus_force()
        except Exception:
            pass

    def _render(self) -> None:
        for child in self._root.winfo_children():
            if child is not self._content:
                try:
                    child.destroy()
                except Exception:
                    pass

        header = ttk.Frame(self._root, style="SummarizeAudio.TFrame", padding=(18, 18, 18, 0))
        header.pack(fill="x")
        ttk.Label(header, textvariable=self._title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, textvariable=self._subtitle, style="Sub.TLabel").pack(anchor="w", pady=(2, 0))

        body = self._clear_body()
        ttk.Label(body, textvariable=self._status, style="Step.TLabel").pack(anchor="w")
        ttk.Label(body, text=self._detail_text, style="Detail.TLabel", wraplength=820, justify="left").pack(anchor="w", pady=(8, 14))

        if self._state == "processing":
            self._progress = ttk.Progressbar(
                body,
                mode="indeterminate",
                style="Progress.Horizontal.TProgressbar",
                length=2700,
            )
            self._progress.pack(fill="x", pady=(0, 18))
            self._progress.start(20)
        else:
            self._progress = None

        if self._state == "chooser":
            self._render_chooser(body)
        elif self._state == "prompt":
            self._render_prompt(body)
        elif self._state == "name":
            self._render_name(body)
        elif self._state == "summary":
            self._render_summary(body)
        elif self._state == "message":
            self._render_message(body)
        elif self._state == "processing":
            self._render_processing(body)
        self._raise_window()

    def _render_chooser(self, body: ttk.Frame) -> None:
        self._title.set("Choose your file")
        self._subtitle.set("Select a file to continue.")
        self._status.set("Waiting for file selection")
        self._step_state = "chooser"
        self._detail_text = (
            "Click Choose File to open the native macOS picker. The window stays here and continues "
            "through processing."
        )
        self._render_steps(body)
        actions = ttk.Frame(body, style="Card.TFrame")
        actions.pack(fill="x", pady=(18, 0))
        self._button(actions, text="Choose File", command=self._choose_file, primary=True).pack(side="left")
        self._button(actions, text="Cancel", command=self._close, primary=False).pack(side="left", padx=(8, 0))

    def _render_processing(self, body: ttk.Frame) -> None:
        self._title.set("Processing")
        self._subtitle.set("We keep the workflow in one window from start to finish.")
        if self._step_state == "summarizing":
            self._status.set("Summarize transcript")
        elif self._mode == "record":
            self._status.set("Transcribe recording")
        elif self._mode == "audio":
            self._status.set("Transcribe audio")
        else:
            self._status.set("Summarize transcript")
        if self._step_state == "chooser":
            self._step_state = "processing"
        self._detail_text = "This window remains open while the app finishes the current step and moves to the next one."
        self._render_steps(body)

    def _render_prompt(self, body: ttk.Frame) -> None:
        if self._progress is not None:
            self._progress.stop()
        self._title.set("Review prompt")
        self._subtitle.set("You can edit the summarization prompt without leaving the workflow.")
        self._status.set("Prompt override requested")
        self._detail_text = "Keep {transcript} in the prompt. It will be replaced before summarization starts."
        self._render_steps(body)
        prompt_box = ttk.Frame(body, style="Card.TFrame")
        prompt_box.pack(side="top", fill="both", expand=True, pady=(8, 8))
        text = self._text_widget(prompt_box, width=92, height=11)
        text.pack(fill="both", expand=True)
        text.insert("1.0", self._prompt_text)
        text.focus_set()

        def confirm() -> None:
            value = text.get("1.0", "end-1c")
            if "{transcript}" not in value:
                value = value.rstrip() + "\n\nTranscript:\n{transcript}\n"
            if self._resolver is not None:
                self._resolver._resolve(value)
            self._resolver = None
            self._state = "processing"
            self._render()
            self._raise_window()

        actions = ttk.Frame(body, style="Card.TFrame")
        actions.pack(side="bottom", fill="x", pady=(8, 0))
        confirm_btn = self._button(actions, text="Update Prompt", command=confirm, primary=True)
        confirm_btn.pack(side="right")

    def _render_name(self, body: ttk.Frame) -> None:
        if self._progress is not None:
            self._progress.stop()
        self._title.set("Name the output")
        self._subtitle.set("This name will be applied to the recording, transcript, and summary.")
        self._status.set("Name the output")
        self._detail_text = "The suggested name is based on the topic we just processed."
        self._render_steps(body)
        name_var = tk.StringVar(value=self._default_name)
        entry = self._entry_widget(body, textvariable=name_var)
        entry.pack(fill="x", pady=(10, 10))
        entry.focus_set()

        def confirm() -> None:
            value = name_var.get().strip() or self._default_name
            if self._resolver is not None:
                self._resolver._resolve(value)
            self._resolver = None
            self._state = "processing"
            self._render()
            self._raise_window()

        def cancel() -> None:
            if self._resolver is not None:
                self._resolver._resolve(None)
            self._resolver = None
            self._state = "processing"
            self._render()
            self._raise_window()

        actions = ttk.Frame(body, style="Card.TFrame")
        actions.pack(fill="x")
        confirm_btn = self._button(actions, text="Save Name", command=confirm, primary=True)
        confirm_btn.pack(side="left")
        cancel_btn = self._button(actions, text="Cancel", command=cancel, primary=False)
        cancel_btn.pack(side="left", padx=(8, 0))

    def _render_message(self, body: ttk.Frame) -> None:
        if self._progress is not None:
            self._progress.stop()
        self._render_steps(body)
        ttk.Label(body, text=self._detail_text, style="Detail.TLabel", wraplength=820, justify="left").pack(anchor="w", pady=(10, 16))
        actions = ttk.Frame(body, style="Card.TFrame")
        actions.pack(fill="x")
        self._button(actions, text="Close", command=self._close, primary=True).pack(side="right")

    def _render_summary(self, body: ttk.Frame) -> None:
        if self._progress is not None:
            self._progress.stop()
        self._title.set("Summary ready")
        self._subtitle.set("Review the result or open the output folder.")
        self._status.set("Summary complete")
        self._detail_text = (
            "The summary was saved successfully. You can open it now, view the containing folder, "
            "or close this window when you're done."
        )
        self._render_steps(body)

        summary_path = self._summary_path
        path_box = ttk.Frame(body, style="Card.TFrame")
        path_box.pack(fill="x", pady=(8, 12))
        ttk.Label(path_box, text="Summary file", style="Detail.TLabel").pack(anchor="w")
        ttk.Label(path_box, text=str(summary_path) if summary_path else "", style="Step.TLabel", wraplength=820, justify="left").pack(anchor="w", pady=(2, 0))

        preview_box = ttk.Frame(body, style="Card.TFrame")
        preview_box.pack(fill="both", expand=True, pady=(0, 8))
        preview = self._text_widget(preview_box, width=96, height=8)
        preview.pack(fill="both", expand=True)
        preview.insert("1.0", self._summary_preview)
        preview.configure(state="disabled")

        actions = ttk.Frame(body, style="Card.TFrame")
        actions.pack(fill="x", pady=(8, 0))
        if summary_path is not None:
            self._button(actions, text="Open Summary", command=lambda: self._open_path(summary_path), primary=True).pack(side="left")
        self._button(actions, text="Close", command=self._close, primary=False).pack(side="right")

    def _render_steps(self, body: ttk.Frame) -> None:
        steps = ttk.Frame(body, style="Card.TFrame")
        steps.pack(fill="x", pady=(6, 16))
        for idx, label in enumerate(self._steps_for_mode()):
            if idx < self._completed_step_count():
                prefix = "✓"
            elif idx == self._current_step_index():
                prefix = "→"
            else:
                prefix = "•"
            ttk.Label(steps, text=f"{prefix} {label}", style="Detail.TLabel").pack(anchor="w", pady=1)

    def _steps_for_mode(self) -> list[str]:
        if self._mode == "record":
            return ["Record audio", "Transcribe recording", "Summarize transcript", "Name the output"]
        if self._mode == "audio":
            return ["Choose audio file", "Transcribe audio", "Summarize transcript", "Name the output"]
        return ["Choose transcript file", "Summarize transcript", "Name the output"]

    def _completed_step_count(self) -> int:
        if self._mode == "record":
            if self._step_state in {"chooser", "processing"}:
                return 1 if self._step_state == "processing" else 0
            if self._step_state in {"summarizing", "prompt"}:
                return 2
            if self._step_state == "name":
                return 3
            if self._step_state == "message":
                return 4
        if self._mode in {"audio", "text"}:
            if self._step_state == "chooser":
                return 0
            if self._step_state == "processing":
                return 1
            if self._step_state in {"summarizing", "prompt"}:
                return 1 if self._mode == "text" else 2
            if self._step_state == "name":
                return 2 if self._mode == "text" else 3
            if self._step_state == "message":
                return len(self._steps_for_mode())
        return 0

    def _current_step_index(self) -> int:
        if self._mode == "record":
            if self._step_state == "chooser":
                return 0
            if self._step_state == "processing":
                return 1
            if self._step_state in {"summarizing", "prompt"}:
                return 2
            if self._step_state == "name":
                return 3
            return 3
        if self._mode == "audio":
            if self._step_state == "chooser":
                return 0
            if self._step_state == "processing":
                return 1
            if self._step_state in {"summarizing", "prompt"}:
                return 2
            if self._step_state == "name":
                return 3
            return 3
        if self._step_state == "chooser":
            return 0
        if self._step_state == "processing":
            return 1
        if self._step_state in {"summarizing", "prompt"}:
            return 1
        if self._step_state == "name":
            return 2
        return 2

    def _choose_file(self) -> None:
        title = "Select Audio File" if self._mode == "audio" else "Select Text File"
        try:
            self._root.attributes("-topmost", False)
            self._root.grab_release()
        except Exception:
            pass
        path = _native_audio_picker(title) if self._mode == "audio" else _native_text_picker(title)
        try:
            self._root.lift()
            self._root.grab_set()
            self._root.attributes("-topmost", True)
            self._root.after(200, lambda: self._root.attributes("-topmost", False))
        except Exception:
            pass
        if not path:
            self._step_text = "Waiting for file selection"
            self._detail_text = "No file selected yet."
            self._render()
            return
        self._active_source = Path(path)
        self._pipeline_started = True
        self._state = "processing"
        self._step_state = "processing"
        self._render()
        self._start_pipeline()

    def _start_pipeline(self) -> None:
        if self._processing_started:
            return
        self._processing_started = True

        def run() -> None:
            if self._mode == "record":
                assert self._active_source is not None
                self._pipeline.run(PipelineMode.RECORD, "recording", mp3_path=self._active_source)
            elif self._mode == "audio":
                assert self._active_source is not None
                self._pipeline.run(PipelineMode.LOCAL_AUDIO, "audio", source_path=self._active_source)
            else:
                assert self._active_source is not None
                self._pipeline.run(PipelineMode.LOCAL_TEXT, "text", source_path=self._active_source)

        threading.Thread(target=run, daemon=True).start()

    def _pump_queue(self) -> None:
        try:
            while True:
                item = self._ui_queue.get_nowait()
                self._handle_item(item)
        except queue.Empty:
            pass
        if self._root.winfo_exists():
            self._root.after(100, self._pump_queue)

    def _handle_item(self, item: tuple) -> None:
        kind = item[0]
        if kind == "override_dialog":
            _, override, prompt = item
            self._resolver = override
            self._resolver_kind = kind
            self._prompt_text = prompt
            self._step_state = "summarizing"
            self._state = "prompt"
            self._render()
        elif kind == "name_dialog":
            _, name_event, default_name = item
            self._resolver = name_event
            self._resolver_kind = kind
            self._default_name = default_name
            self._step_state = "name"
            self._state = "name"
            self._render()
        elif kind == "info_dialog":
            _, title, message = item
            self._title.set(title)
            self._subtitle.set("SummarizeAudio")
            self._step_state = "message"
            self._state = "message"
            self._detail_text = message
            self._render()
            self._raise_window()
        elif kind == "fatal_error":
            _, title, message = item
            self._title.set(title)
            self._subtitle.set("SummarizeAudio")
            self._step_state = "message"
            self._state = "message"
            self._detail_text = message
            self._render()
            self._raise_window()
        elif kind == "error":
            _, component, message, tb = item
            self._title.set(component)
            self._subtitle.set("SummarizeAudio")
            self._step_state = "message"
            self._state = "message"
            self._detail_text = f"{message}\n\n{tb}"
            self._render()
            self._raise_window()
        elif kind == "summary_ready":
            _, path = item
            self._summary_path = Path(path)
            try:
                self._summary_preview = self._summary_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                self._summary_preview = ""
            self._step_state = "message"
            self._state = "summary"
            self._detail_text = f"The summary was saved to:\n{path}"
            self._render()
            self._raise_window()
        elif kind == "workflow_phase":
            _, phase = item
            if phase == "summarizing":
                self._step_state = "summarizing"
                self._state = "processing"
                self._render()
                self._raise_window()
        elif kind == "set_icon":
            return

    def _close(self) -> None:
        try:
            self._root.grab_release()
        except Exception:
            pass
        try:
            self._root.destroy()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    window = WorkflowWindow(args.mode, source=args.source or None)
    return window.run()


if __name__ == "__main__":
    raise SystemExit(main())
