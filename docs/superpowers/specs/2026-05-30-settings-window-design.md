# Settings Window — Design

**Date:** 2026-05-30
**Status:** Approved
**Scope:** Add a Settings window for two configurable values (Input Audio device, Summarization model). Replace the existing inline "Summarization Model" submenu with two status-display tray items below the History separator.

---

## Goals

1. Give the user a single place to change the input audio device and the Ollama summarization model.
2. Make the currently configured values visible at-a-glance in the tray menu.
3. Remove the hardcoded "Fast Mode / High Quality Mode" submenu and replace it with a dynamic list of models actually installed in the local Ollama runtime.
4. Reuse the existing window manager / queue / thread-safety patterns without inventing new infrastructure.

## Non-goals

- Diarization toggle (deliberately out of scope; remains env-var gated by `HUGGINGFACE_ACCESS_TOKEN`).
- Whisper model picker (out of scope for this iteration).
- Editing the summarization prompt or other config fields.
- Persisting per-session settings; settings are global.

---

## Tray menu changes

**Before** (`summarizeaudio/tray.py:444-448`):

```
Summarization Model           (disabled header)
  Fast Mode (gemma3:4b)
  High Quality Mode (gemma3:12b)
```

**After**:

```
SummarizeAudio
─────────────────
Start Recording   |   Stop Recording
Transcribe & Summarize Audio File…
Summarize Text File…
─────────────────
History…
─────────────────
Input Audio: <resolved-name>          ← NEW
Summarization: <model-name>           ← NEW
─────────────────
Quit
```

Both new items open the Settings window when clicked. They are display-only labels with click handlers that enqueue `("show_settings",)` onto `ui_queue`.

### Label resolution

**Input Audio:**
- If `cfg.recording.input_device` is `None` or empty string → resolve auto-detect at menu-build time via `sd.query_devices()` + the existing BlackHole-preference logic in `recorder.py`. Display as `Input Audio: Auto (<resolved-name>)`. If resolution fails, display `Input Audio: Auto (none)`.
- Else → display `Input Audio: <cfg.recording.input_device>` verbatim.

**Summarization:**
- Always display `Summarization: <cfg.ollama.model>` verbatim (e.g., `Summarization: gemma3:4b`).
- If the configured model is no longer installed (verified lazily when the Settings window opens, not on every menu rebuild), prefix with `⚠ ` — i.e., `Summarization: ⚠ gemma3:4b`. The warning state is reset whenever the Settings dropdown is reopened and the model becomes either available again or replaced.

`sd.query_devices()` runs only when `_rebuild_menu()` runs (on settings change or icon-state change), not every pump tick.

---

## Settings window

### Module: `summarizeaudio/settings_window.py` (new)

Tk Toplevel class with constructor signature parallel to the existing windows:

```python
class SettingsWindow:
    def __init__(
        self,
        parent_root: tk.Tk,
        cfg: AppConfig,
        ui_queue: queue.Queue,
        pipeline_active: bool = False,
    ) -> None: ...
    def show(self) -> None: ...
    def close(self) -> None: ...
    @property
    def _win(self) -> tk.Toplevel: ...   # for WindowManager._win_alive checks
```

### Layout

Fixed size ~420 × 240 px, non-resizable, styled to match Workflow / History windows:

```
┌─ Settings ───────────────────────────────────────┐
│                                                  │
│  Input Audio                                     │
│  ┌────────────────────────────────────────────┐  │
│  │ Auto-detect (BlackHole)                  ▾ │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  Summarization Model                             │
│  ┌────────────────────────────────────────────┐  │
│  │ gemma3:4b                                ▾ │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  [Banner: "Changes take effect on the next       │
│   run."  — visible only when pipeline_active]    │
│                                                  │
│                          [ Cancel ]  [ Apply ]   │
└──────────────────────────────────────────────────┘
```

### Combobox population

Both comboboxes are `ttk.Combobox(state="readonly")`.

**Input Audio:**
- First entry: `"Auto-detect"` (or `"Auto-detect (<resolved-name>)"` when resolution succeeds).
- Followed by every input device returned by `sd.query_devices()` that has `max_input_channels > 0`.
- If `sd.query_devices()` raises: dropdown contains only `"Auto-detect"`; log the exception at WARN.
- Initial selection reflects current `cfg.recording.input_device` (empty/None → Auto-detect; configured name → that entry; configured name not found in current devices → injected first as `"<name> (not connected)"`, selected).

**Summarization Model:**
- Populated by `ollama_client.list_installed_models()`:
  - Returns `None` → dropdown disabled, placeholder text `"Ollama not running — start Ollama and reopen Settings"`. Apply button disabled.
  - Returns `[]` → dropdown disabled, placeholder text `"No models installed. Run \`ollama pull gemma3:4b\` and reopen."`. Apply button disabled.
  - Returns non-empty list → each entry shows the model name; non-chat models get a suffix indicator (e.g., `nomic-embed-text · embedding`).
- If current `cfg.ollama.model` is not in the returned list → inject as the first entry, labeled `"<name> (not installed)"`, selected. Apply remains enabled so the user can pick a different model.

### Apply button

Single click handler (runs on the Tk main thread):

1. Read the two combobox selections.
2. Translate display labels back to stored values:
   - `"Auto-detect (...)"` → store empty string in `cfg.recording.input_device`.
   - Any other Input Audio entry → store the bare device name.
   - Summarization entry → store the bare model name (strip the ` · embedding` or `(not installed)` suffix if present, though "not installed" should never be applied since the entry remains selected only when the user hasn't changed selection).
3. Call `save_config(cfg)`.
4. Enqueue `("rebuild_tray_menu",)` on `ui_queue`.
5. Destroy the window.

On `save_config` exception: show inline error label inside the window (`"Failed to save settings: <reason>"`), keep window open, revert in-memory cfg to pre-Apply values.

### Cancel button

Destroys the window; no config mutation, no tray refresh.

### Key bindings

- `Return` → Apply (if enabled).
- `Escape` → Cancel.
- `Cmd-W` (mac) / `Alt-F4` (others) → Cancel.

### Active-pipeline banner

A thin amber strip with the text `"Changes take effect on the next run."`, visible only when `pipeline_active=True` is passed to the constructor. WindowManager passes the value derived from the most recent `_on_icon_state` event (`"processing"` or `"recording"` → True; otherwise False).

---

## Module: `summarizeaudio/ollama_client.py` (new)

Single public function:

```python
@dataclass(frozen=True)
class ModelInfo:
    name: str          # e.g., "gemma3:4b"
    family: str | None # e.g., "gemma3", "bert" — used to flag non-chat models

def list_installed_models(host: str, timeout: float = 2.0) -> list[ModelInfo] | None:
    """Return installed models, or None if Ollama is unreachable.

    Hits GET <host>/api/tags. Returns [] when Ollama is up but no models are
    installed. Returns None on connection refused / timeout / unparseable
    response.
    """
```

Implementation: `urllib.request.urlopen(f"{host}/api/tags", timeout=timeout)`. JSON parse. For each entry in `models[]`, extract `name` and `details.family` (may be missing on older responses; default to `None`).

Non-chat flagging is done by the caller: a model is treated as non-chat when its name contains `"embed"` or its family is `"bert"` / `"nomic-bert"`. The flagging is purely cosmetic; users can still select any model.

---

## WindowManager changes

### State

Add `self._settings_win: SettingsWindow | None = None`.

### Methods

```python
def show_settings(self) -> None:
    # Settings can stack on Workflow/History (Q3(b)). It does NOT block them
    # and is NOT blocked by them.
    from summarizeaudio.settings_window import SettingsWindow

    if self._settings_win is not None and _win_alive(self._settings_win._win):
        self._settings_win._focus()
        return

    self._settings_win = SettingsWindow(
        self._root, self._cfg, self._ui_queue,
        pipeline_active=self._last_pipeline_active,
    )
    self._settings_win.show()
```

Track `self._last_pipeline_active: bool = False`, updated from a new branch in `_handle`:

```python
elif kind == "set_icon":
    _, state = item
    self._last_pipeline_active = state in {"recording", "processing"}
    if self._on_icon_state is not None: ...
```

### `_handle` additions

```python
elif kind == "show_settings":
    self.show_settings()
elif kind == "rebuild_tray_menu":
    if self._on_rebuild_tray is not None:
        try:
            self._on_rebuild_tray()
        except Exception:
            log.debug("rebuild_tray callback error", exc_info=True)
```

### `_sweep_stale_window_refs` additions

```python
if self._settings_win is not None and not _win_alive(self._settings_win._win):
    self._settings_win = None
```

### Constructor change

Add optional `on_rebuild_tray: Callable[[], None] | None = None` parameter, store as `self._on_rebuild_tray`. Tray registers a callback that calls `icon.update_menu()`.

### `block_for_open_window` is unchanged

Per Q3(b), Settings does not participate in the Workflow ↔ History blocking rule.

### `_update_activation_policy` adjustment

The "any window open" check should include `_settings_win` so the dock icon and activation policy reflect Settings being visible:

```python
any_open = (
    (self._workflow_win is not None and _win_alive(self._workflow_win._win))
    or (self._history_win is not None and _win_alive(self._history_win._win))
    or (self._settings_win is not None and _win_alive(self._settings_win._win))
)
```

---

## Tray changes (`summarizeaudio/tray.py`)

### Constructor

Pass an `on_rebuild_tray` callback to `WindowManager`:

```python
self._window_manager = WindowManager(
    self._cfg, self._ui_queue,
    on_icon_state=self._on_icon_state,
    on_rebuild_tray=self._on_rebuild_tray_request,
)
```

```python
def _on_rebuild_tray_request(self) -> None:
    # Runs on the Tk main thread. Tray icon's update_menu is documented
    # thread-safe.
    self._rebuild_menu()
```

### `_rebuild_menu`

- Remove the `"Summarization Model"` disabled header, `_on_quality_fast`, `_on_quality_high`, `_model_label` callsites in `_rebuild_menu`.
- Delete the `_on_quality_fast`, `_on_quality_high`, `_model_label`, and `_set_model` methods entirely.
- Add two new `MenuItem` entries below the existing `History…` separator, before the `Quit` separator:

```python
items.append(pystray.MenuItem(self._input_audio_label(), self._on_settings_click))
items.append(pystray.MenuItem(self._summarization_label(), self._on_settings_click))
```

### New label helpers on TrayApp

```python
def _input_audio_label(self) -> str:
    configured = self._cfg.recording.input_device
    if configured:
        return f"Input Audio: {configured}"
    resolved = _resolve_auto_input_device()  # None on failure
    if resolved:
        return f"Input Audio: Auto ({resolved})"
    return "Input Audio: Auto (none)"

def _summarization_label(self) -> str:
    return f"Summarization: {self._cfg.ollama.model}"

def _on_settings_click(self, icon, item) -> None:
    self._ui_queue.put(("show_settings",))
```

### `_resolve_auto_input_device`

New module-level helper (or imported from `recorder.py` if a similar helper already exists). Returns the BlackHole-preferred input device name, or the first input device, or `None` on any exception.

---

## Data flow

### Open Settings

```
User clicks "Input Audio: ..." or "Summarization: ..." (pystray thread)
  → enqueue ("show_settings",)
WindowManager._pump (main thread) drains queue
  → _handle dispatches to show_settings()
  → if already open: focus existing
  → else: SettingsWindow(...).show()
SettingsWindow.__init__ (main thread)
  → ollama_client.list_installed_models(cfg.ollama.host)
  → sd.query_devices()
  → builds comboboxes
```

### Apply

```
User clicks Apply (main thread)
  → window reads selections
  → mutates cfg in place
  → save_config(cfg)
  → enqueue ("rebuild_tray_menu",)
  → window destroys self
WindowManager._pump (main thread) drains queue
  → _handle dispatches "rebuild_tray_menu" to on_rebuild_tray callback
TrayApp._on_rebuild_tray_request (main thread)
  → self._rebuild_menu()
    → reads cfg.recording.input_device, cfg.ollama.model
    → resolves "Auto" name if needed
    → pystray menu rebuilt; icon.update_menu() invoked under the hood
```

### Cancel

Identical to Apply minus mutate/save/enqueue. Just destroy.

---

## Threading model

- **Main thread (Tk):** owns the Settings window, all comboboxes, all button callbacks, `save_config`. Drives `_pump`.
- **pystray thread:** the two new tray callbacks run here and only call `ui_queue.put(...)`. No Tk calls.
- **`on_rebuild_tray` callback:** runs on the main thread because it's invoked from `_handle` (which is called from `_pump`). pystray's menu mutation via `self._tray.menu = pystray.Menu(*items)` is documented thread-safe (internally just flips a flag the menu thread observes).

No new threads are introduced. No locks are required.

---

## Error handling

| Scenario | Handling |
|---|---|
| Ollama unreachable on Settings open | Summarization combobox disabled, placeholder explains. Apply disabled. |
| Ollama up, no models installed | Same as above with a different placeholder. |
| Configured model not in installed list | Inject `"<name> (not installed)"` as first entry, selected. Tray label gets ⚠ prefix. Apply enabled. |
| `sd.query_devices()` fails | Dropdown contains only "Auto-detect". Warn-log the exception. |
| Configured input device no longer present | Inject `"<name> (not connected)"` as first entry, selected. Apply enabled. |
| `save_config` raises | Inline error label, window stays open, in-memory cfg reverted. |
| User opens Settings during active pipeline | Allowed. Amber banner shows "Changes take effect on the next run." |
| Settings already open + click on a tray status item | Focus the existing window, no second instance, no toast. |
| User opens Workflow / History while Settings is open | Workflow / History opens normally (Settings does not block). Workflow ↔ History still block each other. |

---

## Testing

### New file: `tests/test_settings_window.py`

- Construct SettingsWindow with a fake `cfg`, `ui_queue`, patched `ollama_client.list_installed_models` and `sd.query_devices`.
- Assert two `ttk.Combobox` widgets exist with expected values populated.
- Assert Apply mutates `cfg`, calls `save_config`, enqueues `("rebuild_tray_menu",)`, and destroys the window.
- Assert Cancel destroys the window without touching `cfg` or `save_config`.
- Assert "Ollama not running" path (mock returning `None`) disables Summarization combobox and Apply button.
- Assert "no models installed" path (mock returning `[]`) sets the empty-list placeholder.
- Assert "configured model not in list" path injects "(not installed)" entry as selected.
- Assert pipeline-active banner appears only when constructor flag is True.
- Assert "Auto-detect" selection stores empty string back to `cfg.recording.input_device`.

### New file: `tests/test_ollama_client.py`

- Mock `urllib.request.urlopen` to return a canned `/api/tags` payload with two models, one having `details.family = "bert"`.
- Assert `list_installed_models()` parses model name + family correctly.
- Assert `URLError` / `ConnectionRefusedError` → returns `None`.
- Assert empty `models: []` → returns `[]`.
- Assert malformed JSON → returns `None`.

### Extend: `tests/test_window_manager.py`

- Assert `("show_settings",)` queue message routes to `WindowManager.show_settings()`.
- Assert opening Settings when Workflow is open does NOT show the blocking toast.
- Assert opening Settings when Settings is already open focuses the existing window (no second instance constructed).
- Assert `_sweep_stale_window_refs` clears `_settings_win` after destroy.
- Assert `("rebuild_tray_menu",)` invokes the `on_rebuild_tray` callback.
- Assert `_update_activation_policy` keeps the dock icon visible while Settings is the only open window.

### Extend: `tests/test_tray.py`

- Assert the new menu items appear below the History separator in the order Input Audio then Summarization.
- Assert clicking either new item enqueues `("show_settings",)`.
- Assert the old "Summarization Model" header and Fast/High Quality items are gone.
- Assert `_on_rebuild_tray_request` triggers `_rebuild_menu`.
- Update `_fake_wm()` and `_fake_wm_immediate()` to include the new `show_settings` attribute and accept `on_rebuild_tray` kwarg.
- Assert Input Audio label uses `Auto (<name>)` when `cfg.recording.input_device` is empty.

### Pre-existing failures

Per project memory, 7 pre-existing failures exist in `tests/test_workflow_window.py` and one in `tests/test_history_window.py`. Verify against HEAD baseline before claiming any new regressions.

---

## File summary

| File | Type | Notes |
|---|---|---|
| `summarizeaudio/settings_window.py` | new | ~250 LOC, Tk Toplevel + comboboxes + Apply/Cancel |
| `summarizeaudio/ollama_client.py` | new | ~60 LOC, single function + dataclass |
| `summarizeaudio/window_manager.py` | modify | add `show_settings`, `_settings_win`, `_last_pipeline_active`, `on_rebuild_tray` ctor arg, sweep entry, two new `_handle` branches, activation-policy update |
| `summarizeaudio/tray.py` | modify | remove Fast/High Quality items + helpers; add two new menu items, two label helpers, `_on_settings_click`, `_on_rebuild_tray_request`; pass new ctor kwarg to WindowManager |
| `summarizeaudio/recorder.py` | possibly modify | expose `_resolve_auto_input_device()` if not already accessible from tray |
| `summarizeaudio/config.py` | unchanged | existing fields cover both settings |
| `tests/test_settings_window.py` | new | per Testing section |
| `tests/test_ollama_client.py` | new | per Testing section |
| `tests/test_window_manager.py` | modify | extend per Testing section |
| `tests/test_tray.py` | modify | extend per Testing section |
| `docs/adr.md` | append | one ADR entry: "Settings window + dynamic Ollama model list" |
| `docs/learnings.md` | append-if-applicable | only if a new gotcha surfaces during implementation |
| `docs/architecture.md` | update | reflect new `settings_window.py` and `ollama_client.py` in component list and Mermaid diagram |
