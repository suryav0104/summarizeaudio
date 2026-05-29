from __future__ import annotations

from types import SimpleNamespace

from summarizeaudio import window_manager


class _FakeNSImage:
    loaded_paths: list[str] = []

    @classmethod
    def alloc(cls):
        return cls()

    def initWithContentsOfFile_(self, path: str):
        self.loaded_paths.append(path)
        return SimpleNamespace(path=path)


def test_load_dock_icon_prefers_dock_icon(monkeypatch):
    _FakeNSImage.loaded_paths.clear()
    monkeypatch.setitem(
        __import__("sys").modules,
        "AppKit",
        SimpleNamespace(NSImage=_FakeNSImage),
    )

    icon = window_manager.WindowManager.__new__(window_manager.WindowManager)._load_dock_icon()

    assert icon is not None
    assert _FakeNSImage.loaded_paths[-1].endswith("/assets/dock_icon.png")


def test_load_dock_icon_falls_back_to_idle_icon(monkeypatch):
    _FakeNSImage.loaded_paths.clear()
    monkeypatch.setitem(
        __import__("sys").modules,
        "AppKit",
        SimpleNamespace(NSImage=_FakeNSImage),
    )
    original_exists = window_manager.Path.exists

    def fake_exists(path):
        if path.name == "dock_icon.png":
            return False
        return original_exists(path)

    monkeypatch.setattr(window_manager.Path, "exists", fake_exists)

    icon = window_manager.WindowManager.__new__(window_manager.WindowManager)._load_dock_icon()

    assert icon is not None
    assert _FakeNSImage.loaded_paths[-1].endswith("/assets/icon_idle.png")
