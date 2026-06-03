from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest

from summarizeaudio.config import (
    AppConfig,
    BehaviorConfig,
    DiarizationConfig,
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
        diarization=DiarizationConfig(enabled=False),
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
    assert win._apply_disabled is True
    assert str(win._model_combo["state"]) == "disabled"
    assert "Ollama not running" in win._model_combo.get()


def test_no_models_disables_combo_and_apply(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=[]), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
    assert win._apply_disabled is True
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
    assert win._apply_disabled is False


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


def test_focus_target_input_focuses_input_combo(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch(
        "summarizeaudio.settings_window.list_installed_models",
        return_value=[ModelInfo(name="gemma3:4b", family="gemma3")],
    ), patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue(), focus_target="input")
        win.show()
    assert win._win.focus_get() is win._input_combo


def test_focus_target_model_focuses_model_combo(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch(
        "summarizeaudio.settings_window.list_installed_models",
        return_value=[ModelInfo(name="gemma3:4b", family="gemma3")],
    ), patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue(), focus_target="model")
        win.show()
    assert win._win.focus_get() is win._model_combo


def test_focus_target_method_retargets_focus(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch(
        "summarizeaudio.settings_window.list_installed_models",
        return_value=[ModelInfo(name="gemma3:4b", family="gemma3")],
    ), patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue(), focus_target="input")
        win.show()
        win.focus_target("model")
    assert win._win.focus_get() is win._model_combo


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


def test_diarization_toggle_visible_when_available_and_apply_persists(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    saved = []
    monkeypatch.setattr(
        "summarizeaudio.settings_window.save_config",
        lambda cfg: saved.append(cfg.diarization.enabled),
    )
    monkeypatch.setattr("summarizeaudio.diarization.is_available", lambda: True)
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        cfg = _cfg(tmp_path)
        cfg.diarization.enabled = False
        win = SettingsWindow(root, cfg, queue.Queue())
        win.show()
        assert win._diar_available is True
        assert win._diar_combo is not None
        assert list(win._diar_combo["values"]) == ["On", "Off"]
        assert win._diar_combo.get() == "Off"
        win._diar_combo.set("On")
        win._on_apply()
    assert cfg.diarization.enabled is True
    assert saved == [True]


def test_diarization_unavailable_shows_link_not_toggle(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.settings_window.save_config", lambda cfg: None)
    monkeypatch.setattr("summarizeaudio.diarization.is_available", lambda: False)
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        cfg = _cfg(tmp_path)
        cfg.diarization.enabled = True  # stale preference; capability is gone
        win = SettingsWindow(root, cfg, queue.Queue())
        win.show()
        assert win._diar_available is False
        assert win._diar_combo is None
        assert win._diar_link is not None
        assert win._diar_steps_visible is False
        win._on_apply()
    # Diarization being unavailable must not block Apply, and must not silently
    # flip the stored preference — runtime gating handles the capability.
    assert cfg.diarization.enabled is True
    assert win._apply_disabled is False


def test_how_to_enable_link_expands_steps(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.diarization.is_available", lambda: False)
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
        assert win._diar_steps_visible is False
        win._on_diar_how_to_enable()
        assert win._diar_steps_visible is True
        assert "HuggingFace" in win._diar_steps_text


def test_recheck_reloads_env_and_shows_toggle_when_available(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    calls = {"dotenv": 0}

    def fake_load_dotenv(override=False):
        calls["dotenv"] += 1
        return True

    monkeypatch.setattr("summarizeaudio.settings_window.load_dotenv", fake_load_dotenv)
    states = iter([False, True])  # build → unavailable, re-check → available
    monkeypatch.setattr("summarizeaudio.diarization.is_available", lambda: next(states))
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
        assert win._diar_available is False
        win._on_diar_how_to_enable()
        win._on_diar_recheck()
    assert calls["dotenv"] == 1
    assert win._diar_available is True
    assert win._diar_combo is not None


def test_recheck_keeps_steps_and_shows_note_when_still_unavailable(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.settings_window.load_dotenv", lambda override=False: True)
    monkeypatch.setattr("summarizeaudio.diarization.is_available", lambda: False)
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
        win._on_diar_how_to_enable()
        assert win._diar_steps_visible is True
        win._on_diar_recheck()
    # Still unavailable: instructions must stay open and a note must explain why,
    # instead of silently collapsing back to the bare link.
    assert win._diar_available is False
    assert win._diar_steps_visible is True
    assert win._diar_recheck_note is not None
    note = win._diar_recheck_note.cget("text")
    assert note != ""
    # User-facing copy must not use em-dashes (project rule).
    assert "\u2014" not in note


def test_diarization_dropdown_initial_on_when_enabled(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.settings_window.save_config", lambda cfg: None)
    monkeypatch.setattr("summarizeaudio.diarization.is_available", lambda: True)
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        cfg = _cfg(tmp_path)
        cfg.diarization.enabled = True
        win = SettingsWindow(root, cfg, queue.Queue())
        win.show()
        assert win._diar_combo is not None
        assert win._diar_combo.get() == "On"
