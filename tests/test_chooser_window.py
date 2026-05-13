from __future__ import annotations

from summarizeaudio import chooser_window


def test_native_audio_picker_uses_osascript(monkeypatch):
    calls = []

    def fake_osascript(script: str):
        calls.append(script)
        return 0, "/tmp/example.mp3"

    monkeypatch.setattr(chooser_window, "_osascript", fake_osascript)
    monkeypatch.setattr(chooser_window.sys, "platform", "darwin")

    assert chooser_window._native_audio_picker("Select Audio File") == "/tmp/example.mp3"
    assert calls
    assert "choose file with prompt \"Select Audio File\"" in calls[0]
