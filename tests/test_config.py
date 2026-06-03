# tests/test_config.py
import queue
import pytest
import tomllib
from pathlib import Path
from unittest.mock import patch

from summarizeaudio.config import (
    load_config,
    save_config,
    AppConfig,
    ConfigError,
    CONFIG_PATH,
    DEFAULT_TOML,
    DEFAULT_SUMMARIZATION_PROMPT,
    BehaviorConfig,
    DiarizationConfig,
    OllamaConfig,
    RecordingConfig,
    StorageConfig,
    SummarizationConfig,
    WhisperConfig,
)


def _low_ram_cfg(tmp_path, diar_enabled=False):
    # gemma3:12b (~9 GB) + Whisper base (~0.5) + OS (2) easily exceeds an 8 GB box,
    # so memory_warning() fires and we can inspect which components it lists.
    return AppConfig(
        storage=StorageConfig(output_folder=tmp_path),
        whisper=WhisperConfig(model="base", language="en"),
        ollama=OllamaConfig(host="http://localhost:11434", model="gemma3:12b"),
        summarization=SummarizationConfig(default_prompt="x {transcript}"),
        behavior=BehaviorConfig(show_override_dialog=False, auto_open_summary=False),
        recording=RecordingConfig(input_device=None),
        diarization=DiarizationConfig(enabled=diar_enabled),
    )


def test_memory_warning_excludes_diarizer_when_preference_off(tmp_path, monkeypatch):
    from summarizeaudio import config as cfgmod
    from summarizeaudio import diarization
    monkeypatch.setattr(cfgmod, "_get_total_ram_gb", lambda: 8.0)
    # Token present but the user turned diarization OFF — must NOT inflate the budget.
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "hf_real")
    monkeypatch.setattr(diarization, "effective_enabled", lambda cfg: False)
    msg = cfgmod.memory_warning(_low_ram_cfg(tmp_path, diar_enabled=False))
    assert msg is not None
    assert "diarizer" not in msg


def test_memory_warning_includes_diarizer_when_effective_enabled(tmp_path, monkeypatch):
    from summarizeaudio import config as cfgmod
    from summarizeaudio import diarization
    monkeypatch.setattr(cfgmod, "_get_total_ram_gb", lambda: 8.0)
    monkeypatch.delenv("HUGGINGFACE_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(diarization, "effective_enabled", lambda cfg: True)
    msg = cfgmod.memory_warning(_low_ram_cfg(tmp_path, diar_enabled=True))
    assert msg is not None
    assert "diarizer" in msg


def test_creates_default_config_on_first_run(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)
    cfg = load_config()
    assert cfg_path.exists()
    assert isinstance(cfg, AppConfig)


def test_loads_valid_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(DEFAULT_TOML)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)
    cfg = load_config()
    assert cfg.whisper.model == "base"
    assert cfg.ollama.model == "gemma3:4b"
    assert cfg.behavior.show_override_dialog is True


def test_default_prompt_is_strict_and_structured():
    assert "precise meeting-note summarizer" in DEFAULT_SUMMARIZATION_PROMPT
    assert "Output markdown only" in DEFAULT_SUMMARIZATION_PROMPT
    assert "Do not invent details" in DEFAULT_SUMMARIZATION_PROMPT
    assert "**Key Points:**" in DEFAULT_SUMMARIZATION_PROMPT
    assert "**Decisions / Action Items:**" in DEFAULT_SUMMARIZATION_PROMPT
    assert "**Notable Details:**" in DEFAULT_SUMMARIZATION_PROMPT


def test_save_config_persists_model_choice(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(DEFAULT_TOML)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)

    cfg = load_config()
    cfg.ollama.model = "gemma3:12b"
    save_config(cfg)

    reloaded = load_config()
    assert reloaded.ollama.model == "gemma3:12b"


def test_save_config_preserves_transcript_placeholder(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(DEFAULT_TOML)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)

    cfg = load_config()
    cfg.summarization.default_prompt = "Summarize: {transcript}"
    save_config(cfg)

    saved = cfg_path.read_text(encoding="utf-8")
    assert "{transcript}" in saved
    assert "{{transcript}}" not in saved
    assert load_config().summarization.default_prompt == "Summarize: {transcript}"


def test_default_config_has_diarization_disabled(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(DEFAULT_TOML)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)
    cfg = load_config()
    assert cfg.diarization.enabled is False


def test_loads_diarization_enabled_from_toml(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(DEFAULT_TOML.replace("enabled = false", "enabled = true"))
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)
    cfg = load_config()
    assert cfg.diarization.enabled is True


def test_missing_diarization_section_defaults_false(tmp_path, monkeypatch):
    # Older config files predate the [diarization] section.
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[storage]\noutput_folder = "~/x"\n'
                        '[whisper]\nmodel = "base"\nlanguage = "en"\n'
                        '[ollama]\nhost = "http://localhost:11434"\nmodel = "gemma3:4b"\n'
                        '[summarization]\ndefault_prompt = "s {transcript}"\n'
                        '[behavior]\nshow_override_dialog = true\nauto_open_summary = false\n')
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)
    cfg = load_config()
    assert cfg.diarization.enabled is False


def test_save_config_persists_diarization_enabled(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(DEFAULT_TOML)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)

    cfg = load_config()
    cfg.diarization.enabled = True
    save_config(cfg)

    assert load_config().diarization.enabled is True


def test_invalid_whisper_model_falls_back_to_base(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[whisper]\nmodel = "huge"\nlanguage = "en"\n'
                        '[storage]\noutput_folder = "~/Applications/SummarizeAudio/AudioSummaries"\n'
                        '[ollama]\nhost = "http://localhost:11434"\nmodel = "x"\n'
                        '[summarization]\ndefault_prompt = "s {transcript}"\n'
                        '[behavior]\nshow_override_dialog = true\nauto_open_summary = false\n')
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)
    cfg = load_config()
    assert cfg.whisper.model == "base"


def test_malformed_toml_posts_error_and_raises(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("NOT VALID TOML ][[[")
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)
    q = queue.Queue()
    with pytest.raises(ConfigError):
        load_config(ui_queue=q)
    assert not q.empty()
    item = q.get_nowait()
    assert item[0] == "error"
    assert "configuration file could not be read" in item[2].lower()


def test_missing_required_key_posts_error_and_raises(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    # Valid TOML but missing [storage] / output_folder
    cfg_path.write_text('[whisper]\nmodel = "base"\nlanguage = "en"\n')
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)
    q = queue.Queue()
    with pytest.raises(ConfigError):
        load_config(ui_queue=q)
    assert not q.empty()
    item = q.get_nowait()
    assert item[0] == "error"
    assert "missing the output folder setting" in item[2].lower()
