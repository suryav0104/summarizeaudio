"""macOS launch-at-login via a LaunchAgent plist.

The plist's presence on disk is the single source of truth: writing it enables
launch at login (effective next login, RunAtLoad=true), removing it disables.
There is no mirrored flag in config.toml. macOS only; on other platforms the
functions are safe no-ops and is_supported() is False.
"""
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

# Reverse-DNS label; also the plist filename stem so the two cannot drift.
LABEL = "com.summarizeaudio"


def is_supported() -> bool:
    """True only on macOS. Gates the whole feature."""
    return sys.platform == "darwin"


def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path() -> Path:
    """Absolute path to the LaunchAgent plist (filename derived from LABEL)."""
    return _launch_agents_dir() / f"{LABEL}.plist"


def is_enabled() -> bool:
    """True when the LaunchAgent plist exists on disk."""
    return plist_path().exists()


def _install_dir() -> Path:
    # sys.executable is <install>/venv/bin/python; three hops up
    # (bin -> venv -> install) reach the install dir where .env and the
    # editable package live. parents[1] would wrongly stop at <install>/venv.
    return Path(sys.executable).parents[2]


def _log_path() -> Path:
    return Path.home() / ".summarizeaudio" / "launchd.log"


def _plist_dict() -> dict:
    log = str(_log_path())
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "summarizeaudio"],
        # So load_dotenv() (CWD-relative) finds <install>/.env at login.
        "WorkingDirectory": str(_install_dir()),
        "RunAtLoad": True,
        # Login agents get a stripped PATH; restore it so ffmpeg/ollama resolve.
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        },
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def enable() -> None:
    """Write the LaunchAgent plist (creating ~/Library/LaunchAgents if needed)."""
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        plistlib.dump(_plist_dict(), f)


def disable() -> None:
    """Remove the LaunchAgent plist if present (idempotent)."""
    plist_path().unlink(missing_ok=True)
