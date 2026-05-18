from __future__ import annotations

import math
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk
from tkinter.scrolledtext import ScrolledText

from summarizeaudio.config import AppConfig
from summarizeaudio.pipeline import Pipeline, PipelineMode
from summarizeaudio.chooser_window import _native_audio_picker, _native_text_picker
from summarizeaudio.sessions import session_by_id, session_for_summary_path


class _MarqueeProgress:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        width: int,
        height: int = 16,
        track_color: str = "#e7ebf2",
        bar_color: str = "#222222",
        mode: str = "marquee",
        bar_ratio: float = 0.294,
    ) -> None:
        self._frame = ttk.Frame(parent, style="Card.TFrame")
        self._canvas = tk.Canvas(
            self._frame,
            width=width,
            height=height,
            bg="white",
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(fill="x", expand=True)
        self._track_color = track_color
        self._bar_color = bar_color
        self._height = height
        self._base_width = width
        self._bar_ratio = bar_ratio
        self._bar_width = max(30, int(width * bar_ratio))
        self._radius = max(4, height // 2)
        self._bar_x = 0.0
        self._track_items: list[int] = []
        self._bar_items: list[int] = []
        self._after_id: str | None = None
        self._running = False
        self._interval = 16
        self._anim_start: float | None = None
        self._period = 3.5  # seconds for one full left-right-left cycle
        self._mode = mode
        self._pct: float = 0.0
        self._text_item: int | None = None
        self._canvas.bind("<Configure>", self._on_configure)
        self._draw()

    def pack(self, *args, **kwargs) -> None:
        self._frame.pack(*args, **kwargs)

    def set_percent(self, pct: float) -> None:
        if self._mode != "determinate":
            return
        self._pct = max(0.0, min(100.0, pct))
        if not self._canvas.winfo_exists():
            return
        width = max(self._canvas.winfo_width(), self._base_width)
        filled = max(int(2 * self._radius), int(width * self._pct / 100))
        self._set_capsule(self._track_items, 0, 2, width, self._height - 2, self._track_color)
        self._set_capsule(self._bar_items, 0, 2, filled, self._height - 2, self._bar_color)
        if self._text_item is not None:
            self._canvas.itemconfigure(self._text_item, text=f"{int(self._pct)}%")
            self._canvas.coords(self._text_item, filled / 2, self._height / 2)

    def start(self) -> None:
        if self._mode != "marquee":
            return
        if self._running:
            return
        self._running = True
        self._anim_start = time.time()
        self._tick()

    def stop(self) -> None:
        self._running = False
        if self._after_id is not None:
            try:
                self._canvas.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def destroy(self) -> None:
        self.stop()
        self._frame.destroy()

    def _on_configure(self, _event) -> None:
        width = max(self._canvas.winfo_width(), self._base_width)
        if width == self._base_width and self._track_items:
            return
        self._base_width = width
        self._bar_width = max(30, int(width * self._bar_ratio))
        max_x = max(0, width - self._bar_width)
        self._bar_x = min(max(self._bar_x, 0), max_x)
        self._draw()

    def _capsule(self, x1: float, y1: float, x2: float, y2: float, color: str) -> list[int]:
        radius = max(1.0, (y2 - y1) / 2.0)
        rect = self._canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=color, outline="")
        left = self._canvas.create_oval(x1, y1, x1 + radius * 2, y2, fill=color, outline="")
        right = self._canvas.create_oval(x2 - radius * 2, y1, x2, y2, fill=color, outline="")
        return [rect, left, right]

    def _set_capsule(self, items: list[int], x1: float, y1: float, x2: float, y2: float, color: str) -> None:
        radius = max(1.0, (y2 - y1) / 2.0)
        self._canvas.coords(items[0], x1 + radius, y1, x2 - radius, y2)
        self._canvas.coords(items[1], x1, y1, x1 + radius * 2, y2)
        self._canvas.coords(items[2], x2 - radius * 2, y1, x2, y2)
        self._canvas.itemconfigure(items[0], fill=color)
        self._canvas.itemconfigure(items[1], fill=color)
        self._canvas.itemconfigure(items[2], fill=color)

    def _draw(self) -> None:
        self._canvas.delete("all")
        self._text_item = None
        width = max(self._canvas.winfo_width(), self._base_width)
        self._track_items = self._capsule(0, 2, width, self._height - 2, self._track_color)
        if self._mode == "determinate":
            filled = max(int(2 * self._radius), int(width * self._pct / 100))
            self._bar_items = self._capsule(0, 2, filled, self._height - 2, self._bar_color)
            self._text_item = self._canvas.create_text(
                filled / 2, self._height / 2,
                text=f"{int(self._pct)}%",
                fill="white",
                font=("Helvetica Neue", 9, "bold"),
            )
        else:
            self._bar_items = self._capsule(
                self._bar_x,
                2,
                self._bar_x + self._bar_width,
                self._height - 2,
                self._bar_color,
            )

    def _tick(self) -> None:
        if not self._running or not self._canvas.winfo_exists():
            return
        width = max(self._canvas.winfo_width(), self._base_width)
        max_x = max(0, width - self._bar_width)
        if self._anim_start is not None and max_x > 0:
            t = (time.time() - self._anim_start) % self._period
            # Cosine easing: smooth deceleration at each end, no abrupt reversal
            pos = (1.0 - math.cos(math.pi * 2.0 * t / self._period)) / 2.0 * max_x
            self._set_capsule(
                self._bar_items, pos, 2, pos + self._bar_width, self._height - 2, self._bar_color,
            )
        self._after_id = self._canvas.after(self._interval, self._tick)


class _StepIndicator:
    """Horizontal numbered pill stepper shown only during processing.

    Done steps  — dark circle + ✓,  mid-gray label.
    Active step  — dark circle + number, bold dark label.
    Future steps — light circle + number, light-gray label.
    Connector lines: dark between done segments, light otherwise.
    No blue is used; the palette stays within the existing black/gray family.
    """

    _CIRCLE_D = 20
    _CIRCLE_R = 10
    _GAP = 4       # px between circle right-edge and label
    _HEIGHT = 24   # canvas height

    _DONE_BG  = "#162033"
    _DONE_FG  = "white"
    _ACT_BG   = "#162033"
    _ACT_FG   = "white"
    _FUT_BG   = "#e0e6ef"
    _FUT_FG   = "#8898b0"

    _DONE_LABEL   = "#52607a"
    _ACTIVE_LABEL = "#162033"
    _FUT_LABEL    = "#a0aabb"

    _DONE_LINE = "#162033"
    _FUT_LINE  = "#d4dce8"

    def __init__(
        self,
        parent: tk.Misc,
        *,
        steps: list[str],
        current_index: int,
        width: int,
        step_elapsed: dict[int, str] | None = None,
    ) -> None:
        self._steps = steps
        self._current = current_index
        self._step_elapsed = step_elapsed if step_elapsed is not None else {}
        self._base_width = width
        self._last_width: int | None = None
        # Reserve extra vertical space for elapsed labels when parameter is provided.
        self._height = 40 if step_elapsed is not None else self._HEIGHT
        self._canvas = tk.Canvas(
            parent,
            width=width,
            height=self._height,
            bg="white",
            highlightthickness=0,
            bd=0,
        )
        self._canvas.bind("<Configure>", self._on_configure)
        self._draw(width)

    def pack(self, **kwargs) -> None:
        self._canvas.pack(**kwargs)

    def _on_configure(self, event) -> None:
        w = max(event.width, self._base_width)
        if w == self._last_width:
            return
        self._draw(w)

    def _draw(self, width: int) -> None:
        self._last_width = width
        self._canvas.delete("all")
        steps = self._steps
        current = self._current
        n = len(steps)
        if n == 0:
            return

        cy = self._height // 2
        fn = tkfont.Font(family="Helvetica Neue", size=10)
        fb = tkfont.Font(family="Helvetica Neue", size=10, weight="bold")
        fe = tkfont.Font(family="Helvetica Neue", size=8)

        step_widths: list[int] = []
        for i, name in enumerate(steps):
            tw = (fb if i == current else fn).measure(name)
            step_widths.append(self._CIRCLE_D + self._GAP + tw)

        total_step_w = sum(step_widths)
        available_line_w = max(0, width - total_step_w)
        line_w = available_line_w / max(1, n - 1)

        x = 0.0
        for i, name in enumerate(steps):
            if i > 0:
                lx1, lx2 = x, x + line_w
                color = self._DONE_LINE if i <= current else self._FUT_LINE
                self._canvas.create_rectangle(lx1, cy - 1, lx2, cy + 1, fill=color, outline="")
                x += line_w

            cx_c = x + self._CIRCLE_R
            r = self._CIRCLE_R
            if i < current:
                bg, fg, txt = self._DONE_BG, self._DONE_FG, "✓"
                lc, lf = self._DONE_LABEL, fn
            elif i == current:
                bg, fg, txt = self._ACT_BG, self._ACT_FG, str(i + 1)
                lc, lf = self._ACTIVE_LABEL, fb
            else:
                bg, fg, txt = self._FUT_BG, self._FUT_FG, str(i + 1)
                lc, lf = self._FUT_LABEL, fn

            self._canvas.create_oval(
                cx_c - r, cy - r, cx_c + r, cy + r,
                fill=bg, outline="",
            )
            self._canvas.create_text(
                cx_c, cy,
                text=txt,
                fill=fg,
                font=("Helvetica Neue", 9, "bold"),
            )
            lx = x + self._CIRCLE_D + self._GAP
            self._canvas.create_text(lx, cy, text=name, fill=lc, font=lf, anchor="w")

            if i < current and i in self._step_elapsed:
                self._canvas.create_text(
                    lx, cy + 13,
                    text=self._step_elapsed[i],
                    fill="#8898b0",
                    font=fe,
                    anchor="w",
                )

            x += step_widths[i]


class WorkflowWindow:
    def __init__(
        self,
        root: tk.Tk,
        cfg: AppConfig,
        ui_queue: queue.Queue,
        mode: str,
        source: Path | None = None,
        resume_session_id: str | None = None,
    ) -> None:
        self._mode = mode
        self._source = source
        self._resume_session_id = resume_session_id
        self._ui_queue = ui_queue
        self._cfg = cfg
        self._pipeline = Pipeline(cfg=self._cfg, ui_queue=self._ui_queue)
        self._win = tk.Toplevel(root)
        self._win.withdraw()
        self._win.title("SummarizeAudio")
        self._window_width = 560
        self._window_height = 520
        self._win.geometry(f"{self._window_width}x{self._window_height}")
        self._win.resizable(False, False)
        self._win.configure(bg="white")
        self._win.protocol("WM_DELETE_WINDOW", self._close)

        self._state = "chooser" if self._mode in {"audio", "text"} and self._source is None else "processing"
        self._step_text = "Choose a file to begin" if self._state == "chooser" else "Working…"
        self._resolver: object | None = None
        self._resolver_kind: str | None = None
        self._prompt_text = ""
        self._default_name = ""
        self._summary_path: Path | None = None
        self._summary_preview = ""
        self._active_source: Path | None = self._source
        self._resume_session = session_by_id(self._resume_session_id) if self._resume_session_id else None
        self._pipeline_started = False
        self._processing_started = False
        self._step_state = "chooser" if self._state == "chooser" else "processing"
        self._transcription_pct: float = 0.0
        self._step_start_time: float | None = None
        self._step_durations: dict[str, str] = {}
        self._elapsed_tick_id: str | None = None
        self._timing_step: str | None = None
        self._elapsed_var = tk.StringVar(value="")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("SummarizeAudio.TFrame", background="white")
        style.configure("Card.TFrame", background="white")
        style.configure("Title.TLabel", background="white", foreground="#162033", font=("Helvetica Neue", 20, "bold"))
        style.configure("Sub.TLabel", background="white", foreground="#52607a", font=("Helvetica Neue", 11))
        style.configure("Step.TLabel", background="white", foreground="#162033", font=("Helvetica Neue", 13, "bold"))
        style.configure("Detail.TLabel", background="white", foreground="#60708a", font=("Helvetica Neue", 10))
        style.configure("Sep.TFrame", background="#e0e6ef")
        style.configure("StepBadge.TLabel", background="white", foreground="#52607a", font=("Helvetica Neue", 11))
        self._title = tk.StringVar(value="Prepare your workflow")
        self._subtitle = tk.StringVar(value="Pick a file, review the prompt, and finish with a final name.")
        self._status = tk.StringVar(value=self._step_text)
        self._detail_text_var = tk.StringVar(value="")
        self._button_bar: ttk.Frame | None = None
        self._content = None
        self._body = None
        self._progress = None
        self._det_progress_bar: ttk.Progressbar | None = None
        self._text_font = ("Helvetica Neue", 13)
        self._button_font = ("Helvetica Neue", 12, "bold")
        self._button_secondary_bg = "#f0f3f8"
        self._button_secondary_fg = "#1a2030"
        self._button_border = "#b8c4d6"
        self._button_accent_bg = "#1a2030"
        self._button_accent_fg = "white"

    # ── Public lifecycle ──────────────────────────────────────────────────────

    def show(self) -> None:
        """Show the window and start the pipeline if mode requires it."""
        self._render()
        self._center()
        self._win.deiconify()
        self._focus()
        if self._state == "processing":
            self._start_pipeline()

    def retarget(
        self,
        mode: str,
        source: Path | None = None,
        resume_session_id: str | None = None,
    ) -> None:
        """Switch this window to a new workflow without closing it.

        Only valid when no pipeline is actively running (idle or done state).
        Resets all state, creates a fresh pipeline, and re-renders.
        """
        self._mode = mode
        self._source = source
        self._active_source = source
        self._resume_session_id = resume_session_id
        self._resume_session = session_by_id(resume_session_id) if resume_session_id else None
        self._state = "chooser" if mode in {"audio", "text"} and source is None else "processing"
        self._step_state = "chooser" if self._state == "chooser" else "processing"
        self._resolver = None
        self._resolver_kind = None
        self._prompt_text = ""
        self._default_name = ""
        self._summary_path = None
        self._summary_preview = ""
        self._transcription_pct = 0.0
        self._pipeline_started = False
        self._processing_started = False
        self._cancel_elapsed_tick()
        self._step_start_time = None
        self._step_durations = {}
        self._timing_step = None
        self._elapsed_var.set("")
        self._pipeline = Pipeline(cfg=self._cfg, ui_queue=self._ui_queue)
        self._render()
        self._focus()
        if self._state == "processing":
            self._start_pipeline()

    def close(self) -> None:
        """Close and destroy the window."""
        self._close()

    @property
    def pipeline_active(self) -> bool:
        """True when a pipeline is running and the window is in processing state."""
        return self._state == "processing" and self._processing_started

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _stop_progress(self) -> None:
        if self._progress is not None:
            try:
                self._progress.stop()
            except Exception:
                pass
            self._progress = None
        if self._det_progress_bar is not None:
            try:
                self._det_progress_bar.destroy()
            except Exception:
                pass
            self._det_progress_bar = None

    def _center(self) -> None:
        self._win.update_idletasks()
        w = self._window_width
        h = self._window_height
        sw = self._win.winfo_screenwidth()
        sh = self._win.winfo_screenheight()
        x = max((sw - w) // 2, 0)
        y = max((sh - h) // 2, 0)
        self._win.geometry(f"{w}x{h}+{x}+{y}")

    def _clear_body(self) -> ttk.Frame:
        if self._content is not None:
            self._content.destroy()
        self._content = ttk.Frame(self._win, style="SummarizeAudio.TFrame", padding=(20, 16))
        self._content.pack(fill="both", expand=True)
        self._body = self._content
        return self._content

    def _button(self, parent: tk.Misc, *, text: str, command, primary: bool = True) -> tk.Button:
        if primary:
            return tk.Button(
                parent,
                text=text,
                command=command,
                bg=self._button_accent_bg,
                fg=self._button_accent_fg,
                activebackground="#2d3548",
                activeforeground="white",
                relief="flat",
                bd=0,
                padx=16,
                pady=9,
                font=self._button_font,
                highlightthickness=0,
                cursor="hand2",
            )
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=self._button_secondary_bg,
            fg=self._button_secondary_fg,
            activebackground="#dde4ef",
            activeforeground=self._button_secondary_fg,
            relief="flat",
            bd=0,
            padx=16,
            pady=9,
            font=self._button_font,
            highlightthickness=1,
            highlightbackground=self._button_border,
            cursor="hand2",
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
        text.configure(padx=10, pady=8)
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

    def _reveal_in_finder(self, path: Path) -> None:
        try:
            if sys.platform == "darwin":
                safe_path = str(path).replace("\\", "\\\\").replace('"', '\\"')
                script = (
                    f'tell application "Finder" to reveal POSIX file "{safe_path}"\n'
                    "tell application \"Finder\" to activate\n"
                )
                subprocess.run(["osascript", "-e", script], check=False)
            elif hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception:
            pass

    def _focus(self) -> None:
        try:
            self._win.deiconify()
            self._win.lift()
            self._win.attributes("-topmost", True)
            self._win.after(250, lambda: self._win.attributes("-topmost", False))
            self._win.focus_force()
        except Exception:
            pass

    # Keep _raise_window as an alias used internally
    def _raise_window(self) -> None:
        self._focus()

    def _render(self) -> None:
        self._stop_progress()
        for child in self._win.winfo_children():
            if child is not self._content:
                try:
                    child.destroy()
                except Exception:
                    pass
        self._button_bar = None

        # Button bar — packed before header/content so it always claims bottom space.
        self._button_bar = ttk.Frame(self._win, style="SummarizeAudio.TFrame", padding=(20, 10, 20, 16))
        self._button_bar.pack(side="bottom", fill="x")
        ttk.Frame(self._win, style="Sep.TFrame", height=1).pack(side="bottom", fill="x")

        header = ttk.Frame(self._win, style="SummarizeAudio.TFrame", padding=(20, 16, 20, 12))
        header.pack(fill="x")
        if self._state == "processing":
            ttk.Label(header, textvariable=self._title, style="Title.TLabel").pack(anchor="w")
            ttk.Label(header, textvariable=self._subtitle, style="Sub.TLabel").pack(anchor="w", pady=(2, 0))
            _StepIndicator(
                header,
                steps=self._step_short_names(),
                current_index=self._current_step_index(),
                width=self._window_width - 40,
                step_elapsed=self._step_elapsed_by_index(),
            ).pack(fill="x", pady=(10, 2))
        else:
            header_left = ttk.Frame(header, style="SummarizeAudio.TFrame")
            header_left.pack(side="left", fill="both", expand=True)
            ttk.Label(header_left, textvariable=self._title, style="Title.TLabel").pack(anchor="w")
            ttk.Label(header_left, textvariable=self._subtitle, style="Sub.TLabel").pack(anchor="w", pady=(2, 0))
            ttk.Label(header, text=self._step_badge_text(), style="StepBadge.TLabel").pack(side="right", anchor="ne", pady=(4, 0))
        ttk.Frame(self._win, style="Sep.TFrame", height=1).pack(fill="x")

        body = self._clear_body()
        ttk.Label(body, textvariable=self._status, style="Step.TLabel").pack(anchor="w")
        ttk.Label(body, textvariable=self._detail_text_var, style="Detail.TLabel", wraplength=420, justify="left").pack(anchor="w", pady=(6, 10))

        if self._state == "processing":
            progress_width = max(self._window_width - 80, 400)
            if self._step_state in {"summarizing", "diarizing"}:
                self._det_progress_bar = None
                self._progress = _MarqueeProgress(
                    body,
                    width=progress_width,
                    height=32,
                    bar_ratio=0.147,
                )
                self._progress.pack(fill="x", pady=(0, 4))
                self._progress.start()
            else:
                self._det_progress_bar = None
                self._progress = _MarqueeProgress(
                    body,
                    width=progress_width,
                    height=32,
                    mode="determinate",
                )
                self._progress.pack(fill="x", pady=(0, 4))
                self._progress.set_percent(self._transcription_pct)
            tk.Label(
                body,
                textvariable=self._elapsed_var,
                bg="white",
                fg="#8898b0",
                font=("Helvetica Neue", 10),
            ).pack(anchor="w", pady=(0, 10))
        else:
            self._progress = None
            self._det_progress_bar = None

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
        self._detail_text_var.set("Select the file you want to process.")
        if self._button_bar is not None:
            self._button(self._button_bar, text="Choose File", command=self._choose_file, primary=True).pack(side="left")
            self._button(self._button_bar, text="Cancel", command=self._close, primary=False).pack(side="left", padx=(8, 0))

    def _render_processing(self, body: ttk.Frame) -> None:
        if self._step_state == "diarizing":
            self._title.set("Diarizing")
            self._subtitle.set("Identifying and labeling individual speakers.")
            self._status.set("Diarize the audio")
            self._detail_text_var.set("Matching each transcript segment to the speakers detected in the audio.")
        elif self._step_state == "summarizing":
            self._title.set("Summarizing")
            self._subtitle.set("Generating a summary from the transcript.")
            self._status.set("Summarize transcript")
            self._detail_text_var.set("Your AI model is reading through the full transcript and writing a concise summary.")
        elif self._mode == "record":
            self._title.set("Transcribing")
            self._subtitle.set("Converting your recording to text.")
            self._status.set("Transcribe recording")
            self._detail_text_var.set("Whisper is processing the audio — this may take a minute for longer recordings.")
        else:
            self._title.set("Transcribing")
            self._subtitle.set("Converting audio to text.")
            self._status.set("Transcribe audio")
            self._detail_text_var.set("Whisper is processing the audio — this may take a minute for longer files.")

    def _render_prompt(self, body: ttk.Frame) -> None:
        self._stop_progress()
        self._title.set("Review prompt")
        self._subtitle.set("You can edit the summarization prompt without leaving the workflow.")
        self._status.set("Edit the prompt below")
        self._detail_text_var.set("Keep {transcript} in the prompt. It will be replaced before summarization starts.")
        prompt_box = ttk.Frame(body, style="Card.TFrame")
        prompt_box.pack(fill="both", expand=True, pady=(6, 0))
        text = self._text_widget(prompt_box, width=52, height=11)
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

        if self._button_bar is not None:
            self._button(self._button_bar, text="Update Prompt", command=confirm, primary=True).pack(side="right")

    def _render_name(self, body: ttk.Frame) -> None:
        self._stop_progress()
        self._title.set("Name the output")
        self._subtitle.set("This name will be applied to the recording, transcript, and summary.")
        self._status.set("Name the output")
        self._detail_text_var.set("The suggested name is based on the topic we just processed.")
        name_var = tk.StringVar(value=self._default_name)
        entry = self._entry_widget(body, textvariable=name_var)
        entry.pack(fill="x", pady=(8, 8))
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

        if self._button_bar is not None:
            self._button(self._button_bar, text="Save Name", command=confirm, primary=True).pack(side="left")
            self._button(self._button_bar, text="Cancel", command=cancel, primary=False).pack(side="left", padx=(8, 0))

    def _render_message(self, body: ttk.Frame) -> None:
        self._stop_progress()
        if self._button_bar is not None:
            self._button(self._button_bar, text="Close", command=self._close, primary=True).pack(side="right")

    def _render_summary(self, body: ttk.Frame) -> None:
        self._stop_progress()
        self._title.set("Summary complete")
        self._subtitle.set("Review the result or open the transcript or recording.")
        self._status.set("Review the result")
        self._detail_text_var.set(
            "The summary was saved successfully. You can open the transcript or recording if you "
            "want to review the source files, or close this window when you're done."
        )
        session = self._summary_session()
        preview_box = ttk.Frame(body, style="Card.TFrame")
        preview_box.pack(fill="both", expand=True, pady=(6, 0))
        preview = self._text_widget(preview_box, width=56, height=8)
        preview.pack(fill="both", expand=True)
        preview.insert("1.0", self._summary_preview)
        preview.configure(state="disabled")

        if self._button_bar is not None:
            action_specs = self._summary_action_specs(session)
            for index, (label, path) in enumerate(action_specs):
                self._button(
                    self._button_bar,
                    text=label,
                    command=lambda resolved=path: self._open_path(resolved),
                    primary=index == 0,
                ).pack(side="left", padx=(0 if index == 0 else 8, 0))
            self._button(self._button_bar, text="Close", command=self._close, primary=False).pack(side="right")

    def _summary_session(self):
        summary_path = self._summary_path
        resume_session = self._resume_session
        fallback_session = None
        if summary_path is not None:
            fallback_session = session_for_summary_path(self._cfg.storage.output_folder, summary_path)
        if resume_session is None:
            return fallback_session
        if fallback_session is None:
            return resume_session
        try:
            if summary_path is not None and resume_session.summary is not None and resume_session.summary.resolve() != summary_path.resolve():
                return fallback_session
        except Exception:
            return fallback_session
        if (
            resume_session.summary == fallback_session.summary
            and resume_session.transcript == fallback_session.transcript
            and resume_session.audio == fallback_session.audio
            and resume_session.source_path == fallback_session.source_path
        ):
            return resume_session
        return replace(
            resume_session,
            summary=resume_session.summary or fallback_session.summary,
            transcript=resume_session.transcript or fallback_session.transcript,
            audio=resume_session.audio or fallback_session.audio,
            source_path=resume_session.source_path or fallback_session.source_path,
            folder=resume_session.folder or fallback_session.folder,
        )

    def _summary_action_specs(self, session) -> list[tuple[str, Path]]:
        if session is None:
            return []
        specs: list[tuple[str, Path]] = []
        if session.transcript is not None and session.transcript.exists():
            specs.append(("Open Transcript", session.transcript))
        if session.audio is not None and session.audio.exists():
            specs.append(("Open Recording", session.audio))
        return specs

    def _step_badge_text(self) -> str:
        steps = self._steps_for_mode()
        current = self._current_step_index()
        return f"Step {current + 1} of {len(steps)}"

    def _has_diarizer(self) -> bool:
        return bool(os.environ.get("HUGGINGFACE_ACCESS_TOKEN"))

    def _steps_for_mode(self) -> list[str]:
        if self._mode == "record":
            steps = ["Record audio", "Transcribe recording"]
            if self._has_diarizer():
                steps.append("Diarize the audio")
            steps += ["Summarize transcript", "Name the output"]
            return steps
        if self._mode == "audio":
            steps = ["Choose audio file", "Transcribe audio"]
            if self._has_diarizer():
                steps.append("Diarize the audio")
            steps += ["Summarize transcript", "Name the output"]
            return steps
        return ["Choose transcript file", "Summarize transcript", "Name the output"]

    def _step_short_names(self) -> list[str]:
        mapping = {
            "Record audio": "Record",
            "Transcribe recording": "Transcribe",
            "Transcribe audio": "Transcribe",
            "Diarize the audio": "Diarize",
            "Summarize transcript": "Summarize",
            "Name the output": "Name",
            "Choose audio file": "Choose file",
            "Choose transcript file": "Choose file",
        }
        return [mapping.get(s, s) for s in self._steps_for_mode()]

    def _completed_step_count(self) -> int:
        d = self._has_diarizer()
        if self._mode == "record":
            if self._step_state == "chooser":
                return 0
            if self._step_state == "processing":
                return 1
            if self._step_state == "diarizing":
                return 2
            if self._step_state in {"summarizing", "prompt"}:
                return 3 if d else 2
            if self._step_state == "name":
                return 4 if d else 3
            if self._step_state == "message":
                return len(self._steps_for_mode())
        if self._mode in {"audio", "text"}:
            if self._step_state == "chooser":
                return 0
            if self._step_state == "processing":
                return 1
            if self._step_state == "diarizing":
                return 2
            if self._step_state in {"summarizing", "prompt"}:
                return 1 if self._mode == "text" else (3 if d else 2)
            if self._step_state == "name":
                return 2 if self._mode == "text" else (4 if d else 3)
            if self._step_state == "message":
                return len(self._steps_for_mode())
        return 0

    def _current_step_index(self) -> int:
        d = self._has_diarizer()
        if self._mode == "record":
            if self._step_state == "chooser":
                return 0
            if self._step_state == "processing":
                return 1
            if self._step_state == "diarizing":
                return 2
            if self._step_state in {"summarizing", "prompt"}:
                return 3 if d else 2
            if self._step_state == "name":
                return 4 if d else 3
            return len(self._steps_for_mode()) - 1
        if self._mode == "audio":
            if self._step_state == "chooser":
                return 0
            if self._step_state == "processing":
                return 1
            if self._step_state == "diarizing":
                return 2
            if self._step_state in {"summarizing", "prompt"}:
                return 3 if d else 2
            if self._step_state == "name":
                return 4 if d else 3
            return len(self._steps_for_mode()) - 1
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
            self._win.attributes("-topmost", False)
        except Exception:
            pass
        path = _native_audio_picker(title) if self._mode == "audio" else _native_text_picker(title)
        try:
            self._win.lift()
            self._win.attributes("-topmost", True)
            self._win.after(200, lambda: self._win.attributes("-topmost", False))
        except Exception:
            pass
        if not path:
            self._step_text = "Waiting for file selection"
            self._detail_text_var.set("No file selected yet.")
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
        self._start_step_timer("processing")

        def run() -> None:
            if self._mode == "record":
                assert self._active_source is not None
                self._pipeline.run(
                    PipelineMode.RECORD,
                    "recording",
                    mp3_path=self._active_source,
                    resume_session_id=self._resume_session_id,
                )
            elif self._mode == "audio":
                assert self._active_source is not None
                self._pipeline.run(
                    PipelineMode.LOCAL_AUDIO,
                    "audio",
                    source_path=self._active_source,
                    resume_session_id=self._resume_session_id,
                )
            else:
                assert self._active_source is not None
                self._pipeline.run(
                    PipelineMode.LOCAL_TEXT,
                    "text",
                    source_path=self._active_source,
                    resume_session_id=self._resume_session_id,
                )

        threading.Thread(target=run, daemon=True).start()

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
            self._detail_text_var.set(message)
            self._render()
            self._raise_window()
        elif kind == "fatal_error":
            _, title, message = item
            self._title.set(title)
            self._subtitle.set("SummarizeAudio")
            self._step_state = "message"
            self._state = "message"
            self._detail_text_var.set(message)
            self._render()
            self._raise_window()
        elif kind == "error":
            _, component, message, tb = item
            self._title.set(component)
            self._subtitle.set("SummarizeAudio")
            self._step_state = "message"
            self._state = "message"
            self._detail_text_var.set(f"{message}\n\n{tb}")
            self._render()
            self._raise_window()
        elif kind == "summary_ready":
            _, path = item
            self._finish_step_timer()
            self._summary_path = Path(path)
            try:
                self._summary_preview = self._summary_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                self._summary_preview = ""
            if self._resume_session_id:
                self._resume_session = session_by_id(self._resume_session_id) or self._resume_session
            self._step_state = "message"
            self._state = "summary"
            self._render()
            self._raise_window()
        elif kind == "transcription_progress":
            _, pct = item
            self._transcription_pct = pct
            if self._progress is not None and self._det_progress_bar is None:
                self._progress.set_percent(pct)
        elif kind == "workflow_phase":
            _, phase = item
            if phase == "diarizing":
                self._finish_step_timer()
                self._step_state = "diarizing"
                self._state = "processing"
                self._start_step_timer("diarizing")
                self._render()
                self._raise_window()
            elif phase == "summarizing":
                self._finish_step_timer()
                self._step_state = "summarizing"
                self._state = "processing"
                self._start_step_timer("summarizing")
                self._render()
                self._raise_window()
        elif kind == "set_icon":
            return

    def _show_toast(self, message: str) -> None:
        """Show a brief non-blocking banner at the top of the window."""
        if hasattr(self, "_toast_after_id") and self._toast_after_id is not None:
            try:
                self._win.after_cancel(self._toast_after_id)
            except Exception:
                pass
            self._toast_after_id = None
        if hasattr(self, "_toast_frame") and self._toast_frame is not None:
            try:
                self._toast_frame.destroy()
            except Exception:
                pass
            self._toast_frame = None
        toast = tk.Frame(self._win, bg="#f59e0b", padx=16, pady=10)
        tk.Label(toast, text=message, bg="#f59e0b", fg="white",
                 font=("Helvetica Neue", 11), wraplength=520).pack()
        toast.place(x=0, y=0, relwidth=1.0)
        self._toast_frame = toast

        def _dismiss() -> None:
            try:
                toast.destroy()
            except Exception:
                pass
            self._toast_frame = None
            self._toast_after_id = None

        self._toast_after_id = self._win.after(3000, _dismiss)

    # ── Elapsed time tracking ──────────────────────────────────────────────────

    @staticmethod
    def _fmt_elapsed(seconds: float) -> str:
        s = int(seconds)
        return f"{s // 60:02d}:{s % 60:02d} min"

    def _cancel_elapsed_tick(self) -> None:
        if self._elapsed_tick_id is not None:
            try:
                self._win.after_cancel(self._elapsed_tick_id)
            except Exception:
                pass
            self._elapsed_tick_id = None

    def _start_step_timer(self, step_key: str) -> None:
        self._cancel_elapsed_tick()
        self._timing_step = step_key
        self._step_start_time = time.time()
        self._elapsed_var.set("00:00 min")
        self._elapsed_tick_id = self._win.after(1000, self._elapsed_tick)

    def _finish_step_timer(self) -> None:
        self._cancel_elapsed_tick()
        if self._step_start_time is not None and self._timing_step is not None:
            elapsed = time.time() - self._step_start_time
            self._step_durations[self._timing_step] = self._fmt_elapsed(elapsed)
        self._step_start_time = None
        self._timing_step = None

    def _elapsed_tick(self) -> None:
        try:
            if not self._win.winfo_exists():
                return
        except Exception:
            return
        if self._step_start_time is not None:
            self._elapsed_var.set(self._fmt_elapsed(time.time() - self._step_start_time))
        self._elapsed_tick_id = self._win.after(1000, self._elapsed_tick)

    def _step_elapsed_by_index(self) -> dict[int, str]:
        if not self._step_durations:
            return {}
        key_for = {"Transcribe": "processing", "Diarize": "diarizing", "Summarize": "summarizing"}
        result: dict[int, str] = {}
        for idx, name in enumerate(self._step_short_names()):
            key = key_for.get(name)
            if key and key in self._step_durations:
                result[idx] = self._step_durations[key]
        return result

    def _close(self) -> None:
        self._stop_progress()
        self._cancel_elapsed_tick()
        try:
            self._win.destroy()
        except Exception:
            pass
