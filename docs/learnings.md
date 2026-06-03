# Engineering Learnings

Behavioural quirks, vendor / API gotchas, and workarounds discovered while building SummarizeAudio. Distinct from `adr.md` (which captures *why* a choice was made), this file captures *how something actually behaves once you depend on it*. Organised by topic; one section per technology or component.

---

## Tk / ttk

### Combobox `state="disabled"` requires the widget to already exist
In `SettingsWindow._build`, the original ordering called `_populate_input_devices()` and `_populate_models()` *before* the Apply button was created. `_populate_models` disables `self._apply_btn` when Ollama is down — and crashed with `AttributeError` because `_apply_btn` was still `None`. Fix: build the entire widget tree (including buttons) first, then call the populate methods at the end of `_build`. General rule for Tk init: create all widgets the populate code might touch before any populate code runs.

### `ttk.Combobox.configure(state="disabled")` does not block programmatic `.set()`
Disabled combos still accept `.set()` calls. Tests that mutate state must read `str(combo["state"])` to assert disablement, not rely on `.set()` raising. Same applies to button `state` — `_on_apply` must explicitly bail when `_apply_btn["state"] == "disabled"` because the keyboard-bound `<Return>` handler can still fire while the button is disabled.

---

## pystray + Tk threading

### pystray menu callbacks run on a background thread
pystray's `MenuItem` callbacks fire on its own background thread, not on the Tk main thread. Calling any Tk widget method (`_focus()`, `_show_toast()`, `winfo_exists()`, even a debug `winfo_*` call) from a pystray callback can deadlock the entire UI — including the user's ability to close the offending window. Force-quit becomes the only escape. The fix pattern: pystray callbacks only do thread-safe Python checks (`is None`, plain bool flags) and `ui_queue.put_nowait(...)`. The Tk main thread drains the queue in `WindowManager._pump` and dispatches via `_handle`.

### Closing the workflow window mid-pipeline can leave the worker (and the icon pulse) hung
The pipeline worker thread blocks on `resolver.wait(timeout=300)` for the override-prompt and name dialogs (`_OverrideEvent` / `_NameEvent`, a `threading.Event` under the hood). The worker's `finally: ui_queue.put(("set_icon","idle"))` only runs once that wait returns, so anything that leaves the resolver unresolved pins both the worker and the processing-pulse animation for the full 300s. There are TWO distinct close orderings, each needing its own guard:
- **Close while the dialog is visible** — the resolver was already delivered to the window (`WorkflowWindow._handle_item` set `self._resolver`). `WorkflowWindow._close` must resolve it with `None` (mirroring the Cancel button) before destroying the window.
- **Close before the dialog arrives** (e.g. during transcription) — `self._resolver` is still `None` at close, so `_close` has nothing to resolve. The worker keeps running, finishes transcription, and posts `("override_dialog", …)` to a now-dead window. `WindowManager._forward` silently dropped undeliverable items, so the resolver was never satisfied. Fix: in `_forward`, when there is no live workflow window and the item is an `override_dialog`/`name_dialog`, resolve `item[1]._resolve(None)` so the worker unblocks. The summarizer treats a `None` override as "skip summarization" and returns; the namer treats `None` as the default.

Both fixes are complementary; neither alone covers both orderings.

### Window refs outlive their Tk widgets
When the user clicks the window's X button, the underlying Tk widget is destroyed but the Python reference (`WindowManager._workflow_win`, etc.) still points at it. `None`-based gating then produces false positives forever. `_sweep_stale_window_refs()` runs on every pump tick (main thread), checks `_win_alive()`, and resets dead refs to `None`. Without this sweep, the "is a window open?" check is unreliable.

### Concurrent `NSStatusItem` writes from two threads deadlock AppKit
The animated menu-bar icon writes `self._tray.icon` (→ `NSStatusItem` `setImage_`) every ~167ms from a `root.after` loop on the **main thread**. A pystray menu callback (`_on_stop_recording`) runs on the **background thread** and used to also write `self._tray.icon` (via `_set_icon("idle")`). Two threads mutating the same `NSStatusItem` concurrently **deadlocks AppKit** and freezes the main thread. Live symptom: clicking *Stop Recording* hung the whole app and the workflow popup never appeared (the frozen main thread couldn't drain the queue that shows it); the log froze right after the recording health check. This only surfaced once the pulse animation existed — before that, start/stop set the icon once with no concurrent timer, so it never collided. Fix: route ALL icon writes through `ui_queue` so they serialize on the main thread; never write `self._tray.icon` from a pystray-callback-thread path.

---

## Menu-bar icon state machine (error clearing)

There are TWO independent persistent-error flags, owned by different objects and cleared by different mechanisms — easy to assume one covers the other:
- `TrayApp._device_error_active` (device faults). Self-clearing: `_enter_device_error` starts a `_schedule_device_error_reprobe` loop that re-runs `check_input_health` and calls `_clear_device_error_if_active` on a healthy probe. Also cleared by a clean `recorder.start()` (`_on_start_recording` sets it `False`).
- `WindowManager._error_active` (pipeline / fatal errors). NOT self-clearing — there's nothing to re-probe for a transient Ollama / transcription failure. It clears only on (a) `set_icon` `recording`/`processing` (a new pipeline) or (b) the open→all-closed window-dismiss transition tracked by `_prev_any_open`.

### A pipeline error fired with NO window open never cleared (red icon stuck forever)
Because the dismiss-clear path needs an open→closed transition, an error raised while no window is open (`_prev_any_open` already `False`) had no escape hatch — the red icon stuck until the user happened to start a new recording/pipeline. This is reachable: the pipeline worker runs in a background thread, so the user can close the workflow window mid-pipeline (see the Bug-3 entry below) and a later summarization failure surfaces with no window. Fix: in `WindowManager._handle`'s `error` branch, if `not self._any_window_open()`, arm `_schedule_error_auto_clear()` → `root.after(self._error_auto_clear_ms=12000, self._auto_clear_error)`. `_auto_clear_error` bails if a window opened meanwhile (defer to dismiss) or the error was already cleared by a new pipeline; else drops the sticky flag and emits `idle`. With a window open the sticky behaviour is preserved (the error shows in-window and clears on dismiss). The macOS notification is the persistent record; the icon is only a transient signal.

### Recording auto-stop for a bad device went silently idle (no error indicator, no recovery)
`_handle_recording_input_health` (the async post-start device check) reverted via a bare `_set_icon("idle")` for ALL stop reasons. For a genuinely-bad device (`channel_mapping`, `device_missing`, …) that hid the fault behind a healthy-looking idle icon AND skipped the reprobe recovery loop — diverging from the startup path (`_handle_startup_input_health`), which correctly enters device-error. Fix: gate on `_should_alert_input_health(report.issue)` — alert-worthy faults call `_enter_device_error()` (sticky red + reprobe); non-alert stop reasons (e.g. `no_frames`) clear the flag and go idle. Note the two issue sets differ: `_should_stop_recording_for_input_health` ⊇ `_should_alert_input_health` (`no_frames` stops but doesn't alert).

---

## macOS template images vs literal color

### A single status-bar image can't be both theme-adaptive AND carry literal color
macOS auto-tints **template** images to match the menu bar (white silhouette on dark bars, black on light) — but `NSImage.setTemplate_(True)` makes the *entire* image monochrome+alpha; any RGB color you baked in is discarded. So you cannot have one PNG that is a theme-adaptive silhouette in some regions and literal red/green fill in others. Consequence for the pulse icon: the idle frame is a template (adapts), but the colored recording/processing frames must be non-template (literal). With a single neutral-gray body, idle rendered white on a dark bar while the animating base looked gray — a visible mismatch. Resolution (Option B): pre-render two silhouette-base variants — `dark` (white base) and `light` (near-black base) — and pick at runtime via `NSApp.effectiveAppearance().bestMatchFromAppearancesWithNames_([NSAppearanceNameAqua, NSAppearanceNameDarkAqua])`. Returns `NSAppearanceNameAqua` for a light bar. Capture the variant once when the animation starts, not per frame.

## Ollama

### `/api/tags` is the lightweight enumeration endpoint
`GET <host>/api/tags` returns the list of installed models with `name`, `details.family`, etc. — fast and cheap. The heavier `/api/show` per-model call is not needed for a Settings dropdown. Wrap in a 2-second timeout; if Ollama is not running, the request fails fast with `requests.ConnectionError`. Treat that as a sentinel ("Ollama unreachable") distinct from `200 OK` with empty `models` array ("Ollama up, nothing installed").

### Embedding models show up in `/api/tags` alongside chat models
Models like `nomic-embed-text` have family `bert` or `nomic-bert` and are unsuitable for summarisation but indistinguishable from chat models by name alone. The Settings window flags them with a "· embedding" suffix as a soft warning rather than hiding them, so the user can still see what's installed.

---

## sounddevice

### `query_devices()` returns the same device under multiple `max_input_channels` values
Some devices appear with `max_input_channels=0` (output-only) and must be filtered out before populating an input-device dropdown. Filter on `dev.get("max_input_channels", 0) > 0`. De-dupe by name — the same device can show up via different host APIs (Core Audio + AVAudio on macOS).

### `check_input_health()` blocks ~1.5–3s — never call it synchronously on a UI-triggered action
The device probe opens an `sd.InputStream` and `sd.sleep(INPUT_HEALTH_SAMPLE_SECONDS * 1000)` (1.5s) to capture a signal sample, plus stream setup overhead, so each call costs ~1.5–3s. `_on_start_recording` originally ran it synchronously on the pystray callback thread as a pre-start gate *before* `recorder.start()` and the `("set_icon","recording")` enqueue — so clicking Record stalled ~2–3s before recording (and the icon animation) actually began. Live symptom: "2-3 seconds before the icon starts animating when I click Record." Fix: drop the synchronous pre-start probe entirely and rely on the existing async post-start check (`_run_recording_input_health_check` worker → `_handle_recording_input_health`), which is authoritative — it stops the recorder, deletes the wav, reverts the icon, and notifies if the device turns out bad. Behavior tradeoff: a bad device now starts recording, then auto-stops ~1.5s later with the same notification, instead of never starting. The healthy path (the norm) starts instantly. Bonus: removed a duplicate per-record probe (we used to sample the device twice — once sync pre-start, once async post-start).

---

## Diarization (pyannote.audio)

### A lazy import makes `except ImportError` dead code
`diarizer.py` imports pyannote inside `Diarizer._load()`, not at module top. So `Diarizer(token)` never raises `ImportError`, and the pipeline's `try: Diarizer(...) except ImportError: ...` "graceful degrade" guard never fired. With a token set but pyannote not installed, the workflow showed a phantom "Diarize" step and crashed mid-transcription only when `_load()` finally ran the import. Lesson: a guard around a constructor only catches errors the constructor actually raises — if the heavy import is deferred, the guard must wrap the deferred call, or (better) detect capability up front. We now use `importlib.util.find_spec("pyannote.audio")` to detect the package WITHOUT importing torch, in `diarization.is_available()`.

### `find_spec` detects a package without importing it
`importlib.util.find_spec("pyannote.audio") is not None` is true when the package is installed but does NOT import it (so no torch load, no multi-second penalty, no side effects). This is the right probe for an optional heavy dependency you want to gate on cheaply at startup and on every Settings open.

### `load_dotenv()` runs once at startup — a token pasted later is invisible until override
`__main__.py` calls `load_dotenv()` once at process start. Editing `.env` mid-session (e.g. pasting a HuggingFace token while the app is running) does NOT update `os.environ`, because the default `load_dotenv()` will not overwrite variables already set in the environment, and more importantly is not re-invoked. The Settings "Re-check" button calls `load_dotenv(override=True)` to force a re-read of `.env` into `os.environ`, then re-probes `is_available()`. Without `override=True`, a previously-unset var loads but an already-set one would not refresh.

### Honest token detection: a non-empty placeholder fools `bool(os.environ.get(...))`
`token_present()` is `bool(os.environ.get("HUGGINGFACE_ACCESS_TOKEN"))`. If the `.env` scaffold ships `HUGGINGFACE_ACCESS_TOKEN=hf_replace_me`, that is a non-empty value, so the check returns True and the app reports diarization "available" when it is not. Fix: ship the scaffold line commented out (`#HUGGINGFACE_ACCESS_TOKEN=...`) so nothing is exported until the user uncomments and fills it. The installer's `real_hf_token_present()` shell helper applies the same rule (uncommented, non-placeholder, non-empty) before writing `enabled = true`.
