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

# Opt-in speaker diarization (heavy: pulls pyannote.audio + torch/torchaudio).
# Enable with:  SUMMARIZEAUDIO_DIARIZATION=1 bash setup.sh
#          or:  curl -fsSL .../setup.sh | SUMMARIZEAUDIO_DIARIZATION=1 bash
INSTALL_DIARIZATION="${SUMMARIZEAUDIO_DIARIZATION:-0}"

# Opt-in launch-at-login. Enable with: SUMMARIZEAUDIO_AUTOSTART=1 bash setup.sh
INSTALL_AUTOSTART="${SUMMARIZEAUDIO_AUTOSTART:-0}"

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

# True only if .env has an UNCOMMENTED HUGGINGFACE_ACCESS_TOKEN set to a real
# (non-placeholder, non-empty) value. Keeps the config "enabled" flag honest.
real_hf_token_present() {
    local env_file="$1"
    [[ -f "$env_file" ]] || return 1
    grep -E '^[[:space:]]*HUGGINGFACE_ACCESS_TOKEN=' "$env_file" 2>/dev/null \
        | grep -vqE '=(hf_replace_me|hf_your_token_here)?[[:space:]]*$'
}

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

venv/bin/pip install --upgrade pip -q

if [[ "$INSTALL_DIARIZATION" == "1" ]]; then
    info "Installing SummarizeAudio with diarization extra (pyannote.audio + torch — large download)..."
    venv/bin/pip install -e '.[diarization]' -q
    success "SummarizeAudio installed (with diarization)"
else
    info "Installing SummarizeAudio and dependencies..."
    venv/bin/pip install -e . -q
    success "SummarizeAudio installed"
fi

# Launch at login (opt-in)
if [[ "$INSTALL_AUTOSTART" == "1" ]]; then
    info "Enabling launch at login..."
    venv/bin/python -c "from summarizeaudio import startup; startup.enable()"
    success "Launch at login enabled (starts at next login)"
fi

# ── Write config if not already present ──────────────────────────────────────
CONFIG_DIR="$HOME/.summarizeaudio"
CONFIG_FILE="$CONFIG_DIR/config.toml"
mkdir -p "$CONFIG_DIR"

# ── Diarization .env scaffold (opt-in) ───────────────────────────────────────
if [[ "$INSTALL_DIARIZATION" == "1" ]]; then
    ENV_FILE="$SCRIPT_DIR/.env"
    if [[ ! -f "$ENV_FILE" ]]; then
        info "Scaffolding $ENV_FILE for the HuggingFace token..."
        cat > "$ENV_FILE" << 'ENV'
# Speaker diarization is enabled when this token is set and pyannote.audio is installed.
# 1. Create a HuggingFace account and a READ access token: https://huggingface.co/settings/tokens
# 2. Accept the user conditions on BOTH gated models (logged in):
#      https://huggingface.co/pyannote/speaker-diarization-3.1
#      https://huggingface.co/pyannote/segmentation-3.0
# 3. Uncomment the line below and paste your token, then relaunch the app.
#HUGGINGFACE_ACCESS_TOKEN=hf_your_token_here
ENV
        warn "Diarization needs a HuggingFace token. Edit $ENV_FILE and:"
        warn "  • create a READ token at https://huggingface.co/settings/tokens"
        warn "  • accept terms on pyannote/speaker-diarization-3.1 AND pyannote/segmentation-3.0"
        warn "  • replace hf_replace_me with your token, then relaunch."
    else
        success ".env already present — leaving HUGGINGFACE_ACCESS_TOKEN unchanged"
    fi
fi

# Preference flag written to config: on only when the extra is installed AND a
# real token already exists. A fresh scaffold has no real token, so this stays
# false until the user pastes one and toggles it on (Settings or .env + re-check).
DIARIZATION_ENABLED="false"
if [[ "$INSTALL_DIARIZATION" == "1" ]] && real_hf_token_present "$SCRIPT_DIR/.env"; then
    DIARIZATION_ENABLED="true"
fi

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

[diarization]
# Speaker labelling. This is your PREFERENCE; it only takes effect when
# pyannote.audio is installed AND a HuggingFace token is set (see .env).
# Toggle it from the app's Settings window.
enabled = $DIARIZATION_ENABLED

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
echo ""
echo "  LAUNCH AT LOGIN"
if [[ "$INSTALL_AUTOSTART" == "1" ]]; then
echo "    Enabled. The app will start automatically at your next login."
else
echo "    Off. Turn it on anytime from the app's Settings window."
fi
if [[ "$INSTALL_DIARIZATION" == "1" ]]; then
echo ""
echo "  DIARIZATION (speaker labelling) — finish these steps to enable:"
venv/bin/python -c "from summarizeaudio import diarization; print(diarization.render_setup_steps('terminal'))"
fi
echo "══════════════════════════════════════════════════════════"
