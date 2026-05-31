from __future__ import annotations

import logging
import queue
import tkinter as tk
from tkinter import ttk

import sounddevice as sd

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
    ) -> None:
        self._cfg = cfg
        self._ui_queue = ui_queue
        self._pipeline_active = pipeline_active
        self._win = tk.Toplevel(parent_root)
        self._win.title("Settings")
        self._win.resizable(False, False)
        self._win.protocol("WM_DELETE_WINDOW", self.close)

        self._input_combo: ttk.Combobox | None = None
        self._model_combo: ttk.Combobox | None = None
        self._apply_btn: ttk.Button | None = None
        self._cancel_btn: ttk.Button | None = None
        self._error_label: ttk.Label | None = None
        self._input_values: list[str] = []
        self._model_values: list[str] = []
        self._model_list: list[ModelInfo] | None = None

        self._build()

    def _build(self) -> None:
        body = ttk.Frame(self._win, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Input Audio").pack(anchor="w")
        self._input_combo = ttk.Combobox(body, state="readonly", width=44)
        self._input_combo.pack(fill="x", pady=(2, 12))

        ttk.Label(body, text="Summarization Model").pack(anchor="w")
        self._model_combo = ttk.Combobox(body, state="readonly", width=44)
        self._model_combo.pack(fill="x", pady=(2, 12))

        if self._pipeline_active:
            banner = tk.Frame(body, bg="#fde68a")
            banner.pack(fill="x", pady=(0, 8))
            tk.Label(
                banner,
                text="Changes take effect on the next run.",
                bg="#fde68a",
                fg="#92400e",
                padx=8,
                pady=4,
            ).pack(anchor="w")

        self._error_label = ttk.Label(body, text="", foreground="#dc2626")
        self._error_label.pack(anchor="w", pady=(0, 4))

        btn_row = ttk.Frame(body)
        btn_row.pack(fill="x", pady=(8, 0))
        self._cancel_btn = ttk.Button(btn_row, text="Cancel", command=self._on_cancel)
        self._cancel_btn.pack(side="right")
        self._apply_btn = ttk.Button(btn_row, text="Apply", command=self._on_apply)
        self._apply_btn.pack(side="right", padx=(0, 8))

        # Populate after Apply button exists — disabled-state code paths need it.
        self._populate_input_devices()
        self._populate_models()

        self._win.bind("<Return>", lambda _e: self._on_apply())
        self._win.bind("<Escape>", lambda _e: self._on_cancel())

    def _populate_input_devices(self) -> None:
        assert self._input_combo is not None
        configured = self._cfg.recording.input_device or ""
        values: list[str] = []
        try:
            from summarizeaudio.recorder import resolve_auto_input_device_name
            auto_name = resolve_auto_input_device_name()
        except Exception:
            auto_name = None
        auto_label = f"{_AUTO_LABEL_PREFIX} ({auto_name})" if auto_name else _AUTO_LABEL_PREFIX
        values.append(auto_label)
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
        self._input_values = values
        self._input_combo["values"] = values
        self._input_combo.set(initial)

    def _populate_models(self) -> None:
        assert self._model_combo is not None
        assert self._apply_btn is not None
        self._model_list = list_installed_models(self._cfg.ollama.host)
        configured = self._cfg.ollama.model

        if self._model_list is None:
            self._model_combo["values"] = []
            self._model_combo.set("Ollama not running — start Ollama and reopen Settings")
            self._model_combo.configure(state="disabled")
            self._apply_btn.configure(state="disabled")
            self._model_values = []
            return

        if not self._model_list:
            self._model_combo["values"] = []
            self._model_combo.set("No models installed. Run `ollama pull gemma3:4b` and reopen.")
            self._model_combo.configure(state="disabled")
            self._apply_btn.configure(state="disabled")
            self._model_values = []
            return

        values: list[str] = []
        installed_names = {m.name for m in self._model_list}
        if configured not in installed_names:
            values.append(f"{configured} (not installed)")
        for m in self._model_list:
            label = m.name
            if _is_non_chat(m):
                label = f"{m.name} · embedding"
            values.append(label)

        self._model_values = values
        self._model_combo["values"] = values
        if configured not in installed_names:
            self._model_combo.set(f"{configured} (not installed)")
        else:
            match = next((v for v in values if v.split(" · ")[0] == configured), configured)
            self._model_combo.set(match)

    def show(self) -> None:
        self._win.deiconify()
        self._focus()

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
        if self._apply_btn is None or str(self._apply_btn["state"]) == "disabled":
            return
        old_device = self._cfg.recording.input_device
        old_model = self._cfg.ollama.model

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

        try:
            save_config(self._cfg)
        except Exception as exc:
            self._cfg.recording.input_device = old_device
            self._cfg.ollama.model = old_model
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
