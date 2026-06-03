# Architecture Decision Records

Records of significant architectural decisions made during the development of SummarizeAudio. Format: [Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

---

## ADR-001: Run transcription and summarisation locally (no cloud APIs)

**Date:** 2026-03-15
**Status:** Accepted

### Context

The app processes meeting recordings and conversations that may contain sensitive business content. Sending audio or transcripts to a cloud API introduces latency, cost, and privacy risk.

### Decision

Use `faster-whisper` for on-device transcription and a locally running `Ollama` instance for summarisation. No audio, transcript, or summary ever leaves the machine.

### Consequences

- No API keys, no per-use cost, no internet dependency after initial model download.
- First-run model download is large (Whisper base ~150 MB; Ollama model 3–8 GB).
- Performance is bounded by local hardware. Apple Silicon handles the models well; older Intel Macs are slower.
- Users must have Ollama running before the app can summarise. Error handling covers the "Ollama not reachable" case explicitly.

---

## ADR-002: Use `config.py` as the single source of truth for defaults

**Date:** 2026-04-10
**Status:** Accepted

### Context

The default summarisation prompt and the RAM-based model selection logic (`gemma3:4b` for ≤8 GB RAM, `gemma3:12b` for >8 GB) were initially copy-pasted into `setup.sh`, `setup.ps1`, and `config.py` independently. Any prompt change required updating three files.

### Decision

`config.py` is the canonical location for `DEFAULT_SUMMARIZATION_PROMPT`, `_make_default_toml()`, and `_select_model_for_ram()`. The installers call the Python package to generate the initial config rather than maintaining their own inline copies.

### Consequences

- Prompt changes propagate automatically to new installs.
- Installers have a runtime dependency on the Python package being installed first — which they already satisfy (venv install happens before config write).
- RAM detection logic is maintained in one place for all platforms.

---

## ADR-003: Replace `rumps` with `pystray` on macOS; consolidate all windows into the main process

**Date:** 2026-05-13
**Status:** Accepted

### Context

The original implementation used `rumps` for the macOS menu bar icon. `rumps` wraps Apple's `NSApp` and occupies the main thread with its own event loop. Because `tkinter` also requires the main thread, every pop-up window (workflow progress, history, file picker, prompt editor) had to be launched as a separate `subprocess.Popen([sys.executable, ...])` call.

This caused two user-visible problems:

1. **Python dock icons.** Each subprocess is a bare `python3` process. macOS shows a Python duck icon in the dock for every open window. With a workflow and history window open simultaneously, users saw 1–2 Python icons they did not expect and could not remove.

2. **No window reuse.** Because each window was an isolated subprocess, the tray had no way to find, focus, or retarget an existing window. Opening a second workflow while one was already running created a second independent window.

Attempts to suppress dock icons by calling `NSApp.setActivationPolicy_(Accessory)` inside the subprocess were recorded as crashing Tk on the project's Python/Tk build (`chooser_window.py`: "Intentionally left as a no-op. The accessory activation policy crashes Tk on this Python/Tk build."). The crash was caused by setting the policy after Tk had already initialised — a different situation from setting it at process startup.

### Decision

Replace `rumps` with `pystray` on macOS. `pystray` runs the tray icon in a **background thread**, freeing the main thread for `tk.mainloop()`. A new `WindowManager` class runs on the main thread and owns all Tk windows directly — no subprocess spawning.

At process startup in `__main__.py`, before any Tk window is created, call:

```python
import AppKit
NSApp = AppKit.NSApplication.sharedApplication()
NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
```

This marks the entire process as a menu bar accessory, suppressing the dock icon for the whole process lifetime.

Window reuse is implemented in `WindowManager`: when the tray requests a new workflow action and a `WorkflowWindow` is already open and idle, it is retargeted in place and brought to focus. If the pipeline is running, the existing window is closed and a new one opened.

### Consequences

- **No dock icons.** The single process never appears in the dock.
- **Window reuse.** The tray can focus or retarget existing windows.
- `rumps` is removed as a dependency. The `_rebuild_rumps_menu` path in `tray.py` is deleted.
- `pystray` is already a dependency and already has a full macOS implementation in `tray.py` (`_rebuild_menu`). The macOS-specific `_run_rumps()` path is replaced with the existing `pystray` path.
- The `workflow_window`, `history_window`, `chooser_window`, and `prompt_editor` modules are no longer standalone `__main__` entry points. Their subprocess-facing argument parsers and `main()` wrappers are removed.
- **Risk:** setting `NSApplicationActivationPolicyAccessory` before Tk initialises resolves the known crash, but must be validated on the project's Python/Tk build early in implementation.
- Windows and Linux are unaffected — `pystray` already handled both platforms and no subprocess model was used there.

### About Tk, pystray, and rumps (plain English)

**Tkinter (tk)** draws the windows users interact with — progress bars, buttons, text areas. It is built into Python. On macOS it must run on the main thread.

**rumps** puts an icon in the macOS menu bar (the strip at the top-right with Wi-Fi and the clock). It wraps Apple's native menus and runs on the main thread. Because it holds the main thread, Tk cannot run in the same process — hence the subprocess workaround and its resulting dock icons.

**pystray** also puts an icon in the menu bar / system tray, but works on macOS, Windows, and Linux. On macOS it runs in a background thread, leaving the main thread free for Tk. Swapping `rumps` for `pystray` on macOS is the minimal change that lets everything — tray icon, Tk windows, pipeline workers — live in one process with no dock icon.

---

## ADR-004: Workflow window displays summary preview inline on completion

**Date:** 2026-05-13
**Status:** Accepted

### Context

When summarisation completes, the app needs to surface the result to the user. Options considered: auto-close the window and let the macOS notification carry the result; show a separate "done" toast that auto-dismisses; keep the window open with an inline preview.

### Decision

The `WorkflowWindow` stays open on completion and displays the summary text inline, alongside action buttons (Open Summary, Open Transcript, Open Recording, Close). The user dismisses it manually.

### Consequences

- Users can review the summary immediately without opening a file.
- The window does not disappear unexpectedly mid-review.
- If the user triggers a new workflow action from the tray while the done-state window is open, the window closes and a new one opens for the new action (per the window reuse rules in ADR-003).

---

## ADR-005: Redesign workflow and history windows to ~560×480px

**Date:** 2026-05-13
**Status:** Accepted

### Context

The original `WorkflowWindow` was 1440×900px — nearly full-screen — with the history window at 1480×940px. The large size was chosen to accommodate the step tracker and summary preview, but in practice it dominated the screen and felt disproportionate for a helper app.

### Decision

Both `WorkflowWindow` and `HistoryWindow` are redesigned to a streamlined ~560×480px default (resizable). The step tracker, progress bar, and summary preview are retained but laid out more compactly. Fonts, padding, and card styling are refined to match the smaller canvas.

### Consequences

- Windows are less intrusive and proportional to the content they show.
- The step tracker and inline summary preview are preserved — no reduction in functionality.
- Minimum window sizes are updated to match the new defaults.

---

## ADR-006: Consolidate input device and summarization model into a Settings window

**Date:** 2026-05-30
**Status:** Accepted (inline-status-item portion superseded by ADR-009, 2026-06-03; the inline `Input → …` / `Model → …` / `Diarization → …` tray items were later replaced by a single `Settings…` item)

### Context

The tray menu previously exposed a "Summarization Model" submenu with two presets (Fast Mode = `gemma3:4b`, High Quality Mode = `gemma3:12b`) and no UI for changing the audio input device — that knob lived only in `config.toml`. Two problems:

1. The preset coupling was a leaky abstraction. Users with other Ollama models installed (Llama, Qwen, embedding models) had no way to select them from the UI. Users without `gemma3:12b` installed got a silent failure when they clicked High Quality.
2. The audio input device was invisible. Users had no way to confirm what the app was capturing, no way to switch between BlackHole (loopback) and the built-in mic without editing TOML.

### Decision

Replace both with a single shared `SettingsWindow` (`settings_window.py`) containing two readonly `ttk.Combobox` dropdowns: Input Audio and Summarization Model. The tray menu surfaces the current selections as two inline status items below the History separator:

```
Input Audio: BlackHole 2ch
Summarization: gemma3:4b
```

Clicking either opens the Settings window. Both menu items use the same click handler — there is no need for two entry points to the same window.

Settings stacks on top of Workflow and History (it is **not** subject to the one-window-at-a-time rule). If already open, clicking refocuses the existing window instead of duplicating. Apply mutates the in-memory `AppConfig`, calls `save_config()`, then posts `("rebuild_tray_menu",)` onto `ui_queue` so the tray status items refresh in place. Save failures roll the config back and surface the error inline on the dialog.

The model dropdown is populated dynamically via `list_installed_models()` (new `ollama_client.py`), which calls Ollama's `/api/tags` endpoint:
- Returns `None` → Ollama not running. Combo + Apply disabled, instructional text shown.
- Returns `[]` → Ollama running but no models. Combo + Apply disabled.
- Returns models → listed by name. Embedding models (family `bert`/`nomic-bert` or name containing `embed`) get a "· embedding" suffix as a soft warning.
- If the configured model is not installed, a `<model> (not installed)` row is injected at the top so the user can see what was previously configured.

The input device dropdown is populated via `sd.query_devices()` filtered to inputs, with a first entry of `Auto-detect (<resolved name>)` that maps to `recording.input_device = None` (the existing cascade: BlackHole loopback → system default).

The Fast/High Quality preset concept and the standalone Diarization toggle are both dropped entirely.

### Consequences

- Users can select any installed Ollama model, not just the two presets.
- Audio input device is visible at a glance and changeable without editing TOML.
- The tray menu is shorter (two flat items instead of a submenu).
- Pre-existing config keys (`recording.input_device`, `ollama.model`) are unchanged — no migration needed.
- Settings does NOT participate in the Workflow ↔ History block, by design: changing settings during a long transcription is a reasonable user expectation.
- Apply runs `save_config` synchronously on the Tk main thread. Acceptable because `save_config` writes a small TOML file; if it ever grows expensive, move to a worker thread.
- `ollama_client.list_installed_models` swallows connection errors and returns `None` so the Settings window can render a useful state when Ollama is down rather than crashing.

---

## ADR-007: Gate speaker diarization on preference AND capability, not on token presence

### Context

Diarization (pyannote.audio) is an optional, heavy extra. The progress bar in the workflow window listed a "Diarize" step whenever a `HUGGINGFACE_ACCESS_TOKEN` was set, and the pipeline built a `Diarizer` on the same condition with a `try/except ImportError` meant to degrade gracefully when pyannote was not installed.

Two defects fell out of this:

1. The `except ImportError` was dead code. `diarizer.py` imports pyannote lazily inside `Diarizer._load()`, not at module import time, so constructing `Diarizer(token)` never raises `ImportError`. With a token set but pyannote absent, the workflow showed a phantom "Diarize" step and the run crashed mid-transcription when `_load()` finally tried to import the missing package.
2. There was no user-facing preference. Whether to diarize was implied by the presence of a token, which conflates "the user wants speaker labels" with "the machine can produce them".

### Decision

Separate **preference** from **capability** and require both.

- **Preference** lives in config: `[diarization] enabled` (`DiarizationConfig`). This is the user's intent and is the only thing the Settings toggle and the installer write.
- **Capability** is probed at runtime by `diarization.is_available()` = `pyannote_installed() AND token_present()`. `pyannote_installed()` uses `importlib.util.find_spec("pyannote.audio")`, which detects the package WITHOUT importing torch (heavy).
- The single gate is `diarization.effective_enabled(cfg) = cfg.diarization.enabled AND is_available()`. Both the pipeline (`build_diarizer`) and the workflow window (`_has_diarizer`) call only this. The dead `try/except ImportError` is removed.

`diarization.py` is also the single source of truth for the setup instructions (`SETUP_STEPS` / `render_setup_steps`). The installer banner and the Settings "How to enable" expander render the same text, so they cannot drift.

### Consequences

- No phantom "Diarize" step and no mid-run crash: a token set without pyannote installed yields `is_available() == False`, so nothing is built and no step is shown.
- The installer writes `enabled` honestly: true only when the extra is installed AND a real (non-placeholder, uncommented) token already exists. A fresh clone gets `enabled = false`.
- The `.env` scaffold ships the token line commented out, so `token_present()` is not fooled by a placeholder value.
- The user can turn diarization on/off from Settings; when the capability is missing the toggle is replaced by an "Unavailable" label plus a "How to enable" expander with a "Re-check" button (calls `load_dotenv(override=True)` then re-probes; if still unavailable it keeps the instructions visible and shows `missing_reason()` instead of collapsing).
- `config.memory_warning` also routes through `effective_enabled(cfg)`, so the diarizer's ~1.5 GB is only added to the RAM budget when diarization is both preferred and capable — a token set with the preference off no longer triggers a spurious low-memory warning.
- Known limitation (tech debt): when Ollama is unreachable the Settings **Apply** button is disabled wholesale, so a diarization-toggle change made in that state is discarded along with the (unusable) model selection. The diarization toggle is independent of Ollama and could be saved separately; deferred because the workaround (start Ollama, then Apply) is obvious.

---

## ADR-008: Use a macOS LaunchAgent plist as the single source of truth for launch-at-login

**Date:** 2026-06-03
**Status:** Accepted

### Context

SummarizeAudio has no `.app` bundle. It is launched via `venv/bin/python -m summarizeaudio` from the install directory. Users wanted an option to start the app automatically at login without manual shell-profile editing.

Two designs were considered:

1. Mirror the enabled/disabled state in `config.toml` AND write a plist. Two pieces of state that must be kept in sync; drift is possible (plist present but config says off, or vice versa).
2. Treat plist presence on disk as the single source of truth. `is_enabled()` checks whether `~/Library/LaunchAgents/com.summarizeaudio.plist` exists. No config.toml key.

For the activation mechanism, two approaches were considered:

- **`launchctl bootstrap`** the agent immediately on Apply (current session starts a second instance right away).
- **Write the plist only**, let macOS pick it up at the next login.

### Decision

Adopt design 2: the plist file IS the enabled state. `startup.enable()` writes `~/Library/LaunchAgents/com.summarizeaudio.plist` with `RunAtLoad=true`; `startup.disable()` removes it (idempotent); `startup.is_enabled()` checks file presence. No `config.toml` mirror.

Reject immediate `launchctl bootstrap`: a `RunAtLoad=true` agent bootstrapped into the current session would spawn a second instance of the already-running app. Preventing that requires a single-instance guard (lockfile or socket), which adds complexity for negligible benefit. The next-login deferral is the correct user expectation anyway ("will start next time I log in").

`startup.is_supported()` returns `True` only on macOS; the Settings row is hidden on other platforms.

The installer opt-in (`SUMMARIZEAUDIO_AUTOSTART=1 bash setup.sh`) calls `startup.enable()` during setup, mirroring the `SUMMARIZEAUDIO_DIARIZATION=1` pattern.

### Consequences

- Apply in Settings takes effect at the next login, not the current session. The UI makes this explicit ("takes effect at your next login").
- Toggling is durable: the plist survives app updates because setup.sh does not remove it.
- No config drift: deleting the plist manually (or via `startup.disable()`) is the complete disable action.
- `plistlib.dump` is used for serialization (correct typing, proper XML escaping) rather than hand-written XML.
- macOS only. Windows and Linux do not surface the setting.

---

## ADR-009: Collapse the inline tray status items into a single Settings item

**Date:** 2026-06-03
**Status:** Accepted (supersedes the inline-status-item portion of ADR-006)

### Context

ADR-006 surfaced the current input device and model as inline tray status items (`Input → …`, `Model → …`), later joined by `Diarization → …`. Each item doubled as a deep-link that opened Settings with keyboard focus pre-placed on the matching dropdown. Supporting that required a `focus_target` parameter threaded through `WindowManager.show_settings` into `SettingsWindow`, plus `_apply_focus_target`, a public `focus_target()` retarget method, a `_diar_focus_widget` handle, and three per-item click handlers in the tray.

The status items showed live state but were noisy, and the auto-select plumbing existed only to serve them.

### Decision

Replace the three inline status items with a single `Settings…` item at the end of the menu (above the Quit separator). It opens the Settings window with no auto-select. Delete the supporting code: `Tray._input_audio_label/_summarization_label/_diarization_label`, `_on_settings_click_input/model/diarization`, `WindowManager.show_settings(focus_target=…)`, and `SettingsWindow._focus_target/_apply_focus_target/focus_target()/_diar_focus_widget`. The now-unused `diarization` and `resolve_auto_input_device_name` imports are dropped from `tray.py`.

Separately, the launch-at-login control is renamed from "Launch at Login" to **Open at Login** (matching macOS System Settings → Login Items terminology).

### Consequences

- Simpler menu and a whole layer of focus plumbing removed.
- Tradeoff: the current input device / model / diarization state is no longer visible at a glance from the menu; it is seen only by opening Settings.
- All four controls (input, model, diarization, Open at Login) continue to live in the Settings window unchanged.
- The `("show_settings",)` queue message no longer carries a target argument.
