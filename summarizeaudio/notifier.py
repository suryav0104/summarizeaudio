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
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "summarizeaudio.alert_window", "--title", title],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if proc.stdin is not None:
            proc.stdin.write(message)
            proc.stdin.close()
    except Exception:
        _notify_plyer(title, message)


def _notify_plyer(title: str, message: str) -> None:
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=5)
    except Exception:
        logging.info("[SummarizeAudio] %s: %s", title, message)
