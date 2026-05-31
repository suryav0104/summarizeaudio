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

### Window refs outlive their Tk widgets
When the user clicks the window's X button, the underlying Tk widget is destroyed but the Python reference (`WindowManager._workflow_win`, etc.) still points at it. `None`-based gating then produces false positives forever. `_sweep_stale_window_refs()` runs on every pump tick (main thread), checks `_win_alive()`, and resets dead refs to `None`. Without this sweep, the "is a window open?" check is unreliable.

---

## Ollama

### `/api/tags` is the lightweight enumeration endpoint
`GET <host>/api/tags` returns the list of installed models with `name`, `details.family`, etc. — fast and cheap. The heavier `/api/show` per-model call is not needed for a Settings dropdown. Wrap in a 2-second timeout; if Ollama is not running, the request fails fast with `requests.ConnectionError`. Treat that as a sentinel ("Ollama unreachable") distinct from `200 OK` with empty `models` array ("Ollama up, nothing installed").

### Embedding models show up in `/api/tags` alongside chat models
Models like `nomic-embed-text` have family `bert` or `nomic-bert` and are unsuitable for summarisation but indistinguishable from chat models by name alone. The Settings window flags them with a "· embedding" suffix as a soft warning rather than hiding them, so the user can still see what's installed.

---

## sounddevice

### `query_devices()` returns the same device under multiple `max_input_channels` values
Some devices appear with `max_input_channels=0` (output-only) and must be filtered out before populating an input-device dropdown. Filter on `dev.get("max_input_channels", 0) > 0`. De-dupe by name — the same device can show up via different host APIs (Core Audio + AVAudio on macOS).
