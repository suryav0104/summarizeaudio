from __future__ import annotations

from pathlib import Path

from summarizeaudio import history_window
from summarizeaudio.sessions import SessionFiles


class FakeFrame:
    def __init__(self, *args, **kwargs):
        self.children = []

    def pack(self, *args, **kwargs):
        pass

    def winfo_children(self):
        return self.children

    def destroy(self):
        pass


class FakeLabel:
    instances = []

    def __init__(self, parent, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.binds = {}
        FakeLabel.instances.append(self)

    def pack(self, *args, **kwargs):
        pass

    def bind(self, event, callback):
        self.binds[event] = callback

    def configure(self, **kwargs):
        self.kwargs.update(kwargs)


class FakeScrollbar:
    def __init__(self, *args, **kwargs):
        self.command = None

    def configure(self, **kwargs):
        self.command = kwargs.get("command", self.command)

    def pack(self, *args, **kwargs):
        pass

    def set(self, *args, **kwargs):
        pass


class FakeTreeview:
    instances = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.items = []
        self.tags = {}
        self._selection = ()
        self._focus = None
        self._seen = None
        self._binds = {}
        self.heading_calls = []
        self.column_calls = []
        self._tag_config = {}
        FakeTreeview.instances.append(self)

    def pack(self, *args, **kwargs):
        pass

    def insert(self, parent, index, iid=None, text="", values=(), tags=()):
        self.items.append((iid, text, values, tags))

    def bind(self, event, callback):
        self._binds[event] = callback

    def heading(self, *args, **kwargs):
        self.heading_calls.append((args, kwargs))

    def column(self, *args, **kwargs):
        self.column_calls.append((args, kwargs))

    def tag_configure(self, tag, **kwargs):
        self._tag_config[tag] = kwargs

    def selection_set(self, item):
        self._selection = (str(item),)

    def selection(self):
        return self._selection

    def focus(self, item):
        self._focus = str(item)

    def see(self, item):
        self._seen = str(item)

    def yview(self, *args, **kwargs):
        pass


class FakeButton:
    instances = []

    def __init__(self, parent, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.pack_calls = []
        FakeButton.instances.append(self)

    def pack(self, *args, **kwargs):
        self.pack_calls.append((args, kwargs))


class FakeStyle:
    instances = []

    def __init__(self):
        self.configs = {}
        self.maps = {}
        self.themes = []
        FakeStyle.instances.append(self)

    def theme_use(self, *args, **kwargs):
        self.themes.append((args, kwargs))

    def configure(self, name, **kwargs):
        self.configs[name] = kwargs

    def map(self, name, **kwargs):
        self.maps[name] = kwargs


def test_history_window_renders_existing_actions_only(tmp_path, monkeypatch):
    summary = tmp_path / "SummaryFiles" / "Summary - Topic_05-08-26.md"
    transcript = tmp_path / "TranscriptionFiles" / "Transcript_Topic_05-08-26.txt"
    audio = tmp_path / "AudioFiles" / "Audio_Topic_05-08-26.mp3"
    summary.parent.mkdir(parents=True)
    transcript.parent.mkdir(parents=True)
    audio.parent.mkdir(parents=True)
    summary.write_text("summary")
    transcript.write_text("transcript")
    audio.write_text("audio")

    window = history_window.HistoryWindow.__new__(history_window.HistoryWindow)
    window._sessions = [
        SessionFiles(
            label="Topic (05-08-26)",
            date="05-08-26",
            folder=summary.parent,
            summary=summary,
            transcript=transcript,
            audio=audio,
            archived=False,
        )
    ]
    window._selected_index = 0
    window._detail_card = FakeFrame()
    window._button = history_window.HistoryWindow._button.__get__(window, history_window.HistoryWindow)
    window._button_font = ("Helvetica Neue", 13, "bold")
    window._button_bg = "#f6f8fb"
    window._button_fg = "#000000"
    window._button_secondary_bg = "#edf2f9"
    window._button_secondary_fg = "#000000"
    window._button_border = "#d4dce8"
    window._button_accent_bg = "#2e72ff"
    window._button_accent_fg = "#000000"
    window._open_file = lambda path: path
    window._reveal_in_finder = lambda path: path

    monkeypatch.setattr("summarizeaudio.history_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Label", FakeLabel)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Scrollbar", FakeScrollbar)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Treeview", FakeTreeview)
    monkeypatch.setattr("summarizeaudio.history_window.tk.Button", FakeButton)
    FakeButton.instances.clear()
    FakeTreeview.instances.clear()
    FakeLabel.instances.clear()

    window._render_selected_session()

    button_texts = [btn.kwargs["text"] for btn in FakeButton.instances]
    assert button_texts == ["Open Summary", "Open Transcript", "Open Recording", "Archive", "Close"]
    assert not any(label.kwargs.get("text") == "Sessions" for label in FakeLabel.instances)
    assert any(label.kwargs.get("text") == "Date: 05-08-26" for label in FakeLabel.instances)
    location_label = next(label for label in FakeLabel.instances if label.kwargs.get("text") == str(summary.parent))
    assert "<Button-1>" in location_label.binds


def test_history_window_renders_unarchive_for_archived_session(tmp_path, monkeypatch):
    summary = tmp_path / "SummaryFiles" / "Summary - Topic_05-08-26.md"
    transcript = tmp_path / "TranscriptionFiles" / "Transcript_Topic_05-08-26.txt"
    audio = tmp_path / "AudioFiles" / "Audio_Topic_05-08-26.mp3"
    summary.parent.mkdir(parents=True)
    transcript.parent.mkdir(parents=True)
    audio.parent.mkdir(parents=True)
    summary.write_text("summary")
    transcript.write_text("transcript")
    audio.write_text("audio")

    window = history_window.HistoryWindow.__new__(history_window.HistoryWindow)
    window._sessions = [
        SessionFiles(
            label="Topic (05-08-26)",
            date="05-08-26",
            folder=summary.parent,
            summary=summary,
            transcript=transcript,
            audio=audio,
            archived=True,
        )
    ]
    window._selected_index = 0
    window._detail_card = FakeFrame()
    window._button = history_window.HistoryWindow._button.__get__(window, history_window.HistoryWindow)
    window._button_font = ("Helvetica Neue", 13, "bold")
    window._button_bg = "#f6f8fb"
    window._button_fg = "#000000"
    window._button_secondary_bg = "#edf2f9"
    window._button_secondary_fg = "#000000"
    window._button_border = "#d4dce8"
    window._button_accent_bg = "#2e72ff"
    window._button_accent_fg = "#000000"
    window._open_file = lambda path: path
    window._reveal_in_finder = lambda path: path

    monkeypatch.setattr("summarizeaudio.history_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Label", FakeLabel)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Scrollbar", FakeScrollbar)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Treeview", FakeTreeview)
    monkeypatch.setattr("summarizeaudio.history_window.tk.Button", FakeButton)
    FakeButton.instances.clear()
    FakeLabel.instances.clear()

    window._render_selected_session()

    button_texts = [btn.kwargs["text"] for btn in FakeButton.instances]
    assert button_texts[-2:] == ["Unarchive", "Close"]
    assert any(label.kwargs.get("text") == "Archived" for label in FakeLabel.instances)


def test_history_window_omits_missing_actions(tmp_path):
    summary = tmp_path / "SummaryFiles" / "Summary - Notes_05-08-26.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("summary")

    session = SessionFiles(
        label="Notes (05-08-26)",
        date="05-08-26",
        folder=summary.parent,
        summary=summary,
        transcript=None,
        audio=None,
    )

    assert history_window.session_action_specs(session) == [
        ("Open Summary", summary),
    ]


def test_history_window_renders_date_column(tmp_path, monkeypatch):
    summary = tmp_path / "SummaryFiles" / "Summary - Topic_05-08-26.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("summary")

    class FakeRoot:
        def __init__(self):
            self.children = []
            self.geometry_value = None
            self.minsize_value = None

        def withdraw(self):
            pass

        def title(self, *_args):
            pass

        def geometry(self, value):
            self.geometry_value = value

        def minsize(self, *args):
            self.minsize_value = args

        def resizable(self, *args):
            pass

        def configure(self, *args, **kwargs):
            pass

        def protocol(self, *args):
            pass

        def update_idletasks(self):
            pass

        def winfo_screenwidth(self):
            return 1920

        def winfo_screenheight(self):
            return 1080

        def lift(self):
            pass

        def attributes(self, *args):
            pass

        def after(self, *args):
            pass

        def focus_force(self):
            pass

        def mainloop(self):
            pass

        def destroy(self):
            pass

        def winfo_children(self):
            return self.children

    monkeypatch.setattr("summarizeaudio.history_window.load_config", lambda: type("Cfg", (), {"storage": type("S", (), {"output_folder": tmp_path})()})())
    monkeypatch.setattr(
        "summarizeaudio.history_window.load_sessions",
        lambda root, limit=None, include_archived=False: [
            SessionFiles(
                label="Topic (05-08-26)",
                date="05-08-26",
                folder=summary.parent,
                summary=summary,
                transcript=None,
                audio=None,
                archived=False,
            )
        ],
    )
    monkeypatch.setattr("summarizeaudio.history_window.tk.Tk", lambda: FakeRoot())
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Style", lambda: type("S", (), {"theme_use": lambda *a, **k: None, "configure": lambda *a, **k: None, "map": lambda *a, **k: None})())
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Label", FakeLabel)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Scrollbar", FakeScrollbar)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Treeview", FakeTreeview)
    monkeypatch.setattr("summarizeaudio.history_window.tk.Button", FakeButton)
    FakeTreeview.instances.clear()
    FakeLabel.instances.clear()

    window = history_window.HistoryWindow()
    window._render()
    assert FakeTreeview.instances[0].kwargs["columns"] == ("date",)
    assert FakeTreeview.instances[0].items == [("0", "Topic (05-08-26)", ("05-08-26",), ("row_even",))]
    assert FakeTreeview.instances[0].heading_calls[0][1]["text"] == "Session"
    assert FakeTreeview.instances[0].heading_calls[0][1]["anchor"] == "w"
    assert FakeTreeview.instances[0].heading_calls[1][1]["text"] == "Date"
    assert FakeTreeview.instances[0]._tag_config["row_even"]["background"] == "#ffffff"
    assert FakeTreeview.instances[0]._tag_config["row_odd"]["background"] == "#f8faff"
    assert any(label.kwargs.get("text") == "Date: 05-08-26" for label in FakeLabel.instances)
    assert FakeTreeview.instances[0]._selection == ("0",)
    assert FakeTreeview.instances[0]._focus == "0"
    assert FakeTreeview.instances[0]._seen == "0"


def test_history_window_uses_neutral_header_and_selection_colors(tmp_path, monkeypatch):
    summary = tmp_path / "SummaryFiles" / "Summary - Topic_05-08-26.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("summary")

    class FakeRoot:
        def __init__(self):
            self.children = []
            self.geometry_value = None
            self.minsize_value = None

        def withdraw(self):
            pass

        def title(self, *_args):
            pass

        def geometry(self, value):
            self.geometry_value = value

        def minsize(self, *args):
            self.minsize_value = args

        def resizable(self, *args):
            pass

        def configure(self, *args, **kwargs):
            pass

        def protocol(self, *args):
            pass

        def update_idletasks(self):
            pass

        def winfo_screenwidth(self):
            return 1920

        def winfo_screenheight(self):
            return 1080

        def lift(self):
            pass

        def attributes(self, *args):
            pass

        def after(self, *args):
            pass

        def focus_force(self):
            pass

        def mainloop(self):
            pass

        def destroy(self):
            pass

        def winfo_children(self):
            return self.children

    monkeypatch.setattr("summarizeaudio.history_window.load_config", lambda: type("Cfg", (), {"storage": type("S", (), {"output_folder": tmp_path})()})())
    monkeypatch.setattr(
        "summarizeaudio.history_window.load_sessions",
        lambda root, limit=None, include_archived=False: [
            SessionFiles(
                label="Topic (05-08-26)",
                date="05-08-26",
                folder=summary.parent,
                summary=summary,
                transcript=None,
                audio=None,
                archived=False,
            )
        ],
    )
    monkeypatch.setattr("summarizeaudio.history_window.tk.Tk", lambda: FakeRoot())
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Label", FakeLabel)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Scrollbar", FakeScrollbar)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Treeview", FakeTreeview)
    monkeypatch.setattr("summarizeaudio.history_window.tk.Button", FakeButton)
    FakeStyle.instances.clear()
    FakeTreeview.instances.clear()
    FakeLabel.instances.clear()
    FakeButton.instances.clear()

    history_window.HistoryWindow()

    style = FakeStyle.instances[0]
    assert style.configs["SummarizeAudio.Treeview.Heading"]["padding"] == (34, 10, 14, 10)
    assert style.configs["SummarizeAudio.Treeview.Heading"]["foreground"] == "#000000"
    assert style.maps["SummarizeAudio.Treeview"]["background"] == [("selected", "#e4e7ec")]


def test_history_window_renders_only_one_list_and_toggles_modes(tmp_path, monkeypatch):
    active_summary = tmp_path / "SummaryFiles" / "Summary - Active_05-10-26.md"
    archived_summary = tmp_path / "SummaryFiles" / "Summary - Archived_05-08-26.md"
    active_summary.parent.mkdir(parents=True)
    archived_summary.parent.mkdir(parents=True, exist_ok=True)
    active_summary.write_text("active")
    archived_summary.write_text("archived")

    monkeypatch.setattr(
        "summarizeaudio.history_window.load_config",
        lambda: type("Cfg", (), {"storage": type("S", (), {"output_folder": tmp_path})()})(),
    )
    monkeypatch.setattr(
        "summarizeaudio.history_window.load_sessions",
        lambda root, limit=None, include_archived=False: [
            SessionFiles(
                label="Active (05-10-26)",
                date="05-10-26",
                folder=active_summary.parent,
                summary=active_summary,
                transcript=None,
                audio=None,
                id="active-1",
                archived=False,
            )
        ]
        if not include_archived
        else [
            SessionFiles(
                label="Archived (05-08-26)",
                date="05-08-26",
                folder=archived_summary.parent,
                summary=archived_summary,
                transcript=None,
                audio=None,
                id="archived-1",
                archived=True,
            )
        ],
    )

    class FakeRoot:
        def __init__(self):
            self.children = []
            self.geometry_value = None
            self.minsize_value = None

        def withdraw(self):
            pass

        def title(self, *_args):
            pass

        def geometry(self, value):
            self.geometry_value = value

        def minsize(self, *args):
            self.minsize_value = args

        def resizable(self, *args):
            pass

        def configure(self, *args, **kwargs):
            pass

        def protocol(self, *args):
            pass

        def update_idletasks(self):
            pass

        def winfo_screenwidth(self):
            return 1920

        def winfo_screenheight(self):
            return 1080

        def lift(self):
            pass

        def attributes(self, *args):
            pass

        def after(self, *args):
            pass

        def focus_force(self):
            pass

        def mainloop(self):
            pass

        def destroy(self):
            pass

        def winfo_children(self):
            return self.children

    monkeypatch.setattr("summarizeaudio.history_window.tk.Tk", lambda: FakeRoot())
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Style", lambda: type("S", (), {"theme_use": lambda *a, **k: None, "configure": lambda *a, **k: None, "map": lambda *a, **k: None})())
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Label", FakeLabel)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Scrollbar", FakeScrollbar)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Treeview", FakeTreeview)
    monkeypatch.setattr("summarizeaudio.history_window.tk.Button", FakeButton)
    FakeTreeview.instances.clear()
    FakeLabel.instances.clear()
    FakeButton.instances.clear()

    window = history_window.HistoryWindow()
    window._render()

    assert len(FakeTreeview.instances) == 1
    assert FakeTreeview.instances[0].items == [("0", "Active (05-10-26)", ("05-10-26",), ("row_even",))]
    assert any(btn.kwargs.get("text") == "Archive" for btn in FakeButton.instances)

    FakeTreeview.instances.clear()
    FakeLabel.instances.clear()
    FakeButton.instances.clear()
    window._toggle_archived_filter()

    assert len(FakeTreeview.instances) == 1
    assert FakeTreeview.instances[0].items == [("0", "Archived (05-08-26)", ("05-08-26",), ("row_even",))]
    assert any(btn.kwargs.get("text") == "Active" for btn in FakeButton.instances)


def test_history_window_close_button_is_right_aligned(tmp_path, monkeypatch):
    summary = tmp_path / "SummaryFiles" / "Summary - Topic_05-08-26.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("summary")

    monkeypatch.setattr(
        "summarizeaudio.history_window.load_config",
        lambda: type("Cfg", (), {"storage": type("S", (), {"output_folder": tmp_path})()})(),
    )
    monkeypatch.setattr(
        "summarizeaudio.history_window.load_sessions",
        lambda root, limit=None, include_archived=False: [],
    )

    class FakeRoot:
        def __init__(self):
            self.children = []

        def withdraw(self):
            pass

        def title(self, *_args):
            pass

        def geometry(self, *_args):
            pass

        def minsize(self, *_args):
            pass

        def resizable(self, *_args):
            pass

        def configure(self, *_args, **_kwargs):
            pass

        def protocol(self, *_args):
            pass

        def update_idletasks(self):
            pass

        def winfo_screenwidth(self):
            return 1920

        def winfo_screenheight(self):
            return 1080

        def lift(self):
            pass

        def attributes(self, *_args):
            pass

        def after(self, *_args):
            pass

        def focus_force(self):
            pass

        def mainloop(self):
            pass

        def destroy(self):
            pass

        def winfo_children(self):
            return self.children

    monkeypatch.setattr("summarizeaudio.history_window.tk.Tk", lambda: FakeRoot())
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Style", lambda: type("S", (), {"theme_use": lambda *a, **k: None, "configure": lambda *a, **k: None, "map": lambda *a, **k: None})())
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Label", FakeLabel)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Scrollbar", FakeScrollbar)
    monkeypatch.setattr("summarizeaudio.history_window.ttk.Treeview", FakeTreeview)
    monkeypatch.setattr("summarizeaudio.history_window.tk.Button", FakeButton)
    FakeButton.instances.clear()
    FakeLabel.instances.clear()

    window = history_window.HistoryWindow()
    window._render()

    close_button = next(btn for btn in FakeButton.instances if btn.kwargs.get("text") == "Close")
    assert close_button.pack_calls[-1][1]["side"] == "right"


def test_history_window_open_file_uses_open_on_macos(tmp_path, monkeypatch):
    window = history_window.HistoryWindow.__new__(history_window.HistoryWindow)
    calls = []
    monkeypatch.setattr("summarizeaudio.history_window.sys.platform", "darwin")
    monkeypatch.setattr("summarizeaudio.history_window.subprocess.run", lambda cmd, check=False: calls.append(cmd))

    window._open_file(tmp_path / "Transcript.md")

    assert calls
    assert calls[0] == ["open", str(tmp_path / "Transcript.md")]


def test_history_window_reveal_in_finder_uses_finder_reveal_on_macos(tmp_path, monkeypatch):
    window = history_window.HistoryWindow.__new__(history_window.HistoryWindow)
    calls = []
    monkeypatch.setattr("summarizeaudio.history_window.sys.platform", "darwin")
    monkeypatch.setattr("summarizeaudio.history_window.subprocess.run", lambda cmd, check=False: calls.append(cmd))

    window._reveal_in_finder(tmp_path / "History Folder")

    assert calls
    assert calls[0][0] == "osascript"
    assert "reveal POSIX file" in calls[0][2]
