# SummarizeAudio — Design Specification
**Date:** 2026-03-16
**Status:** Approved

---

## One-liner

A cross-platform (macOS + Windows) system tray app with three modes: record live audio, transcribe a local audio file, or summarize a local text file — all transcribed via local Whisper and summarized via a local Ollama model.

---

## Technology Stack

| Technology | Purpose |
|---|---|
| `Python 3.11+` | Primary language |
| `pystray` | Cross-platform system tray icon and menu |
| `sounddevice` | Cross-platform audio capture (wraps PortAudio); mic + system loopback |
| `numpy` | Audio chunk handling in sounddevice callbacks |
| `wave` (stdlib) | Incremental WAV file writing during recording (chunked, flushed every 30s) |
| `pydub` | WAV → MP3 conversion after recording stops |
| `ffmpeg` | **System dependency** (not pip) required by pydub for MP3 encoding; user installs once |
| `faster-whisper` | Local on-device speech-to-text transcription (no API cost, no internet) |
| `requests` | HTTP client for Ollama local API calls |
| `ollama` (Python pkg) | Optional higher-level Ollama client; `requests` used as fallback |
| `tomllib` / `tomli` | Parse `config.toml` configuration file |
| `tkinter` | Name dialog, override prompt dialog, file picker, error popups (stdlib; always dispatched via main-thread queue) |
| `plyer` | Windows desktop notifications (fallback: log-only) |
| `osascript` | macOS native notifications via AppleScript (fallback: `plyer`, then log-only) |
| `BlackHole` (macOS, user-installed) | Virtual audio device enabling system audio loopback capture |
| `Pillow` | Icon image handling for pystray |
| `pyproject.toml` | Project packaging, entry point declaration, dependency specification |

---

## Platform-Specific Behaviour

| Concern | macOS | Windows |
|---|---|---|
| System audio loopback | Requires **BlackHole** virtual device (one-time user install) | WASAPI loopback via `sounddevice` (built-in) |
| Tray icon format | `.png` | `.ico` |
| Notifications | `osascript` → `plyer` fallback → log-only | `plyer` → log-only fallback |
| Error popup dispatch | Via `ui_queue` to main thread → `tkinter.messagebox` | Via `ui_queue` to main thread → `tkinter.messagebox` |
| File picker | `tkinter.filedialog.askopenfilename` | `tkinter.filedialog.askopenfilename` |

If BlackHole is not installed on macOS, the app falls back to mic-only recording and notifies the user once with setup instructions.

---

## Tray Menu Items

| Menu Item | Behaviour |
|---|---|
| **Start Recording** | Begins live audio capture (icon turns red). Simultaneously opens name dialog (non-blocking). |
| **Stop Recording** _(visible during recording)_ | Stops capture, triggers pipeline. |
| **Transcribe & Summarize Audio File…** | Opens file picker (`.mp3 .wav .m4a .ogg .flac`), runs transcription + summarization pipeline on selected file. |
| **Summarize Text File…** | Opens file picker (`.txt .md`), runs summarization pipeline on selected file. |
| _(separator)_ | |
| **Processing…** _(disabled, amber icon)_ | Shown while pipeline is running. All other items disabled. |
| **Quit** | Exit app (cleans up lockfile). |

---

## Component Breakdown

| Component | File | Responsibility |
|---|---|---|
| Tray Manager | `tray.py` | Entry point. Owns `pystray` lifecycle, menu state, icon state, single-instance lockfile, and `ui_queue` drain loop. On startup: validates `output_folder` and all three subfolders exist, creating them if absent. |
| UI Dispatcher | `ui_dispatcher.py` | Thread-safe `queue.Queue` (`ui_queue`) + drain function. All tkinter calls from background threads go through here. |
| Recorder | `recorder.py` | Platform-aware audio capture. Opens mic + system loopback. Writes audio **incrementally** to a temp `.wav` on disk via chunked `wave` writes, flushing every 30 seconds. Converts `.wav` → `.mp3` via pydub on stop. Records start/end timestamps. Requires `output_folder` to already exist (created at startup). |
| Namer | `namer.py` | Posts a non-blocking name-input dialog to `ui_queue` immediately when recording starts. Returns the entered name (or default `Recording_MM-DD-YY`) when queried by the pipeline. |
| Pipeline Orchestrator | `pipeline.py` | Background thread entry point for all three modes. Routes to transcriber and/or summarizer depending on mode. Posts errors to `ui_queue`. Returns icon to idle on completion or error. |
| Transcriber | `transcriber.py` | Loads `faster-whisper` model (auto-downloads on first run with a system notification). Passes file path directly to faster-whisper without pre-conversion; relies on the same system `ffmpeg` dependency for all format decoding (.mp3/.wav/.m4a/.ogg/.flac). Outputs `.txt`. |
| Renamer | `renamer.py` | Moves temp files (Modes 1 & 2) or copies source text (Mode 3, never moves/deletes original) into `AudioFiles/`, `TranscriptionFiles/`, `SummaryFiles/` subfolders using the session name + `MM-DD-YY` format. Resolves filename collisions by appending `_2`, `_3`, etc. consistently across all three files in a session. |
| Summarizer | `summarizer.py` | Builds prompt from config + optional override, calls Ollama local API via `requests`, saves `.md` summary. |
| Notifier | `notifier.py` | Sends system notification on pipeline completion. Platform-specific fallback chain. |
| Error Handler | `error_handler.py` | Posts error popup requests to `ui_queue`. Main thread shows `tkinter.messagebox.showerror` with component, message, and stack trace. |
| Config Loader | `config.py` | Loads/validates `config.toml`. Creates default on first run. Invalid values → safe defaults. Missing required keys → error popup + exit. |

---

## Threading Model

```
Main thread (pystray event loop + ui_queue drain)
  │
  ├─ drains ui_queue every 100ms
  │    └─ executes: tkinter dialogs, error popups, name dialog, file pickers, icon state updates
  │
  ├─ on "Start Recording" click:
  │    ├─ posts name dialog to ui_queue (non-blocking — recording starts immediately)
  │    └─ starts Recorder
  │
  └─ on "Stop Recording" click:
       └─ stops Recorder, spawns Pipeline Thread
          (ignored if pipeline already running)

Recording stream thread (managed by sounddevice internally)
  └─ audio callback writes chunks → wave file on disk, flush every 30s

Name dialog (runs on main thread via ui_queue)
  └─ non-blocking: user types name while recording continues
  └─ result stored in threading-safe container, read by pipeline when it starts

Pipeline Thread (one at a time, guarded)
  └─ [mode: record]        transcriber → renamer → summarizer → notifier
  └─ [mode: local audio]   transcriber → renamer → summarizer → notifier
  └─ [mode: local text]    renamer → summarizer → notifier
       └─ posts ui_queue items for: error popups, override dialog, icon state
```

**Thread-safety rules:**
- `tkinter` is **never** called from the pipeline thread. All dialogs posted to `ui_queue`, executed on main thread.
- Icon state changes are posted to `ui_queue` from the pipeline thread.
- `ui_queue` uses `queue.Queue` (thread-safe FIFO).
- Override dialog: posts a `threading.Event` + result container to `ui_queue`; pipeline thread calls `event.wait(timeout=300)` — on timeout, treats as dismissal (no summary, transcript preserved).
- Name dialog result: stored in a `threading.Event` + string container; pipeline calls `name_event.wait(timeout=30)` — on timeout or dismissal, falls back to default name.

---

## Concurrency Guards

**Single-instance lockfile:**
On startup, writes a lockfile to `~/.summarizeaudio/app.lock` containing the process PID. If the file exists and the PID is alive, exits with notification "SummarizeAudio is already running." Lockfile removed on clean exit or on startup if stored PID is dead.

**Pipeline-running guard:**
`tray.py` holds a `pipeline_running: threading.Event`. While amber (processing), all tray menu actions except Quit are disabled. No new recording or file job can start until the pipeline completes.

---

## Data Flow

### Mode 1: Live Recording

```
[User clicks "Start Recording"]
  - pipeline_running? → if yes, ignore
  - Posts name dialog to ui_queue (non-blocking)
  - recorder.py starts:
      session_id = uuid4()
      Opens {output_folder}/{session_id}.wav for incremental writing
      sounddevice callback writes chunks, flushes every 30s

[User clicks "Stop Recording"]
  - end_time = datetime.now()
  - Closes .wav file
  - If duration < 2s → discard, notify "Too short", return to idle
  - Converts {session_id}.wav → {session_id}.mp3 via pydub/ffmpeg
  - Deletes {session_id}.wav
  - Calls name_event.wait(timeout=30) → uses entered name, or default "Recording_MM-DD-YY" on timeout/dismissal

[pipeline.py — background thread, pipeline_running set]
  ↓
[transcriber.py]
  - Transcribes {session_id}.mp3 → {session_id}.txt
  - On failure → error popup, keep .mp3, abort

[renamer.py]
  - Moves {session_id}.mp3 → AudioFiles/Audio_{name}_MM-DD-YY.mp3
  - Moves {session_id}.txt → TranscriptionFiles/Transcript_{name}_MM-DD-YY.txt

[summarizer.py]
  - Reads transcript, substitutes into prompt
  - If show_override_dialog = true → posts dialog to ui_queue, blocks on event
    - User confirms → proceed
    - User dismisses or event.wait(timeout=300) expires → skip summarization, icon → idle, transcript preserved
  - POST http://localhost:11434/api/generate  { model, prompt }
  - Saves → SummaryFiles/Summary - {name}_MM-DD-YY.md
  - On failure → error popup, transcript preserved

[notifier.py] → "Summary ready — <first 200 chars>"
[tray.py] → pipeline_running cleared, icon → idle
```

### Mode 2: Transcribe & Summarize Local Audio File

```
[User clicks "Transcribe & Summarize Audio File…"]
  - pipeline_running? → if yes, ignore (do not open file picker)
  - Posts file picker to ui_queue → user selects .mp3/.wav/.m4a/.ogg/.flac
  - Posts name dialog to ui_queue → default name = source filename stem + MM-DD-YY
    (e.g. meeting.mp3 → "meeting_03-16-26"); user may override
  - pipeline.py spawns background thread, pipeline_running set

[transcriber.py]
  - Passes selected file path directly to faster-whisper (no pre-conversion)
  - Relies on same system ffmpeg dependency for format decoding
  - Outputs → {session_id}.txt
  - On failure → error popup, abort

[renamer.py] → Transcript_{name}_MM-DD-YY.txt  (source audio file NOT moved/renamed)
[summarizer.py] → Summary - {name}_MM-DD-YY.md
[notifier.py] → notification
[tray.py] → pipeline_running cleared, icon → idle
```

### Mode 3: Summarize Local Text File

```
[User clicks "Summarize Text File…"]
  - pipeline_running? → if yes, ignore (do not open file picker)
  - Posts file picker to ui_queue → user selects .txt/.md
  - Posts name dialog to ui_queue → default name = source filename stem + MM-DD-YY
    (e.g. notes.txt → "notes_03-16-26"); user may override
  - pipeline.py spawns background thread, pipeline_running set

[renamer.py] → COPIES (does not move) source text → TranscriptionFiles/Transcript_{name}_MM-DD-YY.txt
               (original source file is never modified or deleted)
[summarizer.py] → Summary - {name}_MM-DD-YY.md
[notifier.py] → notification
[tray.py] → pipeline_running cleared, icon → idle
```

---

## File Naming Convention

All output files use the user-provided session name + today's date (`MM-DD-YY`), stored in dedicated subfolders:

```
~/AudioSummaries/
  AudioFiles/
    Audio_GTC Keynote_03-16-26.mp3           ← live recording only
  TranscriptionFiles/
    Transcript_GTC Keynote_03-16-26.txt
  SummaryFiles/
    Summary - GTC Keynote_03-16-26.md

  # Temp files during processing (in output root, auto-cleaned):
  3f2a1b4c-....mp3
  3f2a1b4c-....txt
```

**Default names** (if user dismisses dialog or timeout expires):
- Mode 1 (live recording): `Recording_MM-DD-YY`
- Mode 2 (local audio file): source filename stem + `_MM-DD-YY` (e.g. `meeting_03-16-26`)
- Mode 3 (local text file): source filename stem + `_MM-DD-YY` (e.g. `notes_03-16-26`)

**Duplicate filename collision:** If a file with the same name already exists in the target subfolder, `renamer.py` appends an incrementing counter: `_2`, `_3`, etc. The counter is applied consistently across all three files in the same session (audio, transcript, summary) so they remain correlated.

For modes 2 and 3, the source file is **never moved, renamed, or modified** — only transcript and summary outputs are saved to the subfolders.

---

## Configuration

`config.toml` is created at `~/.summarizeaudio/config.toml` on first run.

```toml
[storage]
output_folder = "~/AudioSummaries"
# Subfolders auto-created: AudioFiles/, TranscriptionFiles/, SummaryFiles/

[whisper]
model = "base"      # tiny | base | small | medium | large
language = "en"     # set to "auto" for auto-detect

[ollama]
host = "http://localhost:11434"
model = "mistral-small3.2:24b"

[summarization]
default_prompt = """
You are a helpful assistant. Summarize the following transcript concisely.
Highlight key decisions, action items, and important points.

Transcript:
{transcript}
"""

[behavior]
show_override_dialog = true   # show editable prompt dialog before every summarization
auto_open_summary = false     # open the .md file in default app after saving
```

**Config validation behaviour:**
- Invalid enum values (e.g. `model = "huge"`): log warning, substitute safe default, continue.
- Missing required key (e.g. `output_folder` absent): error popup via `ui_queue`, exit app.
- Malformed TOML: error popup, exit app.

---

## Tray Icon States

| State | Icon Asset | Tray behaviour |
|---|---|---|
| Idle | `icon_idle` (grey/white) | Full menu available |
| Recording | `icon_recording` (red) | Only "Stop Recording" and "Quit" active |
| Processing | `icon_processing` (amber) | Only "Quit" active; all others disabled |
| Error | `icon_error` (red, distinct from recording) | Returns to idle after user dismisses popup |

---

## Error Handling

All pipeline errors shown as `tkinter.messagebox.showerror` via `ui_queue` containing:
- **Component:** e.g. `transcriber.py → faster_whisper`
- **Error:** exception message
- **Details:** last 10 lines of stack trace

After dismissal, icon returns to idle and `pipeline_running` is cleared.

| Scenario | Behaviour |
|---|---|
| `ffmpeg` not installed | Error popup with install instructions (`brew install ffmpeg` / `choco install ffmpeg`). Recording discarded. |
| Ollama not running / unreachable | Error popup: "Ollama not found at {host}. Start Ollama and try again." Transcript preserved. |
| Ollama model not pulled | Error popup: "Model {model} not found. Run: ollama pull {model}". Transcript preserved. |
| Whisper model not downloaded | Auto-downloads on first run; fires system notification "Downloading Whisper model, this may take a few minutes…" at start, and a second notification on completion or failure. On download failure: error popup, abort. |
| Recording < 2 seconds | Discard file, notification "Recording too short." Return to idle. |
| Output folder / subfolder missing | Auto-created on first run. |
| Whisper transcription failure | Error popup. `.mp3` preserved. Summarization skipped. |
| Override dialog dismissed | No popup. Transcript + audio preserved. Silent idle return. |
| Config invalid value | Warning logged, safe default used, app continues. |
| Config missing required key | Error popup, app exits. |
| Second instance launched | Exit with notification "SummarizeAudio is already running." |
| App crash during recording | Partial `.wav` preserved on disk in `output_folder` (up to last 30s flush). User can manually transcribe it via "Transcribe & Summarize Audio File…" menu option. |

---

## Notification Fallback Chain

| Platform | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|
| macOS | `osascript` AppleScript | `plyer` | Log to `~/.summarizeaudio/app.log` |
| Windows | `plyer` | Log to `~/.summarizeaudio/app.log` | — |

---

## Testing Strategy

| Layer | Approach |
|---|---|
| `config.py` | Unit — valid/invalid TOML, defaults, missing fields, invalid enum values |
| `renamer.py` | Unit — verify name+date filename format, subfolder placement |
| `namer.py` | Unit — default name fallback when dialog dismissed; correct date format |
| `ui_dispatcher.py` | Unit — post items, verify drain calls correct handler |
| `recorder.py` | Integration — record 3s, verify `.mp3` in output root, `.wav` deleted, incremental flush creates partial file if stopped mid-write |
| `transcriber.py` | Integration — transcribe short fixture audio, verify `.txt` output |
| `summarizer.py` | Integration — mock Ollama HTTP endpoint, verify prompt construction and `.md` output |
| `notifier.py` | Smoke — fire notification on each platform, verify no crash |
| `pipeline.py` (mode 1) | End-to-end — fixture `.mp3` through full pipeline, verify 3 output files in correct subfolders |
| `pipeline.py` (mode 1) | Edge case — recording < 2s: verify files discarded, notification sent, icon returns to idle |
| `pipeline.py` (mode 1/2) | Edge case — override dialog dismissed: verify no summary file, no error popup, icon returns to idle, transcript preserved |
| `pipeline.py` (mode 1) | Edge case — override dialog timeout (300s): verify same behaviour as dismissal |
| `pipeline.py` (mode 1) | Edge case — duplicate session name: verify `_2` suffix applied consistently across all 3 output files |
| `pipeline.py` (mode 2) | End-to-end — local audio file through pipeline, verify transcript + summary; source file untouched |
| `pipeline.py` (mode 3) | End-to-end — local text file through pipeline, verify summary only; source file untouched |
| `renamer.py` | Unit — collision resolution: same name twice produces `_name_MM-DD-YY.ext` and `_name_MM-DD-YY_2.ext` |
| `tray.py` concurrency | Unit — pipeline_running guard: Mode 2/3 menu clicks ignored while pipeline active |

CI matrix runs against macOS and Windows runners.

---

## Project Structure

```
SummarizeAudio/
├── summarizeaudio/
│   ├── __init__.py
│   ├── __main__.py          # entry point: python -m summarizeaudio
│   ├── tray.py
│   ├── recorder.py
│   ├── namer.py
│   ├── pipeline.py
│   ├── transcriber.py
│   ├── renamer.py
│   ├── summarizer.py
│   ├── notifier.py
│   ├── error_handler.py
│   ├── ui_dispatcher.py
│   └── config.py
├── assets/
│   ├── icon_idle.png / .ico
│   ├── icon_recording.png / .ico
│   ├── icon_processing.png / .ico
│   └── icon_error.png / .ico
├── tests/
│   ├── test_config.py
│   ├── test_renamer.py
│   ├── test_namer.py
│   ├── test_ui_dispatcher.py
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
├── pyproject.toml
└── README.md
```

**Entry point** (`pyproject.toml`):
```toml
[project.scripts]
summarizeaudio = "summarizeaudio.__main__:main"
```

Launch with: `python -m summarizeaudio` or `summarizeaudio` (after `pip install -e .`)
