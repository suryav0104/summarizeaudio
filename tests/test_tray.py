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
from summarizeaudio.recorder import InputHealthReport
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
        root=SimpleNamespace(after=lambda *a: None, quit=lambda: None),
        block_for_open_window=lambda: False,
    )


def _fake_wm_immediate():
    return SimpleNamespace(
        root=SimpleNamespace(after=lambda _delay, func: func(), quit=lambda: None),
        block_for_open_window=lambda: False,
    )


def _drain_input_health_once(app: TrayApp) -> None:
    app._stop_event.set()
    app._pump_input_health_results()


def _ok_health_report() -> InputHealthReport:
    return InputHealthReport(
        ok=True,
        issue="ok",
        warning=None,
        device_name="Multi-input device",
        requested_device="Multi-input device",
        sampled_channels=4,
        active_channels=(1,),
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
    monkeypatch.setattr("summarizeaudio.tray.check_input_health", lambda _device: _ok_health_report())

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


def test_quit_arms_force_exit_and_quits_root(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.LOCK_FILE", tmp_path / "app.lock")

    calls = []

    class FakeRoot:
        def after(self, delay, func=None):
            calls.append(("after", delay))
            if func is not None:
                func()

        def quit(self):
            calls.append(("quit",))

        def destroy(self):
            calls.append(("destroy",))

    fake_wm = SimpleNamespace(root=FakeRoot(), close_all=lambda: calls.append(("close_all",)))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: fake_wm)

    app = TrayApp()
    monkeypatch.setattr(app, "_schedule_force_exit", lambda delay=0.8: calls.append(("force_exit", delay)))

    icon = SimpleNamespace(stop=lambda: calls.append(("icon_stop",)))
    app._on_quit(icon, None)

    assert ("force_exit", 0.8) in calls
    assert ("close_all",) in calls
    assert ("quit",) in calls
    assert ("destroy",) in calls
    assert ("icon_stop",) not in calls


def test_quit_cleans_up_active_recorder(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.LOCK_FILE", tmp_path / "app.lock")
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm_immediate())
    app = TrayApp()
    monkeypatch.setattr(app, "_schedule_force_exit", lambda delay=0.8: None)

    class FakeRecorder:
        def __init__(self):
            self.cleaned = None

        def cleanup(self, delete_wav=False):
            self.cleaned = delete_wav

    recorder = FakeRecorder()
    app._recorder = recorder

    app._on_quit(SimpleNamespace(stop=lambda: None), None)

    assert recorder.cleaned is False
    assert app._recorder is None


def test_startup_input_health_alerts_for_channel_mapping_issue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm_immediate())
    monkeypatch.setattr(
        "summarizeaudio.tray.check_input_health",
        lambda _device: InputHealthReport(
            ok=False,
            issue="channel_mapping",
            warning="channel mapping problem",
            device_name="Multi-input device",
            requested_device="Multi-input device",
            sampled_channels=4,
            active_channels=(3, 4),
        ),
    )
    notifications = []
    monkeypatch.setattr("summarizeaudio.tray.notify", lambda message, title="SummarizeAudio": notifications.append((title, message)))

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr("summarizeaudio.tray.threading.Thread", ImmediateThread)
    app = TrayApp()

    app._run_startup_input_health_check()
    _drain_input_health_once(app)

    assert notifications == [("Recording Input Problem", "channel mapping problem")]


def test_startup_input_health_does_not_alert_for_no_signal(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm())
    monkeypatch.setattr(
        "summarizeaudio.tray.check_input_health",
        lambda _device: InputHealthReport(
            ok=False,
            issue="no_signal",
            warning="quiet room",
            device_name="MacBook Air Microphone",
            requested_device="MacBook Air Microphone",
            sampled_channels=1,
            active_channels=(),
        ),
    )
    notifications = []
    monkeypatch.setattr("summarizeaudio.tray.notify", lambda message, title="SummarizeAudio": notifications.append((title, message)))

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr("summarizeaudio.tray.threading.Thread", ImmediateThread)
    app = TrayApp()

    app._run_startup_input_health_check()
    _drain_input_health_once(app)

    assert notifications == []


def test_start_recording_stops_and_alerts_for_channel_mapping_issue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm_immediate())

    class FakeRecorder:
        def __init__(self, *args, **kwargs):
            self.started = False
            self.cleaned = False

        def start(self):
            raise AssertionError("recorder should not start when pre-start health check fails")

        def cleanup(self, delete_wav=False):
            self.cleaned = delete_wav

    monkeypatch.setattr("summarizeaudio.tray.Recorder", FakeRecorder)
    monkeypatch.setattr(
        "summarizeaudio.tray.check_input_health",
        lambda _device: InputHealthReport(
            ok=False,
            issue="channel_mapping",
            warning="channel mapping problem",
            device_name="Multi-input device",
            requested_device="Multi-input device",
            sampled_channels=4,
            active_channels=(3, 4),
        ),
    )
    notifications = []
    monkeypatch.setattr("summarizeaudio.tray.notify", lambda message, title="SummarizeAudio": notifications.append((title, message)))

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr("summarizeaudio.tray.threading.Thread", ImmediateThread)
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None, icon=None)
    monkeypatch.setattr(app, "_set_icon", lambda state: None)
    monkeypatch.setattr(app, "_rebuild_menu", lambda: None)

    app._on_start_recording(None, None)

    assert app._recorder is None
    assert notifications == [("Recording Input Problem", "channel mapping problem")]


def test_start_recording_keeps_running_for_no_signal(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm_immediate())

    class FakeRecorder:
        def __init__(self, *args, **kwargs):
            self.started = False

        def start(self):
            self.started = True

        def cleanup(self, delete_wav=False):
            raise AssertionError("cleanup should not be called for no_signal")

    monkeypatch.setattr("summarizeaudio.tray.Recorder", FakeRecorder)
    monkeypatch.setattr(
        "summarizeaudio.tray.check_input_health",
        lambda _device: InputHealthReport(
            ok=False,
            issue="no_signal",
            warning="quiet room",
            device_name="MacBook Air Microphone",
            requested_device="MacBook Air Microphone",
            sampled_channels=1,
            active_channels=(),
        ),
    )
    notifications = []
    monkeypatch.setattr("summarizeaudio.tray.notify", lambda message, title="SummarizeAudio": notifications.append((title, message)))

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr("summarizeaudio.tray.threading.Thread", ImmediateThread)
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None, icon=None)
    monkeypatch.setattr(app, "_set_icon", lambda state: None)
    monkeypatch.setattr(app, "_rebuild_menu", lambda: None)

    app._on_start_recording(None, None)
    _drain_input_health_once(app)

    assert app._recorder is not None
    assert notifications == []


def test_start_recording_device_missing_uses_health_warning(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm_immediate())

    warning = (
        "Configured recording device 'Multi-input device' was not found. "
        "Open Audio MIDI Setup or System Settings > Sound and choose a working input device."
    )
    monkeypatch.setattr(
        "summarizeaudio.tray.check_input_health",
        lambda _device: InputHealthReport(
            ok=False,
            issue="device_missing",
            warning=warning,
            device_name=None,
            requested_device="Multi-input device",
            sampled_channels=0,
            active_channels=(),
        ),
    )
    notifications = []
    monkeypatch.setattr("summarizeaudio.tray.notify", lambda message, title="SummarizeAudio": notifications.append((title, message)))

    class FakeRecorder:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise AssertionError("recorder should not start when configured device is missing")

    monkeypatch.setattr("summarizeaudio.tray.Recorder", FakeRecorder)
    app = TrayApp()

    app._on_start_recording(None, None)

    assert notifications == [("Recording Input Problem", warning)]
    assert app._recorder is None


def test_startup_input_health_stops_active_recording_for_channel_mapping_issue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None: _fake_wm_immediate())
    notifications = []
    monkeypatch.setattr("summarizeaudio.tray.notify", lambda message, title="SummarizeAudio": notifications.append((title, message)))

    class FakeRecorder:
        def __init__(self):
            self.cleaned = False

        def cleanup(self, delete_wav=False):
            self.cleaned = delete_wav

    app = TrayApp()
    app._tray = SimpleNamespace(menu=None, icon=None)
    monkeypatch.setattr(app, "_set_icon", lambda state: None)
    monkeypatch.setattr(app, "_rebuild_menu", lambda: None)
    recorder = FakeRecorder()
    app._recorder = recorder

    app._handle_startup_input_health(
        InputHealthReport(
            ok=False,
            issue="channel_mapping",
            warning="channel mapping problem",
            device_name="Multi-input device",
            requested_device="Multi-input device",
            sampled_channels=4,
            active_channels=(3, 4),
        )
    )

    assert recorder.cleaned is True
    assert app._recorder is None
    assert notifications == [("Recording Input Problem", "channel mapping problem")]
