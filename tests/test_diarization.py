"""Tests for the diarization capability/instructions module.

These run without pyannote.audio installed or any HuggingFace token —
the environment is faked via monkeypatch.
"""
from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest

from summarizeaudio import diarization


def _fake_cfg(enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(diarization=SimpleNamespace(enabled=enabled))


# ── token_present ─────────────────────────────────────────────────────────────

def test_token_present_true_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "hf_real")
    assert diarization.token_present() is True


def test_token_present_false_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HUGGINGFACE_ACCESS_TOKEN", raising=False)
    assert diarization.token_present() is False


def test_token_present_false_when_env_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "")
    assert diarization.token_present() is False


# ── pyannote_installed ────────────────────────────────────────────────────────

def test_pyannote_installed_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert diarization.pyannote_installed() is True


def test_pyannote_installed_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert diarization.pyannote_installed() is False


# ── is_available (both prerequisites) ─────────────────────────────────────────

def test_is_available_requires_package_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "hf_real")
    assert diarization.is_available() is True


def test_is_available_false_without_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "hf_real")
    assert diarization.is_available() is False


def test_is_available_false_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.delenv("HUGGINGFACE_ACCESS_TOKEN", raising=False)
    assert diarization.is_available() is False


# ── effective_enabled (preference AND capability) ─────────────────────────────

def test_effective_enabled_true_when_enabled_and_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "hf_real")
    assert diarization.effective_enabled(_fake_cfg(True)) is True


def test_effective_enabled_false_when_config_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "hf_real")
    assert diarization.effective_enabled(_fake_cfg(False)) is False


def test_effective_enabled_false_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Preference on, but package missing → must stay off (the bug we are fixing).
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "hf_real")
    assert diarization.effective_enabled(_fake_cfg(True)) is False


# ── missing_reason ────────────────────────────────────────────────────────────

def test_missing_reason_reports_package_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    monkeypatch.delenv("HUGGINGFACE_ACCESS_TOKEN", raising=False)
    reason = diarization.missing_reason()
    assert reason is not None
    assert "pyannote" in reason.lower()


def test_missing_reason_reports_token_when_package_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.delenv("HUGGINGFACE_ACCESS_TOKEN", raising=False)
    reason = diarization.missing_reason()
    assert reason is not None
    assert "token" in reason.lower()


def test_missing_reason_none_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("HUGGINGFACE_ACCESS_TOKEN", "hf_real")
    assert diarization.missing_reason() is None


# ── setup instructions (single source of truth) ───────────────────────────────

def test_setup_steps_is_nonempty_ordered_list() -> None:
    assert isinstance(diarization.SETUP_STEPS, list)
    assert len(diarization.SETUP_STEPS) >= 3
    assert all(isinstance(s, str) and s for s in diarization.SETUP_STEPS)


def test_render_setup_steps_mentions_both_gated_models() -> None:
    text = diarization.render_setup_steps()
    assert "speaker-diarization-3.1" in text
    assert "segmentation-3.0" in text


def test_render_setup_steps_mentions_token_env_var() -> None:
    text = diarization.render_setup_steps()
    assert "HUGGINGFACE_ACCESS_TOKEN" in text


def test_render_setup_steps_numbered_in_terminal_surface() -> None:
    text = diarization.render_setup_steps(surface="terminal")
    # Terminal rendering numbers the steps.
    assert "1." in text
