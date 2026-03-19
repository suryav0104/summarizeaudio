#!/usr/bin/env bash
# SummarizeAudio one-time setup for macOS
# Run from the project directory: bash setup.sh

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_MODEL="devstral-small-2:24b"   # change this if you switch models
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Helpers ───────────────────────────────────────────────────────────────────
info()    { echo "[setup] $*"; }
success() { echo "[setup] ✓ $*"; }
warn()    { echo "[setup] ⚠ $*"; }
die()     { echo "[setup] ✗ $*" >&2; exit 1; }

# ── Python ────────────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    die "Python 3 not found. Install from https://python.org/downloads then re-run."
fi

PYTHON_VERSION=$(python3 -c "import sys; print(sys.version_info[:2] >= (3,11))")
if [[ "$PYTHON_VERSION" != "True" ]]; then
    die "Python 3.11+ required. Current: $(python3 --version)"
fi
success "Python $(python3 --version)"

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

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  To run the app:"
echo "    venv/bin/python -m summarizeaudio"
echo ""
echo "  Config file: ~/.summarizeaudio/config.toml"
echo "  Log file:    ~/.summarizeaudio/app.log"
echo "══════════════════════════════════════════"
