from __future__ import annotations

import logging
import subprocess
import sys


def notify(message: str, title: str = "SummarizeAudio") -> None:
    """Send a system notification. Falls back gracefully on all platforms."""
    if sys.platform == "darwin":
        _notify_macos(title, message)
    else:
        _notify_plyer(title, message)


def _notify_macos(title: str, message: str) -> None:
    safe_msg = message.replace('"', '\\"')
    safe_title = title.replace('"', '\\"')
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
    except Exception:
        _notify_plyer(title, message)


def _notify_plyer(title: str, message: str) -> None:
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=5)
    except Exception:
        logging.info("[SummarizeAudio] %s: %s", title, message)
