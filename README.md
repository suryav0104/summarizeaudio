# SummarizeAudio

A macOS menu bar app that records conversations or transcribes audio files, then summarises the result using a local AI model — no data leaves your machine.

---

## What it does

- **Record & Summarize** — records from your microphone (or an audio input device you configure), transcribes the audio, and generates a structured summary
- **Transcribe Audio** — pick any `.mp3`, `.wav`, `.m4a`, `.ogg`, or `.flac` file and get a transcript + summary
- **Summarize Text** — feed an existing transcript `.txt` or `.md` file directly to the AI for a summary

All files are saved inside the app folder under `AudioSummaries/`, in three subfolders: `AudioFiles/`, `TranscriptionFiles/`, and `SummaryFiles/`.

---

## Requirements

- macOS (Apple Silicon or Intel)
- Python 3.11+
- [Homebrew](https://brew.sh) (for automatic ffmpeg and BlackHole install)
- *Optional, for speaker diarization:* a [HuggingFace](https://huggingface.co) account + token and the `pyannote.audio` extra (see [Speaker diarization](#speaker-diarization-optional))

---

## Install

Run this single command in Terminal — it installs everything automatically:

```bash
curl -fsSL https://raw.githubusercontent.com/suryav0104/summarizeaudio/main/setup.sh | bash
```

What the installer does:
1. Installs **BlackHole 2ch** (virtual audio driver, needed to capture system audio)
2. Installs **ffmpeg** via Homebrew (audio encoding)
3. Installs **Ollama** (local AI server)
4. Downloads the recommended **gemma3:4b** or **gemma3:12b** AI model based on available RAM
5. Creates a Python virtual environment and installs the app
6. Writes a default config to `~/.summarizeaudio/config.toml`

If you already cloned the repo, you can run the script directly instead:

```bash
bash setup.sh
```

### Updating to the latest version

Re-running the installer pulls the newest code and re-resolves every dependency from `pyproject.toml`, so a single command keeps an existing install current:

```bash
curl -fsSL https://raw.githubusercontent.com/suryav0104/summarizeaudio/main/setup.sh | bash
```

(From a local clone, `git pull` then `bash setup.sh`.)

### Optional: speaker diarization

To install with speaker labelling enabled, set the opt-in flag. This adds `pyannote.audio` and pulls PyTorch (a large download), so it is off by default:

```bash
curl -fsSL https://raw.githubusercontent.com/suryav0104/summarizeaudio/main/setup.sh | SUMMARIZEAUDIO_DIARIZATION=1 bash
# or from a clone:
SUMMARIZEAUDIO_DIARIZATION=1 bash setup.sh
```

The installer also needs a HuggingFace token before diarization actually runs — see [Speaker diarization](#speaker-diarization-optional) below.

---

## Launch

```bash
~/Applications/SummarizeAudio/venv/bin/python -m summarizeaudio
```

Or add a permanent alias to your shell profile (`~/.zshrc` or `~/.bash_profile`):

```bash
alias summarizeaudio='~/Applications/SummarizeAudio/venv/bin/python -m summarizeaudio'
```

Then just type `summarizeaudio` in any new terminal window.

---

## The menu bar icon

After launching, a small round icon appears in the **top-right corner of your Mac's menu bar** (next to the clock and Wi-Fi). It looks like a speech-bubble or audio waveform symbol.

Click it to reveal the menu:

| Menu item | What it does |
|---|---|
| Record & Summarize | Starts recording from your configured input device. Click again to stop and process. |
| Transcribe Audio | Opens a file picker — choose an audio file to transcribe and summarize. |
| Summarize Text | Opens a file picker — choose a `.txt` or `.md` transcript to summarize. |
| History | Browse and reopen past sessions (recording, transcript, summary). |
| Input  →  *device* | Shows the current recording input. Click to open Settings on the input picker. |
| Model  →  *name* | Shows the current summarization model. Click to open Settings on the model picker. |
| Settings | Change the recording input and summarization model, then Apply. |
| Quit | Closes the app and removes the icon from the menu bar. |

While the app is working (transcribing or summarizing), the icon changes to indicate it is busy. When the summary is ready, a notification appears and the `.md` file opens automatically (if `auto_open_summary = true` in config).

---

## Recording live conversations (voice + system audio)

To capture both your microphone and audio playing through your speakers (e.g. a call or meeting), you need to set up an **Aggregate Device** in macOS:

1. Open **Audio MIDI Setup** (in `/Applications/Utilities/`)
2. Click **+** at the bottom left and choose **Create Aggregate Device**
3. Tick both **BlackHole 2ch** and your microphone in the list
4. Set the **Clock Source** to your microphone (not BlackHole)
5. Note the name of the device (e.g. "Aggregate Device")
6. Edit `~/.summarizeaudio/config.toml` and add:

```toml
[recording]
input_device = "Aggregate Device"
```

---

## Speaker diarization (optional)

Diarization labels each part of the transcript by speaker (`Speaker 1:`, `Speaker 2:`, …) instead of producing one undifferentiated block of text. It is **off by default** and only activates when **all three** of these are in place:

1. **The `pyannote.audio` extra is installed** (adds PyTorch — a multi-hundred-MB download).
2. **A HuggingFace access token is set** in the environment.
3. **The toggle is enabled** in the app's Settings window.

The first two are *capability* (can the machine do it?); the third is *preference* (do you want it?). The tray shows the current state as `Diarization → On / Off / Unavailable`, and you can finish the whole setup from inside the app — see [Enabling from the app](#4-enable-it-in-the-app) below.

### 1. Install the extra

If you used `SUMMARIZEAUDIO_DIARIZATION=1` during setup, this is already done. Otherwise, run it from your install directory:

```bash
cd ~/Applications/SummarizeAudio
venv/bin/pip install -e '.[diarization]'
```

### 2. Get a HuggingFace token and accept the model terms

1. Create a free account at [huggingface.co](https://huggingface.co), then a **read** token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
2. While logged in, accept the user conditions on **both** gated models (the pipeline depends on the segmentation model internally):
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)

If you skip the second model, the pipeline fails to load even though the token is valid.

### 3. Provide the token

The app reads `HUGGINGFACE_ACCESS_TOKEN` from a `.env` file in the install directory (loaded automatically at launch). Create or edit `~/Applications/SummarizeAudio/.env`:

```bash
HUGGINGFACE_ACCESS_TOKEN=hf_your_token_here
```

The `SUMMARIZEAUDIO_DIARIZATION=1` installer scaffolds this file with the token line **commented out**, so the app does not mistake the placeholder for a real token. Uncomment the line and paste your token, then restart the app (or use **Re-check** in Settings — see below).

### 4. Enable it in the app

Open **Settings** from the tray (or click the `Diarization → …` status item). The row is headed **Speaker Diarization (Label speakers in transcripts)**. When the capability is in place, you'll see an **On / Off** dropdown — set it to **On** and click **Apply**. When pyannote or the token is still missing, the same row shows **Unavailable** with a **How to enable** link that expands the same step-by-step instructions shown here, plus a **Re-check** button that re-reads `.env` so you don't have to relaunch after pasting a token.

### Notes

- The first diarized run downloads the pyannote model weights to your HuggingFace cache (`~/.cache/huggingface` by default).
- Diarization adds roughly **1.5 GB** of RAM on top of Whisper and the Ollama model; the app warns at startup if total RAM looks tight.
- No token and no extra → the app transcribes normally, just without speaker labels. The workflow skips the "Diarize" step entirely rather than failing partway through.

---

## Launch at login (optional)

To have SummarizeAudio start automatically when you log in, open **Settings** from the menu-bar icon, set **Launch at Login** to **On**, then click **Apply**. It takes effect at your next login.

You can also enable it during install with an opt-in flag:

```bash
curl -fsSL https://raw.githubusercontent.com/suryav0104/summarizeaudio/main/setup.sh | SUMMARIZEAUDIO_AUTOSTART=1 bash
# or from a clone:
SUMMARIZEAUDIO_AUTOSTART=1 bash setup.sh
```

Under the hood this writes a macOS LaunchAgent at `~/Library/LaunchAgents/com.summarizeaudio.plist`. Setting the toggle to **Off** (or deleting that file) disables it. macOS only.

---

## Configuration

The config file is at `~/.summarizeaudio/config.toml`. Key options:

```toml
[ollama]
model = "gemma3:4b"       # AI model to use; the tray menu can switch between 4b and 12b

[whisper]
model = "base"            # Whisper model size: tiny, base, small, medium, large
language = "en"           # Transcription language

[behavior]
show_override_dialog = true   # Show a prompt editor before sending to AI
auto_open_summary = false     # Auto-open the summary .md file when done

[recording]
input_device = ""         # Leave blank for default mic, or set to device name
```

---

## File locations

| Path | Contents |
|---|---|
| `~/Applications/SummarizeAudio/AudioSummaries/AudioFiles/` | Recorded `.mp3` files |
| `~/Applications/SummarizeAudio/AudioSummaries/TranscriptionFiles/` | Transcript `.txt` files |
| `~/Applications/SummarizeAudio/AudioSummaries/SummaryFiles/` | Summary `.md` files |
| `~/.summarizeaudio/config.toml` | App configuration |
| `~/.summarizeaudio/app.log` | Log file for debugging |
