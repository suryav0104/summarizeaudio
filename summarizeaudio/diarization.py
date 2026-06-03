"""Speaker-diarization capability detection and setup instructions.

Single source of truth for *whether* diarization can run and *how* to enable it.
Diarization has three prerequisites; only the third is a user preference:

  1. ``pyannote.audio`` installed                (package)
  2. ``HUGGINGFACE_ACCESS_TOKEN`` set + gated models accepted   (credential)
  3. the user turned it on in config             (preference)

``effective_enabled(cfg)`` is the one true gate: preference AND capability.
The same ``SETUP_STEPS`` drive both the installer's terminal output and the
Settings window's "How to enable" panel, so the instructions never drift.
"""
from __future__ import annotations

import importlib.util
import os
from typing import Any

TOKEN_ENV_VAR = "HUGGINGFACE_ACCESS_TOKEN"


def pyannote_installed() -> bool:
    """True if the optional ``pyannote.audio`` package is importable.

    Uses ``find_spec`` so it does not import torch (a heavy, slow import).
    """
    return importlib.util.find_spec("pyannote.audio") is not None


def token_present() -> bool:
    """True if a non-empty HuggingFace access token is in the environment."""
    return bool(os.environ.get(TOKEN_ENV_VAR))


def is_available() -> bool:
    """True when both diarization prerequisites (package + token) are satisfied."""
    return pyannote_installed() and token_present()


def effective_enabled(cfg: Any) -> bool:
    """True only when the user enabled diarization AND it can actually run.

    Guards against the failure mode where the preference is on but the package
    or token is missing — that would otherwise advertise a step that crashes
    mid-transcription.
    """
    return bool(getattr(cfg.diarization, "enabled", False)) and is_available()


def missing_reason() -> str | None:
    """Human-readable reason diarization is unavailable, or None if available.

    Reports the package gap first since it is the prerequisite for everything.
    """
    if not pyannote_installed():
        return "pyannote.audio is not installed"
    if not token_present():
        return "HuggingFace access token is not set"
    return None


# Canonical setup steps. Rendered to the terminal by the installer and into the
# Settings "How to enable" panel — edit here only.
SETUP_STEPS: list[str] = [
    "Install the optional package: from your install directory run "
    "`venv/bin/pip install -e '.[diarization]'` (this pulls PyTorch, a large download).",
    "Create a free HuggingFace account and a READ token at "
    "https://huggingface.co/settings/tokens.",
    "While logged in, accept the user conditions on BOTH gated models: "
    "https://huggingface.co/pyannote/speaker-diarization-3.1 and "
    "https://huggingface.co/pyannote/segmentation-3.0 "
    "(the pipeline loads the segmentation model internally, so both are required).",
    f"Add the token to the `.env` file in your install directory: "
    f"`{TOKEN_ENV_VAR}=hf_your_token_here`.",
    "Re-check (or relaunch the app) to confirm diarization is now available.",
]


def render_setup_steps(surface: str = "window") -> str:
    """Render SETUP_STEPS as a numbered block.

    surface: "window" or "terminal" — both number the steps; terminal output
    is indented for readability under the installer's banner.
    """
    indent = "  " if surface == "terminal" else ""
    return "\n".join(f"{indent}{i}. {step}" for i, step in enumerate(SETUP_STEPS, start=1))
