# Launch at Login Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user start SummarizeAudio automatically at macOS login via an On/Off toggle in Settings, backed by a LaunchAgent plist whose presence on disk is the single source of truth.

**Architecture:** A new pure-IO module `summarizeaudio/startup.py` writes/removes `~/Library/LaunchAgents/com.summarizeaudio.plist` (`RunAtLoad=true`, launched as the venv python running `-m summarizeaudio`). The Settings window gains a macOS-only "Launch at Login" dropdown that calls `startup.enable()/disable()` on Apply. The installer pre-enables it via an opt-in `SUMMARIZEAUDIO_AUTOSTART=1` env var that calls into the same module.

**Tech Stack:** Python 3.11+, `plistlib` (stdlib, builds the plist safely), Tk/ttk (Settings UI), pytest, bash (`setup.sh`).

**Spec:** `docs/superpowers/specs/2026-06-03-launch-at-login-design.md`

**Reference skills:** @plugin:superpowers:test-driven-development for every code task.

**Conventions (this repo):**
- Run tests with `./venv/bin/python -m pytest`.
- Commits explicit, staged by name (never `git add -A`). Co-author trailer:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Zero em-dashes in user-facing copy.

---

## Chunk 1: startup.py module

### Task 1: `startup.py` capability + path helpers

**Files:**
- Create: `summarizeaudio/startup.py`
- Test: `tests/test_startup.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_startup.py
from __future__ import annotations

import plistlib

import pytest

from summarizeaudio import startup


def test_is_supported_reflects_platform(monkeypatch):
    monkeypatch.setattr(startup.sys, "platform", "darwin")
    assert startup.is_supported() is True
    monkeypatch.setattr(startup.sys, "platform", "linux")
    assert startup.is_supported() is False


def test_plist_path_under_launchagents_and_named_from_label(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = startup.plist_path()
    assert p == tmp_path / "Library" / "LaunchAgents" / f"{startup.LABEL}.plist"
    assert p.name == f"{startup.LABEL}.plist"
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_startup.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'summarizeaudio.startup'`.

- [ ] **Step 3: Write minimal implementation**

```python
# summarizeaudio/startup.py
"""macOS launch-at-login via a LaunchAgent plist.

The plist's presence on disk is the single source of truth: writing it enables
launch at login (effective next login, RunAtLoad=true), removing it disables.
There is no mirrored flag in config.toml. macOS only; on other platforms the
functions are safe no-ops and is_supported() is False.
"""
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

# Reverse-DNS label; also the plist filename stem so the two cannot drift.
LABEL = "com.summarizeaudio"


def is_supported() -> bool:
    """True only on macOS. Gates the whole feature."""
    return sys.platform == "darwin"


def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path() -> Path:
    """Absolute path to the LaunchAgent plist (filename derived from LABEL)."""
    return _launch_agents_dir() / f"{LABEL}.plist"
```

- [ ] **Step 4: Run to verify pass**

Run: `./venv/bin/python -m pytest tests/test_startup.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add summarizeaudio/startup.py tests/test_startup.py
git commit -m "feat(startup): add is_supported + plist_path

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `enable()` / `disable()` / `is_enabled()`

**Files:**
- Modify: `summarizeaudio/startup.py`
- Test: `tests/test_startup.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_startup.py

def test_enable_writes_a_well_formed_plist(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(startup.sys, "executable", "/opt/app/venv/bin/python3.12")

    startup.enable()

    p = startup.plist_path()
    assert p.exists()
    with p.open("rb") as f:
        data = plistlib.load(f)
    assert data["Label"] == startup.LABEL
    assert data["ProgramArguments"] == [
        "/opt/app/venv/bin/python3.12", "-m", "summarizeaudio",
    ]
    # sys.executable is <install>/venv/bin/python -> install dir is 3 hops up.
    assert data["WorkingDirectory"] == "/opt/app"
    assert data["RunAtLoad"] is True
    assert "/opt/homebrew/bin" in data["EnvironmentVariables"]["PATH"]
    assert "/usr/local/bin" in data["EnvironmentVariables"]["PATH"]


def test_is_enabled_tracks_file_presence(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert startup.is_enabled() is False
    startup.enable()
    assert startup.is_enabled() is True


def test_disable_removes_plist_and_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    startup.enable()
    assert startup.is_enabled() is True
    startup.disable()
    assert startup.is_enabled() is False
    # Calling again must not raise.
    startup.disable()
    assert startup.is_enabled() is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_startup.py -q -k "enable or disable or is_enabled"`
Expected: FAIL with `AttributeError: module 'summarizeaudio.startup' has no attribute 'enable'`.

- [ ] **Step 3: Write minimal implementation**

Append to `summarizeaudio/startup.py`:

```python
def is_enabled() -> bool:
    """True when the LaunchAgent plist exists on disk."""
    return plist_path().exists()


def _install_dir() -> Path:
    # sys.executable is <install>/venv/bin/python; three hops up
    # (bin -> venv -> install) reach the install dir where .env and the
    # editable package live. parents[1] would wrongly stop at <install>/venv.
    return Path(sys.executable).parents[2]


def _log_path() -> Path:
    return Path.home() / ".summarizeaudio" / "launchd.log"


def _plist_dict() -> dict:
    log = str(_log_path())
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "summarizeaudio"],
        # So load_dotenv() (CWD-relative) finds <install>/.env at login.
        "WorkingDirectory": str(_install_dir()),
        "RunAtLoad": True,
        # Login agents get a stripped PATH; restore it so ffmpeg/ollama resolve.
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        },
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def enable() -> None:
    """Write the LaunchAgent plist (creating ~/Library/LaunchAgents if needed)."""
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        plistlib.dump(_plist_dict(), f)


def disable() -> None:
    """Remove the LaunchAgent plist if present (idempotent)."""
    plist_path().unlink(missing_ok=True)
```

- [ ] **Step 4: Run to verify pass**

Run: `./venv/bin/python -m pytest tests/test_startup.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add summarizeaudio/startup.py tests/test_startup.py
git commit -m "feat(startup): enable/disable/is_enabled via LaunchAgent plist

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Chunk 2: Settings window row

### Task 3: Render the "Launch at Login" row (macOS only)

**Files:**
- Modify: `summarizeaudio/settings_window.py` (import at top ~line 11; window height line 37; new state in `__init__` after `self._diar_recheck_note = None` ~line 104, before `self._build()` ~line 106; row in `_build` after the diarization row, line 172)
- Test: `tests/test_settings_window.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_settings_window.py

def test_launch_at_login_row_renders_when_supported(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.startup.is_supported", lambda: True)
    monkeypatch.setattr("summarizeaudio.startup.is_enabled", lambda: True)
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
        assert win._startup_combo is not None
        assert list(win._startup_combo["values"]) == ["On", "Off"]
        assert win._startup_combo.get() == "On"


def test_launch_at_login_row_absent_when_unsupported(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.startup.is_supported", lambda: False)
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
        assert win._startup_combo is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_settings_window.py -q -k "launch_at_login"`
Expected: FAIL with `AttributeError: 'SettingsWindow' object has no attribute '_startup_combo'`.

- [ ] **Step 3: Write minimal implementation**

In `summarizeaudio/settings_window.py`:

(a) Add import near line 11 (after `from summarizeaudio import diarization`):

```python
from summarizeaudio import startup
```

(b) In `__init__`, set the height taller when the row will show (replace line 37):

```python
        self._window_height = 432 if startup.is_supported() else 360
```

(c) In `__init__`, add state after `self._diar_recheck_note = None` (~line 104), before the `self._build()` call (~line 106):

```python
        # Launch-at-login row state (macOS only; None when unsupported).
        self._startup_combo: ttk.Combobox | None = None
```

(d) In `_build`, after the diarization row block (after line 172
`self._render_diarization_row()`), add:

```python
        # Launch at Login (macOS only)
        if startup.is_supported():
            ttk.Label(body, text="Launch at Login", style="Step.TLabel").pack(anchor="w")
            self._startup_combo = ttk.Combobox(
                body, state="readonly", width=combo_width, values=["On", "Off"],
            )
            self._startup_combo.set("On" if startup.is_enabled() else "Off")
            self._startup_combo.pack(anchor="w", pady=(4, 0))
            self._bind_arrow_stepping(self._startup_combo)
            ttk.Label(
                body, text="Applies at your next login.", style="Hint.TLabel",
            ).pack(anchor="w", pady=(2, 14))
```

- [ ] **Step 4: Run to verify pass**

Run: `./venv/bin/python -m pytest tests/test_settings_window.py -q -k "launch_at_login"`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full settings suite (no regressions)**

Run: `./venv/bin/python -m pytest tests/test_settings_window.py -q`
Expected: PASS (all prior tests + 2 new).

- [ ] **Step 6: Commit**

```bash
git add summarizeaudio/settings_window.py tests/test_settings_window.py
git commit -m "feat(settings): add Launch at Login row (macOS only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Apply toggles the LaunchAgent

**Files:**
- Modify: `summarizeaudio/settings_window.py` (`_on_apply`, after the `save_config` try/except success path — its `except` block ends at line 560 — and before the `rebuild_tray_menu` put at ~line 563)
- Test: `tests/test_settings_window.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_settings_window.py

def _startup_recorder(monkeypatch):
    """Replace startup.enable/disable with recorders; return the calls list."""
    calls = []
    monkeypatch.setattr("summarizeaudio.startup.is_supported", lambda: True)
    monkeypatch.setattr("summarizeaudio.startup.enable", lambda: calls.append("enable"))
    monkeypatch.setattr("summarizeaudio.startup.disable", lambda: calls.append("disable"))
    return calls


def test_apply_enables_startup_when_toggled_on(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.settings_window.save_config", lambda cfg: None)
    calls = _startup_recorder(monkeypatch)
    monkeypatch.setattr("summarizeaudio.startup.is_enabled", lambda: False)  # currently off
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
        win._startup_combo.set("On")
        win._on_apply()
    assert calls == ["enable"]


def test_apply_disables_startup_when_toggled_off(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.settings_window.save_config", lambda cfg: None)
    calls = _startup_recorder(monkeypatch)
    monkeypatch.setattr("summarizeaudio.startup.is_enabled", lambda: True)  # currently on
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
        win._startup_combo.set("Off")
        win._on_apply()
    assert calls == ["disable"]


def test_apply_leaves_startup_untouched_when_unchanged(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.settings_window.save_config", lambda cfg: None)
    calls = _startup_recorder(monkeypatch)
    monkeypatch.setattr("summarizeaudio.startup.is_enabled", lambda: True)  # already on
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
        win._startup_combo.set("On")  # unchanged
        win._on_apply()
    assert calls == []


def test_apply_surfaces_startup_oserror_in_error_label(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.settings_window.save_config", lambda cfg: None)
    monkeypatch.setattr("summarizeaudio.startup.is_supported", lambda: True)
    monkeypatch.setattr("summarizeaudio.startup.is_enabled", lambda: False)  # currently off

    def _boom():
        raise OSError("disk full")

    monkeypatch.setattr("summarizeaudio.startup.enable", _boom)
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=_query_devices_side_effect):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
        win._startup_combo.set("On")  # changed -> triggers enable() -> OSError
        win._on_apply()
        assert "Failed to update launch at login" in win._error_label.cget("text")
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_settings_window.py -q -k "apply_enables_startup or apply_disables_startup or apply_leaves_startup or apply_surfaces_startup_oserror"`
Expected: FAIL — `calls` is empty for enable/disable and the OSError test sees no error-label text (no toggle code yet).

- [ ] **Step 3: Write minimal implementation**

In `_on_apply`, after the `save_config` try/except (its `except` block `return`
is at line 560) and before the `rebuild_tray_menu` put (~line 563), insert:

```python
        if self._startup_combo is not None:
            want = self._startup_combo.get() == "On"
            if want != startup.is_enabled():
                try:
                    startup.enable() if want else startup.disable()
                except OSError as exc:
                    if self._error_label is not None:
                        self._error_label.configure(
                            text=f"Failed to update launch at login: {exc}"
                        )
                    return
```

- [ ] **Step 4: Run to verify pass**

Run: `./venv/bin/python -m pytest tests/test_settings_window.py -q -k "startup"`
Expected: PASS.

- [ ] **Step 5: Run the full settings suite (no regressions)**

Run: `./venv/bin/python -m pytest tests/test_settings_window.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add summarizeaudio/settings_window.py tests/test_settings_window.py
git commit -m "feat(settings): Apply toggles launch-at-login on change

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Chunk 3: Installer + docs

### Task 5: `setup.sh` opt-in `SUMMARIZEAUDIO_AUTOSTART=1`

**Files:**
- Modify: `setup.sh` (flag near line 17; enable block after the install success ~line 161; banner inserted before the diarization banner `if` at line 276)

Bash is not unit-tested in this repo, so verification is a manual smoke check
with `HOME` redirected to a scratch dir.

- [ ] **Step 1: Add the opt-in flag**

After the `INSTALL_DIARIZATION` line (~line 17), add:

```bash
# Opt-in launch-at-login. Enable with: SUMMARIZEAUDIO_AUTOSTART=1 bash setup.sh
INSTALL_AUTOSTART="${SUMMARIZEAUDIO_AUTOSTART:-0}"
```

- [ ] **Step 2: Enable it after install succeeds**

After the diarization/plain `pip install` block (after line 161, the
`success "SummarizeAudio installed"` fi), add:

```bash
# ── Launch at login (opt-in) ─────────────────────────────────────────────────
if [[ "$INSTALL_AUTOSTART" == "1" ]]; then
    info "Enabling launch at login..."
    venv/bin/python -c "from summarizeaudio import startup; startup.enable()"
    success "Launch at login enabled (starts at next login)"
fi
```

- [ ] **Step 3: Mention it in the final banner**

In the closing banner's SETTINGS section (lines 273-275), insert this block
immediately before the existing diarization banner `if` (line 276):

```bash
echo ""
echo "  LAUNCH AT LOGIN"
if [[ "$INSTALL_AUTOSTART" == "1" ]]; then
echo "    Enabled. The app will start automatically at your next login."
else
echo "    Off. Turn it on anytime from the app's Settings window."
fi
```

- [ ] **Step 4: Verify with a scratch HOME**

Run:
```bash
HOME=$(mktemp -d) ./venv/bin/python -c "from summarizeaudio import startup; startup.enable(); print(startup.plist_path()); print(startup.plist_path().read_text()[:200])"
```
Expected: prints a path under the scratch dir's `Library/LaunchAgents/` and a
plist XML head containing `com.summarizeaudio` and `RunAtLoad`.

- [ ] **Step 5: Commit**

```bash
git add setup.sh
git commit -m "feat(setup): opt-in SUMMARIZEAUDIO_AUTOSTART enables launch at login

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Documentation (README, ADR, learnings)

**Files:**
- Modify: `README.md` (new short "Launch at login" subsection)
- Modify: `docs/adr.md` (new ADR)
- Modify: `docs/learnings.md` (macOS LaunchAgent footguns)

- [ ] **Step 1: README subsection**

Add a short subsection (place it after the diarization section). Content:

```markdown
## Launch at login (optional)

To have SummarizeAudio start automatically when you log in, open **Settings**
from the menu-bar icon and set **Launch at Login** to **On**, then click
**Apply**. It takes effect at your next login.

You can also enable it during install with an opt-in flag:

```bash
SUMMARIZEAUDIO_AUTOSTART=1 bash setup.sh
```

Under the hood this writes a macOS LaunchAgent at
`~/Library/LaunchAgents/com.summarizeaudio.plist`. Setting the toggle to **Off**
(or deleting that file) disables it. macOS only.
```

- [ ] **Step 2: ADR entry**

Append an ADR to `docs/adr.md` (Nygard format) recording:
- Context: a menu-bar app with no `.app` bundle, launched via `venv/bin/python -m summarizeaudio`.
- Decision: use a LaunchAgent plist as the single source of truth (no config.toml mirror); `RunAtLoad=true`; the plist's presence is the state.
- Decision: reject instant launchd registration (`launchctl bootstrap`) because it would spawn a duplicate of the already-running app, forcing a single-instance guard for negligible benefit.
- Consequences: effect lands at next login; toggling off via `bootout` of a login-launched process could terminate it (we do file-only, so this does not apply); installer opt-in mirrors the diarization flag.

- [ ] **Step 3: learnings entry**

Append to `docs/learnings.md` under a new `## macOS LaunchAgent` section:
- Login-launched GUI agents inherit a stripped PATH, so `ffmpeg`/`ollama` are not found unless `EnvironmentVariables.PATH` is set in the plist.
- `load_dotenv()` is CWD-relative, so a login agent must set `WorkingDirectory` to the install dir or `.env` (and `HUGGINGFACE_ACCESS_TOKEN`) is missed.
- `sys.executable` is `<install>/venv/bin/python`, so the install dir is `parents[2]` (three hops), not `parent.parent`.
- Use `plistlib.dump` to build the plist (correct typing/escaping) rather than hand-writing XML.

- [ ] **Step 4: Verify docs render and are accurate**

Run: `./venv/bin/python -m pytest -q` (full suite still green; docs don't break anything).
Read back each edited doc section to confirm no em-dashes and accurate paths.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/adr.md docs/learnings.md
git commit -m "docs: launch-at-login (README, ADR, learnings)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Post-implementation

- [ ] Run the full suite once more: `./venv/bin/python -m pytest -q`.
- [ ] Dispatch a code-review sub-agent (research-only) over the changeset per the
  project's post-change validation rule: check for stale references, the
  `_on_apply` ordering (toggle after `save_config` success), doc/path accuracy,
  and that no test touches the real `~/Library/LaunchAgents`.
- [ ] Manual end-to-end (optional, on a real macOS login): enable in Settings,
  log out/in, confirm the menu-bar icon appears and recording still finds
  `ffmpeg`/`ollama` (the PATH footgun).
