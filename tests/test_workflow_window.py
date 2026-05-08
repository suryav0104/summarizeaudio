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
        self.lift_calls = 0
        self.focus_calls = 0

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
        self.lift_calls += 1

    def attributes(self, *args):
        if args and args[0] == "-topmost":
            self.topmost = args[1]

    def after(self, *args):
        pass

    def focus_force(self):
        self.focus_calls += 1

    def grab_set(self):
        self.grabbed = True

    def grab_release(self):
        self.grabbed = False

    def destroy(self):
        self.destroyed = True

    def winfo_children(self):
        return []


class FakeStyle:
    instances = []

    def __init__(self):
        self.configured = []
        FakeStyle.instances.append(self)

    def theme_use(self, *args, **kwargs):
        return None

    def configure(self, *args, **kwargs):
        self.configured.append((args, kwargs))
        return None


class FakeStringVar:
    def __init__(self, value=""):
        self._value = value

    def set(self, value):
        self._value = value

    def get(self):
        return self._value


class FakeCanvas:
    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.packed = False
        self.deleted = []
        self.bound = []
        self.created = []
        self.coords_calls = []
        self.itemconfigure_calls = []
        self.after_calls = []
        self.after_cancel_calls = []
        self._destroyed = False
        self._next_after = 0
        FakeCanvas.instances.append(self)

    def pack(self, *args, **kwargs):
        self.packed = True

    def bind(self, event, callback):
        self.bound.append((event, callback))

    def create_rectangle(self, *args, **kwargs):
        self.created.append(("rectangle", args, kwargs))
        return len(self.created)

    def create_oval(self, *args, **kwargs):
        self.created.append(("oval", args, kwargs))
        return len(self.created)

    def coords(self, item, *args):
        self.coords_calls.append((item, args))

    def itemconfigure(self, item, **kwargs):
        self.itemconfigure_calls.append((item, kwargs))

    def delete(self, *args):
        self.deleted.append(args)

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))
        self._next_after += 1
        return f"after-{self._next_after}"

    def after_cancel(self, token):
        self.after_cancel_calls.append(token)

    def winfo_width(self):
        return int(self.kwargs.get("width", 0) or 0)

    def winfo_exists(self):
        return 0 if self._destroyed else 1

    def destroy(self):
        self._destroyed = True


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
        self.pack_calls = []
        FakeButton.instances.append(self)

    def pack(self, *args, **kwargs):
        self.packed = True
        self.pack_calls.append(kwargs)


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


class FakeLabel:
    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.pack_calls = []
        self.bind_calls = []
        FakeLabel.instances.append(self)

    def pack(self, *args, **kwargs):
        self.pack_calls.append(kwargs)

    def bind(self, event, callback):
        self.bind_calls.append((event, callback))

    def configure(self, **kwargs):
        self.kwargs.update(kwargs)


def test_workflow_window_chooser_stays_open_after_file_pick(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
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

    window = workflow_window.WorkflowWindow("audio")
    window._render()

    assert window._progress is None


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
    FakeButton.instances.clear()

    window = workflow_window.WorkflowWindow("audio")
    window._render_steps = lambda body: None
    window._render_chooser(FakeFrame())

    assert window._subtitle.get() == "Select a file to continue."
    assert [btn.kwargs["text"] for btn in FakeButton.instances[-2:]] == ["Choose File", "Cancel"]
    assert FakeButton.instances[-2].pack_calls[-1].get("side") == "left"
    assert FakeButton.instances[-1].pack_calls[-1].get("side") == "left"


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
    assert record_window._steps_for_mode() == ["Record audio", "Transcribe recording", "Summarize transcript", "Name the output"]

    record_window._step_state = "summarizing"
    record_window._render_processing(FakeFrame())
    assert record_window._status.get() == "Summarize transcript"
    assert record_window._completed_step_count() == 2
    assert record_window._current_step_index() == 2

    audio_window = workflow_window.WorkflowWindow("audio")
    audio_window._status = FakeStringVar()
    audio_window._step_state = "processing"
    audio_window._render_processing(FakeFrame())
    assert audio_window._status.get() == "Transcribe audio"
    assert audio_window._steps_for_mode() == ["Choose audio file", "Transcribe audio", "Summarize transcript", "Name the output"]

    audio_window._step_state = "summarizing"
    audio_window._render_processing(FakeFrame())
    assert audio_window._status.get() == "Summarize transcript"
    assert audio_window._completed_step_count() == 2
    assert audio_window._current_step_index() == 2

    text_window = workflow_window.WorkflowWindow("text")
    text_window._status = FakeStringVar()
    text_window._step_state = "processing"
    text_window._render_processing(FakeFrame())
    assert text_window._status.get() == "Summarize transcript"
    assert text_window._steps_for_mode() == ["Choose transcript file", "Summarize transcript", "Name the output"]

    text_window._step_state = "summarizing"
    text_window._render_processing(FakeFrame())
    assert text_window._status.get() == "Summarize transcript"
    assert text_window._completed_step_count() == 1
    assert text_window._current_step_index() == 1


def test_workflow_window_progress_bar_is_dark_and_slower(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Canvas", FakeCanvas)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    FakeStyle.instances.clear()
    FakeCanvas.instances.clear()

    window = workflow_window.WorkflowWindow("audio")
    window._state = "processing"
    window._step_state = "processing"
    window._render()

    assert FakeCanvas.instances
    canvas = FakeCanvas.instances[-1]
    assert canvas.kwargs["height"] == 16
    assert canvas.kwargs["width"] == 1320
    assert canvas.after_calls
    assert canvas.after_calls[-1][0] == 16
    assert window._progress._track_color == "#e7ebf2"
    assert window._progress._bar_color == "#222222"
    assert window._progress._interval == 16
    assert window._progress._step == 4
    assert 300 <= window._progress._bar_width <= 420
    max_x = canvas.kwargs["width"] - window._progress._bar_width
    window._progress._bar_x = max_x
    window._progress._direction = 1
    window._progress._tick()
    assert window._progress._bar_x == max_x
    assert window._progress._direction == -1
    window._progress._bar_x = 0
    window._progress._direction = -1
    window._progress._tick()
    assert window._progress._bar_x == 0
    assert window._progress._direction == 1


def test_workflow_window_summary_layout_keeps_actions_visible(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeLabel)
    monkeypatch.setattr("summarizeaudio.workflow_window.ScrolledText", FakeText)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    FakeText.instances.clear()
    FakeButton.instances.clear()
    FakeLabel.instances.clear()

    summary_dir = tmp_path / "SummaryFiles"
    transcript_dir = tmp_path / "TranscriptionFiles"
    audio_dir = tmp_path / "AudioFiles"
    summary_dir.mkdir(parents=True)
    transcript_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)
    summary_path = summary_dir / "Summary - Topic_05-08-26.md"
    summary_path.write_text("summary content", encoding="utf-8")
    transcript_path = transcript_dir / "Transcript_Topic_05-08-26.txt"
    transcript_path.write_text("transcript content", encoding="utf-8")
    audio_path = audio_dir / "Audio_Topic_05-08-26.mp3"
    audio_path.write_text("audio content", encoding="utf-8")
    window = workflow_window.WorkflowWindow("text", source="/tmp/notes.txt")
    window._summary_path = summary_path
    window._summary_preview = "summary content"
    window._render_steps = lambda body: None
    window._render_summary(FakeFrame())

    assert FakeText.instances
    assert FakeText.instances[-1].kwargs["height"] == 8
    assert [btn.kwargs["text"] for btn in FakeButton.instances] == ["Open Transcript", "Open Recording", "Close"]
    assert all(label.kwargs.get("text") != str(summary_path) for label in FakeLabel.instances)


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


def test_workflow_window_name_dialog_buttons_are_left_aligned(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Entry", FakeEntry)
    FakeButton.instances.clear()
    window = workflow_window.WorkflowWindow("record", source="/tmp/recording.mp3")
    window._render_steps = lambda body: None
    window._default_name = "Project Update"
    body = FakeFrame()

    window._render_name(body)

    assert [btn.kwargs["text"] for btn in FakeButton.instances] == ["Save Name", "Cancel"]
    assert FakeButton.instances[0].pack_calls[-1].get("side") == "left"
    assert FakeButton.instances[1].pack_calls[-1].get("side") == "left"


def test_workflow_window_workflow_phase_sets_summarizing_state(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    window = workflow_window.WorkflowWindow("audio")
    render_calls = []
    raised = []
    window._render = lambda: render_calls.append((window._state, window._step_state))
    window._raise_window = lambda: raised.append(True)

    window._handle_item(("workflow_phase", "summarizing"))

    assert window._state == "processing"
    assert window._step_state == "summarizing"
    assert render_calls
    assert raised


def test_workflow_window_save_name_keeps_window_visible(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    window = workflow_window.WorkflowWindow("record", source="/tmp/recording.mp3")
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Entry", FakeEntry)
    FakeButton.instances.clear()
    raised = []
    window._raise_window = lambda: raised.append(True)
    resolved = []
    event = SimpleNamespace(_resolve=lambda value: resolved.append(value))
    window._handle_item(("name_dialog", event, "Project Update"))

    body = FakeFrame()
    window._render_steps = lambda body: None
    window._render_name(body)
    window._render = lambda: None
    FakeButton.instances[0].kwargs["command"]()

    assert resolved == ["Project Update"]
    assert raised


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
    summary_path = tmp_path / "SummaryFiles" / "Summary - Topic.md"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text("summary content", encoding="utf-8")
    window = workflow_window.WorkflowWindow("text", source="/tmp/notes.txt")
    window._render = lambda: None
    window._open_path = lambda path: opened.append(Path(path))
    raised = []
    window._raise_window = lambda: raised.append(True)

    window._handle_item(("summary_ready", summary_path))

    assert window._state == "summary"
    assert window._summary_path == summary_path
    assert window._summary_preview == "summary content"
    assert opened == []
    assert raised
    assert fake_root.destroyed is False


def test_workflow_window_defaults_to_larger_geometry(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.load_config", lambda _q=None: make_config(tmp_path))
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Tk", lambda: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())

    window = workflow_window.WorkflowWindow("text", source="/tmp/notes.txt")

    assert window._window_width == 1440
    assert window._window_height == 900
    assert fake_root.geometry_value == "1440x900"
    assert fake_root.minsize_value == (1180, 700)
