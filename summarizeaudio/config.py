from __future__ import annotations

import logging
import queue
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

CONFIG_DIR = Path.home() / ".summarizeaudio"
CONFIG_PATH = CONFIG_DIR / "config.toml"
LOG_PATH = CONFIG_DIR / "app.log"

VALID_WHISPER_MODELS = {"tiny", "base", "small", "medium", "large"}

DEFAULT_TOML = """\
[storage]
output_folder = "~/AudioSummaries"

[whisper]
model = "base"
language = "en"

[ollama]
host = "http://localhost:11434"
model = "mistral-small3.2:24b"

[summarization]
default_prompt = \"\"\"You are a helpful assistant. Summarize the following transcript concisely.
Highlight key decisions, action items, and important points.

Transcript:
{transcript}\"\"\"

[behavior]
show_override_dialog = true
auto_open_summary = false
"""


@dataclass
class StorageConfig:
    output_folder: Path


@dataclass
class WhisperConfig:
    model: str
    language: str


@dataclass
class OllamaConfig:
    host: str
    model: str


@dataclass
class SummarizationConfig:
    default_prompt: str


@dataclass
class BehaviorConfig:
    show_override_dialog: bool
    auto_open_summary: bool


@dataclass
class AppConfig:
    storage: StorageConfig
    whisper: WhisperConfig
    ollama: OllamaConfig
    summarization: SummarizationConfig
    behavior: BehaviorConfig


def load_config(ui_queue: queue.Queue | None = None) -> AppConfig:
    """Load config.toml, creating default if absent."""
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(DEFAULT_TOML)

    try:
        raw = tomllib.loads(CONFIG_PATH.read_text())
    except tomllib.TOMLDecodeError as exc:
        _post_error(ui_queue, "config.py", str(exc), traceback.format_exc())
        raise

    storage = raw.get("storage", {})
    whisper = raw.get("whisper", {})
    ollama_raw = raw.get("ollama", {})
    summ = raw.get("summarization", {})
    beh = raw.get("behavior", {})

    # Required key: output_folder
    if "output_folder" not in storage:
        msg = "Missing required config key: [storage] output_folder"
        _post_error(ui_queue, "config.py", msg, "")
        sys.exit(1)

    whisper_model = whisper.get("model", "base")
    if whisper_model not in VALID_WHISPER_MODELS:
        logging.warning("Invalid whisper model %r, using 'base'", whisper_model)
        whisper_model = "base"

    return AppConfig(
        storage=StorageConfig(
            output_folder=Path(storage.get("output_folder", "~/AudioSummaries")).expanduser()
        ),
        whisper=WhisperConfig(
            model=whisper_model,
            language=whisper.get("language", "en"),
        ),
        ollama=OllamaConfig(
            host=ollama_raw.get("host", "http://localhost:11434"),
            model=ollama_raw.get("model", "mistral-small3.2:24b"),
        ),
        summarization=SummarizationConfig(
            default_prompt=summ.get("default_prompt", "Summarize:\n{transcript}"),
        ),
        behavior=BehaviorConfig(
            show_override_dialog=beh.get("show_override_dialog", True),
            auto_open_summary=beh.get("auto_open_summary", False),
        ),
    )


def _post_error(q: queue.Queue | None, component: str, msg: str, tb: str) -> None:
    if q is not None:
        try:
            q.put_nowait(("error", component, msg, tb))
        except queue.Full:
            pass
