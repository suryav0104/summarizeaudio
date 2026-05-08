from __future__ import annotations

import sys
import types
from io import StringIO

from summarizeaudio import prompt_editor


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

    def update_idletasks(self):
        pass

    def update(self):
        pass

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def protocol(self, *args):
        pass

    def deiconify(self):
        pass

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
        self.kwargs = kwargs
        self.pack_calls = []

    def pack(self, *args, **kwargs):
        self.pack_calls.append(kwargs)

    def destroy(self):
        pass

    def configure(self, *args, **kwargs):
        self.kwargs.update(kwargs)


class FakeButton(FakeWidget):
    instances = []

    def __init__(self, parent, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent = parent
        FakeButton.instances.append(self)


class FakeText(FakeWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.content = ""

    def insert(self, index, value):
        self.content += value

    def focus_set(self):
        pass

    def get(self, start, end):
        return self.content


class FakeEntry(FakeWidget):
    def focus_set(self):
        pass


class FakeStringVar:
    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _install_fake_tk(monkeypatch):
    fake_tk = types.ModuleType("tkinter")
    fake_tk.Tk = lambda: FakeRoot()
    fake_tk.Button = FakeButton
    fake_tk.Entry = FakeEntry
    fake_tk.StringVar = lambda value="": FakeStringVar(value)
    fake_ttk = types.ModuleType("tkinter.ttk")
    fake_ttk.Frame = FakeWidget
    fake_ttk.Label = FakeWidget
    fake_ttk.Style = lambda: types.SimpleNamespace(theme_use=lambda *a, **k: None, configure=lambda *a, **k: None)
    fake_scrolled = types.ModuleType("tkinter.scrolledtext")
    fake_scrolled.ScrolledText = FakeText
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_ttk)
    monkeypatch.setitem(sys.modules, "tkinter.scrolledtext", fake_scrolled)


def test_prompt_editor_prompt_buttons_are_left_aligned(monkeypatch):
    _install_fake_tk(monkeypatch)
    monkeypatch.setattr(sys, "stdin", StringIO("Summarize: {transcript}"))
    FakeButton.instances.clear()

    result = prompt_editor.main(["--mode", "prompt", "--title", "SummarizeAudio"])

    assert result == 1
    assert [btn.kwargs["text"] for btn in FakeButton.instances] == ["Summarize", "Skip"]
    assert FakeButton.instances[0].pack_calls[-1].get("side") == "left"
    assert FakeButton.instances[1].pack_calls[-1].get("side") == "left"


def test_prompt_editor_name_buttons_are_left_aligned(monkeypatch):
    _install_fake_tk(monkeypatch)
    monkeypatch.setattr(sys, "stdin", StringIO("Project Update"))
    FakeButton.instances.clear()

    result = prompt_editor.main(["--mode", "name", "--title", "SummarizeAudio"])

    assert result == 1
    assert [btn.kwargs["text"] for btn in FakeButton.instances] == ["Save", "Cancel"]
    assert FakeButton.instances[0].pack_calls[-1].get("side") == "left"
    assert FakeButton.instances[1].pack_calls[-1].get("side") == "left"
