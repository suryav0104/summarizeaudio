from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import tkinter as tk
import tkinter.ttk as ttk

from summarizeaudio.config import load_config
from summarizeaudio.sessions import archive_session, load_sessions, session_action_specs


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SummarizeAudio history window.")
    return parser


class HistoryWindow:
    def __init__(self) -> None:
        self._cfg = load_config()
        self._sessions: list = []
        self._selected_index = 0
        self._show_archived = False
        self._reload_sessions()
        self._selected_index = 0 if self._sessions else -1
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("SummarizeAudio History")
        self._window_width = 1480
        self._window_height = 940
        self._root.geometry(f"{self._window_width}x{self._window_height}")
        self._root.minsize(1240, 780)
        self._root.resizable(True, True)
        self._root.configure(bg="#f5f7fb")
        self._root.protocol("WM_DELETE_WINDOW", self._close)

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
        style.configure("Badge.TLabel", background="#eef1f5", foreground="#667084", font=("Helvetica Neue", 11, "bold"))
        style.configure(
            "SummarizeAudio.Treeview",
            background="white",
            fieldbackground="white",
            foreground="#162033",
            bordercolor="#d4dce8",
            borderwidth=1,
            relief="solid",
            rowheight=38,
            font=("Helvetica Neue", 13),
        )
        style.configure(
            "SummarizeAudio.Treeview.Heading",
            font=("Helvetica Neue", 14, "bold"),
            padding=(34, 10, 14, 10),
            background="#f5f7fb",
            foreground="#000000",
        )
        style.map(
            "SummarizeAudio.Treeview",
            background=[("selected", "#e4e7ec")],
            foreground=[("selected", "#162033")],
        )
        style.configure("Link.TLabel", background="white", foreground="#2e72ff")

        self._button_font = ("Helvetica Neue", 13, "bold")
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

    def run(self) -> int:
        self._render()
        self._root.deiconify()
        self._center()
        self._root.lift()
        self._root.attributes("-topmost", True)
        self._root.after(250, lambda: self._root.attributes("-topmost", False))
        self._root.focus_force()
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

    def _clear_body(self) -> ttk.Frame:
        if self._content is not None:
            self._content.destroy()
        self._content = ttk.Frame(self._root, style="SummarizeAudio.TFrame", padding=18)
        self._content.pack(fill="both", expand=True)
        card = ttk.Frame(self._content, style="Card.TFrame", padding=24)
        card.pack(fill="both", expand=True)
        return card

    def _render(self) -> None:
        for child in self._root.winfo_children():
            if child is not self._content:
                try:
                    child.destroy()
                except Exception:
                    pass

        header = ttk.Frame(self._root, style="SummarizeAudio.TFrame", padding=(18, 18, 18, 0))
        header.pack(fill="x")
        header_row = ttk.Frame(header, style="SummarizeAudio.TFrame")
        header_row.pack(fill="x")
        title = "Archived History" if self._show_archived else "History"
        ttk.Label(header_row, text=title, style="Title.TLabel").pack(side="left", anchor="w")
        toggle_label = "Archive" if not self._show_archived else "Active"
        self._button(header_row, text=toggle_label, command=self._toggle_archived_filter, primary=False).pack(side="right")
        body = self._clear_body()
        if not self._sessions:
            empty_title = "No archived sessions yet." if self._show_archived else "No saved sessions yet."
            empty_detail = "Archived sessions will appear here." if self._show_archived else "Completed summaries will appear here."
            ttk.Label(body, text=empty_title, style="Step.TLabel").pack(anchor="w")
            ttk.Label(body, text=empty_detail, style="Detail.TLabel").pack(anchor="w", pady=(8, 16))
            actions = ttk.Frame(body, style="Card.TFrame")
            actions.pack(fill="x")
            self._button(actions, text="Close", command=self._close, primary=True).pack(side="right")
            return

        list_shell = ttk.Frame(body, style="Card.TFrame")
        list_shell.pack(fill="both", expand=True, pady=(0, 16))
        self._session_scrollbar = ttk.Scrollbar(list_shell, orient="vertical")
        self._session_list = ttk.Treeview(
            list_shell,
            columns=("date",),
            show="tree headings",
            selectmode="browse",
            style="SummarizeAudio.Treeview",
            height=10,
            yscrollcommand=self._session_scrollbar.set,
        )
        self._session_list.heading("#0", text="Session", anchor="w")
        self._session_list.heading("date", text="Date", anchor="center")
        self._session_list.column("#0", width=860, anchor="w", stretch=True)
        self._session_list.column("date", width=160, anchor="center", stretch=False)
        self._session_scrollbar.configure(command=self._session_list.yview)
        self._session_list.pack(side="left", fill="both", expand=True)
        self._session_scrollbar.pack(side="right", fill="y")
        for index, session in enumerate(self._sessions):
            tags = ("row_even",) if index % 2 == 0 else ("row_odd",)
            self._session_list.insert("", "end", iid=str(index), text=session.label, values=(session.date,), tags=tags)
        self._session_list.tag_configure("row_even", background="#ffffff")
        self._session_list.tag_configure("row_odd", background="#f8faff")
        self._session_list.bind("<<TreeviewSelect>>", self._on_select)
        if self._selected_index >= 0:
            self._session_list.selection_set(str(self._selected_index))
            self._session_list.focus(str(self._selected_index))
            self._session_list.see(str(self._selected_index))

        bottom = ttk.Frame(body, style="Card.TFrame")
        bottom.pack(fill="both", expand=False)
        self._detail_card = ttk.Frame(bottom, style="Card.TFrame")
        self._detail_card.pack(fill="both", expand=True)
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
        path_box.pack(fill="x", pady=(0, 12))
        title_row = ttk.Frame(path_box, style="Card.TFrame")
        title_row.pack(fill="x")
        ttk.Label(title_row, text=session.label, style="Step.TLabel").pack(side="left", anchor="w")
        if session.archived:
            ttk.Label(title_row, text="Archived", style="Badge.TLabel", padding=(10, 4)).pack(side="left", padx=(12, 0))
            ttk.Label(path_box, text="Archived session", style="Detail.TLabel").pack(anchor="w", pady=(2, 0))
        meta_row = ttk.Frame(path_box, style="Card.TFrame")
        meta_row.pack(fill="x", pady=(2, 0))
        ttk.Label(meta_row, text=f"Date: {session.date}", style="Detail.TLabel").pack(side="left")
        location = ttk.Label(
            meta_row,
            text=str(session.folder),
            style="Link.TLabel",
            cursor="hand2",
            font=("Helvetica Neue", 11, "underline"),
        )
        location.pack(side="left", padx=(28, 0))
        location.bind("<Button-1>", lambda _event, path=session.folder: self._reveal_in_finder(path))
        location.bind("<Enter>", lambda _event: location.configure(foreground="#1f5ddb"))
        location.bind("<Leave>", lambda _event: location.configure(foreground="#2e72ff"))

        details = ttk.Frame(self._detail_card, style="Card.TFrame")
        details.pack(fill="x", pady=(0, 16))
        ttk.Label(details, text=f"Summary: {session.summary.name}", style="Detail.TLabel", wraplength=1080, justify="left").pack(anchor="w", pady=1)
        if session.audio is not None:
            ttk.Label(details, text=f"Recording: {session.audio.name}", style="Detail.TLabel", wraplength=1080, justify="left").pack(anchor="w", pady=1)
        if session.transcript is not None:
            ttk.Label(details, text=f"Transcript: {session.transcript.name}", style="Detail.TLabel", wraplength=1080, justify="left").pack(anchor="w", pady=1)

        actions = ttk.Frame(self._detail_card, style="Card.TFrame")
        actions.pack(fill="x", pady=(8, 0))
        specs = session_action_specs(session)
        for idx, (label, path) in enumerate(specs):
            if idx == 0:
                self._button(actions, text=label, command=lambda p=path: self._open_file(p), primary=True).pack(side="left")
            else:
                self._button(actions, text=label, command=lambda p=path: self._open_file(p), primary=False).pack(side="left", padx=(8, 0))
        if specs:
            archive_label = "Unarchive" if session.archived else "Archive"
            self._button(
                actions,
                text=archive_label,
                command=lambda s=session: self._toggle_archive(s),
                primary=False,
            ).pack(side="left", padx=(8, 0))
        self._button(actions, text="Close", command=self._close, primary=False).pack(side="right")

    def _toggle_archive(self, session: "SessionFiles") -> None:
        archive_session(session.id, archived=not session.archived)
        self._reload_sessions(selected_id=session.id)
        self._render()

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

    def _close(self) -> None:
        try:
            self._root.destroy()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _build_parser().parse_args(argv)
    return HistoryWindow().run()


if __name__ == "__main__":
    raise SystemExit(main())
