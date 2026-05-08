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


def test_history_menu_exposes_only_available_actions(tmp_path, monkeypatch):
    output = tmp_path / "Summaries"
    summary_dir = output / "SummaryFiles"
    transcript_dir = output / "TranscriptionFiles"
    audio_dir = output / "AudioFiles"
    summary_dir.mkdir(parents=True)
    transcript_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)
    summary = summary_dir / "Summary - Team Update_05-08-26.md"
    summary.write_text("summary")
    transcript = transcript_dir / "Transcript_Team Update_05-08-26.txt"
    transcript.write_text("transcript")
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(output, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None)

    app._rebuild_menu()

    items = list(app._tray.menu.items)
    history = next(item for item in items if item.text == "History")
    assert history.submenu is not None
    session_item = next(item for item in history.submenu.items if "Team Update" in item.text)
    actions = list(session_item.submenu.items)
    assert {item.text for item in actions} == {"Open Summary", "Open Transcript", "Open Folder"}


def test_history_menu_summary_only_session_shows_summary_only(tmp_path, monkeypatch):
    output = tmp_path / "Summaries"
    summary_dir = output / "SummaryFiles"
    summary_dir.mkdir(parents=True)
    summary = summary_dir / "Summary - Notes_05-08-26.md"
    summary.write_text("summary")
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(output, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None)

    app._rebuild_menu()

    items = list(app._tray.menu.items)
    history = next(item for item in items if item.text == "History")
    session_item = next(item for item in history.submenu.items if "Notes" in item.text)
    actions = list(session_item.submenu.items)
    assert [item.text for item in actions] == ["Open Summary", "Open Folder"]


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


def test_name_dialog_uses_name_editor_and_resolves_value(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())

    app = TrayApp()
    resolved = []
    name_event = SimpleNamespace(_resolve=lambda value: resolved.append(value))
    default_name = "Project Update"

    called = []

    def fake_run(cmd, input=None, text=None, capture_output=None, check=None):
        called.append((cmd, input))
        return SimpleNamespace(returncode=0, stdout="Project Update Final")

    monkeypatch.setattr("summarizeaudio.tray.subprocess.run", fake_run)

    app._on_name_dialog(name_event, default_name)

    import time
    for _ in range(50):
        if resolved:
            break
        time.sleep(0.01)

    assert called
    assert called[0][0][:3] == [__import__("sys").executable, "-m", "summarizeaudio.prompt_editor"]
    assert "--mode" in called[0][0]
    assert "name" in called[0][0]
    assert resolved == ["Project Update Final"]


def test_start_recording_does_not_prompt_for_name(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())

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


def test_stop_recording_starts_pipeline_without_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    calls = []
    monkeypatch.setattr(
        "summarizeaudio.tray.subprocess.Popen",
        lambda cmd, stdout=None, stderr=None: calls.append(cmd) or SimpleNamespace(),
    )

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
    assert calls
    assert calls[0][:3] == [__import__("sys").executable, "-m", "summarizeaudio.workflow_window"]
    assert "--mode" in calls[0]
    assert "record" in calls[0]
    assert "--source" in calls[0]
    assert str(Path("/tmp/recording.mp3")) in calls[0]


def test_pick_file_uses_chooser_helper(monkeypatch, tmp_path):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())
    calls = []

    def fake_run(cmd, capture_output=None, text=None, check=None):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="/tmp/example.mp3")

    monkeypatch.setattr("summarizeaudio.tray.subprocess.run", fake_run)
    app = TrayApp()

    result = app._pick_file("audio")

    assert result is not None
    assert result.name == "example.mp3"
    assert calls
    assert calls[0][:3] == [__import__("sys").executable, "-m", "summarizeaudio.chooser_window"]


def test_pick_file_cancel_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())

    def fake_run(cmd, capture_output=None, text=None, check=None):
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr("summarizeaudio.tray.subprocess.run", fake_run)
    app = TrayApp()

    assert app._pick_file("audio") is None


def test_pick_file_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr("summarizeaudio.tray.Pipeline", lambda cfg, ui_queue: SimpleNamespace())

    def fake_run(cmd, capture_output=None, text=None, check=None):
        return SimpleNamespace(returncode=2, stdout="", stderr="chooser crashed")

    monkeypatch.setattr("summarizeaudio.tray.subprocess.run", fake_run)
    app = TrayApp()

    try:
        app._pick_file("audio")
        raised = False
    except RuntimeError as exc:
        raised = True
        assert "chooser crashed" in str(exc)

    assert raised


def test_local_audio_flow_starts_after_pick(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    calls = []
    monkeypatch.setattr(
        "summarizeaudio.tray.subprocess.Popen",
        lambda cmd, stdout=None, stderr=None: calls.append(cmd) or SimpleNamespace(),
    )
    app = TrayApp()

    app._run_local_audio_flow()

    assert calls
    assert calls[0][:3] == [__import__("sys").executable, "-m", "summarizeaudio.workflow_window"]
    assert "--mode" in calls[0]
    assert "audio" in calls[0]


def test_local_text_flow_starts_after_pick(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    calls = []
    monkeypatch.setattr(
        "summarizeaudio.tray.subprocess.Popen",
        lambda cmd, stdout=None, stderr=None: calls.append(cmd) or SimpleNamespace(),
    )
    app = TrayApp()

    app._run_local_text_flow()

    assert calls
    assert calls[0][:3] == [__import__("sys").executable, "-m", "summarizeaudio.workflow_window"]
    assert "--mode" in calls[0]
    assert "text" in calls[0]
