from unittest.mock import patch, MagicMock
from summarizeaudio.notifier import notify


def test_notify_does_not_raise():
    """Smoke test — notifier must never crash the app regardless of platform."""
    with patch("summarizeaudio.notifier._notify_plyer"):
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            notify("Test notification")  # must not raise


def test_macos_path_falls_back_to_plyer_when_osascript_fails():
    """Force macOS code path regardless of actual platform to test fallback."""
    with patch("summarizeaudio.notifier.sys") as mock_sys:
        mock_sys.platform = "darwin"
        with patch("subprocess.run", side_effect=FileNotFoundError("osascript not found")):
            with patch("summarizeaudio.notifier._notify_plyer") as mock_plyer:
                notify("Fallback test")
                mock_plyer.assert_called_once()
