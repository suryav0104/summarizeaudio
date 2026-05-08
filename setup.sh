#!/usr/bin/env bash
# SummarizeAudio one-time setup for macOS
#
# Usage:
#   From a local clone:  bash setup.sh
#   One-command install: curl -fsSL https://raw.githubusercontent.com/suryav0104/summarizeaudio/main/setup.sh | bash

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
INSTALL_DIR="$HOME/Applications/SummarizeAudio"
REPO_URL="https://github.com/suryav0104/summarizeaudio.git"

select_model_for_ram() {
    local ram_bytes
    if [[ "$(uname)" == "Darwin" ]]; then
        ram_bytes="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
    else
        ram_bytes=0
    fi

    if [[ "$ram_bytes" =~ ^[0-9]+$ ]] && [[ "$ram_bytes" -gt $((8 * 1024 * 1024 * 1024)) ]]; then
        echo "gemma3:12b"
    else
        echo "gemma3:4b"
    fi
}

OLLAMA_MODEL="$(select_model_for_ram)"

# Detect whether we're running via curl-pipe (no BASH_SOURCE) or local clone
if [[ -z "${BASH_SOURCE[0]:-}" || "${BASH_SOURCE[0]}" == "bash" ]]; then
    # curl | bash — clone the repo first
    RUNNING_VIA_CURL=1
    SCRIPT_DIR="$INSTALL_DIR"
else
    RUNNING_VIA_CURL=0
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

# ── Helpers ───────────────────────────────────────────────────────────────────
info()    { echo "[setup] $*"; }
success() { echo "[setup] ✓ $*"; }
warn()    { echo "[setup] ⚠ $*"; }
die()     { echo "[setup] ✗ $*" >&2; exit 1; }

# ── Clone repo (curl-pipe mode only) ─────────────────────────────────────────
if [[ "$RUNNING_VIA_CURL" -eq 1 ]]; then
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        info "Updating existing install at $INSTALL_DIR..."
        git -C "$INSTALL_DIR" pull --ff-only
    else
        info "Cloning SummarizeAudio to $INSTALL_DIR..."
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
    success "Repo ready at $INSTALL_DIR"
fi

# ── Python ────────────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    die "Python 3 not found. Install from https://python.org/downloads then re-run."
fi

PYTHON_VERSION=$(python3 -c "import sys; print(sys.version_info[:2] >= (3,11))")
if [[ "$PYTHON_VERSION" != "True" ]]; then
    die "Python 3.11+ required. Current: $(python3 --version)"
fi
success "Python $(python3 --version)"

# ── BlackHole (virtual audio driver for system audio capture) ────────────────
if [[ "$(uname)" == "Darwin" ]]; then
    if ! system_profiler SPAudioDataType 2>/dev/null | grep -q "BlackHole"; then
        if command -v brew &>/dev/null; then
            info "Installing BlackHole 2ch (virtual audio driver)..."
            brew install --cask blackhole-2ch
            success "BlackHole 2ch installed"
            warn "ACTION REQUIRED: Open 'Audio MIDI Setup' (in /Applications/Utilities) and"
            warn "create an Aggregate Device combining 'BlackHole 2ch' and your microphone."
            warn "Then set that Aggregate Device as the input in ~/.summarizeaudio/config.toml:"
            warn "  [recording]"
            warn "  input_device = \"<your aggregate device name>\""
        else
            warn "BlackHole not found and Homebrew not available."
            warn "Install Homebrew first (https://brew.sh), then re-run to get BlackHole."
            warn "Without BlackHole, system audio (other party) will not be captured."
        fi
    else
        success "BlackHole already installed"
    fi
fi

# ── ffmpeg ────────────────────────────────────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    if command -v brew &>/dev/null; then
        info "Installing ffmpeg via Homebrew..."
        brew install ffmpeg
    else
        warn "ffmpeg not found and Homebrew not available."
        warn "Install Homebrew first: https://brew.sh, then re-run."
        warn "Or install ffmpeg manually: https://ffmpeg.org/download.html"
        warn "Recording will not work without ffmpeg — continuing anyway."
    fi
else
    success "ffmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
fi

# ── Ollama ────────────────────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    success "Ollama installed"
else
    success "Ollama $(ollama --version 2>/dev/null | head -1)"
fi

# Start Ollama server if not already running
if ! pgrep -x ollama &>/dev/null; then
    info "Starting Ollama server in background..."
    ollama serve &>/dev/null &
    sleep 3
fi

# Pull the model (skips if already present)
info "Pulling model $OLLAMA_MODEL (may take a while on first run)..."
ollama pull "$OLLAMA_MODEL"
success "Model $OLLAMA_MODEL ready"

# ── Python environment ────────────────────────────────────────────────────────
cd "$SCRIPT_DIR"

if [[ ! -d venv ]]; then
    info "Creating Python virtual environment..."
    python3 -m venv venv
fi

info "Installing SummarizeAudio and dependencies..."
venv/bin/pip install -e . -q
success "SummarizeAudio installed"

# ── Write config if not already present ──────────────────────────────────────
CONFIG_DIR="$HOME/.summarizeaudio"
CONFIG_FILE="$CONFIG_DIR/config.toml"
mkdir -p "$CONFIG_DIR"

if [[ ! -f "$CONFIG_FILE" ]]; then
    info "Writing config..."
    cat > "$CONFIG_FILE" << TOML
[storage]
output_folder = "$SCRIPT_DIR/AudioSummaries"

[whisper]
model = "base"
language = "en"

[ollama]
host = "http://localhost:11434"
model = "$OLLAMA_MODEL"

[summarization]
default_prompt = """You are a precise meeting-note summarizer.
Output markdown only. Do not add an introduction, conclusion, apology, or commentary outside the sections below.

Use only facts stated in the transcript. Do not invent details, infer intent, or restate the same point in multiple sections.
Prefer short, specific bullets over paragraphs. If a section has nothing useful to add, omit that section.

Section guidance:
- **Key Points:** 3-6 bullets covering the main topics, themes, and outcomes.
- **Decisions / Action Items:** every decision, owner, deadline, and follow-up.
- **Notable Details:** only concrete supporting details that matter later, such as risks, blockers, dates, or clarifications.

Transcript:
{transcript}"""

[behavior]
show_override_dialog = true
auto_open_summary = false

[recording]
# Leave blank to auto-detect BlackHole (macOS) or WASAPI loopback (Windows).
# Set to an exact device name to override, e.g. "Voice + System Audio" for an Aggregate Device.
input_device = ""
TOML
    success "Config written to $CONFIG_FILE"
else
    info "Config already exists — leaving it unchanged"
fi

# ── Done — user instructions ──────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  HOW TO LAUNCH"
echo "  Run this command to start the app:"
echo "    $SCRIPT_DIR/venv/bin/python -m summarizeaudio"
echo ""
echo "  TIP: Add an alias to your shell profile:"
echo "    alias summarizeaudio='$SCRIPT_DIR/venv/bin/python -m summarizeaudio'"
echo "  A small icon will appear in your macOS menu bar (top-right)."
echo ""
echo "  HOW TO USE"
echo "  Click the menu bar icon to see options:"
echo "    • Record & Summarize  — record from microphone"
echo "    • Transcribe Audio    — pick an existing audio file"
echo "    • Summarize Text      — pick an existing text file (.txt or .md)"
echo ""
echo "  WHERE YOUR FILES ARE SAVED"
echo "    $SCRIPT_DIR/AudioSummaries/"
echo "      AudioFiles/          recorded audio (.mp3)"
echo "      TranscriptionFiles/  transcripts (.txt)"
echo "      SummaryFiles/        summaries (.md)"
echo ""
echo "  SETTINGS"
echo "    Edit $CONFIG_FILE"
echo "    to change the AI model, language, or output folder."
echo "══════════════════════════════════════════════════════════"
