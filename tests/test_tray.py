from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import types

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


def test_model_menu_checks_current_config_model(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:12b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())
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
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())
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


def test_rumps_icon_state_uses_emoji_title(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())
    app = TrayApp()
    app._use_rumps = True
    app._tray = SimpleNamespace(title=None)

    app._set_icon("recording")

    assert app._tray.title == "🔴"


def test_info_dialog_uses_centered_macos_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())
    monkeypatch.setattr("summarizeaudio.tray.sys.platform", "darwin")
    calls = []
    monkeypatch.setattr("summarizeaudio.tray._osascript", lambda script: calls.append(script) or (0, ""))
    app = TrayApp()

    app._on_info_dialog("No usable audio was captured.", "Check your input.")

    assert calls
    assert "display dialog" in calls[0]
    assert "with icon note" in calls[0]


def test_override_dialog_uses_scrollable_editor_and_preserves_full_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())

    app = TrayApp()
    resolved = []
    override = SimpleNamespace(_resolve=lambda value: resolved.append(value))
    prompt = "Line 1\n" + ("long prompt text\n" * 40) + "Transcript:\n{transcript}"

    called = []
    def fake_run(cmd, input=None, text=None, capture_output=None, check=None):
        called.append((cmd, input))
        return SimpleNamespace(returncode=0, stdout=input)

    monkeypatch.setattr("summarizeaudio.tray.subprocess.run", fake_run)

    app._on_override_dialog(override, prompt)

    import time
    for _ in range(50):
        if resolved:
            break
        time.sleep(0.01)

    assert called
    assert called[0][0][:3] == [__import__("sys").executable, "-m", "summarizeaudio.prompt_editor"]
    assert resolved == [prompt]


def test_cancel_name_dialog_stops_active_recording(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())
    monkeypatch.setattr("summarizeaudio.tray.sys.platform", "darwin")
    monkeypatch.setattr("summarizeaudio.tray._osascript", lambda _script: (1, ""))

    class FakeRecorder:
        cleaned = False
        def cleanup(self, delete_wav=False):
            self.cleaned = delete_wav

    app = TrayApp()
    app._tray = SimpleNamespace(menu=None, icon=None)
    namer = SimpleNamespace(_default="Recording_01-01-26", _resolve=lambda _value: None)
    recorder = FakeRecorder()
    app._namer = namer
    app._recorder = recorder

    app._on_name_dialog(namer)

    assert recorder.cleaned is True
    assert app._namer is None
    assert app._recorder is None
