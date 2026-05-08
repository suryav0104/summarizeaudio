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
| Use Fast Model | Switches summarization to the faster `gemma3:4b` model. |
| Use High Quality Model | Switches summarization to the stronger `gemma3:12b` model. |
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
