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
**Status:** Accepted

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
