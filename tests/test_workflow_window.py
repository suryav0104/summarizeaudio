from __future__ import annotations

import queue as queue_mod
from pathlib import Path
from types import SimpleNamespace

import pytest

from summarizeaudio import sessions as session_store
from summarizeaudio import workflow_window
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
        self.bind_calls = []
        FakeFrame.instances.append(self)

    def pack(self, *args, **kwargs):
        self.pack_calls.append(kwargs)

    def bind(self, event, callback):
        self.bind_calls.append((event, callback))

    def configure(self, **kwargs):
        self.kwargs.update(kwargs)


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
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    picked = []
    monkeypatch.setattr("summarizeaudio.workflow_window._native_audio_picker", lambda title: picked.append(title) or "/tmp/example.mp3")

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "audio")
    window._render = lambda: picked.append("render")
    started = []
    window._start_pipeline = lambda: started.append(window._active_source)

    window._choose_file()

    assert picked[0] == "Select Audio File"
    assert isinstance(window._active_source, Path)
    assert window._active_source.name == "example.mp3"
    assert started and started[0].name == "example.mp3"
    assert fake_root.destroyed is False


def test_workflow_window_chooser_has_no_spinner(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
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

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "audio")
    window._render()

    assert window._progress is None


def test_workflow_window_chooser_uses_short_subtitle(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    FakeButton.instances.clear()

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "audio")
    window._render_steps = lambda body: None
    window._button_bar = FakeFrame()
    window._render_chooser(FakeFrame())

    assert window._subtitle.get() == "Select a file to continue."
    assert [btn.kwargs["text"] for btn in FakeButton.instances[-2:]] == ["Choose File", "Cancel"]
    assert FakeButton.instances[-2].pack_calls[-1].get("side") == "left"
    assert FakeButton.instances[-1].pack_calls[-1].get("side") == "left"


def test_workflow_window_uses_imperative_status_labels(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)

    cfg = make_config(tmp_path)
    record_window = workflow_window.WorkflowWindow(SimpleNamespace(), cfg, queue_mod.Queue(), "record", source=Path("/tmp/recording.mp3"))
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

    audio_window = workflow_window.WorkflowWindow(SimpleNamespace(), cfg, queue_mod.Queue(), "audio")
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

    text_window = workflow_window.WorkflowWindow(SimpleNamespace(), cfg, queue_mod.Queue(), "text")
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
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Canvas", FakeCanvas)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    FakeStyle.instances.clear()
    FakeCanvas.instances.clear()

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "audio")
    window._state = "processing"
    window._step_state = "summarizing"
    window._render()

    assert FakeCanvas.instances
    canvas = FakeCanvas.instances[-1]
    assert canvas.kwargs["height"] == 32
    assert canvas.kwargs["width"] == 480
    assert canvas.after_calls
    assert canvas.after_calls[-1][0] == 16
    assert window._progress._track_color == "#ccd4e0"
    assert window._progress._bar_color == "#222222"
    assert window._progress._interval == 16
    assert window._progress._step == 4
    assert 60 <= window._progress._bar_width <= 200
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
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeLabel)
    monkeypatch.setattr("summarizeaudio.workflow_window.ScrolledText", FakeText)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Label", FakeLabel)
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
    summary_path = summary_dir / "Summary - Topic 05-08-26.md"
    summary_path.write_text("summary content", encoding="utf-8")
    transcript_path = transcript_dir / "Transcript - Topic 05-08-26.txt"
    transcript_path.write_text("transcript content", encoding="utf-8")
    audio_path = audio_dir / "Audio - Topic 05-08-26.mp3"
    audio_path.write_text("audio content", encoding="utf-8")
    monkeypatch.setattr(
        "summarizeaudio.workflow_window.session_for_summary_path",
        lambda root, path: session_store.SessionFiles(
            label="Topic",
            date="05-08-26",
            folder=summary_path.parent,
            summary=summary_path,
            transcript=transcript_path,
            audio=audio_path,
            source_path=audio_path,
            id="summary-layout",
            created_at="2026-05-08T00:00:00+00:00",
            completed_at="2026-05-08T00:01:00+00:00",
            status="completed",
            archived=False,
            mode="text",
            source_key="summary-layout",
        ),
    )
    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "text", source=Path("/tmp/notes.txt"))
    window._summary_path = summary_path
    window._summary_preview = "summary content"
    window._render_steps = lambda body: None
    window._button_bar = FakeFrame()
    window._button = lambda parent, text, command, primary=True: FakeButton(parent, text=text)
    window._render_summary(FakeFrame())

    assert FakeText.instances
    assert FakeText.instances[-1].kwargs["height"] == 8
    assert [btn.kwargs["text"] for btn in FakeButton.instances] == ["Open Recording", "Open Transcript", "Close"]


def test_workflow_window_summary_layout_uses_path_when_session_lookup_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeLabel)
    monkeypatch.setattr("summarizeaudio.workflow_window.ScrolledText", FakeText)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    FakeText.instances.clear()
    FakeButton.instances.clear()
    FakeLabel.instances.clear()

    summary_path = tmp_path / "SummaryFiles" / "Summary - Topic.md"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text("summary content", encoding="utf-8")
    monkeypatch.setattr("summarizeaudio.workflow_window.session_for_summary_path", lambda root, path: None)

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "text", source=Path("/tmp/notes.txt"))
    window._summary_path = summary_path
    window._summary_preview = "summary content"
    window._button_bar = FakeFrame()
    window._button = lambda parent, text, command, primary=True: FakeButton(parent, text=text)

    window._render_summary(FakeFrame())

    assert [btn.kwargs["text"] for btn in FakeButton.instances] == ["Close"]
    assert FakeText.instances[-1].content == "summary content"


def test_close_during_pending_resolver_unblocks_worker(tmp_path, monkeypatch):
    """Closing the window while a dialog resolver is pending must resolve it
    with None so the blocked pipeline worker wakes, runs its `finally`, and
    emits ("set_icon","idle"). Otherwise the worker stays blocked on
    resolver.wait(300) and the processing pulse never stops."""
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "record", source=Path("/tmp/recording.mp3"))
    window._render = lambda: None

    resolved = []
    window._resolver = SimpleNamespace(_resolve=lambda value: resolved.append(value))

    window._close()

    assert resolved == [None]
    assert window._resolver is None
    assert fake_root.destroyed is True


def test_close_during_active_processing_stops_pulse(tmp_path, monkeypatch):
    """Closing the window while the pipeline is mid-run (no dialog resolver
    pending, e.g. partway through transcription) must post ('set_icon','idle')
    so the processing pulse stops immediately, instead of running until the
    pipeline finishes on its own."""
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())

    q = queue_mod.Queue()
    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), q, "record", source=Path("/tmp/recording.mp3"))
    window._render = lambda: None
    window._processing_started = True
    window._resolver = None

    window._close()

    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert ("set_icon", "idle") in items
    assert fake_root.destroyed is True


def test_determinate_fill_width_is_proportional_from_zero():
    """The transcribe progress fill must reflect the percentage from 0 with no
    fat minimum-width clamp, so the gray track is dominant at the start and the
    fill grows smoothly (the 0-7% 'stuck blob' bug)."""
    from summarizeaudio.workflow_window import _determinate_fill_width
    assert _determinate_fill_width(480, 0) == 0
    assert _determinate_fill_width(480, 100) == 480
    assert _determinate_fill_width(480, 50) == 240
    # A low percentage must produce a small fill, never a ~32px clamp.
    assert _determinate_fill_width(480, 2) <= 12


def test_determinate_label_color_contrasts_with_fill():
    """The percent label must never read as the same color as the dark fill.
    On the gray track (fill hasn't reached the label) it is a readable slate;
    once the fill covers the label center it flips to white."""
    from summarizeaudio.workflow_window import _determinate_label_color
    assert _determinate_label_color(filled=20, width=480) == "#475569"
    assert _determinate_label_color(filled=300, width=480) == "white"


def test_capsule_coords_collapse_to_a_point_at_zero_width():
    """A 0% fill has zero width. Every piece of the capsule must collapse to a
    single point so Tk renders nothing — no vertical black sliver against the
    rounded grey track."""
    from summarizeaudio.workflow_window import _capsule_coords
    rect, left, right = _capsule_coords(0, 2, 0, 30)
    assert rect == (0, 2, 0, 2)
    assert left == (0, 2, 0, 2)
    assert right == (0, 2, 0, 2)


def test_capsule_coords_form_rounded_pill_when_wide():
    """A full-width shape keeps the height-based corner radius, composed of a
    centre rectangle flanked by two end ovals."""
    from summarizeaudio.workflow_window import _capsule_coords
    rect, left, right = _capsule_coords(0, 2, 480, 30)
    radius = 14.0  # min((30-2)/2, (480-0)/2)
    assert rect == (0 + radius, 2, 480 - radius, 30)
    assert left == (0, 2, 0 + radius * 2, 30)
    assert right == (480 - radius * 2, 2, 480, 30)


def test_total_processing_label_sums_active_step_seconds(tmp_path):
    """Total processing time is the sum of the active phase durations only
    (transcribe + diarize + summarize), formatted MM:SS. Idle interaction gaps
    are never timed, so they cannot leak in."""
    win = _bare_window(make_config(tmp_path), "record")
    win._step_seconds = {"processing": 100.0, "summarizing": 22.0}
    assert win._total_processing_label() == "Total Processing Time: 02:02 min"


def test_total_processing_label_none_without_timing(tmp_path):
    win = _bare_window(make_config(tmp_path), "record")
    win._step_seconds = {}
    assert win._total_processing_label() is None


def test_header_badge_shows_total_time_on_summary(tmp_path):
    win = _bare_window(make_config(tmp_path), "record")
    win._state = "summary"
    win._step_seconds = {"processing": 60.0}
    assert win._header_badge_text() == "Total Processing Time: 01:00 min"


def test_header_badge_uses_step_badge_off_summary(tmp_path):
    """Only the summary page shows the total time; every other state keeps the
    'Step N of M' badge even when timings exist."""
    win = _bare_window(make_config(tmp_path), "record")
    win._state = "name"
    win._step_seconds = {"processing": 60.0}
    win._step_badge_text = lambda: "Step 9 of 9"
    assert win._header_badge_text() == "Step 9 of 9"


def test_header_badge_falls_back_to_step_badge_when_no_timing(tmp_path):
    win = _bare_window(make_config(tmp_path), "record")
    win._state = "summary"
    win._step_seconds = {}
    win._step_badge_text = lambda: "Step 3 of 3"
    assert win._header_badge_text() == "Step 3 of 3"


def test_finish_step_timer_records_raw_seconds(tmp_path, monkeypatch):
    """Finishing a phase records its raw duration in seconds (for summing) in
    addition to the human-readable per-step string."""
    import summarizeaudio.workflow_window as ww
    win = _bare_window(make_config(tmp_path), "record")
    win._elapsed_tick_id = None
    win._step_start_time = 1000.0
    win._timing_step = "processing"
    win._step_durations = {}
    win._step_seconds = {}
    monkeypatch.setattr(ww.time, "time", lambda: 1042.0)
    win._finish_step_timer()
    assert win._step_seconds["processing"] == 42.0
    assert win._step_durations["processing"] == "00:42 min"


def _timer_window(tmp_path):
    win = _bare_window(make_config(tmp_path), "record")
    win._render = lambda: None
    win._resolver = None
    win._elapsed_tick_id = None
    win._step_durations = {}
    win._step_seconds = {}
    win._timing_step = "processing"
    win._step_start_time = 1000.0
    return win


def test_prompt_dialog_banks_active_phase_and_stops_timing(tmp_path, monkeypatch):
    """Opening the prompt-review dialog ends the transcription phase and stops
    the clock, so the time the user spends editing the prompt is not counted in
    the total processing time."""
    import summarizeaudio.workflow_window as ww
    win = _timer_window(tmp_path)
    monkeypatch.setattr(ww.time, "time", lambda: 1030.0)
    win._handle_item(("override_dialog", SimpleNamespace(), "Prompt {transcript}"))
    assert win._step_seconds["processing"] == 30.0
    assert win._step_start_time is None


def test_name_dialog_banks_active_phase_and_stops_timing(tmp_path, monkeypatch):
    """Opening the name/confirm dialog stops the clock for the same reason —
    confirming the file name is interaction time, not processing time."""
    import summarizeaudio.workflow_window as ww
    win = _timer_window(tmp_path)
    monkeypatch.setattr(ww.time, "time", lambda: 1030.0)
    win._handle_item(("name_dialog", SimpleNamespace(), "My Recording"))
    assert win._step_seconds["processing"] == 30.0
    assert win._step_start_time is None


def test_diarizing_detail_sets_time_expectation(tmp_path, monkeypatch):
    """Before any percent arrives, the Diarize step must set the expectation
    that it is slow (CPU-bound, roughly the length of the audio), so a multi-
    minute wait does not look like a hang."""
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)

    cfg = make_config(tmp_path)
    win = workflow_window.WorkflowWindow(SimpleNamespace(), cfg, queue_mod.Queue(), "record", source=Path("/tmp/recording.mp3"))
    win._status = FakeStringVar()
    win._step_state = "diarizing"
    win._render_processing(FakeFrame())
    assert win._status.get() == "Diarize the audio"
    assert "minute" in win._detail_text_var.get().lower()


@pytest.fixture
def tk_root():
    import tkinter as tk
    try:
        r = tk.Tk()
    except Exception:
        pytest.skip("Tk not available")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except Exception:
        pass


def test_marquee_to_determinate_shows_centered_percent(tk_root):
    """During the measurable embeddings step the bar switches to a filled bar
    with the percent printed inside it, like the transcription bar, and stops
    bouncing."""
    from summarizeaudio.workflow_window import _MarqueeProgress
    bar = _MarqueeProgress(tk_root, width=400, height=32, mode="marquee")
    bar.pack()
    bar.start()
    bar.to_determinate(50.0)
    assert bar._mode == "determinate"
    assert bar._pct == 50.0
    assert bar._text_item is not None
    assert bar._running is False


def test_marquee_to_marquee_resumes_bounce(tk_root):
    """The non-measurable diarization steps switch the bar back to the bouncing
    marquee, dropping the percent text."""
    from summarizeaudio.workflow_window import _MarqueeProgress
    bar = _MarqueeProgress(tk_root, width=400, height=32, mode="marquee")
    bar.pack()
    bar.to_determinate(50.0)
    bar.to_marquee()
    assert bar._mode == "marquee"
    assert bar._text_item is None
    assert bar._running is True


class _FakeProgress:
    def __init__(self):
        self.calls = []

    def to_determinate(self, pct):
        self.calls.append(("determinate", pct))

    def to_marquee(self):
        self.calls.append(("marquee",))


def test_handle_diarization_progress_fills_bar_for_measurable_step():
    """A measurable fraction switches the bar to the in-bar percent display,
    leaves the expectation detail text untouched, keeps the step timer running,
    and does NOT re-render (re-rendering would reset the bar)."""
    win = _bare_window(None, "record")
    win._step_state = "diarizing"
    win._detail_text_var = FakeStringVar("expectation message")
    win._progress = _FakeProgress()
    win._step_start_time = 1234.0
    rendered = []
    win._render = lambda: rendered.append(True)
    win._handle_item(("diarization_progress", "embeddings", 0.5))
    assert win._progress.calls == [("determinate", 50.0)]
    assert win._detail_text_var.get() == "expectation message"
    assert win._step_start_time == 1234.0
    assert rendered == []


def test_handle_diarization_progress_bounces_bar_for_unmeasurable_step():
    """A step that reports no fraction switches the bar back to the bouncing
    marquee, and still leaves the expectation message in place."""
    win = _bare_window(None, "record")
    win._step_state = "diarizing"
    win._detail_text_var = FakeStringVar("expectation message")
    win._progress = _FakeProgress()
    win._render = lambda: None
    win._handle_item(("diarization_progress", "segmentation", None))
    assert win._progress.calls == [("marquee",)]
    assert win._detail_text_var.get() == "expectation message"


def test_handle_diarization_progress_ignored_when_not_diarizing():
    """A late progress item that arrives after the phase moved on must not touch
    the bar or the detail line."""
    win = _bare_window(None, "record")
    win._step_state = "summarizing"
    win._detail_text_var = FakeStringVar("summary detail")
    win._progress = _FakeProgress()
    win._render = lambda: None
    win._handle_item(("diarization_progress", "embeddings", 0.5))
    assert win._progress.calls == []
    assert win._detail_text_var.get() == "summary detail"


def test_workflow_window_name_dialog_uses_same_window(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "record", source=Path("/tmp/recording.mp3"))
    window._render = lambda: None

    resolved = []
    event = SimpleNamespace(_resolve=lambda value: resolved.append(value))

    window._handle_item(("name_dialog", event, "Project Update"))

    assert window._state == "name"
    assert resolved == []
    assert fake_root.destroyed is False


def test_workflow_window_name_dialog_has_no_summary_preview(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeLabel)
    monkeypatch.setattr("summarizeaudio.workflow_window.ScrolledText", FakeText)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Label", FakeLabel)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Entry", FakeEntry)
    FakeText.instances.clear()
    FakeButton.instances.clear()

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "record", source=Path("/tmp/recording.mp3"))
    window._render_steps = lambda body: None
    window._default_name = "Project Update"
    window._summary_preview = "summary preview"
    window._button_bar = FakeFrame()
    body = FakeFrame()

    window._render_name(body)

    assert FakeText.instances == []
    assert "Review the summary" not in window._detail_text_var.get()


def test_workflow_window_name_dialog_buttons_are_left_aligned(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Entry", FakeEntry)
    FakeButton.instances.clear()
    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "record", source=Path("/tmp/recording.mp3"))
    window._render_steps = lambda body: None
    window._default_name = "Project Update"
    window._button_bar = FakeFrame()
    window._button = lambda parent, text, command, primary=True: FakeButton(parent, text=text, command=command)
    body = FakeFrame()

    window._render_name(body)

    assert [btn.kwargs["text"] for btn in FakeButton.instances] == ["Save Name", "Cancel"]
    assert FakeButton.instances[0].pack_calls[-1].get("side") == "left"
    assert FakeButton.instances[1].pack_calls[-1].get("side") == "left"


def test_workflow_window_workflow_phase_sets_summarizing_state(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "audio")
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
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "record", source=Path("/tmp/recording.mp3"))
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
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ScrolledText", FakeText)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)
    FakeText.instances.clear()
    FakeButton.instances.clear()

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "record", source=Path("/tmp/recording.mp3"))
    window._render_steps = lambda body: None
    window._prompt_text = "Prompt body"
    window._button_bar = FakeFrame()
    body = FakeFrame()
    window._render_prompt(body)

    assert FakeText.instances
    assert FakeText.instances[0].kwargs["bg"] == "white"
    assert FakeText.instances[0].kwargs["fg"] == "#162033"
    button_texts = [btn.kwargs["text"] for btn in FakeButton.instances]
    assert button_texts == ["Update Prompt"]
    assert FakeButton.instances[0].kwargs["fg"] == "white"


def test_workflow_window_prompt_footer_is_fixed(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ScrolledText", FakeText)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)

    body = FakeFrame()
    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "record", source=Path("/tmp/recording.mp3"))
    window._render_steps = lambda body: None
    window._prompt_text = "Prompt body"
    window._render_prompt(body)

    assert any(call.get("side") == "bottom" for frame in FakeFrame.instances for call in frame.pack_calls)


def test_workflow_window_summary_ready_opens_summary_and_stays_open(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    opened = []
    summary_path = tmp_path / "SummaryFiles" / "Summary - Topic.md"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text("summary content", encoding="utf-8")
    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "text", source=Path("/tmp/notes.txt"))
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


def test_workflow_window_retry_summary_uses_resumed_session_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Frame", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Label", FakeFrame)
    monkeypatch.setattr("summarizeaudio.workflow_window.ScrolledText", FakeText)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Button", FakeButton)

    summary_path = tmp_path / "SummaryFiles" / "Summary - Topic.md"
    transcript_path = tmp_path / "TranscriptionFiles" / "Transcript - Topic.txt"
    audio_path = tmp_path / "AudioFiles" / "Audio - Topic.mp3"
    summary_path.parent.mkdir(parents=True)
    transcript_path.parent.mkdir(parents=True)
    audio_path.parent.mkdir(parents=True)
    summary_path.write_text("summary content", encoding="utf-8")
    transcript_path.write_text("transcript content", encoding="utf-8")
    audio_path.write_text("audio content", encoding="utf-8")

    monkeypatch.setattr(
        "summarizeaudio.workflow_window.session_by_id",
        lambda session_id: session_store.SessionFiles(
            label="Topic",
            date="05-08-26",
            folder=summary_path.parent,
            summary=summary_path,
            transcript=None,
            audio=None,
            source_path=None,
            id=session_id,
            created_at="2026-05-08T00:00:00+00:00",
            completed_at="",
            status="partial",
            archived=False,
            mode="text",
            source_key="resume-1",
        ),
    )
    monkeypatch.setattr(
        "summarizeaudio.workflow_window.session_for_summary_path",
        lambda root, path: session_store.SessionFiles(
            label="Topic",
            date="05-08-26",
            folder=summary_path.parent,
            summary=summary_path,
            transcript=transcript_path,
            audio=audio_path,
            source_path=audio_path,
            id="resume-1",
            created_at="2026-05-08T00:00:00+00:00",
            completed_at="",
            status="partial",
            archived=False,
            mode="text",
            source_key="resume-1",
        ),
    )

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "text", source=Path("/tmp/notes.txt"), resume_session_id="resume-1")
    window._summary_path = summary_path
    window._summary_preview = "summary content"
    window._state = "summary"
    window._step_state = "message"
    FakeButton.instances.clear()
    FakeLabel.instances.clear()

    body = FakeFrame()
    window._button_bar = FakeFrame()
    window._render_summary(body)

    button_texts = [btn.kwargs["text"] for btn in FakeButton.instances]
    assert "Open Transcript" in button_texts
    assert "Open Recording" in button_texts
    assert "Close" in button_texts
    assert any("summary content" in text.content for text in FakeText.instances)


def test_workflow_window_summary_action_specs_include_available_files(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())

    summary_path = tmp_path / "SummaryFiles" / "Summary - Topic.md"
    transcript_path = tmp_path / "TranscriptionFiles" / "Transcript - Topic.txt"
    audio_path = tmp_path / "AudioFiles" / "Audio - Topic.mp3"
    summary_path.parent.mkdir(parents=True)
    transcript_path.parent.mkdir(parents=True)
    audio_path.parent.mkdir(parents=True)
    summary_path.write_text("summary content", encoding="utf-8")
    transcript_path.write_text("transcript content", encoding="utf-8")
    audio_path.write_text("audio content", encoding="utf-8")

    monkeypatch.setattr(
        "summarizeaudio.workflow_window.session_by_id",
        lambda session_id: session_store.SessionFiles(
            label="Topic",
            date="05-08-26",
            folder=summary_path.parent,
            summary=summary_path,
            transcript=None,
            audio=None,
            source_path=None,
            id=session_id,
            created_at="2026-05-08T00:00:00+00:00",
            completed_at="",
            status="partial",
            archived=False,
            mode="text",
            source_key="resume-1",
        ),
    )
    monkeypatch.setattr(
        "summarizeaudio.workflow_window.session_for_summary_path",
        lambda root, path: session_store.SessionFiles(
            label="Topic",
            date="05-08-26",
            folder=summary_path.parent,
            summary=summary_path,
            transcript=transcript_path,
            audio=audio_path,
            source_path=audio_path,
            id="resume-1",
            created_at="2026-05-08T00:00:00+00:00",
            completed_at="",
            status="partial",
            archived=False,
            mode="text",
            source_key="resume-1",
        ),
    )

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "text", source=Path("/tmp/notes.txt"), resume_session_id="resume-1")
    window._summary_path = summary_path
    session = window._summary_session()
    assert session is not None
    assert window._summary_action_specs(session) == [("Open Recording", audio_path), ("Open Transcript", transcript_path)]


def test_workflow_window_has_compact_geometry(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.workflow_window.Pipeline", lambda cfg, ui_queue: SimpleNamespace(run=lambda **kwargs: None))
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())

    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), queue_mod.Queue(), "text", source=Path("/tmp/notes.txt"))

    assert window._window_width == 560
    assert window._window_height == 520
    assert fake_root.geometry_value == "560x520"


class _SyncThread:
    def __init__(self, target=None, daemon=False):
        self._target = target

    def start(self):
        if self._target is not None:
            self._target()


def test_start_pipeline_brackets_run_with_processing_then_idle(tmp_path, monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(
        "summarizeaudio.workflow_window.Pipeline",
        lambda cfg, ui_queue: SimpleNamespace(run=lambda *a, **k: order.append("run")),
    )
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.threading.Thread", _SyncThread)

    q = queue_mod.Queue()
    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), q, "audio")
    window._start_step_timer = lambda *a, **k: None
    window._active_source = Path("/tmp/example.mp3")

    window._start_pipeline()

    items = []
    while not q.empty():
        items.append(q.get_nowait())

    assert ("set_icon", "processing") in items
    assert ("set_icon", "idle") in items
    assert order == ["run"]
    assert items.index(("set_icon", "processing")) < items.index(("set_icon", "idle"))


def test_start_pipeline_sets_idle_icon_even_when_run_raises(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("pipeline blew up")

    monkeypatch.setattr(
        "summarizeaudio.workflow_window.Pipeline",
        lambda cfg, ui_queue: SimpleNamespace(run=_boom),
    )
    fake_root = FakeRoot()
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.Toplevel", lambda root: fake_root)
    monkeypatch.setattr("summarizeaudio.workflow_window.tk.StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr("summarizeaudio.workflow_window.ttk.Style", lambda: FakeStyle())
    monkeypatch.setattr("summarizeaudio.workflow_window.threading.Thread", _SyncThread)

    q = queue_mod.Queue()
    window = workflow_window.WorkflowWindow(SimpleNamespace(), make_config(tmp_path), q, "audio")
    window._start_step_timer = lambda *a, **k: None
    window._active_source = Path("/tmp/example.mp3")

    # In production the worker runs on a daemon thread that swallows the
    # exception; the synchronous test harness re-raises it. Either way the
    # finally clause must have enqueued the idle icon first.
    with pytest.raises(RuntimeError):
        window._start_pipeline()

    items = []
    while not q.empty():
        items.append(q.get_nowait())

    assert ("set_icon", "idle") in items


def _bare_window(cfg, mode):
    win = workflow_window.WorkflowWindow.__new__(workflow_window.WorkflowWindow)
    win._cfg = cfg
    win._mode = mode
    return win


def test_has_diarizer_true_when_effective_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.diarization.effective_enabled", lambda cfg: True)
    cfg = make_config(tmp_path)
    win = _bare_window(cfg, "record")
    assert win._has_diarizer() is True
    assert "Diarize the audio" in win._steps_for_mode()


def test_has_diarizer_false_when_not_effective_enabled(tmp_path, monkeypatch):
    # Preference on but capability missing — workflow must NOT show the Diarize step.
    monkeypatch.setattr("summarizeaudio.diarization.effective_enabled", lambda cfg: False)
    cfg = make_config(tmp_path)
    cfg.diarization.enabled = True
    win = _bare_window(cfg, "record")
    assert win._has_diarizer() is False
    assert "Diarize the audio" not in win._steps_for_mode()
