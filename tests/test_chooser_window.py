from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from summarizeaudio import chooser_window


def test_native_audio_picker_uses_osascript(monkeypatch):
    calls = []

    def fake_osascript(script: str):
        calls.append(script)
        return 0, "/tmp/example.mp3"

    monkeypatch.setattr(chooser_window, "_osascript", fake_osascript)
    monkeypatch.setattr(chooser_window.sys, "platform", "darwin")

    assert chooser_window._native_audio_picker("Select Audio File") == "/tmp/example.mp3"
    assert calls
    assert "choose file with prompt \"Select Audio File\"" in calls[0]


def test_chooser_button_closes_then_launches_native_picker(monkeypatch, capsys):
    order = []
    state = {}

    class FakeRoot:
        def withdraw(self):
            order.append("withdraw")

        def title(self, value):
            order.append(("title", value))

        def geometry(self, value):
            order.append(("geometry", value))

        def minsize(self, *args):
            pass

        def resizable(self, *args):
            pass

        def configure(self, *args, **kwargs):
            pass

        def protocol(self, *args):
            pass

        def deiconify(self):
            order.append("deiconify")

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
            order.append("grab_release")

        def quit(self):
            order.append("quit")

        def destroy(self):
            order.append("destroy")

        def mainloop(self):
            assert state.get("choose") is not None
            state["choose"]()

    class FakeWidget:
        def __init__(self, *args, **kwargs):
            pass

        def pack(self, *args, **kwargs):
            pass

        def place(self, *args, **kwargs):
            pass

        def grid(self, *args, **kwargs):
            pass

        def pack_forget(self):
            pass

        def destroy(self):
            pass

        def config(self, *args, **kwargs):
            pass

        configure = config

    class FakeButton(FakeWidget):
        def __init__(self, parent, *args, **kwargs):
            super().__init__()
            if kwargs.get("text") == "Choose File":
                state["choose"] = kwargs.get("command")

    fake_tk = types.ModuleType("tkinter")
    fake_tk.Tk = lambda: FakeRoot()
    fake_tk.Canvas = FakeWidget
    fake_tk.Frame = FakeWidget
    fake_tk.Label = FakeWidget
    fake_ttk = types.ModuleType("tkinter.ttk")
    fake_ttk.Frame = FakeWidget
    fake_ttk.Button = FakeButton
    fake_ttk.Progressbar = FakeWidget
    fake_ttk.Scrollbar = FakeWidget
    fake_tk.ttk = fake_ttk
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_ttk)
    monkeypatch.setattr(chooser_window.sys, "platform", "darwin")
    monkeypatch.setattr(chooser_window, "_native_audio_picker", lambda title: order.append(("picker", title)) or "/tmp/example.mp3")

    result = chooser_window.main(["--kind", "audio"])

    assert result == 0
    assert order.index("quit") < order.index("destroy")
    assert order.index("destroy") < order.index(("picker", "Select Audio File"))
    assert state.get("choose") is not None
    assert "/tmp/example.mp3" in capsys.readouterr().out


def test_chooser_cancel_returns_one(monkeypatch):
    state = {}

    class FakeRoot:
        def withdraw(self):
            pass

        def title(self, value):
            pass

        def geometry(self, value):
            pass

        def minsize(self, *args):
            pass

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

        def quit(self):
            pass

        def destroy(self):
            pass

        def mainloop(self):
            return None

    class FakeWidget:
        def __init__(self, *args, **kwargs):
            pass

        def pack(self, *args, **kwargs):
            pass

        def place(self, *args, **kwargs):
            pass

        def grid(self, *args, **kwargs):
            pass

        def pack_forget(self):
            pass

        def destroy(self):
            pass

        def config(self, *args, **kwargs):
            pass

        configure = config

    class FakeButton(FakeWidget):
        def __init__(self, parent, *args, **kwargs):
            super().__init__()
            if kwargs.get("text") == "Choose File":
                state["choose"] = kwargs.get("command")

    fake_tk = types.ModuleType("tkinter")
    fake_tk.Tk = lambda: FakeRoot()
    fake_tk.Canvas = FakeWidget
    fake_tk.Frame = FakeWidget
    fake_tk.Label = FakeWidget
    fake_ttk = types.ModuleType("tkinter.ttk")
    fake_ttk.Frame = FakeWidget
    fake_ttk.Button = FakeButton
    fake_ttk.Progressbar = FakeWidget
    fake_ttk.Scrollbar = FakeWidget
    fake_tk.ttk = fake_ttk
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_ttk)
    monkeypatch.setattr(chooser_window.sys, "platform", "darwin")

    assert chooser_window.main(["--kind", "audio"]) == 1
