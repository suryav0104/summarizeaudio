from __future__ import annotations

import plistlib

import pytest

from summarizeaudio import startup


def test_is_supported_reflects_platform(monkeypatch):
    monkeypatch.setattr(startup.sys, "platform", "darwin")
    assert startup.is_supported() is True
    monkeypatch.setattr(startup.sys, "platform", "linux")
    assert startup.is_supported() is False


def test_plist_path_under_launchagents_and_named_from_label(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = startup.plist_path()
    assert p == tmp_path / "Library" / "LaunchAgents" / f"{startup.LABEL}.plist"
    assert p.name == f"{startup.LABEL}.plist"
