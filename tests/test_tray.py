from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from summarizeaudio.config import (
    AppConfig,
    BehaviorConfig,
    OllamaConfig,
    RecordingConfig,
    StorageConfig,
    SummarizationConfig,
    WhisperConfig,
)
from summarizeaudio.tray import TrayApp


def make_config(tmp_path: Path, model: str) -> AppConfig:
    return AppConfig(
        storage=StorageConfig(output_folder=tmp_path),
        whisper=WhisperConfig(model="tiny", language="en"),
        ollama=OllamaConfig(host="http://localhost:11434", model=model),
        summarization=SummarizationConfig(default_prompt="Summarize: {transcript}"),
        behavior=BehaviorConfig(show_override_dialog=False, auto_open_summary=False),
        recording=RecordingConfig(input_device=None),
    )


def _fake_wm():
    return SimpleNamespace(
        root=SimpleNamespace(after=lambda *a: None, quit=lambda: None)
    )


def test_model_menu_checks_current_config_model(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:12b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm())
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None)

    app._rebuild_menu()

    items = list(app._tray.menu.items)
    fast = next(item for item in items if "Fast Mode (gemma3:4b)" in item.text)
    high = next(item for item in items if "High Quality Mode (gemma3:12b)" in item.text)
    assert fast.text == "Fast Mode (gemma3:4b)"
    assert high.text == "✓ High Quality Mode (gemma3:12b)"


def test_model_menu_updates_checkmark_after_selection(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm())
    saved = []

    def fake_save(cfg):
        saved.append(cfg.ollama.model)

    monkeypatch.setattr("summarizeaudio.tray.save_config", fake_save)
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None)

    app._rebuild_menu()
    items = list(app._tray.menu.items)
    fast = next(item for item in items if "Fast Mode (gemma3:4b)" in item.text)
    high = next(item for item in items if "High Quality Mode (gemma3:12b)" in item.text)
    assert fast.text == "✓ Fast Mode (gemma3:4b)"
    assert high.text == "High Quality Mode (gemma3:12b)"

    app._on_quality_high(None, None)

    app._rebuild_menu()
    items = list(app._tray.menu.items)
    fast = next(item for item in items if "Fast Mode (gemma3:4b)" in item.text)
    high = next(item for item in items if "High Quality Mode (gemma3:12b)" in item.text)
    assert fast.text == "Fast Mode (gemma3:4b)"
    assert high.text == "✓ High Quality Mode (gemma3:12b)"
    assert saved[-1] == "gemma3:12b"


def test_history_menu_shows_popup_item(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm())
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None)

    app._rebuild_menu()

    items = list(app._tray.menu.items)
    assert any(item.text == "History…" for item in items)


def test_on_history_posts_show_history_to_queue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm())
    app = TrayApp()

    app._on_history(None, None)

    item = app._ui_queue.get_nowait()
    assert item == ("show_history",)


def test_on_local_audio_posts_show_workflow_to_queue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm())
    app = TrayApp()

    app._on_local_audio(None, None)

    item = app._ui_queue.get_nowait()
    assert item[0] == "show_workflow"
    assert item[1] == "audio"


def test_on_local_text_posts_show_workflow_to_queue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm())
    app = TrayApp()

    app._on_local_text(None, None)

    item = app._ui_queue.get_nowait()
    assert item[0] == "show_workflow"
    assert item[1] == "text"


def test_stop_recording_posts_show_workflow_to_queue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm())

    class FakeRecorder:
        stopped = False

        def stop(self):
            self.stopped = True
            return (Path("/tmp/recording.mp3"), None, None)

        def cleanup(self, delete_wav=False):
            return None

    app = TrayApp()
    app._tray = SimpleNamespace(menu=None, icon=None)
    app._recorder = FakeRecorder()
    monkeypatch.setattr(app, "_set_icon", lambda state: None)
    monkeypatch.setattr(app, "_rebuild_menu", lambda: None)

    app._on_stop_recording(None, None)

    assert app._recorder is None
    item = app._ui_queue.get_nowait()
    assert item[0] == "show_workflow"
    assert item[1] == "record"
    assert item[2] == Path("/tmp/recording.mp3")


def test_start_recording_does_not_prompt_for_name(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm())

    class FakeRecorder:
        def __init__(self, *args, **kwargs):
            self.started = False

        def start(self):
            self.started = True

        def cleanup(self, delete_wav=False):
            return None

    monkeypatch.setattr("summarizeaudio.tray.Recorder", FakeRecorder)
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None, icon=None)

    app._on_start_recording(None, None)

    assert app._recorder is not None


def test_on_icon_state_manages_pipeline_running_flag(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm())
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None, icon=None)

    assert not app._pipeline_running.is_set()

    app._on_icon_state("processing")
    assert app._pipeline_running.is_set()

    app._on_icon_state("idle")
    assert not app._pipeline_running.is_set()
