# SummarizeAudio — Design Specification
**Date:** 2026-03-15
**Status:** Approved

---

## One-liner

A cross-platform (macOS + Windows) system tray app that records audio, transcribes it locally with Whisper, then summarizes it using the Claude Code CLI — all triggered from a single tray icon click.

---

## Technology Stack

| Technology | Purpose |
|---|---|
| `Python 3.11+` | Primary language |
| `pystray` | Cross-platform system tray icon and menu |
| `sounddevice` | Cross-platform audio capture (wraps PortAudio); mic + loopback |
| `numpy` | Audio buffer handling |
| `scipy` | Write captured audio buffers to `.wav` file |
| `faster-whisper` | Local on-device speech-to-text transcription (no API cost) |
| `claude` CLI (`claude -p`) | Non-interactive summarization via Claude Code CLI subprocess |
| `tomllib` / `tomli` | Parse `config.toml` configuration file |
| `tkinter` | Override prompt dialog and error popup dialogs (stdlib, cross-platform) |
| `plyer` | Cross-platform desktop notifications (fallback for Windows) |
| `osascript` | macOS native notifications via AppleScript |
| `BlackHole` (macOS, user-installed) | Virtual audio device enabling system audio loopback capture |
| `Pillow` | Icon image handling for pystray |

---

## Platform-Specific Behaviour

| Concern | macOS | Windows |
|---|---|---|
| System audio loopback | Requires **BlackHole** virtual device (one-time user install) | WASAPI loopback via `sounddevice` (built-in) |
| Tray icon format | `.png` | `.ico` |
| Notifications | `osascript` AppleScript | `plyer` |
| `claude` CLI path resolution | `~/.claude/local/claude` or `shutil.which("claude")` | `shutil.which("claude")` |
| Error popup | `tkinter.messagebox` | `tkinter.messagebox` |

If BlackHole is not installed on macOS, the app falls back to mic-only recording and notifies the user once with setup instructions.

---

## Component Breakdown

| Component | File | Responsibility |
|---|---|---|
| Tray Manager | `tray.py` | Entry point. Owns the `pystray` icon lifecycle, menu items, and icon state (idle / recording / processing / error). Spawns pipeline thread on stop. |
| Recorder | `recorder.py` | Platform-aware audio capture. Opens mic + system loopback streams via `sounddevice`. Streams audio into an in-memory buffer. Writes `.wav` on stop. Records start/end timestamps. |
| Pipeline Orchestrator | `pipeline.py` | Background thread entry point. Calls transcriber → renamer → summarizer → notifier in sequence. Catches and surfaces errors. |
| Transcriber | `transcriber.py` | Loads `faster-whisper` model (auto-downloads on first run). Transcribes `.wav` → `.txt`. |
| Renamer | `renamer.py` | Renames `.wav` and `.txt` files to the canonical `YYYY-MM-DD_HH-MM-SS_to_HH-MM-SS` prefix. |
| Summarizer | `summarizer.py` | Loads default prompt from config, substitutes `{transcript}`, optionally shows override dialog, calls `claude -p` subprocess, saves `.md` summary. |
| Notifier | `notifier.py` | Sends a system notification with a summary snippet when pipeline completes. Platform-specific implementation. |
| Error Handler | `error_handler.py` | Presents a `tkinter` modal popup with the failed component name, error message, and stack trace. Used by all pipeline stages. |
| Config Loader | `config.py` | Loads and validates `config.toml`. Creates default config file on first run if absent. |

---

## Data Flow

```
[User clicks tray icon — idle → recording]
        ↓
[recorder.py]
  - Opens mic stream + system loopback stream (platform-aware)
  - Buffers audio in memory
  - Records start_time = datetime.now()

[User clicks tray icon — recording → processing]
        ↓
  - Records end_time = datetime.now()
  - Writes raw buffer → {output_folder}/temp_audio.wav
  - If duration < 2s → discard, notify "Too short", return to idle

[pipeline.py — background thread starts]
        ↓
[transcriber.py]
  - faster-whisper transcribes temp_audio.wav → temp_transcript.txt
  - On failure → error_handler.py popup, keep .wav, abort pipeline

[renamer.py]
  - Renames temp_audio.wav     → YYYY-MM-DD_HH-MM-SS_to_HH-MM-SS_audio.wav
  - Renames temp_transcript.txt → YYYY-MM-DD_HH-MM-SS_to_HH-MM-SS_transcript.txt

[summarizer.py]
  - Loads default_prompt from config.toml
  - Substitutes {transcript} with transcript content
  - If show_override_dialog = true → opens tkinter dialog pre-filled with prompt
    - User edits and confirms → proceed
    - User dismisses → skip summarization, pipeline ends
  - Calls: claude -p "<prompt>" --output-format text
  - Saves output → YYYY-MM-DD_HH-MM-SS_to_HH-MM-SS_summary.md
  - On failure → error_handler.py popup, transcript still preserved

[notifier.py]
  - Fires system notification: "Summary ready — <first 200 chars>"

[tray.py]
  - Icon returns to idle state
```

---

## File Naming Convention

All three output files share a timestamp prefix derived from the recording start and end times:

```
{output_folder}/
  2026-03-15_14-32-10_to_14-45-33_audio.wav
  2026-03-15_14-32-10_to_14-45-33_transcript.txt
  2026-03-15_14-32-10_to_14-45-33_summary.md
```

End time is captured at the moment the user clicks stop, before any processing begins.

---

## Configuration

`config.toml` is created at `~/.summarizeaudio/config.toml` on first run.

```toml
[storage]
output_folder = "~/AudioSummaries"

[whisper]
model = "base"        # tiny | base | small | medium | large
language = "en"       # set to "auto" for auto-detect

[summarization]
default_prompt = """
You are a helpful assistant. Summarize the following transcript concisely.
Highlight key decisions, action items, and important points.

Transcript:
{transcript}
"""

[behavior]
show_override_dialog = true    # show editable prompt dialog before every summarization
auto_open_summary = false      # open the .md file in default app after saving
```

---

## Tray Icon States

| State | Icon Appearance |
|---|---|
| Idle | Default grey/white icon |
| Recording | Red icon |
| Processing (transcribing / summarizing) | Amber/yellow icon |
| Error | Brief red flash → returns to idle after user dismisses popup |

---

## Error Handling

All pipeline errors present a `tkinter.messagebox.showerror` modal containing:
- **Component:** which module failed (e.g. `transcriber.py → faster_whisper`)
- **Error:** the exception message
- **Details:** truncated stack trace

| Scenario | Behaviour |
|---|---|
| `claude` CLI not found | Popup: "Claude Code CLI not found. Install it and ensure it's on your PATH." Transcript preserved. |
| Whisper model not yet downloaded | Auto-downloads silently on first run with amber icon + tray tooltip "Downloading model…" |
| Recording < 2 seconds | Discard file, tray notification "Recording too short — nothing saved." |
| Output folder missing | Auto-created on first run. |
| `claude -p` timeout / error | Popup with error detail. Transcript + audio preserved. |
| BlackHole not installed (macOS) | Fall back to mic-only, one-time tray notification with BlackHole setup link. |
| Whisper transcription failure | Popup with error detail. Raw `.wav` preserved. Rename + summarization skipped. |

---

## Threading Model

- **Main thread:** `pystray` icon event loop (required by pystray)
- **Recording thread:** `sounddevice` input stream callback (managed by sounddevice internally)
- **Pipeline thread:** single `threading.Thread` spawned when recording stops; runs transcribe → rename → summarize → notify sequentially

No shared mutable state between threads except a `threading.Event` stop flag for the recorder and the output file paths passed to the pipeline on start.

---

## Testing Strategy

| Layer | Approach |
|---|---|
| `config.py` | Unit tests — valid/invalid TOML, defaults, missing fields |
| `renamer.py` | Unit tests — verify filename format with known timestamps |
| `recorder.py` | Integration test — record 3s, verify `.wav` created with correct duration |
| `transcriber.py` | Integration test — transcribe a short known fixture audio clip, verify `.txt` output |
| `summarizer.py` | Integration test — mock `claude -p` subprocess, verify prompt construction and `.md` output |
| `notifier.py` | Smoke test — fire notification on each platform, verify no crash |
| `pipeline.py` | End-to-end test — run full pipeline with fixture `.wav`, verify all 3 output files produced |

CI matrix runs against macOS and Windows runners.

---

## Project Structure

```
SummarizeAudio/
├── summarizeaudio/
│   ├── __init__.py
│   ├── tray.py
│   ├── recorder.py
│   ├── pipeline.py
│   ├── transcriber.py
│   ├── renamer.py
│   ├── summarizer.py
│   ├── notifier.py
│   ├── error_handler.py
│   └── config.py
├── assets/
│   ├── icon_idle.png
│   ├── icon_idle.ico
│   ├── icon_recording.png
│   ├── icon_recording.ico
│   ├── icon_processing.png
│   └── icon_processing.ico
├── tests/
│   ├── test_config.py
│   ├── test_renamer.py
│   ├── test_recorder.py
│   ├── test_transcriber.py
│   ├── test_summarizer.py
│   ├── test_notifier.py
│   └── test_pipeline.py
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-03-15-audio-summarize-design.md
├── config.toml.example
├── requirements.txt
└── README.md
```
