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
    CONFIG_PATH,
    DEFAULT_TOML,
    DEFAULT_SUMMARIZATION_PROMPT,
)


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
    with pytest.raises(Exception):
        load_config(ui_queue=q)
    assert not q.empty()
    item = q.get_nowait()
    assert item[0] == "error"


def test_missing_required_key_posts_error_and_raises(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    # Valid TOML but missing [storage] / output_folder
    cfg_path.write_text('[whisper]\nmodel = "base"\nlanguage = "en"\n')
    monkeypatch.setattr("summarizeaudio.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("summarizeaudio.config.CONFIG_DIR", tmp_path)
    q = queue.Queue()
    with pytest.raises(SystemExit):
        load_config(ui_queue=q)
    assert not q.empty()
    item = q.get_nowait()
    assert item[0] == "error"
    assert "output_folder" in item[2].lower()
