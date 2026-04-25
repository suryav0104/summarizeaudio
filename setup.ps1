# SummarizeAudio one-time setup for Windows
# Run from the folder containing this script in PowerShell:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\setup.ps1

$ErrorActionPreference = "Stop"

# ── Config ────────────────────────────────────────────────────────────────────
$AppName     = "SummarizeAudio"

# Detect RAM and pick an appropriate model
$RamBytes    = (Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum
$RamGB       = [math]::Floor($RamBytes / 1GB)
$OllamaModel = if ($RamGB -gt 8) { "gemma3:12b" } else { "gemma3:4b" }
$InstallDir  = "$env:LOCALAPPDATA\Programs\$AppName"
$OutputDir   = "$InstallDir\AudioSummaries"
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Helpers ───────────────────────────────────────────────────────────────────
function Info    { param($msg) Write-Host "[setup] $msg" -ForegroundColor Cyan }
function Success { param($msg) Write-Host "[setup] OK  $msg" -ForegroundColor Green }
function Warn    { param($msg) Write-Host "[setup] !   $msg" -ForegroundColor Yellow }
function Die     { param($msg) Write-Host "[setup] ERR $msg" -ForegroundColor Red; exit 1 }

function Refresh-Path {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
}

# ── Welcome ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  SummarizeAudio — Setup" -ForegroundColor White
Write-Host "  ──────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  This script will install:" -ForegroundColor Gray
Write-Host "    • Python 3.12 (if not present)" -ForegroundColor Gray
Write-Host "    • ffmpeg      (for audio recording)" -ForegroundColor Gray
Write-Host "    • Ollama      (local AI engine)" -ForegroundColor Gray
Write-Host "    • AI model    $OllamaModel" -ForegroundColor Gray
Write-Host "    • SummarizeAudio app → $InstallDir" -ForegroundColor Gray
Write-Host "  ──────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

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
        Warn "ffmpeg installed but not yet in PATH. Recording may not work until you restart your PC."
    } else {
        Success "ffmpeg installed"
    }
} else {
    Success "ffmpeg already installed"
}

# ── Ollama ────────────────────────────────────────────────────────────────────
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Info "Installing Ollama (local AI engine)..."
    winget install Ollama.Ollama --accept-source-agreements --accept-package-agreements
    Refresh-Path
    Start-Sleep -Seconds 3
    Success "Ollama installed"
} else {
    Success "Ollama already installed"
}

Info "Detected ${RamGB}GB RAM — using model: $OllamaModel"
Info "Downloading AI model '$OllamaModel' — this may take several minutes on first run..."
ollama pull $OllamaModel
Success "AI model $OllamaModel ready"

# ── Copy app to install dir ───────────────────────────────────────────────────
Info "Installing SummarizeAudio to $InstallDir ..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

$exclude = @("venv", "venv-win", "__pycache__", ".git", ".worktrees", "*.egg-info")
Get-ChildItem -Path $ScriptDir | Where-Object {
    $name = $_.Name
    -not ($exclude | Where-Object { $name -like $_ })
} | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $InstallDir -Recurse -Force
}
Success "App files installed"

# ── Output folder structure ───────────────────────────────────────────────────
foreach ($sub in @("AudioFiles", "TranscriptionFiles", "SummaryFiles")) {
    New-Item -ItemType Directory -Force -Path "$OutputDir\$sub" | Out-Null
}
Success "Output folders created"

# ── Python venv inside install dir ───────────────────────────────────────────
$VenvDir = "$InstallDir\venv"
if (-not (Test-Path $VenvDir)) {
    Info "Setting up Python environment..."
    python -m venv $VenvDir
}
& "$VenvDir\Scripts\pip" install -e $InstallDir -q
Success "Python environment ready"

# ── Write config ──────────────────────────────────────────────────────────────
$ConfigDir  = "$env:USERPROFILE\.summarizeaudio"
$ConfigFile = "$ConfigDir\config.toml"
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null

if (-not (Test-Path $ConfigFile)) {
    $OutputDirForward = $OutputDir -replace '\\', '/'
    @"
[storage]
output_folder = "$OutputDirForward"

[whisper]
model = "base"
language = "en"

[ollama]
host = "http://localhost:11434"
model = "$OllamaModel"

[summarization]
default_prompt = """You are a summarization engine. Output ONLY the summary — no preamble, no commentary about the transcript, no meta-remarks. Begin directly with the summary content.

Summarize the transcript below. Structure the output as:
- **Key Points:** the main ideas or topics covered
- **Decisions / Action Items:** anything decided or that requires follow-up (omit section if none)
- **Notable Details:** anything else worth remembering

Transcript:
{transcript}"""

[behavior]
show_override_dialog = true
auto_open_summary = false
"@ | Set-Content -Path $ConfigFile -Encoding UTF8
    Success "Config written"
} else {
    Info "Config already exists — leaving it unchanged"
}

# ── Launcher (.bat hides the console window via pythonw) ─────────────────────
$LauncherPath = "$InstallDir\SummarizeAudio.bat"
@"
@echo off
start "" "$VenvDir\Scripts\pythonw.exe" -m summarizeaudio
"@ | Set-Content -Path $LauncherPath -Encoding ASCII

# ── Desktop shortcut ──────────────────────────────────────────────────────────
$DesktopLink = "$env:USERPROFILE\Desktop\SummarizeAudio.lnk"
$Shell      = New-Object -ComObject WScript.Shell
$Shortcut   = $Shell.CreateShortcut($DesktopLink)
$Shortcut.TargetPath       = $LauncherPath
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description      = "SummarizeAudio — transcribe and summarize audio"
$IconPath = "$InstallDir\assets\icon_idle.ico"
if (Test-Path $IconPath) { $Shortcut.IconLocation = $IconPath }
$Shortcut.Save()
Success "Desktop shortcut created"

# ── Done — user instructions ──────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║              Setup complete!                             ║" -ForegroundColor Green
Write-Host "╠══════════════════════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "║                                                          ║"
Write-Host "║  HOW TO LAUNCH                                           ║"
Write-Host "║  Double-click the SummarizeAudio icon on your Desktop.   ║"
Write-Host "║  A small icon will appear in your system tray            ║"
Write-Host "║  (bottom-right corner — expand the ^ arrow if hidden).   ║"
Write-Host "║                                                          ║"
Write-Host "║  HOW TO USE                                              ║"
Write-Host "║  Click the tray icon to see options:                     ║"
Write-Host "║    • Record & Summarize   — record from microphone       ║"
Write-Host "║    • Transcribe Audio     — pick an existing audio file  ║"
Write-Host "║    • Summarize Text       — pick an existing text file   ║"
Write-Host "║                                                          ║"
Write-Host "║  WHERE YOUR FILES ARE SAVED                              ║"
Write-Host "║  $OutputDir" -ForegroundColor White
Write-Host "║    AudioFiles\         recorded audio (.mp3)             ║"
Write-Host "║    TranscriptionFiles\ transcripts (.txt)                ║"
Write-Host "║    SummaryFiles\       summaries (.md)                   ║"
Write-Host "║                                                          ║"
Write-Host "║  SETTINGS                                                ║"
Write-Host "║  Edit $ConfigFile" -ForegroundColor White
Write-Host "║  to change the AI model, language, or output folder.    ║"
Write-Host "║                                                          ║"
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
