from __future__ import annotations

import logging
import queue
import subprocess
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


def _select_model_for_ram() -> str:
    """Return the recommended Ollama model based on available system RAM."""
    try:
        if sys.platform == "darwin":
            result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
            ram_bytes = int(result.stdout.strip())
        elif sys.platform == "win32":
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum"],
                capture_output=True, text=True,
            )
            ram_bytes = int(result.stdout.strip())
        else:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        ram_bytes = int(line.split()[1]) * 1024
                        break
                else:
                    return "gemma3:4b"
    except Exception:
        return "gemma3:4b"
    return "gemma3:12b" if ram_bytes > 8 * 1024 ** 3 else "gemma3:4b"


def _make_default_toml(model: str) -> str:
    return f"""\
[storage]
output_folder = "~/Applications/SummarizeAudio/AudioSummaries"

[whisper]
model = "base"
language = "en"

[ollama]
host = "http://localhost:11434"
model = "{model}"

[summarization]
default_prompt = \"\"\"You are a summarization engine. Output ONLY the summary — no preamble, no commentary about the transcript, no meta-remarks. Begin directly with the summary content.

Summarize the transcript below. Structure the output as:
- **Key Points:** the main ideas or topics covered
- **Decisions / Action Items:** anything decided or that requires follow-up (omit section if none)
- **Notable Details:** anything else worth remembering

Transcript:
{{transcript}}\"\"\"

[behavior]
show_override_dialog = true
auto_open_summary = false

[recording]
# Leave blank to auto-detect BlackHole (macOS) or WASAPI loopback (Windows).
# Set to an exact device name to override, e.g. "Voice + System Audio" for an Aggregate Device.
input_device = ""
"""


# Stable constant used by tests and anywhere that needs a representative TOML blob.
DEFAULT_TOML = _make_default_toml("gemma3:4b")


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
class RecordingConfig:
    input_device: str | None  # None = auto-detect BlackHole; set to exact device name to override


@dataclass
class AppConfig:
    storage: StorageConfig
    whisper: WhisperConfig
    ollama: OllamaConfig
    summarization: SummarizationConfig
    behavior: BehaviorConfig
    recording: RecordingConfig


def load_config(ui_queue: queue.Queue | None = None) -> AppConfig:
    """Load config.toml, creating default if absent."""
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(_make_default_toml(_select_model_for_ram()))

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
    rec = raw.get("recording", {})

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
            model=ollama_raw.get("model", "gemma3:4b"),
        ),
        summarization=SummarizationConfig(
            default_prompt=summ.get("default_prompt", "Summarize:\n{transcript}"),
        ),
        behavior=BehaviorConfig(
            show_override_dialog=beh.get("show_override_dialog", True),
            auto_open_summary=beh.get("auto_open_summary", False),
        ),
        recording=RecordingConfig(
            input_device=rec.get("input_device") or None,
        ),
    )


def _post_error(q: queue.Queue | None, component: str, msg: str, tb: str) -> None:
    if q is not None:
        try:
            q.put_nowait(("error", component, msg, tb))
        except queue.Full:
            pass
