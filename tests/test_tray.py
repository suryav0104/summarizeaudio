from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


def make_config(tmp_path: Path, model: str) -> AppConfig:
    return AppConfig(
        storage=StorageConfig(output_folder=tmp_path),
        whisper=WhisperConfig(model="tiny", language="en"),
        ollama=OllamaConfig(host="http://localhost:11434", model=model),
        summarization=SummarizationConfig(default_prompt="Summarize: {transcript}"),
        behavior=BehaviorConfig(show_override_dialog=False, auto_open_summary=False),
        recording=RecordingConfig(input_device=None),
        diarization=DiarizationConfig(enabled=False),
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


def test_history_menu_shows_popup_item(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None)

    app._rebuild_menu()

    items = list(app._tray.menu.items)
    assert any(item.text == "History…" for item in items)


def test_on_history_posts_show_history_to_queue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())
    app = TrayApp()

    app._on_history(None, None)

    item = app._ui_queue.get_nowait()
    assert item == ("show_history",)


def test_on_local_audio_posts_show_workflow_to_queue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())
    app = TrayApp()

    app._on_local_audio(None, None)

    item = app._ui_queue.get_nowait()
    assert item[0] == "show_workflow"
    assert item[1] == "audio"


def test_on_local_text_posts_show_workflow_to_queue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())
    app = TrayApp()

    app._on_local_text(None, None)

    item = app._ui_queue.get_nowait()
    assert item[0] == "show_workflow"
    assert item[1] == "text"


def test_stop_recording_posts_show_workflow_to_queue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())

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
    items = []
    while not app._ui_queue.empty():
        items.append(app._ui_queue.get_nowait())
    # idle icon is routed through the queue (main-thread) before the popup
    assert ("set_icon", "idle") in items
    assert ("show_workflow", "record", Path("/tmp/recording.mp3"), None) in items


def test_stop_recording_prewarms_ollama_model(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())

    calls = []
    monkeypatch.setattr("summarizeaudio.tray.prewarm_async", lambda host, model: calls.append((host, model)))

    class FakeRecorder:
        def stop(self):
            return (Path("/tmp/recording.mp3"), None, None)

        def cleanup(self, delete_wav=False):
            return None

    app = TrayApp()
    app._tray = SimpleNamespace(menu=None, icon=None)
    app._recorder = FakeRecorder()
    monkeypatch.setattr(app, "_set_icon", lambda state: None)
    monkeypatch.setattr(app, "_rebuild_menu", lambda: None)

    app._on_stop_recording(None, None)

    assert calls == [(app._cfg.ollama.host, "gemma3:4b")]


def test_start_recording_does_not_prompt_for_name(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())
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
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())
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
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: fake_wm)

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
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm_immediate())
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
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm_immediate())
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
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())
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
    """Recording starts immediately; the async post-start check then stops it,
    deletes the wav, and notifies for a channel-mapping problem. (The blocking
    synchronous pre-start probe was removed.)"""
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())

    class FakeRecorder:
        def __init__(self, *args, **kwargs):
            self.started = False
            self.cleaned = None

        def start(self):
            self.started = True

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
    recorder = app._recorder
    assert recorder is not None and recorder.started is True  # started immediately
    _drain_input_health_once(app)

    assert app._recorder is None  # async check stopped it
    assert recorder.cleaned is True  # wav discarded
    assert notifications == [("Recording Input Problem", "channel mapping problem")]


def test_start_recording_keeps_running_for_no_signal(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm_immediate())

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
    """A missing device is caught by the async post-start check, which stops
    recording and surfaces the health warning. (The synchronous pre-start probe
    was removed.)"""
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())

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
            self.started = False
            self.cleaned = None

        def start(self):
            self.started = True

        def cleanup(self, delete_wav=False):
            self.cleaned = delete_wav

    monkeypatch.setattr("summarizeaudio.tray.Recorder", FakeRecorder)

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
    assert app._recorder is not None and app._recorder.started is True
    _drain_input_health_once(app)

    assert notifications == [("Recording Input Problem", warning)]
    assert app._recorder is None


def test_start_recording_has_no_synchronous_prestart_probe(tmp_path, monkeypatch):
    """Clicking Record must start the recorder and emit the recording icon
    immediately, without a blocking pre-start check_input_health probe. The
    only device probe is the deferred async post-start check. Otherwise the
    ~1.5s sampling sleep stalls recording start and the icon animation."""
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm())

    probe_calls = {"n": 0}

    def _counting_probe(_device):
        probe_calls["n"] += 1
        return InputHealthReport(
            ok=False, issue="channel_mapping", warning="bad",
            device_name="Multi-input device", requested_device="Multi-input device",
            sampled_channels=4, active_channels=(3, 4),
        )

    monkeypatch.setattr("summarizeaudio.tray.check_input_health", _counting_probe)

    started = {"flag": False}

    class FakeRecorder:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            started["flag"] = True

        def cleanup(self, delete_wav=False):
            return None

    monkeypatch.setattr("summarizeaudio.tray.Recorder", FakeRecorder)

    # Capture the async health-check thread but do NOT run it during the call,
    # so any probe seen now would have to be a synchronous pre-start one.
    class CapturedThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            pass

    monkeypatch.setattr("summarizeaudio.tray.threading.Thread", CapturedThread)
    monkeypatch.setattr("summarizeaudio.tray.notify", lambda *a, **k: None)

    app = TrayApp()
    app._tray = SimpleNamespace(menu=None, icon=None)
    monkeypatch.setattr(app, "_rebuild_menu", lambda: None)

    app._on_start_recording(None, None)

    assert started["flag"] is True
    assert app._recorder is not None
    assert probe_calls["n"] == 0  # no synchronous pre-start probe
    items = []
    while not app._ui_queue.empty():
        items.append(app._ui_queue.get_nowait())
    assert ("set_icon", "recording") in items


def test_startup_input_health_stops_active_recording_for_channel_mapping_issue(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm_immediate())
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


def test_settings_click_enqueues_show_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr(
        "summarizeaudio.window_manager.WindowManager",
        lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm(),
    )
    app = TrayApp()
    app._on_settings_click(None, None)
    assert app._ui_queue.get_nowait() == ("show_settings",)


def test_rebuild_menu_has_single_settings_item(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr(
        "summarizeaudio.window_manager.WindowManager",
        lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm(),
    )
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None)
    app._rebuild_menu()
    texts = [getattr(item, "text", "") for item in app._tray.menu.items]
    assert "Settings\u2026" in texts
    assert not any("\u2192" in t for t in texts)  # no inline status items remain


def test_on_rebuild_tray_request_calls_rebuild_menu(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr(
        "summarizeaudio.window_manager.WindowManager",
        lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm(),
    )
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None)
    app._rebuild_menu = lambda: setattr(app, "_rebuilt", True)
    app._on_rebuild_tray_request()
    assert getattr(app, "_rebuilt", False) is True


def test_window_manager_receives_on_rebuild_tray(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    captured = {}

    def fake_wm_factory(cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None):
        captured["on_rebuild_tray"] = on_rebuild_tray
        return _fake_wm()

    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", fake_wm_factory)
    app = TrayApp()
    assert captured["on_rebuild_tray"] is not None
    assert captured["on_rebuild_tray"] == app._on_rebuild_tray_request


def _app_with_captured_icon(tmp_path, monkeypatch):
    """Build a TrayApp whose _set_icon records states and _rebuild_menu is a
    no-op, for asserting icon-state transitions directly."""
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr(
        "summarizeaudio.window_manager.WindowManager",
        lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm(),
    )
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None, icon=None)
    states: list[str] = []
    monkeypatch.setattr(app, "_set_icon", lambda state: states.append(state))
    monkeypatch.setattr(app, "_rebuild_menu", lambda: None)
    return app, states


class _StoppableRecorder:
    def __init__(self):
        self.cleaned = None

    def cleanup(self, delete_wav=False):
        self.cleaned = delete_wav


def _stop_report(issue: str, warning: str = "bad device"):
    return InputHealthReport(
        ok=False,
        issue=issue,
        warning=warning,
        device_name="Multi-input device",
        requested_device="Multi-input device",
        sampled_channels=4,
        active_channels=(3, 4),
    )


def test_recording_stop_for_channel_mapping_enters_device_error(tmp_path, monkeypatch):
    """A recording auto-stopped for a genuinely-bad device (channel_mapping)
    must enter the device-error state with its reprobe recovery, mirroring the
    startup path — not silently revert to a healthy-looking idle icon."""
    app, states = _app_with_captured_icon(tmp_path, monkeypatch)
    recorder = _StoppableRecorder()
    app._recorder = recorder
    app._handle_recording_input_health(recorder, _stop_report("channel_mapping"))
    assert app._recorder is None
    assert recorder.cleaned is True
    assert app._device_error_active is True
    assert states[-1] == "error"


def test_recording_stop_for_device_missing_enters_device_error(tmp_path, monkeypatch):
    app, states = _app_with_captured_icon(tmp_path, monkeypatch)
    recorder = _StoppableRecorder()
    app._recorder = recorder
    app._handle_recording_input_health(recorder, _stop_report("device_missing"))
    assert app._recorder is None
    assert app._device_error_active is True
    assert states[-1] == "error"


def test_recording_stop_for_no_frames_goes_idle_not_error(tmp_path, monkeypatch):
    """no_frames is a stop reason but NOT an alert-worthy device fault, so the
    icon goes idle and no sticky device error is armed."""
    app, states = _app_with_captured_icon(tmp_path, monkeypatch)
    recorder = _StoppableRecorder()
    app._recorder = recorder
    app._handle_recording_input_health(recorder, _stop_report("no_frames"))
    assert app._recorder is None
    assert app._device_error_active is False
    assert states[-1] == "idle"
