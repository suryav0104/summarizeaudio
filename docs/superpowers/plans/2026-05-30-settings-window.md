# Settings Window Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Tk Settings window with two dropdowns (Input Audio device, Summarization model), surface their current values as inline tray menu items, and remove the existing Fast/High Quality submenu.

**Architecture:** Settings is a third Toplevel window owned by `WindowManager`. It does NOT participate in the existing Workflow ↔ History blocking rule (can stack on either). Two new inline tray items display current values and open Settings on click. Summarization model list is fetched dynamically from `http://localhost:11434/api/tags`.

**Tech Stack:** Tk/ttk, pystray, sounddevice, urllib (stdlib). All work in Python 3.11+.

**Reference spec:** `docs/superpowers/specs/2026-05-30-settings-window-design.md` — consult for any ambiguity.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `summarizeaudio/ollama_client.py` | create | `list_installed_models(host)` — HTTP GET `/api/tags`, parse, return list or None |
| `summarizeaudio/recorder.py` | modify | add `resolve_auto_input_device_name()` helper |
| `summarizeaudio/settings_window.py` | create | Tk Toplevel with two readonly combos + Apply/Cancel |
| `summarizeaudio/window_manager.py` | modify | track `_settings_win`, `_last_pipeline_active`, `on_rebuild_tray` callback, add `show_settings` + `rebuild_tray_menu` `_handle` branches, extend sweep & activation policy |
| `summarizeaudio/tray.py` | modify | remove Fast/High Quality items + helpers; add two inline status items + `_on_settings_click` + `_on_rebuild_tray_request`; pass `on_rebuild_tray` to WindowManager |
| `tests/test_ollama_client.py` | create | parse / connection-refused / empty / malformed |
| `tests/test_settings_window.py` | create | apply / cancel / disabled-states / banner / auto-detect roundtrip |
| `tests/test_window_manager.py` | modify | add show_settings routing, sweep, activation policy, rebuild_tray callback tests |
| `tests/test_tray.py` | modify | remove old `test_model_menu_*` tests, update fakes, add new inline-items tests |
| `docs/architecture.md` | modify | add new modules to component list + Mermaid diagram; remove stale `rumps` line |
| `docs/adr.md` | append | one ADR for the design choice |

---

## Chunk 1: Ollama client module

Pure stdlib HTTP. No GUI. Build and test in full isolation first.

### Task 1.1: ModelInfo dataclass + list_installed_models scaffold

**Files:**
- Create: `summarizeaudio/ollama_client.py`
- Test: `tests/test_ollama_client.py`

- [ ] **Step 1: Write failing test for parse path**

```python
# tests/test_ollama_client.py
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from summarizeaudio.ollama_client import ModelInfo, list_installed_models


def _fake_response(payload: dict):
    """Mimic urllib.request.urlopen's context-manager return."""
    body = json.dumps(payload).encode("utf-8")
    class _Resp:
        def __enter__(self_inner):
            return self_inner
        def __exit__(self_inner, *_a):
            return False
        def read(self_inner):
            return body
    return _Resp()


def test_list_installed_models_parses_name_and_family():
    payload = {
        "models": [
            {"name": "gemma3:4b", "details": {"family": "gemma3"}},
            {"name": "nomic-embed-text:latest", "details": {"family": "bert"}},
        ]
    }
    with patch("summarizeaudio.ollama_client.urlopen", return_value=_fake_response(payload)):
        models = list_installed_models("http://localhost:11434")

    assert models == [
        ModelInfo(name="gemma3:4b", family="gemma3"),
        ModelInfo(name="nomic-embed-text:latest", family="bert"),
    ]
```

- [ ] **Step 2: Run test, expect ImportError**

Run: `./venv/bin/python -m pytest tests/test_ollama_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'summarizeaudio.ollama_client'`

- [ ] **Step 3: Create module skeleton**

```python
# summarizeaudio/ollama_client.py
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelInfo:
    name: str
    family: str | None


def list_installed_models(host: str, timeout: float = 2.0) -> list[ModelInfo] | None:
    """Return installed Ollama models, or None if Ollama is unreachable.

    Hits GET <host>/api/tags. Returns [] when Ollama is up but no models are
    installed. Returns None on connection refused / timeout / malformed JSON.
    """
    url = host.rstrip("/") + "/api/tags"
    try:
        with urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (URLError, ConnectionRefusedError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        log.debug("ollama list failed: %s", exc)
        return None

    raw_models = data.get("models", [])
    if not isinstance(raw_models, list):
        return None

    out: list[ModelInfo] = []
    for entry in raw_models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        details = entry.get("details") or {}
        family = details.get("family") if isinstance(details, dict) else None
        if family is not None and not isinstance(family, str):
            family = None
        out.append(ModelInfo(name=name, family=family))
    return out
```

- [ ] **Step 4: Run test, expect PASS**

Run: `./venv/bin/python -m pytest tests/test_ollama_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add summarizeaudio/ollama_client.py tests/test_ollama_client.py
git commit -m "feat: add ollama_client.list_installed_models"
```

### Task 1.2: Error-path tests

- [ ] **Step 1: Add three more failing tests**

```python
# Append to tests/test_ollama_client.py

def test_list_installed_models_returns_none_on_connection_refused():
    with patch("summarizeaudio.ollama_client.urlopen", side_effect=ConnectionRefusedError()):
        assert list_installed_models("http://localhost:11434") is None


def test_list_installed_models_returns_empty_list_when_no_models():
    payload = {"models": []}
    with patch("summarizeaudio.ollama_client.urlopen", return_value=_fake_response(payload)):
        assert list_installed_models("http://localhost:11434") == []


def test_list_installed_models_returns_none_on_malformed_json():
    class _BadResp:
        def __enter__(self):
            return self
        def __exit__(self, *_a):
            return False
        def read(self):
            return b"not-json{{{"
    with patch("summarizeaudio.ollama_client.urlopen", return_value=_BadResp()):
        assert list_installed_models("http://localhost:11434") is None


def test_list_installed_models_handles_missing_details():
    payload = {"models": [{"name": "llama3:8b"}]}
    with patch("summarizeaudio.ollama_client.urlopen", return_value=_fake_response(payload)):
        assert list_installed_models("http://localhost:11434") == [
            ModelInfo(name="llama3:8b", family=None)
        ]
```

- [ ] **Step 2: Run, expect all PASS**

Run: `./venv/bin/python -m pytest tests/test_ollama_client.py -v`
Expected: 4 PASS (existing test) + 4 PASS (new). Total 5 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ollama_client.py
git commit -m "test: cover ollama_client error paths"
```

---

## Chunk 2: Recorder helper

Tiny, pure function. One test, one commit.

### Task 2.1: resolve_auto_input_device_name

**Files:**
- Modify: `summarizeaudio/recorder.py` (add module-level function near `_get_loopback_device`)
- Test: `tests/test_recorder.py` (create if not present, else extend)

- [ ] **Step 1: Check whether tests/test_recorder.py exists**

Run: `ls tests/test_recorder.py 2>/dev/null || echo "missing"`

- [ ] **Step 2: Write failing test**

If `tests/test_recorder.py` does not exist, create it with the test below. Otherwise append the test.

```python
# tests/test_recorder.py (create or append)
from __future__ import annotations

from unittest.mock import patch

from summarizeaudio.recorder import resolve_auto_input_device_name


def test_resolve_auto_input_device_name_returns_loopback_name():
    fake_devices = [
        {"name": "Built-in Microphone", "max_input_channels": 1},
        {"name": "BlackHole 2ch", "max_input_channels": 2},
    ]
    def fake_query(idx=None):
        if idx is None:
            return fake_devices
        return fake_devices[idx]

    with patch("summarizeaudio.recorder.sd.query_devices", side_effect=fake_query), \
         patch("summarizeaudio.recorder.platform.system", return_value="Darwin"):
        assert resolve_auto_input_device_name() == "BlackHole 2ch"


def test_resolve_auto_input_device_name_returns_none_when_no_loopback():
    fake_devices = [{"name": "Built-in Microphone", "max_input_channels": 1}]
    def fake_query(idx=None):
        if idx is None:
            return fake_devices
        return fake_devices[idx]

    with patch("summarizeaudio.recorder.sd.query_devices", side_effect=fake_query), \
         patch("summarizeaudio.recorder.platform.system", return_value="Darwin"):
        assert resolve_auto_input_device_name() is None


def test_resolve_auto_input_device_name_returns_none_on_exception():
    with patch("summarizeaudio.recorder.sd.query_devices", side_effect=RuntimeError("boom")):
        assert resolve_auto_input_device_name() is None
```

- [ ] **Step 3: Run test, expect ImportError**

Run: `./venv/bin/python -m pytest tests/test_recorder.py::test_resolve_auto_input_device_name_returns_loopback_name -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_auto_input_device_name'`

- [ ] **Step 4: Add helper to `recorder.py`**

Insert right after `_get_loopback_device` (around line 38):

```python
def resolve_auto_input_device_name() -> str | None:
    """Return the name of the device that auto-detect would pick, or None.

    Surfaces the *name* (not index) of the auto-detect target for display
    in the tray menu. All exceptions caught and converted to None.
    """
    try:
        idx = _get_loopback_device()
        if idx is None:
            return None
        dev = sd.query_devices(idx)
        name = dev.get("name") if isinstance(dev, dict) else None
        return str(name) if name else None
    except Exception:
        return None
```

- [ ] **Step 5: Run all three new tests**

Run: `./venv/bin/python -m pytest tests/test_recorder.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add summarizeaudio/recorder.py tests/test_recorder.py
git commit -m "feat(recorder): add resolve_auto_input_device_name helper"
```

---

## Chunk 3: WindowManager extensions

Extend without breaking existing behavior. Each step adds one concern.

### Task 3.1: Constructor accepts `on_rebuild_tray`; `_settings_win` field

**Files:**
- Modify: `summarizeaudio/window_manager.py`
- Test: `tests/test_window_manager.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_window_manager.py`:

```python
import queue
from unittest.mock import MagicMock

from summarizeaudio import window_manager
from summarizeaudio.config import (
    AppConfig, BehaviorConfig, OllamaConfig, RecordingConfig,
    StorageConfig, SummarizationConfig, WhisperConfig,
)


def _make_cfg(tmp_path):
    return AppConfig(
        storage=StorageConfig(output_folder=tmp_path),
        whisper=WhisperConfig(model="tiny", language="en"),
        ollama=OllamaConfig(host="http://localhost:11434", model="gemma3:4b"),
        summarization=SummarizationConfig(default_prompt="x"),
        behavior=BehaviorConfig(show_override_dialog=False, auto_open_summary=False),
        recording=RecordingConfig(input_device=None),
    )


def test_window_manager_accepts_on_rebuild_tray(tmp_path, monkeypatch):
    # Avoid real Tk by mocking tk.Tk.
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    cb = MagicMock()
    wm = window_manager.WindowManager(
        _make_cfg(tmp_path), queue.Queue(), on_rebuild_tray=cb
    )
    assert wm._on_rebuild_tray is cb
    assert wm._settings_win is None
```

- [ ] **Step 2: Run, expect FAIL**

Run: `./venv/bin/python -m pytest tests/test_window_manager.py::test_window_manager_accepts_on_rebuild_tray -v`
Expected: FAIL — `TypeError: unexpected keyword argument 'on_rebuild_tray'` or AttributeError on `_settings_win`.

- [ ] **Step 3: Update WindowManager `__init__`**

In `summarizeaudio/window_manager.py`, change the constructor signature and body:

```python
def __init__(
    self,
    cfg: AppConfig,
    ui_queue: queue.Queue,
    on_icon_state: Callable[[str], None] | None = None,
    on_rebuild_tray: Callable[[], None] | None = None,
) -> None:
    self._cfg = cfg
    self._ui_queue = ui_queue
    self._on_icon_state = on_icon_state
    self._on_rebuild_tray = on_rebuild_tray
    self._root = tk.Tk()
    # ... rest unchanged ...
    self._workflow_win: WorkflowWindow | None = None
    self._history_win: HistoryWindow | None = None
    self._settings_win: SettingsWindow | None = None
    self._last_pipeline_active: bool = False
    self._dock_icon: Any = None
```

Also extend the `TYPE_CHECKING` block:

```python
if TYPE_CHECKING:
    from summarizeaudio.workflow_window import WorkflowWindow
    from summarizeaudio.history_window import HistoryWindow
    from summarizeaudio.settings_window import SettingsWindow
```

- [ ] **Step 4: Run test, expect PASS**

Run: `./venv/bin/python -m pytest tests/test_window_manager.py::test_window_manager_accepts_on_rebuild_tray -v`
Expected: PASS

- [ ] **Step 5: Verify nothing else broke**

Run: `./venv/bin/python -m pytest tests/test_window_manager.py -v`
Expected: all PASS (3 existing tests + 1 new)

- [ ] **Step 6: Commit**

```bash
git add summarizeaudio/window_manager.py tests/test_window_manager.py
git commit -m "feat(wm): accept on_rebuild_tray + _settings_win field"
```

### Task 3.2: `show_settings` + `_handle` branch + sweep + activation policy

- [ ] **Step 1: Write failing tests**

Append to `tests/test_window_manager.py`:

```python
def test_show_settings_message_invokes_show_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    wm = window_manager.WindowManager(_make_cfg(tmp_path), queue.Queue())
    wm.show_settings = MagicMock()  # replace to observe routing
    wm._handle(("show_settings",))
    wm.show_settings.assert_called_once()


def test_rebuild_tray_menu_message_invokes_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    cb = MagicMock()
    wm = window_manager.WindowManager(_make_cfg(tmp_path), queue.Queue(), on_rebuild_tray=cb)
    wm._handle(("rebuild_tray_menu",))
    cb.assert_called_once()


def test_sweep_clears_dead_settings_win(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    wm = window_manager.WindowManager(_make_cfg(tmp_path), queue.Queue())
    dead_win = MagicMock()
    dead_win.winfo_exists.return_value = False
    wm._settings_win = MagicMock(_win=dead_win)
    wm._sweep_stale_window_refs()
    assert wm._settings_win is None


def test_set_icon_tracks_pipeline_active(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    wm = window_manager.WindowManager(_make_cfg(tmp_path), queue.Queue())
    wm._handle(("set_icon", "recording"))
    assert wm._last_pipeline_active is True
    wm._handle(("set_icon", "idle"))
    assert wm._last_pipeline_active is False
    wm._handle(("set_icon", "processing"))
    assert wm._last_pipeline_active is True
```

- [ ] **Step 2: Run, expect 4 FAIL**

Run: `./venv/bin/python -m pytest tests/test_window_manager.py -v -k "show_settings or rebuild_tray or sweep_clears_dead_settings or set_icon_tracks"`
Expected: 4 FAIL

- [ ] **Step 3: Implement in `window_manager.py`**

Add to `_handle`:

```python
elif kind == "show_settings":
    self.show_settings()

elif kind == "rebuild_tray_menu":
    if self._on_rebuild_tray is not None:
        try:
            self._on_rebuild_tray()
        except Exception:
            log.debug("Error in on_rebuild_tray callback", exc_info=True)
```

Update the existing `set_icon` branch to track pipeline state (preserve existing try/except body):

```python
elif kind == "set_icon":
    _, state = item
    self._last_pipeline_active = state in {"recording", "processing"}
    if self._on_icon_state is not None:
        try:
            self._on_icon_state(state)
        except Exception:
            log.debug("Error in on_icon_state callback", exc_info=True)
```

Add method:

```python
def show_settings(self) -> None:
    """Open the Settings window. Stacks on top of Workflow/History; refocuses
    if already open. Does NOT participate in the Workflow ↔ History block."""
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

Extend `_sweep_stale_window_refs`:

```python
if self._settings_win is not None and not _win_alive(self._settings_win._win):
    self._settings_win = None
```

Extend `_update_activation_policy`'s `any_open` expression:

```python
any_open = (
    (self._workflow_win is not None and _win_alive(self._workflow_win._win))
    or (self._history_win is not None and _win_alive(self._history_win._win))
    or (self._settings_win is not None and _win_alive(self._settings_win._win))
)
```

- [ ] **Step 4: Run all WindowManager tests, expect PASS**

Note: `show_settings` test will fail because `SettingsWindow` doesn't exist yet. Patch the import inside the test for now — or skip that single test. Better: use MagicMock to intercept.

Append a final test using a patched SettingsWindow:

```python
def test_show_settings_creates_window_when_none(tmp_path, monkeypatch):
    monkeypatch.setattr(window_manager.tk, "Tk", MagicMock())
    wm = window_manager.WindowManager(_make_cfg(tmp_path), queue.Queue())

    fake_window_cls = MagicMock()
    instance = MagicMock(_win=MagicMock(winfo_exists=lambda: True))
    fake_window_cls.return_value = instance
    monkeypatch.setattr(
        "summarizeaudio.settings_window.SettingsWindow", fake_window_cls, raising=False
    )
    # Inject a fake module to satisfy the lazy import in show_settings.
    import sys, types
    fake_mod = types.ModuleType("summarizeaudio.settings_window")
    fake_mod.SettingsWindow = fake_window_cls
    monkeypatch.setitem(sys.modules, "summarizeaudio.settings_window", fake_mod)

    wm.show_settings()
    fake_window_cls.assert_called_once()
    instance.show.assert_called_once()
    assert wm._settings_win is instance
```

Run: `./venv/bin/python -m pytest tests/test_window_manager.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add summarizeaudio/window_manager.py tests/test_window_manager.py
git commit -m "feat(wm): add show_settings, rebuild_tray_menu, pipeline-active tracking"
```

---

## Chunk 4: SettingsWindow

Largest chunk. Build incrementally: skeleton → populate dropdowns → Apply/Cancel → disabled states → banner.

### Task 4.1: Skeleton (Toplevel + two combos + buttons, no behavior)

**Files:**
- Create: `summarizeaudio/settings_window.py`
- Create: `tests/test_settings_window.py`

- [ ] **Step 1: Write failing skeleton test**

```python
# tests/test_settings_window.py
from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest

from summarizeaudio.config import (
    AppConfig, BehaviorConfig, OllamaConfig, RecordingConfig,
    StorageConfig, SummarizationConfig, WhisperConfig,
)
from summarizeaudio.ollama_client import ModelInfo


def _cfg(tmp_path: Path, model: str = "gemma3:4b", device: str | None = None) -> AppConfig:
    return AppConfig(
        storage=StorageConfig(output_folder=tmp_path),
        whisper=WhisperConfig(model="tiny", language="en"),
        ollama=OllamaConfig(host="http://localhost:11434", model=model),
        summarization=SummarizationConfig(default_prompt="x"),
        behavior=BehaviorConfig(show_override_dialog=False, auto_open_summary=False),
        recording=RecordingConfig(input_device=device),
    )


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk not available")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except Exception:
        pass


def _fake_devices():
    return [
        {"name": "Built-in Microphone", "max_input_channels": 1},
        {"name": "BlackHole 2ch", "max_input_channels": 2},
    ]


def _fake_models():
    return [ModelInfo(name="gemma3:4b", family="gemma3")]


def test_settings_window_builds_with_two_comboboxes(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=_fake_models()), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=lambda idx=None: _fake_devices() if idx is None else _fake_devices()[idx]):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
    assert win._input_combo is not None
    assert win._model_combo is not None
    assert win._apply_btn is not None
    assert win._cancel_btn is not None
    win.close()
```

- [ ] **Step 2: Run, expect ImportError**

Run: `./venv/bin/python -m pytest tests/test_settings_window.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create `settings_window.py` skeleton**

```python
# summarizeaudio/settings_window.py
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
        self._populate_input_devices()

        ttk.Label(body, text="Summarization Model").pack(anchor="w")
        self._model_combo = ttk.Combobox(body, state="readonly", width=44)
        self._model_combo.pack(fill="x", pady=(2, 12))
        self._populate_models()

        if self._pipeline_active:
            banner = tk.Frame(body, bg="#fde68a")
            banner.pack(fill="x", pady=(0, 8))
            tk.Label(
                banner,
                text="Changes take effect on the next run.",
                bg="#fde68a", fg="#92400e",
                padx=8, pady=4,
            ).pack(anchor="w")

        self._error_label = ttk.Label(body, text="", foreground="#dc2626")
        self._error_label.pack(anchor="w", pady=(0, 4))

        btn_row = ttk.Frame(body)
        btn_row.pack(fill="x", pady=(8, 0))
        self._cancel_btn = ttk.Button(btn_row, text="Cancel", command=self._on_cancel)
        self._cancel_btn.pack(side="right", padx=(0, 0))
        self._apply_btn = ttk.Button(btn_row, text="Apply", command=self._on_apply)
        self._apply_btn.pack(side="right", padx=(0, 8))

        self._win.bind("<Return>", lambda _e: self._on_apply())
        self._win.bind("<Escape>", lambda _e: self._on_cancel())

    def _populate_input_devices(self) -> None:
        assert self._input_combo is not None
        configured = self._cfg.recording.input_device or ""
        values: list[str] = []
        # Resolve auto-detect name for the first entry.
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
        # Inject not-connected entry if configured device not in list.
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
            # Match the label form (may have suffix).
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

        # Translate input device label → stored value.
        if input_choice.startswith(_AUTO_LABEL_PREFIX):
            new_device: str | None = None
        elif input_choice.endswith("(not connected)"):
            new_device = input_choice.rsplit(" (not connected)", 1)[0]
        else:
            new_device = input_choice

        # Translate model label → stored value.
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
            # Restore in-memory cfg; keep window open with error.
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
```

- [ ] **Step 4: Run the skeleton test**

Run: `./venv/bin/python -m pytest tests/test_settings_window.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add summarizeaudio/settings_window.py tests/test_settings_window.py
git commit -m "feat: add SettingsWindow skeleton with comboboxes + Apply/Cancel"
```

### Task 4.2: Apply / Cancel behavior tests

- [ ] **Step 1: Append tests**

```python
# Append to tests/test_settings_window.py

def test_apply_mutates_cfg_calls_save_and_enqueues_rebuild(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    saved = []
    monkeypatch.setattr(
        "summarizeaudio.settings_window.save_config",
        lambda cfg: saved.append((cfg.recording.input_device, cfg.ollama.model)),
    )
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=[ModelInfo(name="gemma3:4b", family="gemma3"), ModelInfo(name="gemma3:12b", family="gemma3")]), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=lambda idx=None: _fake_devices() if idx is None else _fake_devices()[idx]):
        cfg = _cfg(tmp_path, model="gemma3:4b", device=None)
        q: queue.Queue = queue.Queue()
        win = SettingsWindow(root, cfg, q)
        win.show()
        win._input_combo.set("BlackHole 2ch")
        win._model_combo.set("gemma3:12b")
        win._on_apply()

    assert saved == [("BlackHole 2ch", "gemma3:12b")]
    assert cfg.recording.input_device == "BlackHole 2ch"
    assert cfg.ollama.model == "gemma3:12b"
    assert q.get_nowait() == ("rebuild_tray_menu",)


def test_apply_autodetect_stores_none(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    monkeypatch.setattr("summarizeaudio.settings_window.save_config", lambda _cfg: None)
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=[ModelInfo(name="gemma3:4b", family="gemma3")]), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=lambda idx=None: _fake_devices() if idx is None else _fake_devices()[idx]):
        cfg = _cfg(tmp_path, device="BlackHole 2ch")
        win = SettingsWindow(root, cfg, queue.Queue())
        win.show()
        # Pick the auto-detect entry (first value).
        win._input_combo.set(win._input_values[0])
        win._on_apply()
    assert cfg.recording.input_device is None


def test_cancel_does_not_mutate_or_save(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow
    save_calls = []
    monkeypatch.setattr("summarizeaudio.settings_window.save_config", lambda cfg: save_calls.append(cfg))
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=[ModelInfo(name="gemma3:4b", family="gemma3")]), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=lambda idx=None: _fake_devices() if idx is None else _fake_devices()[idx]):
        cfg = _cfg(tmp_path)
        win = SettingsWindow(root, cfg, queue.Queue())
        win.show()
        win._input_combo.set("BlackHole 2ch")
        win._on_cancel()
    assert save_calls == []
    assert cfg.recording.input_device is None


def test_apply_restores_cfg_on_save_failure(root, tmp_path, monkeypatch):
    from summarizeaudio.settings_window import SettingsWindow

    def boom(_cfg):
        raise OSError("disk full")

    monkeypatch.setattr("summarizeaudio.settings_window.save_config", boom)
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=[ModelInfo(name="gemma3:4b", family="gemma3"), ModelInfo(name="gemma3:12b", family="gemma3")]), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=lambda idx=None: _fake_devices() if idx is None else _fake_devices()[idx]):
        cfg = _cfg(tmp_path, model="gemma3:4b")
        q: queue.Queue = queue.Queue()
        win = SettingsWindow(root, cfg, q)
        win.show()
        win._model_combo.set("gemma3:12b")
        win._on_apply()
    # Cfg reverted.
    assert cfg.ollama.model == "gemma3:4b"
    # Window still alive.
    assert win._win.winfo_exists()
    # Error label populated.
    assert "Failed to save settings" in win._error_label.cget("text")
    # No rebuild enqueued.
    with pytest.raises(queue.Empty):
        q.get_nowait()
```

- [ ] **Step 2: Run all settings tests**

Run: `./venv/bin/python -m pytest tests/test_settings_window.py -v`
Expected: 5 PASS (1 skeleton + 4 new)

- [ ] **Step 3: Commit**

```bash
git add tests/test_settings_window.py
git commit -m "test(settings): cover apply/cancel/restore paths"
```

### Task 4.3: Disabled-state tests (Ollama down, no models, not-installed)

- [ ] **Step 1: Append tests**

```python
def test_ollama_down_disables_combo_and_apply(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=None), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=lambda idx=None: _fake_devices() if idx is None else _fake_devices()[idx]):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
    assert str(win._apply_btn["state"]) == "disabled"
    assert str(win._model_combo["state"]) == "disabled"
    assert "Ollama not running" in win._model_combo.get()


def test_no_models_disables_combo_and_apply(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=[]), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=lambda idx=None: _fake_devices() if idx is None else _fake_devices()[idx]):
        win = SettingsWindow(root, _cfg(tmp_path), queue.Queue())
        win.show()
    assert str(win._apply_btn["state"]) == "disabled"
    assert "No models installed" in win._model_combo.get()


def test_configured_model_not_installed_injects_entry(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=[ModelInfo(name="llama3:8b", family="llama")]), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=lambda idx=None: _fake_devices() if idx is None else _fake_devices()[idx]):
        cfg = _cfg(tmp_path, model="gemma3:4b")
        win = SettingsWindow(root, cfg, queue.Queue())
        win.show()
    assert win._model_combo.get() == "gemma3:4b (not installed)"
    assert "gemma3:4b (not installed)" in win._model_values
    # Apply remains enabled.
    assert str(win._apply_btn["state"]) != "disabled"


def test_embedding_model_gets_suffix(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=[
        ModelInfo(name="gemma3:4b", family="gemma3"),
        ModelInfo(name="nomic-embed-text", family="bert"),
    ]), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=lambda idx=None: _fake_devices() if idx is None else _fake_devices()[idx]):
        cfg = _cfg(tmp_path, model="gemma3:4b")
        win = SettingsWindow(root, cfg, queue.Queue())
        win.show()
    assert "nomic-embed-text · embedding" in win._model_values


def test_banner_visible_only_when_pipeline_active(root, tmp_path):
    from summarizeaudio.settings_window import SettingsWindow
    with patch("summarizeaudio.settings_window.list_installed_models", return_value=[ModelInfo(name="gemma3:4b", family="gemma3")]), \
         patch("summarizeaudio.settings_window.sd.query_devices", side_effect=lambda idx=None: _fake_devices() if idx is None else _fake_devices()[idx]):
        win_inactive = SettingsWindow(root, _cfg(tmp_path), queue.Queue(), pipeline_active=False)
        win_active = SettingsWindow(root, _cfg(tmp_path), queue.Queue(), pipeline_active=True)
        win_inactive.show()
        win_active.show()

    def has_banner(win) -> bool:
        for child in win._win.winfo_children():
            for grand in child.winfo_children():
                if isinstance(grand, tk.Frame) and grand.cget("bg") == "#fde68a":
                    return True
        return False

    assert not has_banner(win_inactive)
    assert has_banner(win_active)
```

- [ ] **Step 2: Run all settings tests**

Run: `./venv/bin/python -m pytest tests/test_settings_window.py -v`
Expected: 10 PASS total

- [ ] **Step 3: Commit**

```bash
git add tests/test_settings_window.py
git commit -m "test(settings): cover disabled states + embedding marker + banner"
```

---

## Chunk 5: Tray integration

Remove old menu items, wire up new ones, register rebuild callback.

### Task 5.1: Remove old tests and helpers; update _fake_wm

**Files:**
- Modify: `tests/test_tray.py`
- Modify: `summarizeaudio/tray.py`

- [ ] **Step 1: Delete obsolete tests from `tests/test_tray.py`**

Remove these two tests entirely (they test removed behavior):

- `test_model_menu_checks_current_config_model`
- `test_model_menu_updates_checkmark_after_selection`

Update `_fake_wm` and `_fake_wm_immediate` to accept the new keyword arg (signature change is in Chunk 3):

```python
def _fake_wm():
    return SimpleNamespace(
        root=SimpleNamespace(after=lambda *a: None, quit=lambda: None),
        block_for_open_window=lambda: False,
    )


def _fake_wm_immediate():
    return SimpleNamespace(
        root=SimpleNamespace(after=lambda _delay, func: func(), quit=lambda: None),
        block_for_open_window=lambda: False,
    )
```

(No change needed if the fakes are already keyword-tolerant via SimpleNamespace; the `WindowManager` factory monkeypatch needs to accept `on_rebuild_tray=None` though.)

Update every monkeypatch that intercepts `WindowManager(...)` to accept the new kwargs. Search for `WindowManager:` lambda signatures in `tests/test_tray.py`:

```python
# Before:
lambda cfg, ui_queue, on_icon_state=None: _fake_wm()
# After:
lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm()
```

Apply to every occurrence in `tests/test_tray.py`.

- [ ] **Step 2: Run tests to confirm baseline still passes (some may be RED)**

Run: `./venv/bin/python -m pytest tests/test_tray.py -v 2>&1 | tail -40`
Expected: many failures because tray.py still references removed methods AND because we removed two tests. That's fine — we'll fix tray.py next.

- [ ] **Step 3: Commit the test cleanup**

```bash
git add tests/test_tray.py
git commit -m "test(tray): drop Fast/High Quality menu tests; accept on_rebuild_tray kwarg"
```

### Task 5.2: Tray refactor — remove old, add new

- [ ] **Step 1: Write the new tests first**

Append to `tests/test_tray.py`:

```python
def test_rebuild_menu_has_input_audio_and_summarization_items(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr(
        "summarizeaudio.window_manager.WindowManager",
        lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm(),
    )
    monkeypatch.setattr("summarizeaudio.tray.resolve_auto_input_device_name", lambda: "BlackHole 2ch")
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None)
    app._rebuild_menu()

    items = list(app._tray.menu.items)
    texts = [getattr(item, "text", "") for item in items]
    assert "Input Audio: Auto (BlackHole 2ch)" in texts
    assert "Summarization: gemma3:4b" in texts
    # Old items gone.
    assert not any("Fast Mode" in t for t in texts)
    assert not any("High Quality Mode" in t for t in texts)
    assert not any("Summarization Model" in t and "gemma3" not in t for t in texts)


def test_input_audio_label_uses_configured_name_when_set(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr(
        "summarizeaudio.window_manager.WindowManager",
        lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm(),
    )
    app = TrayApp()
    app._cfg.recording.input_device = "USB Mic"
    assert app._input_audio_label() == "Input Audio: USB Mic"


def test_input_audio_label_falls_back_when_resolution_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr(
        "summarizeaudio.window_manager.WindowManager",
        lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm(),
    )
    monkeypatch.setattr("summarizeaudio.tray.resolve_auto_input_device_name", lambda: None)
    app = TrayApp()
    assert app._input_audio_label() == "Input Audio: Auto (none)"


def test_settings_click_enqueues_show_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr(
        "summarizeaudio.window_manager.WindowManager",
        lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm(),
    )
    app = TrayApp()
    app._on_settings_click(None, None)
    assert app._ui_queue.get_nowait() == ("show_settings",)


def test_on_rebuild_tray_request_calls_rebuild_menu(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    monkeypatch.setattr(
        "summarizeaudio.window_manager.WindowManager",
        lambda cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None: _fake_wm(),
    )
    app = TrayApp()
    app._tray = SimpleNamespace(menu=None)
    app._rebuild_menu = lambda: setattr(app, "_rebuilt", True)
    app._on_rebuild_tray_request()
    assert getattr(app, "_rebuilt", False) is True


def test_window_manager_receives_on_rebuild_tray(tmp_path, monkeypatch):
    monkeypatch.setattr("summarizeaudio.tray.load_config", lambda _q=None: make_config(tmp_path, "gemma3:4b"))
    captured = {}
    def fake_wm_factory(cfg, ui_queue, on_icon_state=None, on_rebuild_tray=None):
        captured["on_rebuild_tray"] = on_rebuild_tray
        return _fake_wm()
    monkeypatch.setattr("summarizeaudio.window_manager.WindowManager", fake_wm_factory)
    app = TrayApp()
    assert captured["on_rebuild_tray"] is not None
    # It should be the bound method.
    assert captured["on_rebuild_tray"] == app._on_rebuild_tray_request
```

- [ ] **Step 2: Run, expect FAIL on imports / attributes**

Run: `./venv/bin/python -m pytest tests/test_tray.py -v 2>&1 | tail -40`
Expected: many failures referencing `_input_audio_label`, `_on_settings_click`, etc.

- [ ] **Step 3: Refactor `summarizeaudio/tray.py`**

Make these changes:

(a) Add import near the top:

```python
from summarizeaudio.recorder import Recorder, check_input_health, resolve_auto_input_device_name
```

(b) Update `WindowManager` construction in `__init__`:

```python
self._window_manager = WindowManager(
    self._cfg, self._ui_queue,
    on_icon_state=self._on_icon_state,
    on_rebuild_tray=self._on_rebuild_tray_request,
)
```

(c) **Delete** these methods entirely:
- `_on_quality_fast`
- `_on_quality_high`
- `_model_label`
- `_set_model`

(d) **Add** these new methods to `TrayApp`:

```python
def _input_audio_label(self) -> str:
    configured = self._cfg.recording.input_device
    if configured:
        return f"Input Audio: {configured}"
    resolved = resolve_auto_input_device_name()
    if resolved:
        return f"Input Audio: Auto ({resolved})"
    return "Input Audio: Auto (none)"

def _summarization_label(self) -> str:
    return f"Summarization: {self._cfg.ollama.model}"

def _on_settings_click(self, icon, item) -> None:
    self._ui_queue.put(("show_settings",))

def _on_rebuild_tray_request(self) -> None:
    # Runs on the Tk main thread (invoked from WindowManager._handle).
    # Do not call from the pystray thread.
    self._rebuild_menu()
```

(e) **Replace** the Summarization Model section in `_rebuild_menu`. Find:

```python
items.append(pystray.MenuItem("Summarization Model", None, enabled=False))
fast_label = self._model_label("gemma3:4b", "Fast Mode (gemma3:4b)")
high_label = self._model_label("gemma3:12b", "High Quality Mode (gemma3:12b)")
items.append(pystray.MenuItem(fast_label, self._on_quality_fast))
items.append(pystray.MenuItem(high_label, self._on_quality_high))
```

Replace with:

```python
items.append(pystray.MenuItem(self._input_audio_label(), self._on_settings_click))
items.append(pystray.MenuItem(self._summarization_label(), self._on_settings_click))
```

- [ ] **Step 4: Run tray tests**

Run: `./venv/bin/python -m pytest tests/test_tray.py -v 2>&1 | tail -60`
Expected: all PASS

- [ ] **Step 5: Run full test suite to catch regressions**

Run: `./venv/bin/python -m pytest --ignore=tests/test_pipeline.py -v 2>&1 | tail -40`
Expected: PASS for everything in this work. The 7 pre-existing failures in `tests/test_workflow_window.py` and 1 in `tests/test_history_window.py` (per project memory) are unrelated and remain.

If new failures appear in `test_workflow_window.py` or `test_history_window.py` that are NOT in the documented baseline, fix them. To verify baseline:

```bash
git stash
./venv/bin/python -m pytest tests/test_workflow_window.py tests/test_history_window.py 2>&1 | grep -E "FAIL|ERROR" | sort > /tmp/baseline_failures.txt
git stash pop
./venv/bin/python -m pytest tests/test_workflow_window.py tests/test_history_window.py 2>&1 | grep -E "FAIL|ERROR" | sort > /tmp/current_failures.txt
diff /tmp/baseline_failures.txt /tmp/current_failures.txt
```

Empty diff = no regressions.

- [ ] **Step 6: Commit**

```bash
git add summarizeaudio/tray.py tests/test_tray.py
git commit -m "feat(tray): replace Fast/High Quality submenu with status items + Settings"
```

---

## Chunk 6: Manual smoke test + docs

### Task 6.1: Manual smoke test

The app must be quit and relaunched after every code change (Python doesn't hot-reload).

- [ ] **Step 1: Quit any running instance**

If the app is running, click the menu bar icon → Quit.

- [ ] **Step 2: Launch dev build**

Run: `./venv/bin/python -m summarizeaudio &`
Expected: tray icon appears within ~2 seconds.

- [ ] **Step 3: Verify menu structure**

Click the tray icon. Confirm the menu shows:
- Start Recording
- Transcribe & Summarize Audio File…
- Summarize Text File…
- ──
- History…
- ──
- Input Audio: Auto (...) — or your configured device
- Summarization: gemma3:4b — or your configured model
- ──
- Quit

The "Summarization Model" header + Fast / High Quality items must be gone.

- [ ] **Step 4: Open Settings via Input Audio item**

Click `Input Audio: ...`. Settings window opens with both dropdowns populated.

- [ ] **Step 5: Verify dropdown selection round-trip**

Pick a different model. Click Apply. Window closes. Tray menu now shows the new model in the Summarization label.

- [ ] **Step 6: Verify Settings can stack on Workflow**

Open Workflow (Start Recording, stop after 3s — Workflow opens after stop). With Workflow open, click `Summarization: ...`. Settings window opens on top. Confirm both windows are visible. Close Settings — Workflow remains.

- [ ] **Step 7: Verify Settings-already-open refocuses**

With Settings open, click `Input Audio: ...` again. Settings window is brought to front, no second window opened.

- [ ] **Step 8: Verify Ollama-down state**

Run: `pkill -f ollama` (if Ollama is running). Reopen Settings. Summarization combobox shows "Ollama not running..." and Apply is disabled. Then `ollama serve &` to bring it back.

- [ ] **Step 9: No commit; this step is manual verification only.**

### Task 6.2: Update architecture.md

- [ ] **Step 1: Read current `docs/architecture.md`**

Run: `head -40 docs/architecture.md`

- [ ] **Step 2: Edit `docs/architecture.md`**

(a) Find and **remove** the stale `rumps` reference line (project memory says: "rumps appears in docs but pystray is the active library").

(b) Add two new bullets to the component list, modeled after the existing entries:

```
- `settings_window.py` — Tk Toplevel for editing input audio device + summarization model; opens from new tray menu items, stacks on top of other windows.
- `ollama_client.py` — Stdlib HTTP helper that lists models installed in the local Ollama runtime via GET /api/tags.
```

(c) Update the Mermaid diagram if it shows window types: add a `SettingsWindow` node connected to `WindowManager` and to a `SettingsClick` arrow from the tray.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "docs(architecture): add settings_window + ollama_client; drop stale rumps note"
```

### Task 6.3: Append ADR

- [ ] **Step 1: Edit `docs/adr.md`**

Append a new ADR entry in Nygard format:

```markdown
## ADR: Inline status items + shared Settings window for input/model

### Context

The tray menu carried a hardcoded "Summarization Model" submenu with two
fixed model choices (Fast Mode, High Quality Mode) and no way to change the
input audio device without editing config.toml. Users want to:

1. See the active values without opening anything.
2. Change either value through the UI.
3. Pick from whatever Ollama models are actually installed.

### Decision

Replace the hardcoded submenu with two inline tray items that display the
current values:

- `Input Audio: <resolved-name>`
- `Summarization: <model-name>`

Clicking either opens a single shared Settings window with two readonly
dropdowns and Apply/Cancel buttons. The Summarization dropdown is populated
dynamically from `GET <ollama-host>/api/tags`. Settings can stack on top of
Workflow/History (does not participate in the one-window-at-a-time rule
that blocks Workflow ↔ History).

### Consequences

- Removes the hardcoded model list; users can pick any installed Ollama model.
- Introduces a new window type that must be tracked by WindowManager (sweep,
  activation policy, focus rule when already open).
- Adds a soft dependency on Ollama being reachable at Settings-open time;
  failure is surfaced as a disabled combobox with explanatory text.
- Diarization remains env-var gated by `HUGGINGFACE_ACCESS_TOKEN`; no UI
  toggle introduced.
```

- [ ] **Step 2: Commit**

```bash
git add docs/adr.md
git commit -m "docs(adr): record settings window decision"
```

---

## Final verification

- [ ] **Step 1: Full test suite (excluding slow pipeline tests)**

Run: `./venv/bin/python -m pytest --ignore=tests/test_pipeline.py 2>&1 | tail -20`
Expected: only the documented pre-existing failures remain (7 in test_workflow_window.py, 1 in test_history_window.py).

- [ ] **Step 2: Restart and smoke test once more**

Quit + relaunch the app. Verify the entire flow end-to-end:
1. Tray shows new items with current values.
2. Apply persists to `~/.summarizeaudio/config.toml`.
3. Restart app — values persist.

- [ ] **Step 3: Push branch (only if user confirms)**

Do NOT push without user confirmation. Surface the branch state and ask.
