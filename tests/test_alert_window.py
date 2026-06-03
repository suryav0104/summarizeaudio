from __future__ import annotations

import sys
import types
from io import StringIO

from summarizeaudio import alert_window


class FakeRoot:
    instances = []

    def __init__(self):
        self.calls = []
        FakeRoot.instances.append(self)

    def withdraw(self):
        self.calls.append(("withdraw",))

    def title(self, value):
        self.title_value = value

    def geometry(self, value):
        self.calls.append(("geometry", value))
        self.geometry_value = value

    def minsize(self, *args):
        self.minsize_value = args

    def resizable(self, *args):
        pass

    def configure(self, *args, **kwargs):
        pass

    def protocol(self, *args):
        pass

    def deiconify(self):
        self.calls.append(("deiconify",))

    def update_idletasks(self):
        self.calls.append(("update_idletasks",))

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

    def grab_set(self):
        pass

    def grab_release(self):
        pass

    def destroy(self):
        pass

    def mainloop(self):
        return None


class FakeWidget:
    instances = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.pack_calls = []
        FakeWidget.instances.append(self)

    def pack(self, *args, **kwargs):
        self.pack_calls.append(kwargs)

    def configure(self, *args, **kwargs):
        pass

    config = configure

    def bind(self, sequence, func):
        self.binds = getattr(self, "binds", {})
        self.binds[sequence] = func


class FakeButton(FakeWidget):
    pass


def _install_fake_tk(monkeypatch):
    fake_tk = types.ModuleType("tkinter")
    fake_tk.Tk = lambda: FakeRoot()
    fake_tk.Frame = FakeWidget
    fake_tk.Label = FakeWidget
    fake_tk.Button = FakeButton
    fake_ttk = types.ModuleType("tkinter.ttk")
    fake_ttk.Frame = FakeWidget
    fake_ttk.Label = FakeWidget
    fake_ttk.Style = lambda: types.SimpleNamespace(theme_use=lambda *a, **k: None, configure=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_ttk)


def test_alert_window_shows_close_button(monkeypatch):
    _install_fake_tk(monkeypatch)
    monkeypatch.setattr(sys, "stdin", StringIO("Something happened"))
    FakeWidget.instances.clear()
    FakeRoot.instances.clear()

    assert alert_window.main(["--title", "SummarizeAudio"]) == 0
    assert any(getattr(widget, "kwargs", {}).get("text") == "Close" for widget in FakeWidget.instances)


def test_alert_window_centers_before_showing(monkeypatch):
    _install_fake_tk(monkeypatch)
    monkeypatch.setattr(sys, "stdin", StringIO("Something happened"))
    FakeRoot.instances.clear()

    assert alert_window.main(["--title", "SummarizeAudio"]) == 0

    calls = FakeRoot.instances[0].calls
    final_geometry_index = calls.index(("geometry", "760x360+580+360"))
    deiconify_index = calls.index(("deiconify",))
    assert final_geometry_index < deiconify_index


def test_message_parts_separates_primary_error_from_details():
    primary, supporting = alert_window._message_parts(
        "Component: tray.py -> recorder\n\n"
        "Configured recording device 'Multi-input device' was not found.\n\n"
        "Technical details were saved to /Users/surya/.summarizeaudio/app.log."
    )

    assert primary == "Configured recording device 'Multi-input device' was not found."
    assert "Component: tray.py -> recorder" in supporting
    assert "Technical details were saved" in supporting


def test_alert_window_renders_error_and_details_as_separate_left_aligned_messages(monkeypatch):
    _install_fake_tk(monkeypatch)
    monkeypatch.setattr(
        sys,
        "stdin",
        StringIO(
            "Component: tray.py -> recorder\n\n"
            "Configured recording device 'Multi-input device' was not found.\n\n"
            "Technical details were saved to /Users/surya/.summarizeaudio/app.log."
        ),
    )
    FakeWidget.instances.clear()

    assert alert_window.main(["--title", "Recording Input Problem"]) == 0

    primary = next(
        widget for widget in FakeWidget.instances
        if widget.kwargs.get("text") == "Configured recording device 'Multi-input device' was not found."
    )
    assert primary.kwargs.get("font") == ("Helvetica Neue", 11)
    assert primary.kwargs.get("justify") == "left"
    assert primary.kwargs.get("anchor") == "w"

    assert any(widget.kwargs.get("text") == "Component: tray.py -> recorder" for widget in FakeWidget.instances)
    # The log path is now split out into its own clickable link label rather
    # than baked into the sentence text.
    assert any(
        widget.kwargs.get("text") == "/Users/surya/.summarizeaudio/app.log"
        for widget in FakeWidget.instances
    )
    assert any(
        widget.kwargs.get("text") == "Technical details were saved to "
        for widget in FakeWidget.instances
    )


def test_split_log_path_extracts_path():
    result = alert_window._split_log_path(
        "Technical details were saved to /Users/surya/.summarizeaudio/app.log.",
        "/Users/surya/.summarizeaudio/app.log",
    )
    assert result == (
        "Technical details were saved to ",
        "/Users/surya/.summarizeaudio/app.log",
        ".",
    )


def test_split_log_path_returns_none_when_absent():
    assert alert_window._split_log_path("no path in here", "/x/app.log") is None


def test_alert_window_renders_log_path_as_clickable_link(monkeypatch):
    _install_fake_tk(monkeypatch)
    opened = []
    monkeypatch.setattr(alert_window, "_open_path", lambda p: opened.append(p))
    log_path = str(alert_window.LOG_PATH)
    monkeypatch.setattr(
        sys,
        "stdin",
        StringIO(
            "Component: summarizer.py\n\n"
            "Ollama timed out while generating the summary.\n\n"
            f"Technical details were saved to {log_path}."
        ),
    )
    FakeWidget.instances.clear()

    assert alert_window.main(["--title", "SummarizeAudio Error"]) == 0

    link = next(w for w in FakeWidget.instances if w.kwargs.get("text") == log_path)
    assert link.kwargs.get("fg") == "#2563eb"
    assert "underline" in link.kwargs.get("font", ())
    assert link.kwargs.get("cursor")
    # Clicking the link opens the log file.
    link.binds["<Button-1>"](None)
    assert opened == [log_path]
