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
    assert any(
        widget.kwargs.get("text") == "Technical details were saved to /Users/surya/.summarizeaudio/app.log."
        for widget in FakeWidget.instances
    )
