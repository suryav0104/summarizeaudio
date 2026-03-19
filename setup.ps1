# SummarizeAudio one-time setup for Windows
# Run from the project directory in PowerShell:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\setup.ps1

$ErrorActionPreference = "Stop"

# ── Config ────────────────────────────────────────────────────────────────────
$OllamaModel = "devstral-small-2:24b"   # change this if you switch models
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Helpers ───────────────────────────────────────────────────────────────────
function Info    { param($msg) Write-Host "[setup] $msg" -ForegroundColor Cyan }
function Success { param($msg) Write-Host "[setup] OK $msg" -ForegroundColor Green }
function Warn    { param($msg) Write-Host "[setup] WARN $msg" -ForegroundColor Yellow }
function Die     { param($msg) Write-Host "[setup] ERROR $msg" -ForegroundColor Red; exit 1 }

function Refresh-Path {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
}

# ── Python ────────────────────────────────────────────────────────────────────
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Info "Python not found. Installing Python 3.12 via winget..."
    winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Refresh-Path
}

$pyVersion = python -c "import sys; print(sys.version_info[:2] >= (3,11))" 2>$null
if ($pyVersion -ne "True") {
    Die "Python 3.11+ required. Current: $(python --version). Install from https://python.org"
}
Success "Python $(python --version)"

# ── ffmpeg ────────────────────────────────────────────────────────────────────
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Info "Installing ffmpeg..."
    winget install ffmpeg --accept-source-agreements --accept-package-agreements
    Refresh-Path
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        Warn "ffmpeg installed but not yet in PATH. You may need to restart PowerShell."
        Warn "Recording will not work until ffmpeg is in PATH."
    } else {
        Success "ffmpeg installed"
    }
} else {
    Success "ffmpeg already installed"
}

# ── Ollama ────────────────────────────────────────────────────────────────────
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Info "Installing Ollama..."
    winget install Ollama.Ollama --accept-source-agreements --accept-package-agreements
    Refresh-Path
    # Give Windows installer a moment to register the service
    Start-Sleep -Seconds 3
    Success "Ollama installed"
} else {
    Success "Ollama already installed"
}

# Pull the model (skips if already present)
Info "Pulling model $OllamaModel (may take a while on first run)..."
ollama pull $OllamaModel
Success "Model $OllamaModel ready"

# ── Python environment ────────────────────────────────────────────────────────
Set-Location $ScriptDir

if (-not (Test-Path "venv")) {
    Info "Creating Python virtual environment..."
    python -m venv venv
}

Info "Installing SummarizeAudio and dependencies..."
& venv\Scripts\pip install -e . -q
Success "SummarizeAudio installed"

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  To run the app:"
Write-Host "    venv\Scripts\python -m summarizeaudio"
Write-Host ""
Write-Host "  Config file: $env:USERPROFILE\.summarizeaudio\config.toml"
Write-Host "  Log file:    $env:USERPROFILE\.summarizeaudio\app.log"
Write-Host "══════════════════════════════════════════" -ForegroundColor Green
