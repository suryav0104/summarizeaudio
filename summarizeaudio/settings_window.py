from __future__ import annotations

import logging
import queue
import tkinter as tk
from tkinter import ttk

import sounddevice as sd
from dotenv import load_dotenv

from summarizeaudio import diarization
from summarizeaudio.config import AppConfig, save_config
from summarizeaudio.ollama_client import ModelInfo, list_installed_models

log = logging.getLogger(__name__)

_AUTO_LABEL_PREFIX = "Auto-detect"


class SettingsWindow:
    def __init__(
        self,
        parent_root: tk.Tk,
        cfg: AppConfig,
        ui_queue: queue.Queue,
        pipeline_active: bool = False,
        focus_target: str | None = None,
    ) -> None:
        self._cfg = cfg
        self._ui_queue = ui_queue
        self._pipeline_active = pipeline_active
        self._focus_target = focus_target
        self._win = tk.Toplevel(parent_root)
        self._win.withdraw()
        self._win.title("Settings")
        self._window_width = 480
        self._window_height = 360
        self._win.geometry(f"{self._window_width}x{self._window_height}")
        self._win.resizable(False, False)
        self._win.configure(bg="white")
        self._win.protocol("WM_DELETE_WINDOW", self.close)

        # ── Styles (match WorkflowWindow) ────────────────────────────────────
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("SummarizeAudio.TFrame", background="white")
        style.configure("Card.TFrame", background="white")
        style.configure("Sep.TFrame", background="#e0e6ef")
        style.configure(
            "Title.TLabel",
            background="white",
            foreground="#162033",
            font=("Helvetica Neue", 20, "bold"),
        )
        style.configure(
            "Step.TLabel",
            background="white",
            foreground="#162033",
            font=("Helvetica Neue", 13, "bold"),
        )
        style.configure(
            "Error.TLabel",
            background="white",
            foreground="#dc2626",
            font=("Helvetica Neue", 10),
        )
        style.configure(
            "Hint.TLabel",
            background="white",
            foreground="#5b6577",
            font=("Helvetica Neue", 11),
        )

        self._button_font = ("Helvetica Neue", 12, "bold")
        self._button_secondary_bg = "#f0f3f8"
        self._button_secondary_fg = "#1a2030"
        self._button_border = "#b8c4d6"
        self._button_accent_bg = "#1a2030"
        self._button_accent_fg = "white"

        self._input_combo: ttk.Combobox | None = None
        self._model_combo: ttk.Combobox | None = None
        self._apply_btn: tk.Frame | None = None
        self._cancel_btn: tk.Frame | None = None
        self._error_label: ttk.Label | None = None
        self._input_values: list[str] = []
        self._model_values: list[str] = []
        self._model_list: list[ModelInfo] | None = None
        self._apply_disabled: bool = False
        self._combo_width: int = 20

        # Diarization row state.
        self._diar_row: ttk.Frame | None = None
        self._diar_available: bool = False
        self._diar_combo: ttk.Combobox | None = None
        self._diar_link: tk.Label | None = None
        self._diar_steps_frame: tk.Frame | None = None
        self._diar_steps_visible: bool = False
        self._diar_steps_text: str = ""
        self._diar_focus_widget: tk.Widget | None = None
        self._diar_recheck_note: tk.Label | None = None

        self._build()

    # ── Build ───────────────────────────────────────────────────────────────
    def _build(self) -> None:
        # Pre-compute values so we can size the combos correctly *at creation*.
        # Reconfiguring width after creation isn't reliable on macOS clam.
        input_values, input_initial = self._compute_input_devices()
        model_values, model_initial, model_disabled_msg = self._compute_models()

        self._input_values = input_values
        self._model_values = model_values

        all_strings = [*input_values, *model_values]
        if model_disabled_msg:
            all_strings.append(model_disabled_msg)
        if input_initial:
            all_strings.append(input_initial)
        if model_initial:
            all_strings.append(model_initial)
        # +2 for the chevron / inner padding.
        combo_width = (max((len(s) for s in all_strings), default=20)) + 2
        # Stored so the diarization row (rebuilt later on Re-check) can match the
        # Input/Model dropdown width for a clean, aligned column.
        self._combo_width = combo_width

        # ── Bottom button bar (packed first so it always claims the bottom) ──
        button_bar = ttk.Frame(self._win, style="SummarizeAudio.TFrame", padding=(20, 10, 20, 16))
        button_bar.pack(side="bottom", fill="x")
        ttk.Frame(self._win, style="Sep.TFrame", height=1).pack(side="bottom", fill="x")

        self._apply_btn = self._button(button_bar, text="Apply", command=self._on_apply, primary=True)
        self._apply_btn.pack(side="right")
        self._cancel_btn = self._button(button_bar, text="Cancel", command=self._on_cancel, primary=False)
        self._cancel_btn.pack(side="right", padx=(0, 10))

        # ── Body ──────────────────────────────────────────────────────────────
        body = ttk.Frame(self._win, style="SummarizeAudio.TFrame", padding=(24, 20, 24, 8))
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Settings", style="Title.TLabel").pack(anchor="w", pady=(0, 14))

        # Input Audio
        ttk.Label(body, text="Input Audio", style="Step.TLabel").pack(anchor="w")
        self._input_combo = ttk.Combobox(body, state="readonly", width=combo_width)
        self._input_combo["values"] = input_values
        self._input_combo.set(input_initial)
        self._input_combo.pack(anchor="w", pady=(4, 14))
        self._bind_arrow_stepping(self._input_combo)

        # Summarization Model
        ttk.Label(body, text="Summarization Model", style="Step.TLabel").pack(anchor="w")
        self._model_combo = ttk.Combobox(body, state="readonly", width=combo_width)
        if model_disabled_msg is not None:
            self._model_combo.set(model_disabled_msg)
            self._model_combo.configure(state="disabled")
            self._disable_button(self._apply_btn)
            self._apply_disabled = True
        else:
            self._model_combo["values"] = model_values
            self._model_combo.set(model_initial)
            self._bind_arrow_stepping(self._model_combo)
        self._model_combo.pack(anchor="w", pady=(4, 14))

        # Speaker Diarization
        self._diar_row = ttk.Frame(body, style="SummarizeAudio.TFrame")
        self._diar_row.pack(anchor="w", fill="x", pady=(0, 12))
        self._render_diarization_row()

        if self._pipeline_active:
            banner = tk.Frame(body, bg="#fde68a")
            banner.pack(fill="x", pady=(0, 10))
            tk.Label(
                banner,
                text="Changes take effect on the next run.",
                bg="#fde68a",
                fg="#92400e",
                font=("Helvetica Neue", 10),
                padx=10,
                pady=6,
            ).pack(anchor="w")

        self._error_label = ttk.Label(body, text="", style="Error.TLabel")
        self._error_label.pack(anchor="w")

        self._win.bind("<Return>", lambda _e: self._on_apply())
        self._win.bind("<Escape>", lambda _e: self._on_cancel())

    # ── Button helper (Frame+Label since tk.Button ignores colors on Aqua) ──
    def _button(self, parent: tk.Misc, *, text: str, command, primary: bool) -> tk.Frame:
        if primary:
            btn_bg = self._button_accent_bg
            btn_fg = self._button_accent_fg
            hover_bg = "#2d3548"
            outer = tk.Frame(parent, bg=btn_bg)
            container = outer
        else:
            btn_bg = self._button_secondary_bg
            btn_fg = self._button_secondary_fg
            hover_bg = "#dde4ef"
            outer = tk.Frame(parent, bg=self._button_border)
            container = tk.Frame(outer, bg=btn_bg)
            container.pack(padx=1, pady=1)

        label = tk.Label(
            container,
            text=text,
            bg=btn_bg,
            fg=btn_fg,
            font=self._button_font,
            padx=16,
            pady=8,
        )
        label.pack()

        def _enter(_e: tk.Event) -> None:
            if self._is_disabled(outer):
                return
            container.configure(bg=hover_bg)
            label.configure(bg=hover_bg)

        def _leave(_e: tk.Event) -> None:
            if self._is_disabled(outer):
                return
            container.configure(bg=btn_bg)
            label.configure(bg=btn_bg)

        def _click(_e: tk.Event) -> None:
            if self._is_disabled(outer):
                return
            command()

        for widget in (outer, container, label):
            widget.bind("<Enter>", _enter)
            widget.bind("<Leave>", _leave)
            widget.bind("<Button-1>", _click)

        outer._sa_label = label  # type: ignore[attr-defined]
        outer._sa_container = container  # type: ignore[attr-defined]
        outer._sa_normal_bg = btn_bg  # type: ignore[attr-defined]
        outer._sa_disabled = False  # type: ignore[attr-defined]
        return outer

    def _is_disabled(self, outer: tk.Frame) -> bool:
        return bool(getattr(outer, "_sa_disabled", False))

    def _disable_button(self, outer: tk.Frame) -> None:
        outer._sa_disabled = True  # type: ignore[attr-defined]
        outer.configure(bg="#cbd2dc")
        container = getattr(outer, "_sa_container", outer)
        label = getattr(outer, "_sa_label", None)
        try:
            container.configure(bg="#cbd2dc")
        except Exception:
            pass
        if label is not None:
            try:
                label.configure(bg="#cbd2dc", fg="#8b94a3")
            except Exception:
                pass

    # ── Diarization row ─────────────────────────────────────────────────────
    def _render_diarization_row(self, available: bool | None = None) -> None:
        """(Re)build the diarization row from current capability.

        Probes diarization.is_available() (unless the caller passes a value it
        already probed). When available we show a toggle bound to the stored
        preference; otherwise an "Unavailable" label plus a "How to enable" link
        that expands the shared setup steps.
        """
        assert self._diar_row is not None
        for child in self._diar_row.winfo_children():
            child.destroy()
        self._diar_combo = None
        self._diar_link = None
        self._diar_steps_frame = None
        self._diar_steps_visible = False
        self._diar_recheck_note = None
        self._diar_available = (
            diarization.is_available() if available is None else available
        )

        # Heading reads identically in both states: a bold title plus a light
        # parenthetical purpose caption on the same line.
        heading = ttk.Frame(self._diar_row, style="SummarizeAudio.TFrame")
        heading.pack(anchor="w")
        ttk.Label(heading, text="Speaker Diarization", style="Step.TLabel").pack(side="left")
        ttk.Label(
            heading, text=" (Label speakers in transcripts)", style="Hint.TLabel"
        ).pack(side="left", anchor="s", pady=(0, 2))

        if self._diar_available:
            self._diar_combo = ttk.Combobox(
                self._diar_row, state="readonly", width=self._combo_width,
                values=["On", "Off"],
            )
            self._diar_combo.set("On" if self._cfg.diarization.enabled else "Off")
            self._diar_combo.pack(anchor="w", pady=(4, 0))
            self._bind_arrow_stepping(self._diar_combo)
            self._diar_focus_widget = self._diar_combo
            self._resize_for_steps(False)
            return

        status = tk.Frame(self._diar_row, bg="white")
        status.pack(anchor="w", pady=(4, 0))
        tk.Label(
            status, text="Unavailable", bg="white", fg="#92400e",
            font=("Helvetica Neue", 11),
        ).pack(side="left")
        self._diar_link = tk.Label(
            status, text="How to enable", bg="white", fg="#2563eb",
            font=("Helvetica Neue", 11, "underline"),
        )
        self._diar_link.pack(side="left", padx=(8, 0))
        self._diar_link.bind("<Button-1>", lambda _e: self._on_diar_how_to_enable())
        self._diar_focus_widget = self._diar_link
        self._resize_for_steps(False)

    def _on_diar_how_to_enable(self) -> None:
        if self._diar_steps_visible or self._diar_row is None:
            return
        self._diar_steps_text = diarization.render_setup_steps("window")
        frame = tk.Frame(self._diar_row, bg="#f6f8fc")
        frame.pack(fill="x", pady=(8, 0))
        tk.Label(
            frame, text=self._diar_steps_text, bg="#f6f8fc", fg="#1a2030",
            font=("Helvetica Neue", 10), justify="left", wraplength=410,
        ).pack(anchor="w", padx=10, pady=(8, 4))
        recheck = self._button(frame, text="Re-check", command=self._on_diar_recheck, primary=False)
        recheck.pack(anchor="w", padx=10, pady=(0, 8))
        self._diar_recheck_note = tk.Label(
            frame, text="", bg="#f6f8fc", fg="#92400e",
            font=("Helvetica Neue", 10), justify="left", wraplength=410,
        )
        self._diar_recheck_note.pack(anchor="w", padx=10, pady=(0, 8))
        self._diar_steps_frame = frame
        self._diar_steps_visible = True
        self._resize_for_steps(True)

    def _on_diar_recheck(self) -> None:
        # .env is loaded once at startup; override=True picks up a token the user
        # pasted after launch so "Re-check" works without relaunching.
        load_dotenv(override=True)
        if diarization.is_available():
            # Capability arrived — swap the whole row to the toggle.
            self._render_diarization_row(available=True)
            return
        # Still unavailable: keep the instructions on screen and say what's missing
        # rather than silently collapsing back to the bare link.
        reason = diarization.missing_reason() or "still unavailable"
        if self._diar_recheck_note is not None:
            self._diar_recheck_note.configure(text=f"Still unavailable: {reason}.")

    def _resize_for_steps(self, expanded: bool) -> None:
        try:
            if not self._win.winfo_ismapped():
                return
            w = self._window_width
            h = self._window_height + (240 if expanded else 0)
            self._win.update_idletasks()
            sw = self._win.winfo_screenwidth()
            sh = self._win.winfo_screenheight()
            x = max((sw - w) // 2, 0)
            y = max((sh - h) // 2, 0)
            self._win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    # ── Pure value computation (no widget side-effects) ─────────────────────
    def _compute_input_devices(self) -> tuple[list[str], str]:
        configured = self._cfg.recording.input_device or ""
        try:
            from summarizeaudio.recorder import resolve_auto_input_device_name
            auto_name = resolve_auto_input_device_name()
        except Exception:
            auto_name = None
        auto_label = f"{_AUTO_LABEL_PREFIX} ({auto_name})" if auto_name else _AUTO_LABEL_PREFIX
        values: list[str] = [auto_label]
        try:
            for dev in sd.query_devices():
                if isinstance(dev, dict) and dev.get("max_input_channels", 0) > 0:
                    name = str(dev.get("name", "")).strip()
                    if name and name not in values:
                        values.append(name)
        except Exception:
            log.warning("sd.query_devices failed; only Auto-detect shown", exc_info=True)
        if configured and configured not in values:
            values.insert(1, f"{configured} (not connected)")
            initial = f"{configured} (not connected)"
        elif configured:
            initial = configured
        else:
            initial = auto_label
        return values, initial

    def _compute_models(self) -> tuple[list[str], str, str | None]:
        """Return (values, initial, disabled_msg).

        disabled_msg is non-None when the model combo should be disabled
        (Ollama unreachable or no models installed); in that case the caller
        should show the message text and disable both the combo and Apply.
        """
        self._model_list = list_installed_models(self._cfg.ollama.host)
        configured = self._cfg.ollama.model

        if self._model_list is None:
            return [], "", "Ollama not running — start Ollama and reopen Settings"
        if not self._model_list:
            return [], "", "No models installed. Run `ollama pull gemma3:4b` and reopen."

        values: list[str] = []
        installed_names = {m.name for m in self._model_list}
        if configured not in installed_names:
            values.append(f"{configured} (not installed)")
        for m in self._model_list:
            label = m.name
            if _is_non_chat(m):
                label = f"{m.name} · embedding"
            values.append(label)

        if configured not in installed_names:
            initial = f"{configured} (not installed)"
        else:
            initial = next((v for v in values if v.split(" · ")[0] == configured), configured)
        return values, initial, None

    # ── Lifecycle ───────────────────────────────────────────────────────────
    def show(self) -> None:
        self._center()
        self._win.deiconify()
        self._focus()
        self._apply_focus_target()

    def _bind_arrow_stepping(self, combo: ttk.Combobox) -> None:
        """Make Up/Down cycle the value by one in a single press.

        On macOS Aqua, Tk binds <Down> to 'post the popdown menu' and leaves
        <Up> dead, so the arrows never step the value. We override both to step
        directly and return "break" to suppress the default menu-post.
        """
        combo.bind("<Down>", lambda _e: self._step_combo(combo, 1))
        combo.bind("<Up>", lambda _e: self._step_combo(combo, -1))

    def _step_combo(self, combo: ttk.Combobox, delta: int) -> str:
        """Move the combo selection by delta, clamped to the value range.

        Mirrors ttk::combobox::SelectEntry: set current, select the text, and
        fire <<ComboboxSelected>>. Returns "break" to stop the default binding.
        """
        if str(combo["state"]) == "disabled":
            return "break"
        count = len(combo["values"])
        if count == 0:
            return "break"
        current = combo.current()
        if current < 0:
            current = 0
        new = max(0, min(count - 1, current + delta))
        if new != combo.current():
            combo.current(new)
            combo.selection_range(0, "end")
            combo.event_generate("<<ComboboxSelected>>")
        return "break"

    def _apply_focus_target(self) -> None:
        target = self._focus_target
        combo = None
        if target == "input":
            combo = self._input_combo
        elif target == "model":
            combo = self._model_combo
        elif target == "diarization":
            if self._diar_focus_widget is not None:
                try:
                    self._diar_focus_widget.focus_set()
                except Exception:
                    pass
            return
        if combo is not None:
            try:
                combo.focus_set()
            except Exception:
                pass

    def focus_target(self, target: str) -> None:
        """Used when SettingsWindow is already open and the user clicks the
        other status item — refocus the matching combo."""
        self._focus_target = target
        self._apply_focus_target()

    def _center(self) -> None:
        self._win.update_idletasks()
        w = self._window_width
        h = self._window_height
        sw = self._win.winfo_screenwidth()
        sh = self._win.winfo_screenheight()
        x = max((sw - w) // 2, 0)
        y = max((sh - h) // 2, 0)
        self._win.geometry(f"{w}x{h}+{x}+{y}")

    def _focus(self) -> None:
        try:
            self._win.lift()
            self._win.focus_force()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._win.destroy()
        except Exception:
            pass

    def _on_cancel(self) -> None:
        self.close()

    def _on_apply(self) -> None:
        if self._apply_disabled:
            return
        old_device = self._cfg.recording.input_device
        old_model = self._cfg.ollama.model
        old_diar = self._cfg.diarization.enabled

        assert self._input_combo is not None
        assert self._model_combo is not None
        input_choice = self._input_combo.get()
        model_choice = self._model_combo.get()

        if input_choice.startswith(_AUTO_LABEL_PREFIX):
            new_device: str | None = None
        elif input_choice.endswith("(not connected)"):
            new_device = input_choice.rsplit(" (not connected)", 1)[0]
        else:
            new_device = input_choice

        if model_choice.endswith("(not installed)"):
            new_model = model_choice.rsplit(" (not installed)", 1)[0]
        elif " · " in model_choice:
            new_model = model_choice.split(" · ", 1)[0]
        else:
            new_model = model_choice

        self._cfg.recording.input_device = new_device
        self._cfg.ollama.model = new_model
        if self._diar_available and self._diar_combo is not None:
            self._cfg.diarization.enabled = self._diar_combo.get() == "On"

        try:
            save_config(self._cfg)
        except Exception as exc:
            self._cfg.recording.input_device = old_device
            self._cfg.ollama.model = old_model
            self._cfg.diarization.enabled = old_diar
            if self._error_label is not None:
                self._error_label.configure(text=f"Failed to save settings: {exc}")
            return

        try:
            self._ui_queue.put_nowait(("rebuild_tray_menu",))
        except Exception:
            pass
        self.close()


def _is_non_chat(m: ModelInfo) -> bool:
    name = m.name.lower()
    if "embed" in name:
        return True
    fam = (m.family or "").lower()
    return fam in {"bert", "nomic-bert"}
