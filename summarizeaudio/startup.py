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
