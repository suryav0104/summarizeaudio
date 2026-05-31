from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest

from summarizeaudio.config import (
    AppConfig,
    BehaviorConfig,
    OllamaConfig,
    RecordingConfig,
    StorageConfig,
    SummarizationConfig,
    WhisperConfig,
)
from summarizeaudio.ollama_client import ModelInfo


def _cfg(tmp_path: Path, model: str = "gemma3:4b", device: str | None = None) -> AppConfig:
    return AppConfig(
        storage=StorageConfig(output_folder=tmp_path),
        whisper=WhisperConfig(model="tiny", language="en"),
        ollama=OllamaConfig(host="http://localhost:11434", model=model),
        summarization=SummarizationConfig(default_prompt="x"),
        behavior=BehaviorConfig(show_override_dialog=False, auto_open_summary=False),
        recording=RecordingConfig(input_device=device),
    )


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk not available")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except Exception:
        pass


def _fake_devices():
    return [
        {"name": "Built-in Microphone", "max_input_channels": 1},
        {"name": "BlackHole 2ch", "max_input_channels": 2},
    ]


def _fake_models():
    return [ModelInfo(name="gemma3:4b", family="gemma3")]


def _query_devices_side_effect(idx=None):
    return _fake_devices() if idx is None else _fake_devices()[idx]


def test_settings_window_builds_with_two_comboboxes(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
    assert win._input_combo is not None
    assert win._model_combo is not None
    assert win._apply_btn is not None
    assert win._cancel_btn is not None
    win.close()


def test_apply_mutates_cfg_calls_save_and_enqueues_rebuild(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    saved = []
    monkeypatch.setattr(
        "summarizeaudio.settings_window.save_config",
        lambda cfg: saved.append((cfg.recording.input_device, cfg.ollama.model)),
    )
    with patch(
        "summarizeaudio.settings_window.list_installed_models",
        return_value=[
            ModelInfo(name="gemma3:4b", family="gemma3"),
            ModelInfo(name="gemma3:12b", family="gemma3"),
        ],
    ), patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        cfg = _cfg(tmp_path, model="gemma3:4b", device=None)
        q: queue.Queue = queue.Queue()
        win = SettingsWindow(root, cfg, q)
        win.show()
        win._input_combo.set("BlackHole 2ch")
        win._model_combo.set("gemma3:12b")
        win._on_apply()

    assert saved == [("BlackHole 2ch", "gemma3:12b")]
    assert cfg.recording.input_device == "BlackHole 2ch"
    assert cfg.ollama.model == "gemma3:12b"
    assert q.get_nowait() == ("rebuild_tray_menu",)


def test_apply_autodetect_stores_none(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.settings_window.save_config", lambda _cfg: None)
    with patch(
        "summarizeaudio.settings_window.list_installed_models",
        return_value=[ModelInfo(name="gemma3:4b", family="gemma3")],
    ), patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        cfg = _cfg(tmp_path, device="BlackHole 2ch")
        win = SettingsWindow(root, cfg, queue.Queue())
        win.show()
        win._input_combo.set(win._input_values[0])
        win._on_apply()
    assert cfg.recording.input_device is None


def test_cancel_does_not_mutate_or_save(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    save_calls = []
    monkeypatch.setattr(
        "summarizeaudio.settings_window.save_config",
        lambda cfg: save_calls.append(cfg),
    )
    with patch(
        "summarizeaudio.settings_window.list_installed_models",
        return_value=[ModelInfo(name="gemma3:4b", family="gemma3")],
    ), patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        cfg = _cfg(tmp_path)
        win = SettingsWindow(root, cfg, queue.Queue())
        win.show()
        win._input_combo.set("BlackHole 2ch")
        win._on_cancel()
    assert save_calls == []
    assert cfg.recording.input_device is None


def test_apply_restores_cfg_on_save_failure(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow

    def boom(_cfg):
        raise OSError("disk full")

    monkeypatch.setattr("summarizeaudio.settings_window.save_config", boom)
    with patch(
        "summarizeaudio.settings_window.list_installed_models",
        return_value=[
            ModelInfo(name="gemma3:4b", family="gemma3"),
            ModelInfo(name="gemma3:12b", family="gemma3"),
        ],
    ), patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        cfg = _cfg(tmp_path, model="gemma3:4b")
        q: queue.Queue = queue.Queue()
        win = SettingsWindow(root, cfg, q)
        win.show()
        win._model_combo.set("gemma3:12b")
        win._on_apply()
    assert cfg.ollama.model == "gemma3:4b"
    assert win._win.winfo_exists()
    assert "Failed to save settings" in win._error_label.cget("text")
    with pytest.raises(queue.Empty):
        q.get_nowait()


def test_ollama_down_disables_combo_and_apply(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=None), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
    assert str(win._apply_btn["state"]) == "disabled"
    assert str(win._model_combo["state"]) == "disabled"
    assert "Ollama not running" in win._model_combo.get()


def test_no_models_disables_combo_and_apply(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=[]), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
    assert str(win._apply_btn["state"]) == "disabled"
    assert "No models installed" in win._model_combo.get()


def test_configured_model_not_installed_injects_entry(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch(
        "summarizeaudio.settings_window.list_installed_models",
        return_value=[ModelInfo(name="llama3:8b", family="llama")],
    ), patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        cfg = _cfg(tmp_path, model="gemma3:4b")
        win = SettingsWindow(root, cfg, queue.Queue())
        win.show()
    assert win._model_combo.get() == "gemma3:4b (not installed)"
    assert "gemma3:4b (not installed)" in win._model_values
    assert str(win._apply_btn["state"]) != "disabled"


def test_embedding_model_gets_suffix(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch(
        "summarizeaudio.settings_window.list_installed_models",
        return_value=[
            ModelInfo(name="gemma3:4b", family="gemma3"),
            ModelInfo(name="nomic-embed-text", family="bert"),
        ],
    ), patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        cfg = _cfg(tmp_path, model="gemma3:4b")
        win = SettingsWindow(root, cfg, queue.Queue())
        win.show()
    assert "nomic-embed-text · embedding" in win._model_values


def test_banner_visible_only_when_pipeline_active(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch(
        "summarizeaudio.settings_window.list_installed_models",
        return_value=[ModelInfo(name="gemma3:4b", family="gemma3")],
    ), patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win_inactive = SettingsWindow(root, _cfg(tmp_path), queue.Queue(), pipeline_active=False)
        win_active = SettingsWindow(root, _cfg(tmp_path), queue.Queue(), pipeline_active=True)
        win_inactive.show()
        win_active.show()

    def has_banner(win) -> bool:
        for child in win._win.winfo_children():
            for grand in child.winfo_children():
                if isinstance(grand, tk.Frame) and grand.cget("bg") == "#fde68a":
                    return True
        return False

    assert not has_banner(win_inactive)
    assert has_banner(win_active)
