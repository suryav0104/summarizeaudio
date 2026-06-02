# Color-Fill Menu-Bar Icon States — Design

Date: 2026-06-02
Status: Proposed

## Problem

The menu-bar icon only reflects two states today: idle (template silhouette) and
recording (a static colored badge icon). The pipeline's processing phase and all
error conditions are invisible in the menu bar. The `("set_icon", …)` queue
message is consumed (`window_manager._handle`, `workflow_window._handle_item`) but
**never produced**, so the processing/error icon machinery is dead wiring.

## Goal

Animate the menu-bar icon to reflect app state with a bottom-to-top color fill:

- **Recording** — red, rising sweep (sawtooth pulse)
- **Processing** — amber/yellow, rising sweep
- **Error** — static full red + small warning mark, persistent until cleared
- **Idle** — unchanged (current template silhouette, theme-adaptive)

## Approach

Pre-rendered frames + main-thread animator.

Pulse frames are generated offline by a script (same pattern as the existing icon
generators). At startup the tray loads them into memory. A `root.after(interval,
advance)` loop on the Tk main thread swaps pre-built `Image` objects into
`self._tray.icon`. No PIL compositing at runtime; no background animation thread.

Rejected alternatives:

- **Dynamic PIL compositing per tick** — composites every ~80ms on the UI thread.
  CPU + jank risk for no benefit; fill levels are a fixed set.
- **Background thread pushing frames via `ui_queue`** — ~12 msgs/sec, and the icon
  must still be set on the main thread anyway. Cross-thread churn for nothing.

## Components

### 1. Artwork — `assets/generate_pulse_icons.py` (new)

Reuse the broadcast-vector silhouette geometry (same source as the live idle icon).
Implemented in `assets/generate_pulse_icons.py` (frames reviewed via
`assets/pulse_preview.png` on light + dark bars).

- Render the mic in a neutral mid-gray `(122,127,134)` (visible on both light and
  dark menu bars, since pulse frames are **literal-color, non-template** images).
- Overlay the state color rising from the base, clipped to the silhouette mask,
  with a soft fill-line band.
- **Base anchor**: a `MIN_FILL = 0.10` floor keeps only the base foot colored at
  all times; the sweep rises from the neck up through the head capsule. The icon
  never goes fully colorless while active.
- Colors: recording = `#dc2626` (crisp red, matches the app's blocking-toast red);
  processing = green `(34,178,84)`; error = same red `#dc2626`.
- 12 fill-level frames each for `recording` and `processing`.
- One static `error` frame: full red mic + a red exclamation mark in the **right
  margin beside the mic** (the tall, narrow mic leaves empty canvas on its side;
  overlaying the mark on the red body washed it out).
- Idle frame unchanged (existing template PNG).

Because a single PNG cannot be both a theme-adaptive template AND carry a literal
color fill (`setTemplate_(True)` strips all color), the pulse silhouette base is
rendered in two appearance variants so it matches the live idle template on
whichever menu bar is active:

- `dark` variant → white silhouette base (for a dark menu bar)
- `light` variant → near-black silhouette base (for a light menu bar)

The tray picks the variant at pulse start from `NSApp.effectiveAppearance`
(`_menu_bar_variant()`), defaulting to `dark` off-darwin or if appearance can't be
read. File outputs: `assets/pulse_{recording,processing}_{dark,light}_NN.png` (12
frames each) and `assets/pulse_error.png` (one static, fully-filled red frame —
base is irrelevant). The pre-existing `assets/icon_error.png` is unused and was
deleted. A preview sheet renders each variant on its matching bar.

### 2. Tray animator — `summarizeaudio/tray.py`

New state on `TrayApp`:

- `_icon_mode: str` — `"idle" | "recording" | "processing" | "error"`
- `_pulse_frames: dict[str, list[Image]]` — recording/processing frame lists
- `_pulse_index: int`
- `_pulse_after_id` — cancelable `root.after` handle

Methods:

- `_start_pulse(mode)` — set `_icon_mode`, reset index, schedule the sawtooth loop
  (advance index, wrap to 0 at the end).
- `_advance_pulse()` — set `self._tray.icon` to the current frame, bump index,
  reschedule via `root.after`. **Interval ≈ 167ms** (12 frames ⇒ ~2s/loop).
- `_set_static(state)` — cancel any pulse loop, set the idle (template) or error
  (literal) icon. Replaces the colored-state branch of `_set_icon`.

`_set_icon(state)` routes: idle/error → `_set_static`; recording/processing →
`_start_pulse`. The `_summarizeaudio_template_icon` flag stays `True` only for idle.

### 3. Producer wiring

- **Recording** — `_on_start_recording` sets recording mode (red pulse);
  `_on_stop_recording` and health-stop paths set idle. Already main-thread.
- **Processing** — the pipeline runs in the WorkflowWindow worker thread, which
  cannot touch the tray. Wrap the `_pipeline.run(...)` call sites
  (`workflow_window.py` ~1016–1032): `ui_queue.put(("set_icon","processing"))`
  before, `("set_icon","idle"))` in a `finally`. Feeds the existing
  `window_manager._handle` "set_icon" → `on_icon_state` → tray path.
- **Error** — `window_manager._handle` "error"/"fatal_error" branches call
  `on_icon_state("error")`. Input-health errors in the tray (which call `notify`
  directly on the main thread) set the error icon directly.

### 4. Error clear logic

Error is persistent. Clear triggers by error source:

Error is persistent and owned by two separate flags depending on source:

- **Device errors** → `TrayApp._device_error_active`. A device error usually
  surfaces with no window open (startup/record-start probe), so window-dismiss is
  the wrong clear signal — the mic is still missing. Clearing on dismiss would flip
  to idle and the 3s re-probe would flip back to error (visible flicker). Device
  errors clear ONLY via re-probe recovery or a clean recording start.
- **Pipeline errors** → `WindowManager._error_active`. These fire while a workflow
  window is open, so window-dismiss is a natural clear signal alongside the next
  successful run.

| Source | Clear triggers |
| --- | --- |
| Device (mic missing, channel mapping, probe error) | (d) periodic health re-probe recovers, or next clean recording start |
| Pipeline (Ollama down, transcription failed) | (c) window dismiss, or next successful pipeline run |

- **(c) window dismiss** — when app windows transition open→all-closed
  (tracked by `WindowManager._prev_any_open`), clear `_error_active`. Applies to
  pipeline errors only.
- **(d) health recovery** — a lightweight periodic re-probe (~3s) **only while a
  device error is active**, reusing `check_input_health`. A healthy report clears
  it. Today health is only checked at startup and record-start, so recovery is not
  detected without this.
- **next success** — on processing-stop/idle after a successful run, and on a clean
  recording start, clear the error flag.

The recording-start clear runs through `ui_queue` (`("set_icon","recording")`) so
`WindowManager._error_active` is cleared on the main thread; the tray clears its
own `_device_error_active` inline before enqueueing.

## Data flow

```
recording:  _on_start_recording (pystray thread) ──ui_queue("set_icon","recording")
              ──▶ _handle (clears _error_active) ──▶ on_icon_state ──▶ _start_pulse
stop:       _on_stop_recording (pystray thread) ──ui_queue("set_icon","idle")
              ──▶ on_icon_state ──▶ _set_static("idle") + rebuild menu (main thread)
              then ──ui_queue("show_workflow",…)
processing: worker thread ──ui_queue("set_icon","processing")──▶ _handle
              ──▶ on_icon_state ──▶ _start_pulse("processing")
            worker finally ──ui_queue("set_icon","idle")──▶ _set_static("idle")
error:      post_error ──ui_queue("error",…)──▶ _handle ──▶ on_icon_state("error")
              ──▶ _set_static("error")
            input-health err (tray, main thread) ──▶ _set_static("error")
clear:      _clear_error_on_window_dismiss (all closed) ──▶ clear pipeline error
            device-error re-probe loop (healthy) ──▶ clear device error
            successful run / clean record start ──▶ clear
```

## Threading

- All `self._tray.icon` writes and `root.after` scheduling happen on the Tk main
  thread (animator loop, pump, activation-policy).
- **Critical:** because the pulse loop now writes `self._tray.icon` continuously on
  the main thread, NO pystray-callback-thread path (start/stop recording) may touch
  the icon directly — concurrent `NSStatusItem` mutation from two threads deadlocks
  AppKit, freezing the main thread (symptom: stop hangs, workflow popup never
  appears). Both `_on_start_recording` and `_on_stop_recording` therefore route the
  icon change through `ui_queue` so every icon write is serialized on the main
  thread.
- The only cross-thread hop is the queue `put(("set_icon",…))`, the safe pattern.
- The error re-probe spawns a daemon worker (like the existing health checks) and
  posts results back through `_input_health_queue`, consumed on the main thread.

## Testing

- Frame generation: assert the script writes the expected frame counts and sizes.
- Animator: unit-test `_start_pulse`/`_advance_pulse`/`_set_static` with a fake
  tray + a stub `after` (assert index wraps, loop cancels on static).
- Producer wiring: assert `("set_icon","processing")`/`("set_icon","idle")` are
  enqueued around a stubbed `_pipeline.run`.
- Error clear: assert all-closed transition, healthy re-probe, and successful run
  each clear `_icon_mode`/`_error_active`.
- Honor existing tray test fixtures (`_fake_wm` must keep `block_for_open_window`,
  `on_rebuild_tray` kwargs).

## Open questions / risks

- Sweep interval + frame count tuning is a visual judgment; settle via the preview
  sheet before install (same loop used for the dock icon).
- Gray "unfilled" tone must read on both light and dark menu bars — verify in the
  preview on both backgrounds.
- The error exclamation mark on a ~22px icon risks clutter; verify legibility.
```
