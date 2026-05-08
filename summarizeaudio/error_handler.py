from __future__ import annotations

import queue
from pathlib import Path


LOG_PATH = Path.home() / ".summarizeaudio" / "app.log"


def friendly_message(component: str, message: str, traceback_str: str = "") -> str:
    text = f"{component}\n{message}\n{traceback_str}".lower()

    if (
        "errno 60" in text
        or "operation timed out" in text
        or "av.error.timeouterror" in text
        or "cloud-synced location" in text
        or "available offline" in text
    ):
        return (
            "SummarizeAudio could not read that audio file because it appears to be in a "
            "cloud-synced location or otherwise unavailable locally. Make the file available "
            "offline, or copy it to a local folder like Downloads or Desktop, then try again."
        )

    if "permission denied" in text or "operation not permitted" in text:
        return (
            "SummarizeAudio does not have permission to access that file or folder. "
            "Check the file permissions or move it to a location the app can read."
        )

    if "file not found" in text or "no such file" in text:
        return (
            "The selected file could not be found. It may have been moved, renamed, or removed."
        )

    if "ollama" in text and (
        "connection refused" in text
        or "failed to establish" in text
        or "max retries exceeded" in text
        or "connect timed out" in text
    ):
        return (
            "The local Ollama server is not reachable. Make sure Ollama is running, "
            "then try again."
        )

    if "ollama" in text and (
        ("model" in text and "not found" in text)
        or "404" in text
        or "does not exist" in text
        or "pull the model" in text
    ):
        return (
            "The selected Ollama model is not installed. Run `ollama pull <model>` and try again."
        )

    if "ffmpeg" in text and (
        "not found" in text
        or "enoent" in text
        or "returned non-zero exit status" in text
        or "invalid data found" in text
        or "conversion failed" in text
        or "error while" in text
    ):
        return (
            "The audio conversion step failed. Make sure ffmpeg is installed and the selected "
            "file is a valid recording."
        )

    if "sounddevice" in text or "portaudio" in text or "inputstream" in text:
        return (
            "SummarizeAudio could not start recording. Check your microphone permission, "
            "input device selection, and system audio setup, then try again."
        )

    if "config" in text and (
        "toml" in text
        or "decode" in text
        or "missing required" in text
        or "could not be read" in text
        or "missing the output folder setting" in text
        or "output folder setting" in text
    ):
        return (
            "The configuration file is invalid. Open `~/.summarizeaudio/config.toml` to fix it, "
            "or delete it to regenerate the default settings."
        )

    if "whisper" in text and ("download" in text or "load" in text):
        return (
            "Whisper could not load its model. Try again after confirming the model is installed "
            "and the network is available for the first download."
        )

    if (
        "recording too short" in text
        or "captured no usable audio" in text
        or "check your input device" in text
    ):
        return (
            "The recording captured no usable audio. Check your microphone or system audio input "
            "device in System Settings, then try recording again."
        )

    if "unsupported audio file" in text or "not a supported audio file" in text:
        return (
            "The selected file is not a supported audio format. Choose an audio file such as "
            "MP3, WAV, M4A, OGG, FLAC, MP4, or WEBM."
        )

    if (
        "summary validation failed" in text
        or "missing required summary sections" in text
        or "duplicate summary sections" in text
        or "unexpected section heading" in text
        or "text before the first summary section" in text
        or "repetitive output" in text
    ):
        return (
            "The model returned a summary that did not match the expected format. "
            "Please try summarizing again."
        )

    return (
        "Something went wrong while processing this request. "
        "Please try again or check the log for details."
    )


def post_error(
    ui_queue: queue.Queue | None,
    component: str,
    message: str,
    traceback_str: str,
) -> None:
    """Post an error popup request to ui_queue for display on the main thread."""
    if ui_queue is None:
        return
    try:
        ui_queue.put_nowait(("error", component, message, traceback_str))
    except queue.Full:
        pass


def format_error(component: str, message: str, traceback_str: str) -> str:
    """Format a human-readable error string for display."""
    friendly = friendly_message(component, message, traceback_str)
    return f"Component: {component}\n\n{friendly}\n\nSee {LOG_PATH} for technical details."
