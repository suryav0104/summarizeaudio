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


def test_enable_writes_a_well_formed_plist(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(startup.sys, "executable", "/opt/app/venv/bin/python3.12")

    startup.enable()

    p = startup.plist_path()
    assert p.exists()
    with p.open("rb") as f:
        data = plistlib.load(f)
    assert data["Label"] == startup.LABEL
    assert data["ProgramArguments"] == [
        "/opt/app/venv/bin/python3.12", "-m", "summarizeaudio",
    ]
    # sys.executable is <install>/venv/bin/python -> install dir is 3 hops up.
    assert data["WorkingDirectory"] == "/opt/app"
    assert data["RunAtLoad"] is True
    assert "/opt/homebrew/bin" in data["EnvironmentVariables"]["PATH"]
    assert "/usr/local/bin" in data["EnvironmentVariables"]["PATH"]


def test_is_enabled_tracks_file_presence(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert startup.is_enabled() is False
    startup.enable()
    assert startup.is_enabled() is True


def test_disable_removes_plist_and_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    startup.enable()
    assert startup.is_enabled() is True
    startup.disable()
    assert startup.is_enabled() is False
    # Calling again must not raise.
    startup.disable()
    assert startup.is_enabled() is False
