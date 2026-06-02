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


def test_show_settings_message_invokes_show_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    wm = window_manager.WindowManager(_make_cfg(tmp_path), queue.Queue())
    wm.show_settings = MagicMock()
    wm._handle(("show_settings",))
    wm.show_settings.assert_called_once_with(focus_target=None)


def test_show_settings_message_threads_focus_target(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    wm = window_manager.WindowManager(_make_cfg(tmp_path), queue.Queue())
    wm.show_settings = MagicMock()
    wm._handle(("show_settings", "input"))
    wm.show_settings.assert_called_once_with(focus_target="input")


def test_rebuild_tray_menu_message_invokes_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    cb = MagicMock()
    wm = window_manager.WindowManager(
        _make_cfg(tmp_path), queue.Queue(), on_rebuild_tray=cb
    )
    wm._handle(("rebuild_tray_menu",))
    cb.assert_called_once()


def test_sweep_clears_dead_settings_win(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    wm = window_manager.WindowManager(_make_cfg(tmp_path), queue.Queue())
    dead_win = MagicMock()
    dead_win.winfo_exists.return_value = False
    wm._settings_win = MagicMock(_win=dead_win)
    wm._sweep_stale_window_refs()
    assert wm._settings_win is None


def test_set_icon_tracks_pipeline_active(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    wm = window_manager.WindowManager(_make_cfg(tmp_path), queue.Queue())
    wm._handle(("set_icon", "recording"))
    assert wm._last_pipeline_active is True
    wm._handle(("set_icon", "idle"))
    assert wm._last_pipeline_active is False
    wm._handle(("set_icon", "processing"))
    assert wm._last_pipeline_active is True


def test_show_settings_creates_window_when_none(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    wm = window_manager.WindowManager(_make_cfg(tmp_path), queue.Queue())

    fake_window_cls = MagicMock()
    instance = MagicMock(_win=MagicMock(winfo_exists=lambda: True))
    fake_window_cls.return_value = instance

    import sys
    import types
    fake_mod = types.ModuleType("summarizeaudio.settings_window")
    fake_mod.SettingsWindow = fake_window_cls
    monkeypatch.setitem(sys.modules, "summarizeaudio.settings_window", fake_mod)

    wm.show_settings()
    fake_window_cls.assert_called_once()
    instance.show.assert_called_once()
    assert wm._settings_win is instance


def test_show_settings_refocuses_when_already_open(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    wm = window_manager.WindowManager(_make_cfg(tmp_path), queue.Queue())
    existing = MagicMock(_win=MagicMock(winfo_exists=lambda: True))
    wm._settings_win = existing

    import sys
    import types
    fake_window_cls = MagicMock()
    fake_mod = types.ModuleType("summarizeaudio.settings_window")
    fake_mod.SettingsWindow = fake_window_cls
    monkeypatch.setitem(sys.modules, "summarizeaudio.settings_window", fake_mod)

    wm.show_settings()
    fake_window_cls.assert_not_called()
    existing._focus.assert_called_once()


def _wm_with_icon_recorder(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    monkeypatch.setattr("summarizeaudio.notifier.notify", lambda *a, **k: None)
    states: list[str] = []
    wm = window_manager.WindowManager(
        _make_cfg(tmp_path), queue.Queue(), on_icon_state=states.append
    )
    return wm, states


def test_error_message_sets_error_icon(tmp_path, monkeypatch):
    wm, states = _wm_with_icon_recorder(tmp_path, monkeypatch)
    wm._handle(("error", "pipeline", "Ollama down", "tb"))
    assert states == ["error"]
    assert wm._error_active is True


def test_idle_suppressed_while_error_active(tmp_path, monkeypatch):
    wm, states = _wm_with_icon_recorder(tmp_path, monkeypatch)
    wm._handle(("error", "pipeline", "Ollama down", "tb"))
    states.clear()
    # the pipeline worker's finally posts idle, but a persistent error must win
    wm._handle(("set_icon", "idle"))
    assert states == []
    assert wm._error_active is True


def test_recording_start_clears_error_active(tmp_path, monkeypatch):
    wm, states = _wm_with_icon_recorder(tmp_path, monkeypatch)
    wm._handle(("error", "pipeline", "Ollama down", "tb"))
    states.clear()
    wm._handle(("set_icon", "recording"))
    assert states == ["recording"]
    assert wm._error_active is False


def test_window_dismiss_transition_clears_error(tmp_path, monkeypatch):
    wm, states = _wm_with_icon_recorder(tmp_path, monkeypatch)
    wm._handle(("error", "pipeline", "Ollama down", "tb"))
    states.clear()
    # a window was open when the error fired; closing it clears the error
    wm._prev_any_open = True  # simulate a window having been open
    wm._clear_error_on_window_dismiss()  # all windows now closed
    assert states == ["idle"]
    assert wm._error_active is False


def test_undeliverable_dialog_resolves_resolver(tmp_path, monkeypatch):
    """If the workflow window is gone when the worker posts an override/name
    dialog, the embedded resolver must be resolved with None so the blocked
    worker thread unblocks (and its finally stops the processing pulse).
    Otherwise it parks on wait(300) and the icon animates forever."""
    wm, _states = _wm_with_icon_recorder(tmp_path, monkeypatch)
    assert wm._workflow_win is None  # no live window to show the dialog

    resolved: list = []
    resolver = SimpleNamespace(_resolve=lambda value: resolved.append(value))
    wm._handle(("override_dialog", resolver, "prompt template"))
    assert resolved == [None]

    resolved.clear()
    name_resolver = SimpleNamespace(_resolve=lambda value: resolved.append(value))
    wm._handle(("name_dialog", name_resolver, "Default Name"))
    assert resolved == [None]


def test_no_window_dismiss_clear_without_open_transition(tmp_path, monkeypatch):
    wm, states = _wm_with_icon_recorder(tmp_path, monkeypatch)
    wm._handle(("error", "device", "Mic missing", "tb"))
    states.clear()
    # device error fired with no window open: no open->closed transition,
    # so window-dismiss must NOT clear it (it clears via re-probe instead)
    wm._prev_any_open = False
    wm._clear_error_on_window_dismiss()
    assert states == []
    assert wm._error_active is True


def _scheduled_auto_clear(wm) -> bool:
    """True if _auto_clear_error was scheduled via root.after."""
    return any(
        call.args[:2] == (wm._error_auto_clear_ms, wm._auto_clear_error)
        for call in wm._root.after.call_args_list
    )


def test_pipeline_error_with_no_window_open_schedules_auto_clear(tmp_path, monkeypatch):
    """A pipeline error surfaced while no window is open can never clear via the
    window-dismiss path (that needs an open->closed transition). So it must
    schedule a time-based auto-revert; otherwise the red icon sticks forever."""
    wm, _states = _wm_with_icon_recorder(tmp_path, monkeypatch)
    assert wm._workflow_win is None and wm._history_win is None and wm._settings_win is None
    wm._handle(("error", "pipeline", "Ollama down", "tb"))
    assert wm._error_active is True
    assert _scheduled_auto_clear(wm) is True


def test_pipeline_error_with_window_open_does_not_schedule_auto_clear(tmp_path, monkeypatch):
    """When a window IS open the error is shown in-window and clears on dismiss;
    the sticky behaviour must be preserved (no time-based auto-clear)."""
    wm, _states = _wm_with_icon_recorder(tmp_path, monkeypatch)
    monkeypatch.setattr(wm, "_any_window_open", lambda: True)
    wm._handle(("error", "pipeline", "Ollama down", "tb"))
    assert wm._error_active is True
    assert _scheduled_auto_clear(wm) is False


def test_auto_clear_error_reverts_to_idle_when_no_window(tmp_path, monkeypatch):
    wm, states = _wm_with_icon_recorder(tmp_path, monkeypatch)
    wm._error_active = True
    wm._auto_clear_error()
    assert states == ["idle"]
    assert wm._error_active is False


def test_auto_clear_error_noop_when_window_opened_meanwhile(tmp_path, monkeypatch):
    """If a window opened after the error fired, defer to the dismiss path —
    the auto-clear must not steal the still-relevant in-window error."""
    wm, states = _wm_with_icon_recorder(tmp_path, monkeypatch)
    wm._error_active = True
    monkeypatch.setattr(wm, "_any_window_open", lambda: True)
    wm._auto_clear_error()
    assert states == []
    assert wm._error_active is True


def test_auto_clear_error_noop_when_already_cleared(tmp_path, monkeypatch):
    """A new recording/pipeline (set_icon recording/processing) already cleared
    the error; the delayed auto-clear must not emit a spurious idle."""
    wm, states = _wm_with_icon_recorder(tmp_path, monkeypatch)
    wm._error_active = False
    wm._auto_clear_error()
    assert states == []
