# SummarizeAudio — UI Window Redesign & Dock Icon Fix

**Date:** 2026-05-13
**Status:** Approved

---

## Problem

1. **Python dock icons.** Every window (workflow progress, history) is launched as a separate `subprocess.Popen([sys.executable, ...])`. macOS shows a bare Python duck icon in the dock for each. With a workflow and history window open simultaneously, users see 1–2 Python icons they cannot explain or remove.

2. **Oversized windows.** `WorkflowWindow` is 1440×900px and `HistoryWindow` is 1480×940px — nearly full-screen for a helper app.

3. **No window reuse.** Triggering a new tray action while a window is open spawns another independent window. There is no way to focus or retarget the existing one.

---

## Goals

- Zero Python dock icons under normal use on macOS.
- Windows sized proportionally to their content (~560×480px).
- Tray actions reuse or close/replace the existing window rather than stacking new ones.
- Both `WorkflowWindow` and `HistoryWindow` get the same treatment.
- Summary preview stays inline on completion (user dismisses manually).
- Windows and Linux: subprocess spawning for windows is preserved. Window reuse via `WindowManager` applies on all platforms.

---

## Architecture Changes

### Replace `rumps` with `pystray` on macOS

`rumps` holds the main thread, which forces all Tk windows into subprocesses. `pystray` runs in a background thread on macOS, freeing the main thread for `tk.mainloop()`.

`tray.py` already has a full `pystray` implementation (`_rebuild_menu`, `_tray.run(setup=setup)`). The macOS-specific `_run_rumps()` path and `_rebuild_rumps_menu()` are deleted. `TrayApp.run()` calls the pystray path on all platforms.

`rumps` is removed from `pyproject.toml` dependencies.

### Activation policy at startup (macOS only)

In `__main__.py`, this call must happen **before any `import tkinter`** — Tk initialises AppKit state on import, which would invalidate the policy. All tkinter imports in the codebase are already inside functions or class bodies (not at module top level), so the call order is safe as long as `__main__.py` applies the policy before creating `TrayApp`.

```python
# __main__.py — very first thing, before any other imports that touch Tk
if sys.platform == "darwin":
    try:
        import AppKit
        NSApp = AppKit.NSApplication.sharedApplication()
        NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    except Exception:
        pass  # non-fatal: best-effort dock suppression
```

This marks the entire process as a menu bar accessory. macOS does not show accessory apps in the dock or CMD+Tab. **Risk:** must be validated on the actual Python/Tk build as the first implementation step (see Risk section).

### Tk root window ownership

`WindowManager` creates and owns a single hidden `tk.Tk()` root at initialisation:

```python
class WindowManager:
    def __init__(self, ui_queue: queue.Queue) -> None:
        self._root = tk.Tk()
        self._root.withdraw()   # hidden — never shown directly
        self._root.after(100, self._pump)
        ...
```

`WorkflowWindow` and `HistoryWindow` use `tk.Toplevel(self._root)` instead of `tk.Tk()`. This is the standard Tk multi-window pattern: one hidden root drives the event loop; all visible windows are Toplevels attached to it.

`root.mainloop()` is called on the main thread in `__main__.py` after `TrayApp.run()` is started on its background thread:

```python
# __main__.py
tray = TrayApp(window_manager=wm)
threading.Thread(target=tray.run, daemon=True).start()
wm.root.mainloop()   # blocks main thread — Tk pump runs here
```

When the user quits, `tray.run()` calls `root.after(0, root.quit)` to stop the mainloop cleanly.

### Queue pump

`WindowManager._pump()` replaces both the `UIDispatcher.drain()` loop in `pystray`'s setup callback and the per-window `_pump_queue` methods:

```python
def _pump(self) -> None:
    try:
        while True:
            item = self._ui_queue.get_nowait()
            self._handle(item)
    except queue.Empty:
        pass
    if self._root.winfo_exists():
        self._root.after(100, self._pump)
```

This is the single drain point. `WorkflowWindow` and `HistoryWindow` no longer own their own `_pump_queue` methods.

### New `WindowManager` class

`window_manager.py` is a new module. It owns the Tk root, the queue pump, and all window instances.

```python
class WindowManager:
    def __init__(self, ui_queue: queue.Queue) -> None: ...

    # Called from queue pump (main thread) in response to tray commands:
    def show_workflow(self, mode: str, source: Path | None = None) -> None: ...
    def show_history(self) -> None: ...
    def close_all(self) -> None: ...   # called on quit

    @property
    def root(self) -> tk.Tk: ...       # exposed for mainloop() in __main__.py
```

`TrayApp` receives a `WindowManager` instance at construction and posts `("show_workflow", mode, source)` and `("show_history",)` items to `ui_queue` from menu callbacks. `_handle()` in `WindowManager` dispatches these.

### Pipeline guard

`TrayApp._pipeline_running` guard **stays in `TrayApp`**. The tray menu already disables workflow actions while a pipeline runs (current behaviour). This is unchanged.

The `WindowManager` window reuse rules apply only to window state, not pipeline state:

| Situation | Action |
|---|---|
| `show_workflow` called, no window open | Create new `WorkflowWindow` |
| `show_workflow` called, window open in idle or done state (chooser / summary / message) | Retarget in place; bring to focus |
| `show_workflow` called, window open and pipeline actively running | Bring existing window to focus; do not interrupt pipeline or open a second window |
| `show_history` called, no history window open | Create new `HistoryWindow` |
| `show_history` called, history window already open | Bring to focus; call `refresh()` |

The "pipeline actively running" row is consistent with the existing guard: the tray already prevents launching a second pipeline. `WindowManager` surfaces the existing window rather than blocking silently.

### Remove subprocess entry points

The following modules lose their `__main__` wrappers and argparse:

- `workflow_window.py` — `WorkflowWindow` becomes a plain class instantiated by `WindowManager`. The file picker (`_native_audio_picker`, `_native_text_picker`) is already called inline in `WorkflowWindow._choose_file()` — no change needed there.
- `history_window.py` — same treatment.
- `chooser_window.py` — `main()` and argparse removed. `_native_audio_picker` / `_native_text_picker` helpers stay as module-level functions (used by `workflow_window.py`). The file is kept as a helper module, not deleted.
- `prompt_editor.py` — deleted. The prompt editor UI already lives inline in `workflow_window.py` (`_render_prompt`). `tray.py`'s `_on_override_dialog` and `_on_name_dialog` (which spawn `prompt_editor` as a subprocess) are replaced: these events are now handled directly by `WorkflowWindow._handle_item()`, which already has the inline `_render_prompt` and `_render_name` states. `TrayApp` no longer needs to handle `override_dialog` and `name_dialog` queue items — they go directly to the window.

The `tray.py` methods removed: `_launch_workflow()`, `_launch_history()`, `_pick_file()`, `_on_override_dialog()`, `_on_name_dialog()`.

---

## Threading model (per platform)

### macOS (after this change)

```
Main thread: tk.mainloop() — owned by WindowManager.root
  └── root.after(100, wm._pump)
        └── dispatches queue items to WindowManager / WorkflowWindow / HistoryWindow

pystray thread (background, new on macOS):
  └── renders tray icon + native NSMenu
  └── menu callbacks → ui_queue.put(...)

Pipeline worker thread (one at a time):
  └── posts progress / results / errors → ui_queue
```

### Windows / Linux (unchanged threading)

```
pystray setup thread (continues as before):
  └── runs UIDispatcher.drain() every 100ms
  └── menu callbacks → ui_queue.put(...)

WindowManager still used on Windows/Linux for window reuse,
but its _pump runs in the pystray setup thread (not a Tk mainloop).
WorkflowWindow / HistoryWindow are still Toplevel windows created
from the same Tk root, but root.mainloop() is called from the
pystray setup thread on Windows/Linux.

Pipeline worker thread: unchanged.
```

---

## WorkflowWindow Redesign

### Size and layout

| Property | Current | New |
|---|---|---|
| Default size | 1440×900px | 560×480px |
| Min size | 1180×700px | 480×400px |
| Resizable | Yes | Yes |

The window keeps its existing states and content but uses tighter padding and a layout that fits the smaller canvas. Font sizes and wraplengths adjusted proportionally.

### States (unchanged)

`chooser` → `processing` → `prompt` → `name` → `summary` → `message`

The step tracker (✓ / → / •) and determinate + marquee progress bars are retained as-is.

### Constructor change

`WorkflowWindow` no longer creates a `tk.Tk()` root. It receives the shared root from `WindowManager`:

```python
class WorkflowWindow:
    def __init__(self, root: tk.Tk, cfg: AppConfig, ui_queue: queue.Queue) -> None:
        self._win = tk.Toplevel(root)
        ...
```

### Retarget method

```python
def retarget(self, mode: str, source: Path | None = None) -> None:
    """Switch this window to a new mode without closing it.
    Resets all state, cancels any pending resolver, re-renders, brings to focus.
    Only valid when no pipeline is running (idle or done state).
    """
```

---

## HistoryWindow Redesign

### Size

| Property | Current | New |
|---|---|---|
| Default size | 1480×940px | 740×520px |
| Min size | 1240×780px | 600×420px |

History shows a session list + detail panel. A wider default (740px vs 560px) gives the two-column layout enough room. Content and layout otherwise unchanged.

### Constructor change

Same as `WorkflowWindow` — receives shared root, uses `tk.Toplevel(root)`.

### Refresh method

```python
def refresh(self) -> None:
    """Reload session list and bring to focus."""
```

---

## Migration Summary

| File | Change |
|---|---|
| `__main__.py` | Apply activation policy (macOS, before any Tk); create `WindowManager`; start `TrayApp` in background thread; call `root.mainloop()` on main thread |
| `tray.py` | Delete `_run_rumps()`, `_rebuild_rumps_menu()`, `_launch_workflow()`, `_launch_history()`, `_pick_file()`, `_on_override_dialog()`, `_on_name_dialog()`; receive `WindowManager` at construction; post `show_workflow` / `show_history` to `ui_queue` from menu callbacks |
| `window_manager.py` | New file — owns Tk root, queue pump, `WorkflowWindow` and `HistoryWindow` instances |
| `workflow_window.py` | Remove `__main__` / `argparse` / `main()`; constructor takes `(root, cfg, ui_queue)`; add `retarget()` method; remove `_pump_queue()`; resize to 560×480px |
| `history_window.py` | Remove `__main__` / `argparse` / `main()`; constructor takes `(root, cfg)`; add `refresh()` method; remove own pump; resize to 740×520px |
| `chooser_window.py` | Remove `main()` and `argparse`; keep `_native_audio_picker` and `_native_text_picker` as helpers |
| `prompt_editor.py` | Delete |
| `pyproject.toml` | Remove `rumps` dependency |

---

## Risk: Tk + activation policy compatibility

`chooser_window.py` documented a crash when calling `setActivationPolicy_` after Tk had already initialised. The fix is to call it before any `import tkinter` in the process.

All existing Tk imports in the codebase are inside function bodies or class constructors — not at module top level — so no `import tkinter` runs until `WindowManager.__init__()` is called. As long as `__main__.py` applies the policy before constructing `WindowManager`, the order is guaranteed.

**First implementation task:** validate `setActivationPolicy_` → `import tkinter` → `tk.Tk()` → `tk.Toplevel()` in isolation on the project's Python/Tk build. If Tk windows render correctly with no dock icon, proceed. If not:

1. Accept one app-named dock icon (not a Python icon — pystray gives the process a real name) and suppress it at packaging time via `py2app` + `LSUIElement = 1` in `Info.plist`.
2. Use `ctypes`-based Objective-C messaging instead of `AppKit` import to avoid framework init side effects.

---

## Testing

| Area | Approach |
|---|---|
| Activation policy validation | Run in isolation before any other work: verify `setActivationPolicy_` succeeds before Tk init, Toplevel windows open, no dock icon appears |
| Dock icon suppression | Manual: launch app, open workflow + history, confirm no Python icon in dock |
| Window reuse — idle/done | Open workflow window to done state; trigger new action from tray; confirm same window retargets |
| Window reuse — running | Open workflow window with active pipeline; trigger new action; confirm existing window comes to focus, no new window opens |
| History reuse | Open history; click History again from tray; confirm focus + refresh, not a second window |
| Quit handling | Confirm `root.quit()` is called cleanly and all Toplevels close |
| Existing unit tests | Must pass unchanged — pipeline, config, sessions, renamer, transcriber, summarizer |
| Windows/Linux regression | Tray icon, all three workflow modes, file picker, notifications work after `rumps` removal |
| Test file updates | `test_tray.py` mocks for `_launch_workflow` replaced with `WindowManager` mocks; `test_workflow_window.py` and `test_history_window.py` updated to pass a shared root fixture |
