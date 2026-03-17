from __future__ import annotations

import queue
import traceback as tb_module


def post_error(
    ui_queue: queue.Queue | None,
    component: str,
    message: str,
    traceback_str: str,
) -> None:
    """Post an error popup request to ui_queue for display on the main thread."""
    if ui_queue is None:
        return
    try:
        ui_queue.put_nowait(("error", component, message, traceback_str))
    except queue.Full:
        pass


def format_error(component: str, message: str, traceback_str: str) -> str:
    """Format a human-readable error string for display."""
    lines = traceback_str.strip().splitlines()
    last_10 = "\n".join(lines[-10:]) if lines else ""
    return f"Component: {component}\n\nError: {message}\n\nDetails:\n{last_10}"
