from __future__ import annotations

from unittest.mock import patch

from summarizeaudio.recorder import resolve_auto_input_device_name


def test_resolve_auto_input_device_name_returns_resolved_name():
    with patch(
        "summarizeaudio.recorder._resolve_input_device",
        return_value=(3, "BlackHole 2ch"),
    ) as mock_resolve:
        assert resolve_auto_input_device_name() == "BlackHole 2ch"
    mock_resolve.assert_called_once_with(None)


def test_resolve_auto_input_device_name_returns_none_when_no_device():
    with patch(
        "summarizeaudio.recorder._resolve_input_device",
        return_value=(None, None),
    ):
        assert resolve_auto_input_device_name() is None


def test_resolve_auto_input_device_name_returns_none_on_exception():
    with patch(
        "summarizeaudio.recorder._resolve_input_device",
        side_effect=RuntimeError("portaudio blew up"),
    ):
        assert resolve_auto_input_device_name() is None
