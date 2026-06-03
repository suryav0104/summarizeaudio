from __future__ import annotations

import os
import platform
import queue
import signal
import subprocess
import sys
import threading
import traceback
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pystray
from PIL import Image

from summarizeaudio import diarization
from summarizeaudio.config import load_config
from summarizeaudio.error_handler import format_error
from summarizeaudio.notifier import notify
from summarizeaudio.ollama_client import prewarm_async
from summarizeaudio.recorder import Recorder, check_input_health, resolve_auto_input_device_name

if TYPE_CHECKING:
    from summarizeaudio.window_manager import WindowManager

ASSETS = Path(__file__).parent.parent / "assets"
LOCK_FILE = Path.home() / ".summarizeaudio" / "app.lock"
log = logging.getLogger(__name__)


def _patch_pystray_darwin(icon: "pystray.Icon") -> None:
    """Work around macOS Tahoe (NSSceneStatusItem) click-handling regression.

    pystray calls NSStatusItem.setMenu_(), which on Tahoe may silently fail
    to attach the popup menu to the click target.  The reliable modern path is:
      1. Leave statusItem.menu NIL (so the button's action selector fires).
      2. In the action handler, manually pop up the stored NSMenu.

    We monkey-patch _update_menu to skip setMenu_ and instead store the menu,
    then patch the ObjC delegate to pop it up on click.
    """
    import AppKit
    import objc

    # ── patch image creation so idle can be an AppKit template image ─────────
    # Template images are rendered by macOS in the correct menu-bar color
    # (black on light menu bars, white on dark menu bars).  Keep this opt-in so
    # colored recording/processing/error badges remain colored.
    original_assert_image = icon._assert_image  # bound method

    def _patched_assert_image() -> None:
        original_assert_image()
        image = getattr(icon, "_icon_image", None)
        if image is not None:
            try:
                image.setTemplate_(bool(getattr(icon, "_summarizeaudio_template_icon", False)))
                icon._status_item.button().setImage_(image)
            except Exception:
                pass

    icon._assert_image = _patched_assert_image  # type: ignore[method-assign]

    # ── patch _update_menu ──────────────────────────────────────────────────
    original_create_menu = icon._create_menu  # bound method

    def _patched_update_menu(self) -> None:  # type: ignore[override]
        callbacks: list = []
        nsmenu = original_create_menu(self.menu, callbacks)
        if nsmenu is not None:
            # Keep the menu handle so the action handler can reach it.
            self._menu_handle = (nsmenu, callbacks)
            # Try the old path too – harmless if Tahoe ignores it.
            try:
                self._status_item.setMenu_(nsmenu)
            except Exception:
                pass
        else:
            self._menu_handle = None
            try:
                self._status_item.setMenu_(None)
            except Exception:
                pass

    # Bind to the Icon *instance* so we don't break other icons.
    icon._update_menu = _patched_update_menu.__get__(icon, type(icon))  # type: ignore[method-assign]

    # ── patch ObjC delegate to pop up the menu on click ─────────────────────
    # We subclass IconDelegate dynamically (ObjC doesn't allow per-instance
    # method swaps), then swap the delegate on the button.
    existing_delegate = icon._delegate

    class _PatchedDelegate(type(existing_delegate)):  # type: ignore[misc]
        @objc.namedSelector(b"activate:sender")
        def activate_button(self, sender) -> None:  # type: ignore[override]
            icon_ref = getattr(self, "icon", None)
            if icon_ref is None:
                return
            menu_handle = getattr(icon_ref, "_menu_handle", None)
            if menu_handle:
                nsmenu, _callbacks = menu_handle
                btn = icon_ref._status_item.button()
                # Pop the menu up from the bottom-left of the button,
                # which places it just below the menu bar item.
                loc = AppKit.NSPoint(0, btn.bounds().size.height)
                nsmenu.popUpMenuPositioningItem_atLocation_inView_(
                    None, loc, btn
                )
            else:
                # No menu – fall back to the original default action.
                icon_ref()

    new_delegate = _PatchedDelegate.alloc().init()
    new_delegate.icon = existing_delegate.icon  # copy the weak/strong ref
    icon._delegate = new_delegate
    try:
        icon._status_item.button().setTarget_(new_delegate)
    except Exception as exc:
        log.debug("_patch_pystray_darwin: could not swap delegate: %s", exc)


def _load_icon(name: str) -> Image.Image:
    suffix = ".ico" if platform.system() == "Windows" else ".png"
    path = ASSETS / f"{name}{suffix}"
    if path.exists():
        return Image.open(path)
    img = Image.new("RGBA", (64, 64), (120, 120, 120, 255))
    return img


def _load_pulse_frames(prefix: str) -> list[Image.Image]:
    """Load the sequential ``<prefix>_NN.png`` pulse frames in order."""
    frames: list[Image.Image] = []
    i = 0
    while True:
        path = ASSETS / f"{prefix}_{i:02d}.png"
        if not path.exists():
            break
        frames.append(Image.open(path))
        i += 1
    return frames


def _menu_bar_variant() -> str:
    """Return ``"dark"`` or ``"light"`` to match the active menu-bar appearance.

    Pulse frames are literal-color (non-template), so they can't auto-adapt the
    way the idle template does. We pick the silhouette-base variant that matches
    whatever the idle template would render as on the current bar: ``"dark"`` →
    white silhouette (dark menu bar), ``"light"`` → near-black silhouette (light
    menu bar). Defaults to ``"dark"`` off-darwin or if appearance can't be read.
    """
    if sys.platform != "darwin":
        return "dark"
    try:
        import AppKit
        nsapp = AppKit.NSApplication.sharedApplication()
        match = nsapp.effectiveAppearance().bestMatchFromAppearancesWithNames_(
            [AppKit.NSAppearanceNameAqua, AppKit.NSAppearanceNameDarkAqua]
        )
        return "light" if match == AppKit.NSAppearanceNameAqua else "dark"
    except Exception:
        return "dark"


class TrayApp:
    def __init__(self) -> None:
        self._ui_queue: queue.Queue = queue.Queue()
        self._pipeline_running = threading.Event()
        self._stop_event = threading.Event()
        self._recorder: Recorder | None = None
        self._input_health_queue: queue.Queue = queue.Queue()
        self._cfg = load_config(self._ui_queue)

        root = self._cfg.storage.output_folder
        for sub in ("AudioFiles", "TranscriptionFiles", "SummaryFiles"):
            (root / sub).mkdir(parents=True, exist_ok=True)

        self._icons = {
            "idle":       _load_icon("icon_idle"),
            "recording":  _load_icon("icon_recording"),
            "processing": _load_icon("icon_processing"),
            "error":      _load_icon("pulse_error"),
        }
        # Pre-rendered "rising sweep" pulse frames (literal-color, non-template).
        # Nested by appearance variant so the silhouette base matches the idle
        # template on either menu bar; the variant is chosen at pulse start.
        self._pulse_frames: dict[str, dict[str, list[Image.Image]]] = {
            "recording": {
                "dark":  _load_pulse_frames("pulse_recording_dark"),
                "light": _load_pulse_frames("pulse_recording_light"),
            },
            "processing": {
                "dark":  _load_pulse_frames("pulse_processing_dark"),
                "light": _load_pulse_frames("pulse_processing_light"),
            },
        }
        self._icon_mode = "idle"
        self._pulse_variant = "dark"
        self._pulse_index = 0
        self._pulse_after_id = None
        self._pulse_interval_ms = 167  # 12 frames -> ~2s/loop
        self._device_error_active = False
        self._device_reprobe_interval_ms = 3000
        self._tray: pystray.Icon | None = None

        # WindowManager owns the Tk root and all visible windows.
        # Imported here to avoid circular imports at module level.
        from summarizeaudio.window_manager import WindowManager
        self._window_manager = WindowManager(
            self._cfg,
            self._ui_queue,
            on_icon_state=self._on_icon_state,
            on_rebuild_tray=self._on_rebuild_tray_request,
        )
        self._startup_input_check_started = False
        self._input_health_pump_started = False

    @property
    def window_manager(self) -> "WindowManager":
        return self._window_manager

    # ── Menu actions ──────────────────────────────────────────────────────────

    def _on_start_recording(self, icon, item) -> None:
        if self._pipeline_running.is_set():
            return
        if self._window_manager.block_for_open_window():
            log.info("_on_start_recording: blocked because a window is open")
            return
        # No synchronous pre-start health probe: check_input_health samples the
        # device for ~1.5s, which stalled both recording start and the icon
        # animation. The async post-start check (_run_recording_input_health_check
        # → _handle_recording_input_health) is authoritative — it stops the
        # recorder, deletes the wav, reverts the icon, and notifies if the device
        # turns out bad. Start immediately and let it validate in the background.
        recorder = Recorder(self._cfg.storage.output_folder, self._cfg.recording.input_device)
        try:
            recorder.start()
        except Exception as exc:
            recorder.cleanup(delete_wav=True)
            notify(
                format_error("tray.py → recorder", str(exc), traceback.format_exc()),
                "SummarizeAudio Error",
            )
            return
        self._recorder = recorder
        self._device_error_active = False  # a clean start clears any prior error
        # Route through the UI queue so WindowManager (owner of the persistent
        # pipeline-error flag) clears `_error_active` on the main thread before
        # emitting the recording icon. A direct `_set_icon` here would leave a
        # prior pipeline error armed, suppressing the subsequent idle.
        self._ui_queue.put(("set_icon", "recording"))
        self._rebuild_menu()
        self._run_recording_input_health_check(recorder)

    def _should_alert_input_health(self, issue: str) -> bool:
        return issue in {"device_missing", "no_device", "channel_mapping", "probe_error"}

    def _should_stop_recording_for_input_health(self, issue: str) -> bool:
        return issue in {"device_missing", "no_device", "channel_mapping", "probe_error", "no_frames"}

    def _run_startup_input_health_check(self) -> None:
        if self._startup_input_check_started:
            return
        self._startup_input_check_started = True
        self._start_input_health_pump()

        def _worker() -> None:
            report = check_input_health(self._cfg.recording.input_device)
            log.info(
                "startup input health: issue=%s device=%r active_channels=%s sampled_channels=%d",
                report.issue,
                report.device_name,
                report.active_channels,
                report.sampled_channels,
            )
            self._input_health_queue.put(("startup", report, None))

        threading.Thread(target=_worker, daemon=True).start()

    def _run_recording_input_health_check(self, recorder: Recorder) -> None:
        self._start_input_health_pump()

        def _worker() -> None:
            report = check_input_health(self._cfg.recording.input_device)
            log.info(
                "recording input health: issue=%s device=%r active_channels=%s sampled_channels=%d",
                report.issue,
                report.device_name,
                report.active_channels,
                report.sampled_channels,
            )
            self._input_health_queue.put(("recording", report, recorder))

        threading.Thread(target=_worker, daemon=True).start()

    def _start_input_health_pump(self) -> None:
        if self._input_health_pump_started:
            return
        self._input_health_pump_started = True
        try:
            self._window_manager.root.after(100, self._pump_input_health_results)
        except Exception:
            self._input_health_pump_started = False

    def _pump_input_health_results(self) -> None:
        try:
            while True:
                kind, report, recorder = self._input_health_queue.get_nowait()
                if kind == "startup":
                    self._handle_startup_input_health(report)
                elif kind == "recording":
                    self._handle_recording_input_health(recorder, report)
                elif kind == "reprobe":
                    self._handle_reprobe_input_health(report)
        except queue.Empty:
            pass

        if self._stop_event.is_set():
            self._input_health_pump_started = False
            return
        try:
            self._window_manager.root.after(100, self._pump_input_health_results)
        except Exception:
            self._input_health_pump_started = False

    def _handle_recording_input_health(self, recorder: Recorder, report) -> None:
        if self._recorder is not recorder:
            return
        if not self._should_stop_recording_for_input_health(report.issue):
            return

        recorder.cleanup(delete_wav=True)
        self._recorder = None
        if report.warning:
            notify(report.warning, "Recording Input Problem")
        # Mirror the startup path: an alert-worthy device fault (channel_mapping,
        # device_missing, …) must enter the sticky device-error state with its
        # reprobe recovery loop so the icon reflects reality and self-clears when
        # the device returns. A non-alert stop reason (e.g. no_frames) just reverts
        # to idle. A bare _set_icon("idle") here would both hide the fault and skip
        # the recovery probe.
        if self._should_alert_input_health(report.issue):
            self._enter_device_error()
        else:
            self._device_error_active = False
            self._set_icon("idle")
            self._rebuild_menu()

    def _handle_startup_input_health(self, report) -> None:
        if self._recorder is not None and self._should_stop_recording_for_input_health(report.issue):
            self._handle_recording_input_health(self._recorder, report)
            return
        if self._should_alert_input_health(report.issue):
            if report.warning:
                notify(report.warning, "Recording Input Problem")
            self._enter_device_error()
        else:
            self._clear_device_error_if_active()

    def _handle_reprobe_input_health(self, report) -> None:
        """Recovery loop result: clear the error on a healthy probe, else keep
        watching."""
        if not self._device_error_active:
            return
        if self._should_alert_input_health(report.issue):
            self._schedule_device_error_reprobe()
        else:
            self._clear_device_error_if_active()

    def _enter_device_error(self) -> None:
        self._device_error_active = True
        self._set_icon("error")
        self._rebuild_menu()
        self._schedule_device_error_reprobe()

    def _clear_device_error_if_active(self) -> None:
        if not self._device_error_active:
            return
        self._device_error_active = False
        self._set_icon("idle")
        self._rebuild_menu()

    def _schedule_device_error_reprobe(self) -> None:
        if not self._device_error_active or self._stop_event.is_set():
            return
        try:
            self._window_manager.root.after(
                self._device_reprobe_interval_ms, self._fire_device_error_reprobe
            )
        except Exception:
            pass

    def _fire_device_error_reprobe(self) -> None:
        if not self._device_error_active or self._stop_event.is_set():
            return

        def _worker() -> None:
            report = check_input_health(self._cfg.recording.input_device)
            self._input_health_queue.put(("reprobe", report, None))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_stop_recording(self, icon, item) -> None:
        # Runs on the pystray callback thread. A recording-state pulse loop is
        # mutating the NSStatusItem image from the Tk main thread, so we must
        # NOT touch the icon (or menu) here — concurrent NSStatusItem access
        # from two threads deadlocks AppKit. Route the idle switch through the
        # UI queue; WindowManager pumps it on the main thread, which also
        # rebuilds the menu via `_on_icon_state`.
        recorder = self._recorder
        if recorder is None:
            return
        try:
            mp3_path, _start, _end = recorder.stop()
        except Exception as exc:
            recorder.cleanup(delete_wav=False)
            self._recorder = None
            notify(
                format_error("tray.py → recorder", str(exc), traceback.format_exc()),
                "SummarizeAudio Error",
            )
            self._ui_queue.put(("set_icon", "idle"))
            return

        self._recorder = None
        # Start loading the Ollama model now (fire-and-forget) so it is warm by
        # the time transcription finishes and summarization begins — avoids a
        # cold-load read timeout on the first real request.
        prewarm_async(self._cfg.ollama.host, self._cfg.ollama.model)
        self._ui_queue.put(("set_icon", "idle"))
        self._ui_queue.put(("show_workflow", "record", mp3_path, None))

    def _on_local_audio(self, icon, item) -> None:
        self._ui_queue.put(("show_workflow", "audio", None, None))

    def _on_local_text(self, icon, item) -> None:
        self._ui_queue.put(("show_workflow", "text", None, None))

    def _on_history(self, icon, item) -> None:
        self._ui_queue.put(("show_history",))

    def _input_audio_label(self) -> str:
        configured = self._cfg.recording.input_device
        if configured:
            return f"Input  \u2192  {configured}"
        resolved = resolve_auto_input_device_name()
        if resolved:
            return f"Input  \u2192  Auto ({resolved})"
        return "Input  \u2192  Auto (none)"

    def _summarization_label(self) -> str:
        return f"Model  \u2192  {self._cfg.ollama.model}"

    def _diarization_label(self) -> str:
        if not diarization.is_available():
            return "Diarization  \u2192  Unavailable"
        state = "On" if self._cfg.diarization.enabled else "Off"
        return f"Diarization  \u2192  {state}"

    def _on_settings_click(self, icon, item) -> None:
        self._ui_queue.put(("show_settings",))

    def _on_settings_click_input(self, icon, item) -> None:
        self._ui_queue.put(("show_settings", "input"))

    def _on_settings_click_model(self, icon, item) -> None:
        self._ui_queue.put(("show_settings", "model"))

    def _on_settings_click_diarization(self, icon, item) -> None:
        self._ui_queue.put(("show_settings", "diarization"))

    def _on_rebuild_tray_request(self) -> None:
        # Runs on the Tk main thread (invoked from WindowManager._handle).
        self._rebuild_menu()

    def _remove_tray_icon(self) -> None:
        """Explicitly remove the NSStatusItem via AppKit.

        Must be called on the main thread.  pystray's visible=False and
        icon.stop() both silently fail on macOS Tahoe with run_detached.
        We try removeStatusItem_ first, then setVisible_(False) as a fallback,
        checking both known attribute names across pystray versions.
        """
        if sys.platform != "darwin" or self._tray is None:
            return
        try:
            from AppKit import NSStatusBar  # type: ignore[import]
            # Try attribute names used across pystray versions.
            ns_item = None
            for attr in ("_status_item", "_status_bar_item"):
                ns_item = getattr(self._tray, attr, None)
                if ns_item is not None:
                    break
            if ns_item is not None:
                try:
                    NSStatusBar.systemStatusBar().removeStatusItem_(ns_item)
                except Exception:
                    pass
                try:
                    ns_item.setVisible_(False)  # belt-and-suspenders
                except Exception:
                    pass
        except Exception:
            pass

    def _on_quit(self, icon, item) -> None:
        log.info("Quit requested")
        LOCK_FILE.unlink(missing_ok=True)
        self._stop_event.set()

        # Arm the hard exit before touching pystray/AppKit. Those calls can
        # block on macOS, but the terminal process must still exit promptly.
        self._schedule_force_exit(0.8)

        if self._recorder is not None:
            try:
                self._recorder.cleanup(delete_wav=False)
            except Exception:
                pass
            self._recorder = None

        def _do_quit() -> None:
            try:
                self._window_manager.close_all()
            except Exception:
                pass
            try:
                self._window_manager.root.quit()
            except Exception:
                pass
            try:
                self._window_manager.root.destroy()
            except Exception:
                pass
            if sys.platform != "darwin":
                try:
                    icon.stop()
                except Exception:
                    pass

        try:
            self._window_manager.root.after(0, _do_quit)
        except Exception:
            _do_quit()

    def _schedule_force_exit(self, delay: float = 0.8) -> None:
        timer = threading.Timer(delay, lambda: os._exit(0))
        timer.daemon = True
        timer.start()

    # ── Icon state callback (invoked from WindowManager on main thread) ───────

    def _on_icon_state(self, state: str) -> None:
        if state == "processing":
            self._pipeline_running.set()
        else:
            self._pipeline_running.clear()
        self._set_icon(state)
        self._rebuild_menu()

    # ── Icon and menu helpers ─────────────────────────────────────────────────

    def _set_icon(self, state: str) -> None:
        if state in self._pulse_frames:
            self._start_pulse(state)
        else:
            self._set_static(state)

    def _start_pulse(self, mode: str) -> None:
        """Begin the rising-sweep loop for ``recording``/``processing``."""
        self._cancel_pulse()
        self._icon_mode = mode
        self._pulse_variant = _menu_bar_variant()
        self._pulse_index = 0
        if self._tray and sys.platform == "darwin":
            setattr(self._tray, "_summarizeaudio_template_icon", False)
        self._advance_pulse()

    def _advance_pulse(self) -> None:
        """Show the current frame, bump the index (sawtooth wrap), reschedule."""
        variants = self._pulse_frames.get(self._icon_mode)
        if not variants:
            return
        frames = variants.get(self._pulse_variant) or next(iter(variants.values()), [])
        if not frames:
            return
        if self._tray:
            self._tray.icon = frames[self._pulse_index]
        self._pulse_index = (self._pulse_index + 1) % len(frames)
        self._pulse_after_id = self._window_manager.root.after(
            self._pulse_interval_ms, self._advance_pulse
        )

    def _set_static(self, state: str) -> None:
        """Cancel any pulse loop and set a static idle/error icon."""
        self._cancel_pulse()
        self._icon_mode = state
        if self._tray:
            if sys.platform == "darwin":
                setattr(self._tray, "_summarizeaudio_template_icon", state == "idle")
            self._tray.icon = self._icons.get(state, self._icons["idle"])

    def _cancel_pulse(self) -> None:
        if self._pulse_after_id is not None:
            try:
                self._window_manager.root.after_cancel(self._pulse_after_id)
            except Exception:
                pass
            self._pulse_after_id = None

    def _rebuild_menu(self) -> None:
        if self._tray is None:
            return
        recording = self._recorder is not None
        processing = self._pipeline_running.is_set()
        items = []
        if recording:
            items.append(pystray.MenuItem("Stop Recording", self._on_stop_recording))
        elif not processing:
            items.append(pystray.MenuItem("Start Recording", self._on_start_recording))
            items.append(pystray.MenuItem(
                "Transcribe & Summarize Audio File…", self._on_local_audio))
            items.append(pystray.MenuItem(
                "Summarize Text File…", self._on_local_text))
            items.append(pystray.Menu.SEPARATOR)
            items.append(pystray.MenuItem("History…", self._on_history))
            items.append(pystray.Menu.SEPARATOR)
            items.append(pystray.MenuItem(self._input_audio_label(), self._on_settings_click_input))
            items.append(pystray.MenuItem(self._summarization_label(), self._on_settings_click_model))
            items.append(pystray.MenuItem(self._diarization_label(), self._on_settings_click_diarization))
        else:
            items.append(pystray.MenuItem("Processing…", None, enabled=False))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit", self._on_quit))
        self._tray.menu = pystray.Menu(*items)

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            elif hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:
            notify(format_error("tray.py → open", str(exc), traceback.format_exc()), "SummarizeAudio Error")

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _create_icon(self) -> None:
        """Creates the pystray Icon and rebuilds the menu.

        Must be called from the main thread on macOS — NSStatusItem creation
        requires the main thread on Tahoe and later.
        """
        kwargs: dict = {}
        if sys.platform == "darwin":
            try:
                import AppKit
                # By this point tk.Tk() has already created TKApplication
                # (Tk's NSApplication subclass, which defines macOSVersion and
                # other selectors). Passing it here tells pystray to use that
                # existing NSApplication rather than creating a new one.
                kwargs["nsapplication"] = AppKit.NSApplication.sharedApplication()
            except Exception:
                pass
        self._tray = pystray.Icon(
            "SummarizeAudio",
            icon=self._icons["idle"],
            title="SummarizeAudio",
            **kwargs,
        )
        if sys.platform == "darwin":
            setattr(self._tray, "_summarizeaudio_template_icon", True)
        if sys.platform == "darwin":
            _patch_pystray_darwin(self._tray)
        self._rebuild_menu()

    def _setup_signals(self) -> None:
        def _handle_signal(sig, frame) -> None:
            log.info("Signal %s received; quitting", sig)
            LOCK_FILE.unlink(missing_ok=True)
            self._stop_event.set()
            self._schedule_force_exit(0.8)
            if self._recorder is not None:
                try:
                    self._recorder.cleanup(delete_wav=False)
                except Exception:
                    pass
                self._recorder = None
            try:
                self._window_manager.root.after(0, self._window_manager.close_all)
                self._window_manager.root.after(0, self._window_manager.root.quit)
            except Exception:
                pass

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

    def run(self) -> None:
        """Runs the pystray icon loop (Windows/Linux background thread path)."""
        self._create_icon()
        self._setup_signals()
        self._run_startup_input_health_check()
        self._tray.run(setup=lambda icon: setattr(icon, "visible", True))

    def run_detached(self) -> None:
        """Starts pystray without its own event loop (macOS main-thread path).

        Must be called from the main thread before entering Tk's mainloop.
        Tk drives the shared NSApplication event loop, so pystray status bar
        events are delivered through it automatically.
        """
        self._setup_signals()
        # Defer ALL NSStatusBar/pystray init to after the Tk mainloop starts.
        # On macOS Tahoe, creating NSStatusItem before NSApp's run loop is
        # active results in the item being constructed but never rendered in
        # the menu bar (button is non-hidden, image is set, but invisible).
        log.info("run_detached: deferring icon creation until mainloop starts")
        self._window_manager.root.after(100, self._init_icon_in_mainloop)
        self._window_manager.root.after(600, self._run_startup_input_health_check)

    def _init_icon_in_mainloop(self) -> None:
        """Creates and shows the tray icon now that NSApp's run loop is active."""
        log.info("_init_icon_in_mainloop: creating icon inside running mainloop")
        try:
            self._create_icon()
            log.info("_init_icon_in_mainloop: calling pystray run_detached")
            self._tray.run_detached(setup=lambda icon: None)
            log.info("_init_icon_in_mainloop: scheduling visibility")
            self._window_manager.root.after(200, self._show_icon_when_ready)
        except Exception:
            log.exception("_init_icon_in_mainloop: failed")

    def _show_icon_when_ready(self, attempt: int = 0) -> None:
        log.info("_show_icon_when_ready: attempt %d", attempt)
        try:
            self._tray.visible = True
        except Exception:
            log.exception("_show_icon_when_ready: visible=True failed (attempt %d)", attempt)

        # Diagnostic: check actual AppKit button state after pystray's call.
        try:
            btn = self._tray._status_item.button()  # type: ignore[attr-defined]
            log.info(
                "button hidden=%s image=%s pystray_visible=%s",
                btn.isHidden(), btn.image(), self._tray._visible,  # type: ignore[attr-defined]
            )
        except Exception:
            log.exception("diagnostic failed")

        # macOS Tahoe: setHidden_(False) on the button alone may not be enough.
        # Also call setVisible_(True) on the NSStatusItem itself.
        try:
            self._tray._status_item.setVisible_(True)  # type: ignore[attr-defined]
            log.info("_show_icon_when_ready: setVisible_(True) called on status item")
        except Exception:
            log.exception("_show_icon_when_ready: setVisible_(True) failed")

        self._rebuild_menu()


def _check_single_instance() -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            if _pid_alive(pid) and _pid_is_summarizeaudio(pid):
                notify("SummarizeAudio is already running.")
                sys.exit(0)
        except (ValueError, OSError):
            pass
    LOCK_FILE.write_text(str(os.getpid()))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _pid_is_summarizeaudio(pid: int) -> bool:
    """Verify the locked PID is actually our process, not a reused PID."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=2,
        )
        cmd = result.stdout.lower()
        return "summarizeaudio" in cmd or "summarize" in cmd
    except Exception:
        return False  # can't verify — don't block startup


def run() -> None:
    app: "TrayApp | None" = None
    try:
        _check_single_instance()
        app = TrayApp()
        if sys.platform == "darwin":
            # On macOS, NSStatusItem must be created on the main thread and
            # pystray must not run its own NSApp event loop (Tk owns it).
            app.run_detached()
        else:
            tray_thread = threading.Thread(target=app.run, daemon=True)
            tray_thread.start()
        app.window_manager.root.mainloop()
    except Exception:
        msg = format_error("startup", "SummarizeAudio could not start.", traceback.format_exc())
        notify(msg, "SummarizeAudio Error")
        raise SystemExit(1)
    finally:
        # Delete lock file first so a restarted instance isn't blocked.
        LOCK_FILE.unlink(missing_ok=True)
        # Force-terminate so library threads (Whisper, pyannote telemetry,
        # pystray/AppKit) can't keep the terminal process alive.
        os._exit(0)
