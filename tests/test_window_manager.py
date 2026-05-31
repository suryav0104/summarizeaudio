from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest.mock import MagicMock

from summarizeaudio import window_manager
from summarizeaudio.config import (
    AppConfig,
    BehaviorConfig,
    OllamaConfig,
    RecordingConfig,
    StorageConfig,
    SummarizationConfig,
    WhisperConfig,
)


class _FakeNSImage:
    loaded_paths: list[str] = []

    @classmethod
    def alloc(cls):
        return cls()

    def initWithContentsOfFile_(self, path: str):
        self.loaded_paths.append(path)
        return SimpleNamespace(path=path)


def _make_cfg(tmp_path):
    return AppConfig(
        storage=StorageConfig(output_folder=tmp_path),
        whisper=WhisperConfig(model="tiny", language="en"),
        ollama=OllamaConfig(host="http://localhost:11434", model="gemma3:4b"),
        summarization=SummarizationConfig(default_prompt="x"),
        behavior=BehaviorConfig(show_override_dialog=False, auto_open_summary=False),
        recording=RecordingConfig(input_device=None),
    )


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


def test_window_manager_accepts_on_rebuild_tray(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    cb = MagicMock()
    wm = window_manager.WindowManager(
        _make_cfg(tmp_path), queue.Queue(), on_rebuild_tray=cb
    )
    assert wm._on_rebuild_tray is cb
    assert wm._settings_win is None
    assert wm._last_pipeline_active is False
