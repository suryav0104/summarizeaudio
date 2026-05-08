from __future__ import annotations

import sys
import types
from io import StringIO

from summarizeaudio import alert_window


class FakeRoot:
    def withdraw(self):
        pass

    def title(self, value):
        self.title_value = value

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

    def deiconify(self):
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

    assert alert_window.main(["--title", "SummarizeAudio"]) == 0
    assert any(getattr(widget, "kwargs", {}).get("text") == "Close" for widget in FakeWidget.instances)
