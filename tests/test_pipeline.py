# tests/test_pipeline.py
import queue
import shutil
import tempfile
import wave
import threading
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from summarizeaudio import sessions as session_store
from summarizeaudio.pipeline import Pipeline, PipelineMode, _derive_default_name
from summarizeaudio.config import (
    AppConfig, StorageConfig, WhisperConfig, OllamaConfig,
    SummarizationConfig, BehaviorConfig, RecordingConfig, DiarizationConfig,
)
from summarizeaudio.sessions import load_sessions


def today():
    return date.today().strftime("%m-%d-%y")


def make_config(tmp_output):
    return AppConfig(
        storage=StorageConfig(output_folder=tmp_output),
        whisper=WhisperConfig(model="tiny", language="en"),
        ollama=OllamaConfig(host="http://localhost:11434", model="x"),
        summarization=SummarizationConfig(default_prompt="Summarize: {transcript}"),
        behavior=BehaviorConfig(show_override_dialog=False, auto_open_summary=False),
        recording=RecordingConfig(input_device=None),
        diarization=DiarizationConfig(enabled=False),
    )


def test_build_diarizer_none_when_config_disabled(tmp_path, monkeypatch):
    from summarizeaudio import pipeline, diarization
    monkeypatch.setattr(diarization, "is_available", lambda: True)
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "hf_real")
    cfg = make_config(tmp_path)
    cfg.diarization.enabled = False
    assert pipeline.build_diarizer(cfg) is None


def test_build_diarizer_none_when_unavailable(tmp_path, monkeypatch):
    # Preference on but pyannote missing — must NOT build a diarizer (the bug fix).
    from summarizeaudio import pipeline, diarization
    monkeypatch.setattr(diarization, "is_available", lambda: False)
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "hf_real")
    cfg = make_config(tmp_path)
    cfg.diarization.enabled = True
    assert pipeline.build_diarizer(cfg) is None


def test_build_diarizer_built_when_enabled_and_available(tmp_path, monkeypatch):
    from summarizeaudio import pipeline, diarization
    from summarizeaudio.diarizer import Diarizer
    monkeypatch.setattr(diarization, "is_available", lambda: True)
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "hf_real")
    cfg = make_config(tmp_path)
    cfg.diarization.enabled = True
    assert isinstance(pipeline.build_diarizer(cfg), Diarizer)


def make_silence_mp3(path: Path) -> Path:
    """Create a minimal MP3 file for testing (pydub broken on Python 3.14)."""
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
         "-t", "0.1", "-ar", "16000", str(path)],
        capture_output=True, check=True
    )
    return path


def mock_ollama(monkeypatch):
    mock = MagicMock()
    mock.status_code = 200
    mock.iter_lines.return_value = [
        b'{"response": "**Key Points:**\\n- A summary.\\n\\n**Decisions / Action Items:**\\n- None.\\n\\n**Notable Details:**\\n- None.\\n", "done": false}',
        b'{"response": "", "done": true}',
    ]
    monkeypatch.setattr("requests.post", lambda *a, **kw: mock)


def resolve_name_dialog(ui_queue, response="Project Update"):
    def worker():
        while True:
            item = ui_queue.get(timeout=5)
            if item[0] == "name_dialog":
                item[1]._resolve(response)
                return

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


class SpyQueue(queue.Queue):
    def __init__(self):
        super().__init__()
        self.recorded = []

    def put_nowait(self, item):
        self.recorded.append(item)
        return super().put_nowait(item)


def test_mode1_produces_three_output_files(tmp_output, ui_queue, monkeypatch):
    """Pipeline orchestration test — mocks Transcriber to avoid requiring Whisper install."""
    mock_ollama(monkeypatch)
    monkeypatch.setattr(
        "summarizeaudio.transcriber.Transcriber.transcribe",
        lambda self, audio, out_txt, **kwargs: out_txt.write_text("fake transcript content for testing purposes", encoding="utf-8"),
    )
    cfg = make_config(tmp_output)
    mp3 = make_silence_mp3(tmp_output / "session.mp3")
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)
    resolve_name_dialog(ui_queue, "Project Update")
    p.run(mode=PipelineMode.RECORD, session_name="TestSession", mp3_path=mp3)
    assert any((tmp_output / "AudioFiles").iterdir())
    assert any((tmp_output / "TranscriptionFiles").iterdir())
    assert any((tmp_output / "SummaryFiles").iterdir())


def test_derive_default_name_skips_heading_labels():
    name = _derive_default_name(
        "Key Points\n- Mobile checkout drop-off is the main issue.\n- Billing screen is confusing."
    )
    assert name.startswith("Mobile checkout")
    assert "Key Points" not in name


def test_mode1_default_name_comes_from_summary_topic(tmp_output, ui_queue, monkeypatch):
    def fake_summarize(self, transcript_text, out_md):
        out_md.write_text(
            "Key Points\n- Mobile checkout drop-off is the main issue.\n- Billing screen is confusing.\n",
            encoding="utf-8",
        )

    mock_ollama(monkeypatch)
    monkeypatch.setattr(
        "summarizeaudio.transcriber.Transcriber.transcribe",
        lambda self, audio, out_txt, **kwargs: out_txt.write_text("transcript content long enough to summarize", encoding="utf-8"),
    )
    monkeypatch.setattr("summarizeaudio.summarizer.Summarizer.summarize", fake_summarize)
    cfg = make_config(tmp_output)
    mp3 = make_silence_mp3(tmp_output / "session.mp3")
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)
    captured = {}

    def worker():
        while True:
            item = ui_queue.get(timeout=5)
            if item[0] == "name_dialog":
                captured["default_name"] = item[2]
                item[1]._resolve("Project Update")
                return

    threading.Thread(target=worker, daemon=True).start()
    p.run(mode=PipelineMode.RECORD, session_name="TestSession", mp3_path=mp3)
    assert captured["default_name"].startswith("Mobile checkout")
    assert "Key Points" not in captured["default_name"]


def test_mode1_posts_summarizing_phase_before_name_dialog(tmp_output, monkeypatch):
    def fake_summarize(self, transcript_text, out_md):
        out_md.write_text(
            "Key Points\n- Mobile checkout drop-off is the main issue.\n- Billing screen is confusing.\n",
            encoding="utf-8",
        )

    mock_ollama(monkeypatch)
    monkeypatch.setattr(
        "summarizeaudio.transcriber.Transcriber.transcribe",
        lambda self, audio, out_txt, **kwargs: out_txt.write_text("transcript content long enough to summarize", encoding="utf-8"),
    )
    monkeypatch.setattr("summarizeaudio.summarizer.Summarizer.summarize", fake_summarize)
    cfg = make_config(tmp_output)
    mp3 = make_silence_mp3(tmp_output / "session.mp3")
    ui_queue = SpyQueue()
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)

    def worker():
        while True:
            item = ui_queue.get(timeout=5)
            if item[0] == "name_dialog":
                item[1]._resolve("Project Update")
                return

    threading.Thread(target=worker, daemon=True).start()
    p.run(mode=PipelineMode.RECORD, session_name="TestSession", mp3_path=mp3)

    kinds = [item[0] for item in ui_queue.recorded]
    assert "workflow_phase" in kinds
    assert "name_dialog" in kinds
    assert kinds.index("workflow_phase") < kinds.index("name_dialog")


def test_partial_session_is_saved_before_summarization_completes(tmp_output, ui_queue, monkeypatch):
    db_path = tmp_output / "history.sqlite3"
    monkeypatch.setattr(session_store, "HISTORY_DB", db_path)

    def failing_summarize(self, transcript_text, out_md):
        raise RuntimeError("summary crashed")

    mock_ollama(monkeypatch)
    monkeypatch.setattr(
        "summarizeaudio.transcriber.Transcriber.transcribe",
        lambda self, audio, out_txt, **kwargs: out_txt.write_text("transcript content long enough to summarize", encoding="utf-8"),
    )
    monkeypatch.setattr("summarizeaudio.summarizer.Summarizer.summarize", failing_summarize)
    cfg = make_config(tmp_output)
    mp3 = make_silence_mp3(tmp_output / "session.mp3")
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)

    p.run(mode=PipelineMode.RECORD, session_name="CrashDuringSummarize", mp3_path=mp3)

    sessions = load_sessions(tmp_output, include_archived=False)
    assert sessions
    assert sessions[0].status == "partial"
    assert sessions[0].summary is None or not sessions[0].summary.exists()


def test_mode2_does_not_touch_source_file(tmp_output, ui_queue, monkeypatch):
    """Pipeline orchestration test — mocks Transcriber."""
    mock_ollama(monkeypatch)
    monkeypatch.setattr(
        "summarizeaudio.transcriber.Transcriber.transcribe",
        lambda self, audio, out_txt, **kwargs: out_txt.write_text("transcript content long enough to summarize", encoding="utf-8"),
    )
    cfg = make_config(tmp_output)
    source = make_silence_mp3(tmp_output / "source_audio.mp3")
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)
    resolve_name_dialog(ui_queue, "Audio Topic")
    p.run(mode=PipelineMode.LOCAL_AUDIO, session_name="LocalAudio", source_path=source)
    assert source.exists(), "source audio must not be deleted"


def test_mode2_copies_source_audio_to_local_temp_file(tmp_output, ui_queue, monkeypatch):
    mock_ollama(monkeypatch)
    monkeypatch.setattr(
        "summarizeaudio.transcriber.Transcriber.transcribe",
        lambda self, audio, out_txt, **kwargs: out_txt.write_text("transcript content long enough to summarize", encoding="utf-8"),
    )
    copied = []

    real_copyfile = shutil.copyfile

    def spy_copyfile(src, dst, *args, **kwargs):
        copied.append((Path(src), Path(dst)))
        return real_copyfile(src, dst, *args, **kwargs)

    monkeypatch.setattr("summarizeaudio.pipeline.shutil.copyfile", spy_copyfile)
    cfg = make_config(tmp_output)
    source = make_silence_mp3(tmp_output / "source_audio.mp3")
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)
    resolve_name_dialog(ui_queue, "Audio Topic")
    p.run(mode=PipelineMode.LOCAL_AUDIO, session_name="LocalAudio", source_path=source)
    assert copied, "local audio should be copied before transcription"
    assert copied[0][0] == source
    assert copied[0][1].parent == Path(tempfile.gettempdir())


def test_mode2_copy_timeout_posts_cloud_sync_message(tmp_output, ui_queue, monkeypatch):
    cfg = make_config(tmp_output)
    source = make_silence_mp3(tmp_output / "source_audio.mp3")

    def timeout_copyfile(_src, _dst, *args, **kwargs):
        raise TimeoutError(
            "[Errno 60] Operation timed out: "
            "'/Users/surya/Library/CloudStorage/OneDrive-Personal/source_audio.mp3'"
        )

    monkeypatch.setattr("summarizeaudio.pipeline.shutil.copyfile", timeout_copyfile)
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)

    p.run(mode=PipelineMode.LOCAL_AUDIO, session_name="LocalAudio", source_path=source)

    assert not ui_queue.empty()
    item = ui_queue.get_nowait()
    assert item[0] == "error"
    assert "cloud-synced location" in item[2].lower()


def test_mode3_prewarms_ollama_model_before_summarizing(tmp_output, ui_queue, monkeypatch):
    """Text-only mode has no transcription step, so prewarm fires at the start of
    the run to overlap model loading with the file copy/read."""
    mock_ollama(monkeypatch)
    calls = []
    monkeypatch.setattr("summarizeaudio.pipeline.prewarm_async", lambda host, model: calls.append((host, model)))
    cfg = make_config(tmp_output)
    source = tmp_output / "notes.txt"
    source.write_text("my notes")
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)
    resolve_name_dialog(ui_queue, "Notes Topic")
    p.run(mode=PipelineMode.LOCAL_TEXT, session_name="notes", source_path=source)
    assert calls == [("http://localhost:11434", "x")]


def test_record_mode_does_not_prewarm_in_pipeline(tmp_output, ui_queue, monkeypatch):
    """RECORD already prewarmed at end-of-recording (tray), so the pipeline must
    not fire a redundant prewarm for that mode."""
    mock_ollama(monkeypatch)
    monkeypatch.setattr(
        "summarizeaudio.transcriber.Transcriber.transcribe",
        lambda self, src, out, on_progress=None, on_diarize_start=None: out.write_text(
            "transcript content long enough to summarize", encoding="utf-8"
        ),
    )
    monkeypatch.setattr(
        "summarizeaudio.summarizer.Summarizer.summarize",
        lambda self, transcript, out_md: out_md.write_text(
            "**Key Points:**\n- A.\n\n**Decisions / Action Items:**\n- None.\n\n**Notable Details:**\n- None.\n",
            encoding="utf-8",
        ),
    )
    calls = []
    monkeypatch.setattr("summarizeaudio.pipeline.prewarm_async", lambda host, model: calls.append((host, model)))
    cfg = make_config(tmp_output)
    mp3 = tmp_output / "recording.mp3"
    make_silence_mp3(mp3)
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)
    resolve_name_dialog(ui_queue, "Recorded Topic")
    p.run(mode=PipelineMode.RECORD, session_name="rec", mp3_path=mp3)
    assert calls == []


def test_mode3_does_not_touch_source_txt(tmp_output, ui_queue, monkeypatch):
    """Pipeline orchestration test — no transcription in Mode 3."""
    mock_ollama(monkeypatch)
    cfg = make_config(tmp_output)
    source = tmp_output / "notes.txt"
    source.write_text("my notes")
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)
    resolve_name_dialog(ui_queue, "Notes Topic")
    p.run(mode=PipelineMode.LOCAL_TEXT, session_name="notes", source_path=source)
    assert source.exists()
    assert source.read_text() == "my notes"


def test_mode3_resume_keeps_existing_recording_path(tmp_output, ui_queue, monkeypatch):
    db_path = tmp_output / "history.sqlite3"
    monkeypatch.setattr(session_store, "HISTORY_DB", db_path)

    mock_ollama(monkeypatch)
    monkeypatch.setattr(
        "summarizeaudio.summarizer.Summarizer.summarize",
        lambda self, transcript_text, out_md: out_md.write_text(
            "**Key Points:**\n- Retry summary.\n\n**Decisions / Action Items:**\n- Keep recording.\n\n**Notable Details:**\n- None.\n",
            encoding="utf-8",
        ),
    )

    source = tmp_output / "notes.txt"
    source.write_text("transcript content long enough to summarize", encoding="utf-8")
    recording = tmp_output / "recording.mp3"
    make_silence_mp3(recording)
    existing = session_store.create_session_record(
        root=tmp_output,
        source_key="resume-session",
        label="Topic",
        date=today(),
        mode="text",
        folder=tmp_output / "SummaryFiles",
        status="partial",
        transcript_path=source,
        audio_path=recording,
        source_path=recording,
    )

    p = Pipeline(cfg=make_config(tmp_output), ui_queue=ui_queue)
    resolve_name_dialog(ui_queue, "Retry Topic")
    p.run(mode=PipelineMode.LOCAL_TEXT, session_name="notes", source_path=source, resume_session_id=existing.id)

    resumed = session_store.session_by_id(existing.id)
    assert resumed is not None
    assert resumed.audio is not None
    assert resumed.audio.exists()


def test_pipeline_override_dismissed_produces_no_summary(tmp_output, ui_queue, monkeypatch):
    mock_ollama(monkeypatch)
    monkeypatch.setattr(
        "summarizeaudio.transcriber.Transcriber.transcribe",
        lambda self, audio, out_txt, **kwargs: out_txt.write_text("transcript content long enough to summarize", encoding="utf-8"),
    )
    cfg = make_config(tmp_output)
    cfg.behavior.show_override_dialog = True
    mp3 = make_silence_mp3(tmp_output / "s.mp3")
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)

    import threading
    def drain_and_dismiss():
        item = ui_queue.get(timeout=5)  # blocks until pipeline posts override event
        if item[0] == "override_dialog":
            item[1]._resolve(None)  # dismiss

    threading.Thread(target=drain_and_dismiss, daemon=True).start()
    p.run(mode=PipelineMode.RECORD, session_name="TestSkip", mp3_path=mp3)
    assert not any((tmp_output / "SummaryFiles").iterdir())


def test_transcription_failure_posts_error_and_preserves_mp3(tmp_output, ui_queue, monkeypatch):
    import threading
    cfg = make_config(tmp_output)
    mp3 = make_silence_mp3(tmp_output / "s.mp3")
    done = threading.Event()
    done.set()  # pretend pipeline is running
    with patch("summarizeaudio.transcriber.Transcriber.transcribe",
               side_effect=RuntimeError("whisper crashed")):
        p = Pipeline(cfg=cfg, ui_queue=ui_queue)
        p.run(mode=PipelineMode.RECORD, session_name="Crash", mp3_path=mp3,
              done_event=done)
    assert mp3.exists(), "MP3 must be preserved on transcription failure"
    assert not done.is_set(), "done_event must be cleared even after exception"
    # error must have been posted to ui_queue by pipeline
    assert not ui_queue.empty()
    item = ui_queue.get_nowait()
    assert item[0] == "error"
    assert "something went wrong" in item[2].lower()


def test_too_short_transcript_posts_centered_info_dialog(tmp_output, ui_queue, monkeypatch):
    monkeypatch.setattr(
        "summarizeaudio.transcriber.Transcriber.transcribe",
        lambda self, audio, out_txt, **kwargs: out_txt.write_text("...", encoding="utf-8"),
    )
    cfg = make_config(tmp_output)
    mp3 = make_silence_mp3(tmp_output / "short.mp3")
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)

    p.run(mode=PipelineMode.RECORD, session_name="Short", mp3_path=mp3)

    assert not ui_queue.empty()
    item = ui_queue.get_nowait()
    assert item[0] == "info_dialog"
    assert item[1] == "No usable audio was captured."
    assert "microphone" in item[2]


def test_mode2_too_short_transcript_mentions_selected_file(tmp_output, ui_queue, monkeypatch):
    monkeypatch.setattr(
        "summarizeaudio.transcriber.Transcriber.transcribe",
        lambda self, audio, out_txt, **kwargs: out_txt.write_text("...", encoding="utf-8"),
    )
    cfg = make_config(tmp_output)
    source = make_silence_mp3(tmp_output / "short_source.mp3")
    p = Pipeline(cfg=cfg, ui_queue=ui_queue)

    p.run(mode=PipelineMode.LOCAL_AUDIO, session_name="ShortSource", source_path=source)

    assert not ui_queue.empty()
    item = ui_queue.get_nowait()
    assert item[0] == "info_dialog"
    assert item[1] == "No usable speech was found."
    assert "selected audio file" in item[2]
    assert "microphone" not in item[2]


def test_transcription_timeout_posts_cloud_sync_message(tmp_output, ui_queue, monkeypatch):
    import threading
    cfg = make_config(tmp_output)
    mp3 = make_silence_mp3(tmp_output / "timeout.mp3")
    done = threading.Event()
    done.set()
    with patch(
        "summarizeaudio.transcriber.Transcriber.transcribe",
        side_effect=RuntimeError("[Errno 60] Operation timed out: '/Users/surya/OneDrive/file.mp3'"),
    ):
        p = Pipeline(cfg=cfg, ui_queue=ui_queue)
        p.run(mode=PipelineMode.RECORD, session_name="Timeout", mp3_path=mp3, done_event=done)
    assert not ui_queue.empty()
    item = ui_queue.get_nowait()
    assert item[0] == "error"
    assert "cloud-synced location" in item[2].lower()
