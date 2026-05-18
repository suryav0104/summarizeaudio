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

DEFAULT_SUMMARIZATION_PROMPT = """You are a precise meeting-note summarizer.
Output markdown only. Do not add an introduction, conclusion, apology, or commentary outside the sections below.

Use only facts stated in the transcript. Do not invent details, infer intent, or restate the same point in multiple sections.
Prefer short, specific bullets over paragraphs. If a section has nothing useful to add, omit that section.

Section guidance:
- **Key Points:** 3-6 bullets covering the main topics, themes, and outcomes.
- **Decisions / Action Items:** every decision, owner, deadline, and follow-up.
- **Notable Details:** only concrete supporting details that matter later, such as risks, blockers, dates, or clarifications.

Transcript:
{transcript}
"""


def _toml_multiline_literal(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def _toml_basic_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _get_total_ram_gb() -> float:
    """Return total system RAM in GB, or 0.0 if undetectable."""
    try:
        if sys.platform == "darwin":
            result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
            return int(result.stdout.strip()) / (1024 ** 3)
        elif sys.platform == "win32":
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum"],
                capture_output=True, text=True,
            )
            return int(result.stdout.strip()) / (1024 ** 3)
        else:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024 / (1024 ** 3)
    except Exception:
        pass
    return 0.0


# Approximate in-memory footprint for each component (GB).
_WHISPER_RAM_GB: dict[str, float] = {
    "tiny": 0.5, "base": 0.5, "small": 1.0, "medium": 2.0, "large": 3.5,
}
_OLLAMA_RAM_GB: dict[str, float] = {
    "gemma3:4b": 4.0, "gemma3:12b": 9.0,
}
_DIARIZER_RAM_GB = 1.5
_OS_OVERHEAD_GB  = 2.0


def memory_warning(cfg: "AppConfig", needs_transcription: bool = True) -> str | None:
    """Return a human-readable warning string if RAM looks insufficient, else None.

    needs_transcription=False skips Whisper + diarizer budgets (text-only mode).
    """
    total_gb = _get_total_ram_gb()
    if total_gb <= 0:
        return None  # can't determine — stay silent

    ollama_gb  = _OLLAMA_RAM_GB.get(cfg.ollama.model, 4.0)
    whisper_gb = _WHISPER_RAM_GB.get(cfg.whisper.model, 1.0) if needs_transcription else 0.0
    import os as _os
    diarizer_gb = _DIARIZER_RAM_GB if (needs_transcription and _os.environ.get("HUGGINGFACE_ACCESS_TOKEN")) else 0.0
    needed_gb  = ollama_gb + whisper_gb + diarizer_gb + _OS_OVERHEAD_GB

    if total_gb >= needed_gb:
        return None

    parts = [f"{cfg.ollama.model} (~{ollama_gb:.0f} GB)"]
    if whisper_gb:
        parts.append(f"Whisper {cfg.whisper.model} (~{whisper_gb:.1f} GB)")
    if diarizer_gb:
        parts.append(f"diarizer (~{diarizer_gb:.1f} GB)")
    components = ", ".join(parts)
    return (
        f"Low memory: your system has {total_gb:.0f} GB RAM but "
        f"{components} needs ~{needed_gb:.0f} GB total. "
        "Processing may be slow or fail."
    )


def _select_model_for_ram() -> str:
    """Return the recommended Ollama model based on available system RAM."""
    ram_gb = _get_total_ram_gb()
    if ram_gb <= 0:
        return "gemma3:4b"
    return "gemma3:12b" if ram_gb > 8 else "gemma3:4b"


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
default_prompt = \"\"\"{_toml_multiline_literal(DEFAULT_SUMMARIZATION_PROMPT)}\"\"\"

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


class ConfigError(RuntimeError):
    """Raised when the config file cannot be loaded safely."""


def load_config(ui_queue: queue.Queue | None = None) -> AppConfig:
    """Load config.toml, creating default if absent."""
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(_make_default_toml(_select_model_for_ram()))

    try:
        raw = tomllib.loads(CONFIG_PATH.read_text())
    except tomllib.TOMLDecodeError as exc:
        message = (
            "The configuration file could not be read. Open "
            "`~/.summarizeaudio/config.toml` to fix it, or delete it to regenerate the "
            "default settings."
        )
        _post_error(ui_queue, "config.py", message, traceback.format_exc())
        raise ConfigError(message) from exc

    storage = raw.get("storage", {})
    whisper = raw.get("whisper", {})
    ollama_raw = raw.get("ollama", {})
    summ = raw.get("summarization", {})
    beh = raw.get("behavior", {})
    rec = raw.get("recording", {})

    # Required key: output_folder
    if "output_folder" not in storage:
        msg = (
            "Your configuration is missing the output folder setting. Open "
            "`~/.summarizeaudio/config.toml` and add `[storage] output_folder`, or delete the "
            "file to regenerate the defaults."
        )
        _post_error(ui_queue, "config.py", msg, "")
        raise ConfigError(msg)

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
            default_prompt=summ.get("default_prompt", DEFAULT_SUMMARIZATION_PROMPT),
        ),
        behavior=BehaviorConfig(
            show_override_dialog=beh.get("show_override_dialog", True),
            auto_open_summary=beh.get("auto_open_summary", False),
        ),
        recording=RecordingConfig(
            input_device=rec.get("input_device") or None,
        ),
    )


def save_config(cfg: AppConfig) -> None:
    """Persist the current config back to CONFIG_PATH."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        f"""\
[storage]
output_folder = "{_toml_basic_string(str(cfg.storage.output_folder))}"

[whisper]
model = "{_toml_basic_string(cfg.whisper.model)}"
language = "{_toml_basic_string(cfg.whisper.language)}"

[ollama]
host = "{_toml_basic_string(cfg.ollama.host)}"
model = "{_toml_basic_string(cfg.ollama.model)}"

[summarization]
default_prompt = \"\"\"{_toml_multiline_literal(cfg.summarization.default_prompt)}\"\"\"

[behavior]
show_override_dialog = {"true" if cfg.behavior.show_override_dialog else "false"}
auto_open_summary = {"true" if cfg.behavior.auto_open_summary else "false"}

[recording]
input_device = "{_toml_basic_string(cfg.recording.input_device or "")}"
""",
        encoding="utf-8",
    )


def _post_error(q: queue.Queue | None, component: str, msg: str, tb: str) -> None:
    if q is not None:
        try:
            q.put_nowait(("error", component, msg, tb))
        except queue.Full:
            pass
