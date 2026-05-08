from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from summarizeaudio import workflow_window
from summarizeaudio.config import (
    AppConfig,
    BehaviorConfig,
    OllamaConfig,
    RecordingConfig,
    StorageConfig,
    SummarizationConfig,
    WhisperConfig,
)


def make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        storage=StorageConfig(output_folder=tmp_path),
        whisper=WhisperConfig(model="tiny", language="en"),
        ollama=OllamaConfig(host="http://localhost:11434", model="gemma3:4b"),
        summarization=SummarizationConfig(default_prompt="Summarize: {transcript}"),
        behavior=BehaviorConfig(show_override_dialog=False, auto_open_summary=False),
        recording=RecordingConfig(input_device=None),
    )


class FakeRoot:
    def __init__(self):
        self.destroyed = False
        self.grabbed = False
        self.topmost = False
        self.minsize_value = None

    def withdraw(self):
        pass

    def title(self, value):
        self.value = value

    def geometry(self, value):
        self.geometry_value = value

    def minsize(self, *args):
        self.minsize_value = args

    def resizable(self, *args):
        pass

    def configure(self, *args, **kwargs):
        pass

    def protocol(self, *args):
        pass

    def update_idletasks(self):
        pass

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def lift(self):
        pass

    def attributes(self, *args):
        if args and args[0] == "-topmost":
            self.topmost = args[1]

    def after(self, *args):
        pass

    def focus_force(self):
        pass

    def grab_set(self):
        self.grabbed = True

    def grab_release(self):
        self.grabbed = False

    def destroy(self):
        self.destroyed = True

    def winfo_children(self):
        return []


class FakeStyle:
    def theme_use(self, *args, **kwargs):
        return None

    def configure(self, *args, **kwargs):
        return None


class FakeStringVar:
    def __init__(self, value=""):
        self._value = value

    def set(self, value):
        self._value = value

    def get(self):
        return self._value


class FakeProgressbar:
    started = 0

    def __init__(self, *args, **kwargs):
        self.packed = False

    def pack(self, *args, **kwargs):
        self.packed = True

    def start(self, *args, **kwargs):
        FakeProgressbar.started += 1

    def stop(self):
        pass


class FakeText:
    instances = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.content = ""
        self.packed = False
        self.focused = False
        self.inserted = []
        FakeText.instances.append(self)

    def pack(self, *args, **kwargs):
        self.packed = True

    def insert(self, index, value):
        self.content += value
        self.inserted.append((index, value))

    def focus_set(self):
        self.focused = True

    def get(self, start, end):
        return self.content

    def configure(self, *args, **kwargs):
        self.kwargs.update(kwargs)


class FakeButton:
    instances = []

    def __init__(self, parent, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.packed = False
        FakeButton.instances.append(self)

    def pack(self, *args, **kwargs):
        self.packed = True


class FakeEntry:
    instances = []

    def __init__(self, parent, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.packed = False
        self.focused = False
        FakeEntry.instances.append(self)

    def pack(self, *args, **kwargs):
        self.packed = True

    def focus_set(self):
        self.focused = True


class FakeFrame:
    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.pack_calls = []
        FakeFrame.instances.append(self)

    def pack(self, *args, **kwargs):
        self.pack_calls.append(kwargs)


def test_workflow_window_chooser_stays_open_after_file_pick(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Progressbar", FakeProgressbar)
    picked = []
    monkeypatch.setattr("summarizeaudio.workflow_window._native_audio_picker", lambda title: picked.append(title) or "/tmp/example.mp3")

    window = workflow_window.WorkflowWindow("audio")
    window._render = lambda: picked.append("render")
    started = []
    window._start_pipeline = lambda: started.append(window._active_source)

    window._choose_file()

    assert picked[0] == "Select Audio File"
    assert isinstance(window._active_source, Path)
    assert window._active_source.name == "example.mp3"
    assert started and started[0].name == "example.mp3"
    assert fake_root.destroyed is False
    assert fake_root.grabbed is True


def test_workflow_window_chooser_has_no_spinner(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Progressbar", FakeProgressbar)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    class FakeWidget:
        def __init__(self, *args, **kwargs):
            pass

        def pack(self, *args, **kwargs):
            pass

        def destroy(self):
            pass

    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeWidget)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeWidget)
    FakeProgressbar.started = 0

    window = workflow_window.WorkflowWindow("audio")
    window._render()

    assert FakeProgressbar.started == 0


def test_workflow_window_chooser_uses_short_subtitle(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)

    window = workflow_window.WorkflowWindow("audio")
    window._render_steps = lambda body: None
    window._render_chooser(FakeFrame())

    assert window._subtitle.get() == "Select a file to continue."


def test_workflow_window_uses_imperative_status_labels(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)

    record_window = workflow_window.WorkflowWindow("record", source="/tmp/recording.mp3")
    record_window._status = FakeStringVar()
    record_window._step_state = "processing"
    record_window._render_processing(FakeFrame())
    assert record_window._status.get() == "Transcribe recording"
    assert record_window._steps_for_mode() == ["Recording completed", "Transcribe recording", "Summarize transcript", "Name the output"]

    audio_window = workflow_window.WorkflowWindow("audio")
    audio_window._status = FakeStringVar()
    audio_window._step_state = "processing"
    audio_window._render_processing(FakeFrame())
    assert audio_window._status.get() == "Transcribe audio"
    assert audio_window._steps_for_mode() == ["Choose audio file", "Transcribe audio", "Summarize transcript", "Name the output"]

    text_window = workflow_window.WorkflowWindow("text")
    text_window._status = FakeStringVar()
    text_window._step_state = "processing"
    text_window._render_processing(FakeFrame())
    assert text_window._status.get() == "Summarize transcript"
    assert text_window._steps_for_mode() == ["Choose transcript file", "Summarize transcript", "Name the output"]


def test_workflow_window_name_dialog_uses_same_window(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())

    window = workflow_window.WorkflowWindow("record", source="/tmp/recording.mp3")
    window._render = lambda: None

    resolved = []
    event = SimpleNamespace(_resolve=lambda value: resolved.append(value))

    window._handle_item(("name_dialog", event, "Project Update"))

    assert window._state == "name"
    assert resolved == []
    assert fake_root.destroyed is False


def test_workflow_window_prompt_uses_light_widgets(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ScrolledText", FakeText)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    FakeText.instances.clear()
    FakeButton.instances.clear()

    window = workflow_window.WorkflowWindow("record", source="/tmp/recording.mp3")
    window._render_steps = lambda body: None
    window._prompt_text = "Prompt body"
    body = FakeFrame()
    window._render_prompt(body)

    assert FakeText.instances
    assert FakeText.instances[0].kwargs["bg"] == "white"
    assert FakeText.instances[0].kwargs["fg"] == "#162033"
    button_texts = [btn.kwargs["text"] for btn in FakeButton.instances]
    assert button_texts == ["Update Prompt"]
    assert FakeButton.instances[0].kwargs["fg"] == "#000000"


def test_workflow_window_prompt_footer_is_fixed(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ScrolledText", FakeText)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)

    body = FakeFrame()
    window = workflow_window.WorkflowWindow("record", source="/tmp/recording.mp3")
    window._render_steps = lambda body: None
    window._prompt_text = "Prompt body"
    window._render_prompt(body)

    assert any(call.get("side") == "bottom" for frame in FakeFrame.instances for call in frame.pack_calls)


def test_workflow_window_summary_ready_opens_summary_and_stays_open(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    opened = []
    window = workflow_window.WorkflowWindow("text", source="/tmp/notes.txt")
    window._render = lambda: None
    window._open_path = lambda path: opened.append(Path(path))

    window._handle_item(("summary_ready", Path("/tmp/output/Summary - Topic.md")))

    assert window._state == "summary"
    assert window._summary_path == Path("/tmp/output/Summary - Topic.md")
    assert opened == [Path("/tmp/output/Summary - Topic.md")]
    assert fake_root.destroyed is False


def test_workflow_window_defaults_to_larger_geometry(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())

    window = workflow_window.WorkflowWindow("text", source="/tmp/notes.txt")

    assert window._window_width == 1040
    assert window._window_height == 760
    assert fake_root.geometry_value == "1040x760"
    assert fake_root.minsize_value == (860, 620)
