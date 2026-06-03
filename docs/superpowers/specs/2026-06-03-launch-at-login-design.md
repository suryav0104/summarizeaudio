# Launch at Login — Design

Date: 2026-06-03
Status: Approved (design phase)

## Summary

Add a "Launch at Login" preference to SummarizeAudio so the menu-bar app starts
automatically when the user logs in to macOS. The user controls it from the
Settings window (an On/Off dropdown consistent with the existing Input / Model /
Diarization rows), and the first-time installer can pre-enable it via an opt-in
environment variable.

The mechanism is a macOS **LaunchAgent plist**. The plist's presence on disk is
the single source of truth — there is no mirrored flag in `config.toml`. The
agent uses `RunAtLoad=true`, so launchd starts the app at the next login. The
effect is observed at the next login; the app does not relaunch itself in the
current session.

Scope is **macOS only**. On other platforms the feature is hidden and all
operations are no-ops.

## Goals

- A persistent "Launch at Login" On/Off control in Settings.
- Toggling it writes/removes the LaunchAgent plist immediately (durable the
  moment the user clicks Apply).
- A login-launched run must actually work end to end (find `ffmpeg`/`ollama`,
  load `.env`).
- First-time installer can enable it via an opt-in env var, consistent with the
  existing `SUMMARIZEAUDIO_DIARIZATION=1` pattern.

## Non-goals

- No instant launchd registration in the current session (no `launchctl
  bootstrap`/`bootout`). Rejected during brainstorming because bootstrapping a
  `RunAtLoad=true` agent would immediately spawn a second instance, forcing a
  single-instance guard for negligible benefit (the app is already running).
- No single-instance guard.
- No Windows / Linux startup support.
- No mirrored `config.toml` field (avoids drift with the plist).

## Architecture

### New module: `summarizeaudio/startup.py`

Single source of truth for *whether* launch-at-login is on and *how* the plist
is shaped. Pure file I/O; no subprocess. Mirrors the isolation style of
`diarization.py`.

```
LABEL = "com.summarizeaudio"

def is_supported() -> bool:
    """True only on macOS. Gates the whole feature."""
    return sys.platform == "darwin"

def plist_path() -> Path:
    """~/Library/LaunchAgents/com.summarizeaudio.plist"""

def is_enabled() -> bool:
    """True when the LaunchAgent plist exists on disk."""

def enable() -> None:
    """Write the LaunchAgent plist (creating ~/Library/LaunchAgents if needed)."""

def disable() -> None:
    """Remove the LaunchAgent plist if present (idempotent)."""

def _plist_contents() -> str:
    """Build the plist XML (see below)."""
```

`is_enabled()` / `enable()` / `disable()` are safe to call on any platform but
only meaningful on macOS; callers gate on `is_supported()` for UI visibility.
`disable()` is idempotent (no error if the file is already gone).

### The plist

Built from runtime values so it never hard-codes an install path:

- `Label` = `com.summarizeaudio`
- `ProgramArguments` = `[sys.executable, "-m", "summarizeaudio"]`
  (`sys.executable` is the venv's python, already absolute)
- `WorkingDirectory` = `str(Path(sys.executable).parent.parent)`
  (the install dir, so `load_dotenv()` finds `.env`)
- `RunAtLoad` = `true`
- `EnvironmentVariables.PATH` =
  `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`
- `StandardOutPath` / `StandardErrorPath` = `~/.summarizeaudio/launchd.log`

#### Footgun 1 — stripped PATH (addressed)

Login-launched GUI agents inherit a minimal PATH. Without an explicit PATH the
app would not find `ffmpeg` (recording) or `ollama` (summarization), and those
steps would fail only when launched at login — a confusing, environment-specific
break. The `EnvironmentVariables.PATH` key above covers both Apple-silicon
(`/opt/homebrew/bin`) and Intel (`/usr/local/bin`) Homebrew layouts.

#### Footgun 2 — `.env` discovery (addressed)

`__main__.main()` calls `load_dotenv()`, which searches from the current working
directory. Login-launched agents start with an arbitrary CWD, so `.env` (which
holds `HUGGINGFACE_ACCESS_TOKEN`) would be missed. Setting `WorkingDirectory` to
the install dir fixes this.

### Modified: `summarizeaudio/settings_window.py`

A new "Launch at Login" row, consistent with the existing On/Off dropdowns:

- Heading: **Launch at Login** (`Step.TLabel`).
- A light hint line under the dropdown: "Applies at your next login."
  (`Hint.TLabel`).
- Dropdown values `["On", "Off"]`, width `self._combo_width`, initialized from
  `startup.is_enabled()`.
- Arrow stepping bound via the existing `_bind_arrow_stepping` helper (so the
  macOS arrow-cycling fix applies here too).
- The whole row is built only when `startup.is_supported()` is True; otherwise
  it is omitted entirely.
- Window height grows by one row (~+34px) when the row is present.

On **Apply** (`_on_apply`), only when the dropdown value differs from
`startup.is_enabled()`:

- "On"  → `startup.enable()`
- "Off" → `startup.disable()`

Wrapped so a failure surfaces as an amber warning toast (consistent with the
existing warning-toast convention) rather than crashing the window. The plist
write/remove is the durable part.

### Modified: `setup.sh`

- Read opt-in flag near the diarization flag:
  `INSTALL_AUTOSTART="${SUMMARIZEAUDIO_AUTOSTART:-0}"`.
- After the venv install succeeds, when `INSTALL_AUTOSTART == 1`:
  `venv/bin/python -c "from summarizeaudio import startup; startup.enable()"`.
  The installer calls into the Python module instead of hand-writing plist XML,
  so the plist format has one source of truth.
- Final banner: always print a line noting launch-at-login can be toggled in the
  Settings window; when enabled during install, confirm it is on.

Default is OFF. Rationale: `setup.sh` is commonly run via `curl | bash` (no TTY,
so interactive prompts are unreliable), and silently adding a login item without
consent is a known anti-pattern. The env-var opt-in mirrors the established
`SUMMARIZEAUDIO_DIARIZATION=1` convention.

## Data flow

```
User toggles "Launch at Login" -> On, clicks Apply
  settings_window._on_apply()
    if value changed: startup.enable()
      writes ~/Library/LaunchAgents/com.summarizeaudio.plist
  (no further action; app keeps running)

Next login
  launchd auto-loads ~/Library/LaunchAgents/*.plist
    RunAtLoad=true -> runs [venv-python, -m, summarizeaudio]
      WorkingDirectory + PATH set -> .env loads, ffmpeg/ollama resolve
      menu-bar app appears
```

State is read back purely from the filesystem: `startup.is_enabled()` checks
whether the plist file exists. No caching, no config mirror.

## Error handling

- `enable()` / `disable()` are file operations; `disable()` is idempotent.
  `enable()` creates `~/Library/LaunchAgents` if missing.
- Settings Apply wraps the call; on `OSError` it posts an amber warning toast and
  leaves the dropdown reflecting the real on-disk state on next open.
- Non-macOS: `is_supported()` False → row never built → `enable`/`disable` never
  called from the UI.

## Testing (TDD)

`startup.py` (pure, fast):
- `is_supported()` reflects `sys.platform` (monkeypatch).
- `plist_path()` resolves under `~/Library/LaunchAgents` with the right
  filename.
- `enable()` writes a file (point the LaunchAgents dir at `tmp_path` via
  monkeypatched home) whose contents contain `sys.executable`, `-m`,
  `summarizeaudio`, `<key>RunAtLoad</key>`, `<true/>`, and the PATH string.
- `disable()` removes the file; calling it when absent is a no-op (idempotent).
- `is_enabled()` is False before `enable()`, True after, False after `disable()`.

`settings_window.py`:
- With `startup.is_supported()` True and `is_enabled()` mocked, the row renders
  an On/Off dropdown set to the mocked state.
- Apply with a changed value calls `startup.enable()` / `disable()` (module
  mocked); unchanged value calls neither.
- With `is_supported()` False, the row is absent (no `_startup_combo`).

All `launchctl`/filesystem boundaries are mocked or redirected to `tmp_path`; no
test touches the real `~/Library/LaunchAgents`.

## Documentation updates

- `README.md`: a short "Launch at login" subsection (Settings toggle + the
  `SUMMARIZEAUDIO_AUTOSTART=1` install flag).
- `docs/adr.md`: ADR for the plist-file-as-source-of-truth decision and the
  rejection of instant launchd registration.
- `docs/learnings.md`: the two footguns (stripped PATH, `.env`/CWD) under a
  macOS LaunchAgent section.

## Post-implementation

This is a cross-layer, multi-file change (new module, settings UI, installer,
docs). Per project convention, dispatch a code-review sub-agent after
implementation to audit for stale references, doc drift, and coverage gaps.
