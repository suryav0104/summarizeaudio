from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

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
from summarizeaudio.recorder import InputHealthReport
from summarizeaudio.tray import TrayApp


def _device_error_report() -> InputHealthReport:
    return InputHealthReport(
        ok=False,
        issue="device_missing",
        warning="Microphone not found",
        device_name=None,
        requested_device="BlackHole 2ch",
        sampled_channels=0,
        active_channels=(),
    )


def _ok_report() -> InputHealthReport:
    return InputHealthReport(
        ok=True,
        issue="ok",
        warning=None,
        device_name="BlackHole 2ch",
        requested_device="BlackHole 2ch",
        sampled_channels=2,
        active_channels=(1,),
    )


def make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        storage=StorageConfig(output_folder=tmp_path),
        whisper=WhisperConfig(model="tiny", language="en"),
        ollama=OllamaConfig(host="http://localhost:11434", model="gemma3:4b"),
        summarization=SummarizationConfig(default_prompt="Summarize: {transcript}"),
        behavior=BehaviorConfig(show_override_dialog=False, auto_open_summary=False),
        recording=RecordingConfig(input_device=None),
        diarization=DiarizationConfig(enabled=False),
    )


class RecordingRoot:
    """Tk-root stand-in that records after()/after_cancel() without firing."""

    def __init__(self) -> None:
        self.after_calls: list[tuple] = []
        self.cancelled: list = []
        self._n = 0

    def after(self, delay, func=None):
        self._n += 1
        handle = f"after#{self._n}"
        self.after_calls.append((delay, func, handle))
        return handle

    def after_cancel(self, handle):
        self.cancelled.append(handle)

    def quit(self):
        pass


def _fake_wm():
    return SimpleNamespace(
        root=RecordingRoot(),
        block_for_open_window=lambda: False,
    )


def _make_app(tmp_path, monkeypatch) -> TrayApp:
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr(
        "summarizeaudio.window_manager.WindowManager",
        lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm(),
    )
    # Deterministic menu-bar appearance for frame-identity assertions.
    monkeypatch.setattr("summarizeaudio.tray._menu_bar_variant", lambda: "dark", raising=False)
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None, icon=None)
    return app


def test_pulse_frames_loaded(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    for mode in ("recording", "processing"):
        for variant in ("dark", "light"):
            assert len(app._pulse_frames[mode][variant]) == 12
    assert "error" in app._icons


def test_set_icon_recording_starts_pulse(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app._set_icon("recording")
    assert app._icon_mode == "recording"
    assert app._pulse_variant == "dark"
    # first frame shown immediately, index advanced to 1
    assert app._tray.icon is app._pulse_frames["recording"]["dark"][0]
    assert app._pulse_index == 1
    # a follow-up tick was scheduled
    assert len(app._window_manager.root.after_calls) == 1


def test_advance_pulse_wraps_index(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app._start_pulse("processing")
    app._pulse_index = 11
    app._advance_pulse()
    assert app._tray.icon is app._pulse_frames["processing"]["dark"][11]
    assert app._pulse_index == 0  # wraps back to base of the sawtooth


def test_start_pulse_selects_light_variant(tmp_path, monkeypatch):
    """On a light menu bar the pulse uses the near-black silhouette base."""
    app = _make_app(tmp_path, monkeypatch)
    monkeypatch.setattr("summarizeaudio.tray._menu_bar_variant", lambda: "light")
    app._start_pulse("recording")
    assert app._pulse_variant == "light"
    assert app._tray.icon is app._pulse_frames["recording"]["light"][0]


def test_menu_bar_variant_defaults_dark_off_darwin(monkeypatch):
    from summarizeaudio import tray as tray_mod

    monkeypatch.setattr(tray_mod.sys, "platform", "linux")
    assert tray_mod._menu_bar_variant() == "dark"


def test_set_icon_idle_cancels_pulse(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app._set_icon("recording")
    pending = app._pulse_after_id
    assert pending is not None
    app._set_icon("idle")
    assert app._icon_mode == "idle"
    assert pending in app._window_manager.root.cancelled
    assert app._pulse_after_id is None
    assert app._tray.icon is app._icons["idle"]


def test_set_icon_error_is_static_and_persistent(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app._set_icon("processing")
    app._set_icon("error")
    assert app._icon_mode == "error"
    assert app._pulse_after_id is None
    assert app._tray.icon is app._icons["error"]
    # advancing must NOT restart a loop while in error mode
    before = len(app._window_manager.root.after_calls)
    app._advance_pulse()
    assert len(app._window_manager.root.after_calls) == before


def test_startup_device_error_sets_error_icon(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.notify", lambda *a, **k: None)
    app = _make_app(tmp_path, monkeypatch)
    app._handle_startup_input_health(_device_error_report())
    assert app._device_error_active is True
    assert app._icon_mode == "error"
    assert app._tray.icon is app._icons["error"]


def test_reprobe_recovery_clears_device_error(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.notify", lambda *a, **k: None)
    app = _make_app(tmp_path, monkeypatch)
    app._device_error_active = True
    app._set_icon("error")
    app._handle_reprobe_input_health(_ok_report())
    assert app._device_error_active is False
    assert app._icon_mode == "idle"
    assert app._tray.icon is app._icons["idle"]


def test_reprobe_still_broken_keeps_error(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.notify", lambda *a, **k: None)
    app = _make_app(tmp_path, monkeypatch)
    app._device_error_active = True
    app._set_icon("error")
    app._handle_reprobe_input_health(_device_error_report())
    assert app._device_error_active is True
    assert app._icon_mode == "error"


def test_healthy_startup_clears_active_device_error(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.notify", lambda *a, **k: None)
    app = _make_app(tmp_path, monkeypatch)
    app._device_error_active = True
    app._set_icon("error")
    app._handle_startup_input_health(_ok_report())
    assert app._device_error_active is False
    assert app._icon_mode == "idle"


def test_on_start_recording_routes_icon_through_queue(tmp_path, monkeypatch):
    """A clean recording start must go through ui_queue so the window manager
    (owner of the persistent error flag) clears any prior pipeline error."""
    monkeypatch.setattr("summarizeaudio.tray.check_input_health", lambda _device: _ok_report())

    class FakeRecorder:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def cleanup(self, delete_wav=False):
            return None

    monkeypatch.setattr("summarizeaudio.tray.Recorder", FakeRecorder)
    app = _make_app(tmp_path, monkeypatch)

    app._on_start_recording(None, None)

    items = []
    while not app._ui_queue.empty():
        items.append(app._ui_queue.get_nowait())
    assert ("set_icon", "recording") in items


def test_on_stop_recording_routes_icon_through_queue(tmp_path, monkeypatch):
    """Stopping must not mutate the pystray icon directly. A main-thread pulse
    loop may be writing the same NSStatusItem image; touching it from the
    pystray-callback thread deadlocks AppKit. The idle switch is routed through
    ui_queue so it runs on the main thread, and the workflow popup follows."""
    app = _make_app(tmp_path, monkeypatch)

    mp3 = tmp_path / "rec.mp3"

    class FakeRecorder:
        def stop(self):
            return (mp3, 0.0, 1.0)

        def cleanup(self, delete_wav=False):
            return None

    app._recorder = FakeRecorder()

    direct_calls: list[str] = []
    monkeypatch.setattr(app, "_set_icon", lambda state: direct_calls.append(state))

    app._on_stop_recording(None, None)

    items = []
    while not app._ui_queue.empty():
        items.append(app._ui_queue.get_nowait())
    assert ("set_icon", "idle") in items
    assert ("show_workflow", "record", mp3, None) in items
    # icon must NOT be set directly on the pystray-callback thread
    assert direct_calls == []


@pytest.mark.skipif(sys.platform != "darwin", reason="template flag is darwin-only")
def test_template_flag_only_idle(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app._set_icon("idle")
    assert getattr(app._tray, "_summarizeaudio_template_icon") is True
    for state in ("recording", "processing", "error"):
        app._set_icon(state)
        assert getattr(app._tray, "_summarizeaudio_template_icon") is False
