from __future__ import annotations

import os
import queue
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import tkinter as tk
import tkinter.ttk as ttk

from summarizeaudio.config import AppConfig
from summarizeaudio.sessions import archive_session, display_artifact_name, display_session_label, load_sessions, session_action_specs

if TYPE_CHECKING:
    pass


class HistoryWindow:
    def __init__(self, root: tk.Tk, cfg: AppConfig, ui_queue: queue.Queue) -> None:
        self._cfg = cfg
        self._ui_queue = ui_queue
        self._sessions: list = []
        self._selected_index = 0
        self._show_archived = False
        self._reload_sessions()
        self._selected_index = 0 if self._sessions else -1
        self._win = tk.Toplevel(root)
        self._win.withdraw()
        self._win.title("SummarizeAudio History")
        self._window_width = 740
        self._window_height = 520
        self._win.geometry(f"{self._window_width}x{self._window_height}")
        self._win.minsize(600, 420)
        self._win.resizable(True, True)
        self._win.configure(bg="#f5f7fb")
        self._win.protocol("WM_DELETE_WINDOW", self.close)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("SummarizeAudio.TFrame", background="#f5f7fb")
        style.configure("Card.TFrame", background="white")
        style.configure("Title.TLabel", background="#f5f7fb", foreground="#162033", font=("Helvetica Neue", 20, "bold"))
        style.configure("Sub.TLabel", background="#f5f7fb", foreground="#52607a", font=("Helvetica Neue", 12))
        style.configure("Step.TLabel", background="white", foreground="#162033", font=("Helvetica Neue", 13, "bold"))
        style.configure("Detail.TLabel", background="white", foreground="#60708a", font=("Helvetica Neue", 10))
        style.configure("Badge.TLabel", background="#eef1f5", foreground="#667084", font=("Helvetica Neue", 10, "bold"))
        style.configure(
            "SummarizeAudio.Treeview",
            background="white",
            fieldbackground="white",
            foreground="#162033",
            bordercolor="#d4dce8",
            borderwidth=1,
            relief="solid",
            rowheight=32,
            font=("Helvetica Neue", 12),
        )
        style.configure(
            "SummarizeAudio.Treeview.Heading",
            font=("Helvetica Neue", 12, "bold"),
            padding=(10, 8, 12, 8),
            background="#f5f7fb",
            foreground="#000000",
        )
        style.map(
            "SummarizeAudio.Treeview",
            background=[("selected", "#cbd2dd")],
            foreground=[("selected", "#162033")],
        )
        style.configure("Link.TLabel", background="white", foreground="#2e72ff")

        self._button_font = ("Helvetica Neue", 12, "bold")
        self._button_bg = "#f6f8fb"
        self._button_fg = "#000000"
        self._button_secondary_bg = "#edf2f9"
        self._button_secondary_fg = "#000000"
        self._button_border = "#d4dce8"
        self._button_accent_bg = "#2e72ff"
        self._button_accent_fg = "#000000"

        self._content = None
        self._session_list = None
        self._session_scrollbar = None
        self._detail_card = None
        self._button_bar = None

    def show(self) -> None:
        self._render()
        self._win.deiconify()
        self._center()
        self._focus()

    def refresh(self) -> None:
        self._reload_sessions()
        self._render()
        self._win.deiconify()
        self._focus()

    def close(self) -> None:
        try:
            self._win.destroy()
        except Exception:
            pass

    def _focus(self) -> None:
        self._win.lift()
        self._win.attributes("-topmost", True)
        self._win.after(250, lambda: self._win.attributes("-topmost", False))
        self._win.focus_force()

    def _reload_sessions(self, selected_id: str | None = None) -> None:
        self._sessions = load_sessions(
            self._cfg.storage.output_folder,
            limit=None,
            include_archived=self._show_archived,
        )
        if not self._sessions:
            self._selected_index = -1
            return
        if selected_id is not None:
            for idx, session in enumerate(self._sessions):
                if session.id == selected_id:
                    self._selected_index = idx
                    return
        current_index = getattr(self, "_selected_index", 0)
        self._selected_index = min(max(current_index, 0), len(self._sessions) - 1)

    def _center(self) -> None:
        self._win.update_idletasks()
        w = self._window_width
        h = self._window_height
        sw = self._win.winfo_screenwidth()
        sh = self._win.winfo_screenheight()
        x = max((sw - w) // 2, 0)
        y = max((sh - h) // 2, 0)
        self._win.geometry(f"{w}x{h}+{x}+{y}")

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
                padx=14,
                pady=8,
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
            padx=14,
            pady=8,
            font=self._button_font,
            highlightthickness=1,
            highlightbackground=self._button_border,
        )

    def _clear_body(self) -> ttk.Frame:
        if self._content is not None:
            self._content.destroy()
        self._content = ttk.Frame(self._win, style="SummarizeAudio.TFrame", padding=14)
        self._content.pack(fill="both", expand=True)
        card = ttk.Frame(self._content, style="Card.TFrame", padding=18)
        card.pack(fill="both", expand=True)
        return card

    def _render(self) -> None:
        for child in self._win.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        self._content = None
        self._button_bar = None

        header = ttk.Frame(self._win, style="SummarizeAudio.TFrame", padding=(14, 14, 14, 0))
        header.pack(fill="x")
        header_row = ttk.Frame(header, style="SummarizeAudio.TFrame")
        header_row.pack(fill="x")
        title = "Archived History" if self._show_archived else "History"
        ttk.Label(header_row, text=title, style="Title.TLabel").pack(side="left", anchor="w")
        toggle_label = "Archived Sessions" if not self._show_archived else "Active Sessions"
        self._button(header_row, text=toggle_label, command=self._toggle_archived_filter, primary=False).pack(side="right")

        # Button bar — packed before body so it always claims space at the bottom.
        self._button_bar = ttk.Frame(self._win, style="SummarizeAudio.TFrame", padding=(14, 8))
        self._button_bar.pack(side="bottom", fill="x")

        if not self._sessions:
            body = self._clear_body()
            empty_title = "No archived sessions yet." if self._show_archived else "No saved sessions yet."
            empty_detail = "Archived sessions will appear here." if self._show_archived else "Completed summaries will appear here."
            ttk.Label(body, text=empty_title, style="Step.TLabel").pack(anchor="w")
            ttk.Label(body, text=empty_detail, style="Detail.TLabel").pack(anchor="w", pady=(8, 16))
            self._button(self._button_bar, text="Close", command=self.close, primary=True).pack(side="right")
            return

        body = self._clear_body()
        list_shell = ttk.Frame(body, style="Card.TFrame")
        list_shell.pack(fill="both", expand=True, pady=(0, 8))
        self._session_scrollbar = ttk.Scrollbar(list_shell, orient="vertical")
        self._session_list = ttk.Treeview(
            list_shell,
            columns=("session", "date"),
            show="headings",
            selectmode="browse",
            style="SummarizeAudio.Treeview",
            height=8,
            yscrollcommand=self._session_scrollbar.set,
        )
        self._session_list.heading("session", text="Session", anchor="w")
        self._session_list.heading("date", text="Date", anchor="w")
        self._session_list.column("session", width=420, anchor="w", stretch=True)
        self._session_list.column("date", width=120, anchor="w", stretch=False)
        self._session_scrollbar.configure(command=self._session_list.yview)
        self._session_list.pack(side="left", fill="both", expand=True)
        self._session_scrollbar.pack(side="right", fill="y")
        for index, session in enumerate(self._sessions):
            tags = ("row_even",) if index % 2 == 0 else ("row_odd",)
            self._session_list.insert(
                "",
                "end",
                iid=str(index),
                values=(self._session_row_label(session), f"  {session.date}"),
                tags=tags,
            )
        self._session_list.tag_configure("row_even", background="#ffffff")
        self._session_list.tag_configure("row_odd", background="#f8faff")
        self._session_list.bind("<<TreeviewSelect>>", self._on_select)
        if self._selected_index >= 0:
            self._session_list.selection_set(str(self._selected_index))
            self._session_list.focus(str(self._selected_index))
            self._session_list.see(str(self._selected_index))

        self._detail_card = ttk.Frame(body, style="Card.TFrame")
        self._detail_card.pack(fill="x", expand=False)
        self._render_selected_session()

    def _toggle_archived_filter(self) -> None:
        self._show_archived = not self._show_archived
        selected_id = None
        if 0 <= self._selected_index < len(self._sessions):
            selected_id = self._sessions[self._selected_index].id
        self._reload_sessions(selected_id=selected_id)
        self._render()

    def _on_select(self, _event) -> None:
        if self._session_list is None:
            return
        selection = self._session_list.selection()
        if not selection:
            return
        self._selected_index = int(selection[0])
        self._render_selected_session()

    def _render_selected_session(self) -> None:
        if self._detail_card is None:
            return
        for child in self._detail_card.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        session = self._sessions[self._selected_index] if 0 <= self._selected_index < len(self._sessions) else None
        if session is None:
            ttk.Label(self._detail_card, text="Select a session.", style="Step.TLabel").pack(anchor="w")
            return

        path_box = ttk.Frame(self._detail_card, style="Card.TFrame")
        path_box.pack(fill="x", pady=(0, 8))
        title_row = ttk.Frame(path_box, style="Card.TFrame")
        title_row.pack(fill="x")
        ttk.Label(title_row, text=display_session_label(session.label), style="Step.TLabel").pack(side="left", anchor="w")
        if session.archived:
            ttk.Label(title_row, text="Archived", style="Badge.TLabel", padding=(8, 3)).pack(side="left", padx=(10, 0))
            ttk.Label(path_box, text="Archived session", style="Detail.TLabel").pack(anchor="w", pady=(2, 0))
        meta_row = ttk.Frame(path_box, style="Card.TFrame")
        meta_row.pack(fill="x", pady=(2, 0))
        ttk.Label(meta_row, text=f"Date: {session.date}", style="Detail.TLabel").pack(side="left")
        location = ttk.Label(
            meta_row,
            text=str(session.folder),
            style="Link.TLabel",
            cursor="hand2",
            font=("Helvetica Neue", 10, "underline"),
        )
        location.pack(side="left", padx=(20, 0))
        location.bind("<Button-1>", lambda _event, path=session.folder: self._reveal_in_finder(path))
        location.bind("<Enter>", lambda _event: location.configure(foreground="#1f5ddb"))
        location.bind("<Leave>", lambda _event: location.configure(foreground="#2e72ff"))

        details = ttk.Frame(self._detail_card, style="Card.TFrame")
        details.pack(fill="x", pady=(0, 12))
        if session.summary is not None:
            ttk.Label(details, text=f"Summary: {session.summary.name}", style="Detail.TLabel", wraplength=580, justify="left").pack(anchor="w", pady=1)
        else:
            ttk.Label(details, text="Summary: not yet created", style="Detail.TLabel", wraplength=580, justify="left").pack(anchor="w", pady=1)
        if getattr(session, "source_path", None) is not None:
            ttk.Label(details, text=f"Source: {session.source_path.name}", style="Detail.TLabel", wraplength=580, justify="left").pack(anchor="w", pady=1)
        if session.audio is not None:
            ttk.Label(details, text=f"Recording: {session.audio.name}", style="Detail.TLabel", wraplength=580, justify="left").pack(anchor="w", pady=1)
        if session.transcript is not None:
            ttk.Label(details, text=f"Transcript: {session.transcript.name}", style="Detail.TLabel", wraplength=580, justify="left").pack(anchor="w", pady=1)

        # Buttons go into the fixed bar at the bottom of the window.
        if self._button_bar is None:
            return
        for child in self._button_bar.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        # Left side: open-file actions then resume actions.
        specs = session_action_specs(session)
        for idx, (label, path) in enumerate(specs):
            if idx == 0:
                self._button(self._button_bar, text=label, command=lambda p=path: self._open_file(p), primary=True).pack(side="left")
            else:
                self._button(self._button_bar, text=label, command=lambda p=path: self._open_file(p), primary=False).pack(side="left", padx=(6, 0))
        resume_actions = self._resume_actions(session)
        for label, callback in resume_actions:
            self._button(self._button_bar, text=label, command=callback, primary=False).pack(side="left", padx=(6, 0))
        # Right side: archive toggle then close (pack order puts close rightmost).
        if session.summary is not None and session.summary.exists():
            archive_label = "Unarchive" if session.archived else "Archive"
            self._button(
                self._button_bar,
                text=archive_label,
                command=lambda s=session: self._toggle_archive(s),
                primary=False,
            ).pack(side="right", padx=(6, 0))
        self._button(self._button_bar, text="Close", command=self.close, primary=False).pack(side="right")

    def _toggle_archive(self, session: "SessionFiles") -> None:
        archive_session(session.id, archived=not session.archived)
        self._reload_sessions(selected_id=session.id)
        self._render()

    def _resume_actions(self, session: "SessionFiles") -> list[tuple[str, Callable[[], None]]]:
        status = getattr(session, "status", "completed")
        if status not in {"partial", "failed", "in_progress"}:
            return []
        if session.summary is None or not session.summary.exists():
            if session.transcript is not None and session.transcript.exists():
                return [("Retry Summarization", lambda s=session: self._resume_text_session(s))]
            if session.audio is not None and session.audio.exists():
                return [("Retry Transcription", lambda s=session: self._resume_audio_session(s))]
            source_path = getattr(session, "source_path", None)
            if source_path is not None and source_path.exists():
                return [("Retry Transcription", lambda s=session: self._resume_audio_session(s))]
        return []

    def _resume_audio_session(self, session: "SessionFiles") -> None:
        source = session.audio if session.audio is not None and session.audio.exists() else getattr(session, "source_path", None)
        if source is None:
            return
        self._ui_queue.put(("show_workflow", "audio", source, session.id))
        self._win.withdraw()

    def _resume_text_session(self, session: "SessionFiles") -> None:
        if session.transcript is None or not session.transcript.exists():
            return
        self._ui_queue.put(("show_workflow", "text", session.transcript, session.id))
        self._win.withdraw()

    def _session_display_label(self, session) -> str:
        return session.label

    def _session_row_label(self, session) -> str:
        label = display_session_label(self._session_display_label(session))
        if getattr(session, "status", "completed") in {"partial", "failed", "in_progress"}:
            return f"* {label}"
        return f"  {label}"

    def _open_file(self, path: Path) -> None:
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
                    f'tell application "Finder" to activate'
                )
                subprocess.run(["osascript", "-e", script], check=False)
            elif hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception:
            pass
