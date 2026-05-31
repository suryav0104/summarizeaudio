from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import sounddevice as sd

from summarizeaudio.notifier import notify

MIN_DURATION_SECONDS = 2.0
SAMPLE_RATE = 16000
CHANNELS = 1
FLUSH_INTERVAL_SECONDS = 30
INPUT_HEALTH_SAMPLE_SECONDS = 1.5
INPUT_HEALTH_MAX_CHANNELS = 8
INPUT_HEALTH_SIGNAL_THRESHOLD = 0.003


def _get_loopback_device() -> int | None:
    """Return device index for system audio loopback, or None if unavailable."""
    if platform.system() == "Darwin":
        for i, dev in enumerate(sd.query_devices()):
            if "blackhole" in dev["name"].lower() and dev["max_input_channels"] > 0:
                return i
    elif platform.system() == "Windows":
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0 and "loopback" in dev["name"].lower():
                return i
    return None


def _find_device_by_name(name: str) -> int | None:
    """Return device index for a device whose name contains `name` (case-insensitive)."""
    for i, dev in enumerate(sd.query_devices()):
        if name.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
            return i
    return None


@dataclass
class InputHealthReport:
    ok: bool
    issue: str
    warning: str | None
    device_name: str | None
    requested_device: str | None
    sampled_channels: int
    active_channels: tuple[int, ...]


def _resolve_input_device(input_device: str | None) -> tuple[int | None, str | None]:
    if input_device:
        device_index = _find_device_by_name(input_device)
        if device_index is None:
            return None, input_device
        dev = sd.query_devices(device_index)
        return device_index, str(dev["name"])

    device_index = _get_loopback_device()
    if device_index is not None:
        dev = sd.query_devices(device_index)
        return device_index, str(dev["name"])

    default_input, _default_output = sd.default.device
    if default_input is None or default_input < 0:
        return None, None
    dev = sd.query_devices(default_input)
    return int(default_input), str(dev["name"])


def resolve_auto_input_device_name() -> str | None:
    """Return the name auto-detect would pick (loopback or system default).

    Returns None when no input device is reachable or the probe raises.
    Used by the Settings window to render "Auto (BlackHole 2ch)" style labels
    without committing the resolved name to config.
    """
    try:
        _index, name = _resolve_input_device(None)
        return name
    except Exception:
        return None


def check_input_health(input_device: str | None) -> InputHealthReport:
    """Probe the selected input device and detect silent/default-channel issues."""
    try:
        device_index, resolved_name = _resolve_input_device(input_device)
        if device_index is None:
            if input_device:
                return InputHealthReport(
                    ok=False,
                    issue="device_missing",
                    warning=(
                        f"Configured recording device '{input_device}' was not found. "
                        "Open Audio MIDI Setup or System Settings > Sound and choose a working input device."
                    ),
                    device_name=None,
                    requested_device=input_device,
                    sampled_channels=0,
                    active_channels=(),
                )
            return InputHealthReport(
                ok=False,
                issue="no_device",
                warning=(
                    "No input device is available for recording. Check microphone permission and your "
                    "Sound input settings, then reopen SummarizeAudio."
                ),
                device_name=None,
                requested_device=input_device,
                sampled_channels=0,
                active_channels=(),
            )

        device_info = sd.query_devices(device_index)
        max_input_channels = int(device_info["max_input_channels"])
        sampled_channels = max(1, min(max_input_channels, INPUT_HEALTH_MAX_CHANNELS))
        captured_chunks: list[np.ndarray] = []

        def _capture(indata: np.ndarray, frames: int, time_info, status) -> None:
            captured_chunks.append(np.array(indata, copy=True))

        with sd.InputStream(
            samplerate=int(device_info["default_samplerate"]) or 48000,
            channels=sampled_channels,
            dtype="float32",
            device=device_index,
            callback=_capture,
        ):
            sd.sleep(int(INPUT_HEALTH_SAMPLE_SECONDS * 1000))

        if not captured_chunks:
            return InputHealthReport(
                ok=False,
                issue="no_frames",
                warning=(
                    f"SummarizeAudio could open '{resolved_name}', but it did not receive any audio frames. "
                    "Check microphone permission and the device routing in Audio MIDI Setup."
                ),
                device_name=resolved_name,
                requested_device=input_device,
                sampled_channels=sampled_channels,
                active_channels=(),
            )

        sample = np.concatenate(captured_chunks, axis=0)
        per_channel_peak = np.max(np.abs(sample), axis=0)
        active_channels = tuple(
            index + 1
            for index, peak in enumerate(per_channel_peak.tolist())
            if peak >= INPUT_HEALTH_SIGNAL_THRESHOLD
        )

        if not active_channels:
            return InputHealthReport(
                ok=False,
                issue="no_signal",
                warning=(
                    f"'{resolved_name}' is not carrying any detectable input signal. "
                    "Check the microphone mute state, input level, and aggregate-device routing before recording."
                ),
                device_name=resolved_name,
                requested_device=input_device,
                sampled_channels=sampled_channels,
                active_channels=(),
            )

        if CHANNELS == 1 and 1 not in active_channels:
            channel_list = ", ".join(str(channel) for channel in active_channels)
            return InputHealthReport(
                ok=False,
                issue="channel_mapping",
                warning=(
                    f"'{resolved_name}' has signal on input channel(s) {channel_list}, but SummarizeAudio records "
                    "channel 1 only. Recording will likely be silent until the device is remapped."
                ),
                device_name=resolved_name,
                requested_device=input_device,
                sampled_channels=sampled_channels,
                active_channels=active_channels,
            )

        return InputHealthReport(
            ok=True,
            issue="ok",
            warning=None,
            device_name=resolved_name,
            requested_device=input_device,
            sampled_channels=sampled_channels,
            active_channels=active_channels,
        )
    except Exception as exc:
        device_label = input_device or "the selected input device"
        return InputHealthReport(
            ok=False,
            issue="probe_error",
            warning=(
                f"SummarizeAudio could not test {device_label}: {exc}. "
                "Check microphone permission and audio-device access, then reopen the app."
            ),
            device_name=None,
            requested_device=input_device,
            sampled_channels=0,
            active_channels=(),
        )


class Recorder:
    def __init__(self, output_folder: Path, input_device: str | None = None) -> None:
        self._output_folder = output_folder
        self._input_device = input_device
        self._session_id: str | None = None
        self._wav_path: Path | None = None
        self._raw_file = None  # raw file handle for portable flush
        self._wav_writer: wave.Wave_write | None = None
        self._stream: sd.InputStream | None = None
        self._start_time: datetime | None = None
        self._chunk_count = 0

    def cleanup(self, delete_wav: bool = False) -> None:
        """Close any open handles and optionally remove the unfinished WAV."""
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._wav_writer is not None:
            try:
                self._wav_writer.close()
            except Exception:
                pass
            self._wav_writer = None
        if self._raw_file is not None:
            try:
                self._raw_file.close()
            except Exception:
                pass
            self._raw_file = None
        if delete_wav and self._wav_path and self._wav_path.exists():
            self._wav_path.unlink(missing_ok=True)

    def start(self) -> None:
        try:
            self._session_id = str(uuid4())
            self._wav_path = self._output_folder / f"{self._session_id}.wav"
            # Open raw file first so we can flush it portably without relying on
            # CPython internals like wave.Wave_write._ensure_header_written
            self._raw_file = open(self._wav_path, "wb")  # noqa: WPS515
            self._wav_writer = wave.open(self._raw_file, "wb")
            self._wav_writer.setnchannels(CHANNELS)
            self._wav_writer.setsampwidth(2)  # 16-bit
            self._wav_writer.setframerate(SAMPLE_RATE)
            self._start_time = datetime.now()
            self._chunk_count = 0

            if self._input_device:
                loopback_device = _find_device_by_name(self._input_device)
                if loopback_device is None:
                    raise RuntimeError(
                        f"Configured recording device '{self._input_device}' was not found."
                    )
            else:
                loopback_device = _get_loopback_device()
                if loopback_device is None and not getattr(self, "_loopback_warned", False):
                    self._loopback_warned = True
                    if platform.system() == "Darwin":
                        notify(
                            "System audio not found. Recording mic only. Install BlackHole for system audio capture."
                        )
                    elif platform.system() == "Windows":
                        notify("No WASAPI loopback device found. Recording mic only.")

            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                device=loopback_device,
                callback=self._callback,
            )
            self._stream.start()
        except Exception:
            self.cleanup(delete_wav=True)
            raise

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if self._wav_writer is None:
            return
        self._wav_writer.writeframes(indata.tobytes())
        self._chunk_count += 1
        # Flush every ~30 seconds worth of callbacks
        callbacks_per_flush = int(FLUSH_INTERVAL_SECONDS * SAMPLE_RATE / 1024)
        if self._chunk_count % max(callbacks_per_flush, 1) == 0:
            if self._raw_file is not None:
                self._raw_file.flush()

    def stop(self) -> tuple[Path, datetime, datetime]:
        end_time = datetime.now()
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._wav_writer:
            self._wav_writer.close()
            self._wav_writer = None
        if self._raw_file:
            self._raw_file.close()
            self._raw_file = None

        duration = (end_time - self._start_time).total_seconds()
        if duration < MIN_DURATION_SECONDS:
            self.cleanup(delete_wav=True)
            raise ValueError(f"Recording too short ({duration:.1f}s < {MIN_DURATION_SECONDS}s)")

        # Convert WAV → MP3 using ffmpeg
        mp3_path = self._wav_path.with_suffix(".mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(self._wav_path), str(mp3_path)],
            check=True,
            capture_output=True,
        )
        self._wav_path.unlink()

        return mp3_path, self._start_time, end_time
