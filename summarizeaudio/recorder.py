from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import wave
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

    def start(self) -> None:
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
            if loopback_device is None and not getattr(self, "_loopback_warned", False):
                self._loopback_warned = True
                notify(f"Configured input device '{self._input_device}' not found. Recording from system default.")
        else:
            loopback_device = _get_loopback_device()
            if loopback_device is None and not getattr(self, "_loopback_warned", False):
                self._loopback_warned = True
                if platform.system() == "Darwin":
                    notify("System audio not found. Recording mic only. Install BlackHole for system audio capture.")
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
            if self._wav_path and self._wav_path.exists():
                self._wav_path.unlink()
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
