from io import StringIO
from unittest.mock import patch, MagicMock
from summarizeaudio.notifier import notify


def test_notify_does_not_raise():
    """Smoke test — notifier must never crash the app regardless of platform."""
    with patch("summarizeaudio.notifier._notify_plyer"):
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.stdin = StringIO()
            mock_popen.return_value = mock_proc
            notify("Test notification")  # must not raise


def test_macos_path_launches_alert_window():
    """Force macOS code path regardless of actual platform to test popup helper."""
    with patch("summarizeaudio.notifier.sys.platform", "darwin"), patch("summarizeaudio.notifier.sys.executable", "/usr/bin/python3"):
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.stdin = StringIO()
            mock_popen.return_value = mock_proc
            notify("Fallback test", "Custom Title")
            assert mock_popen.called
            args, kwargs = mock_popen.call_args
            assert args[0][:3] == ["/usr/bin/python3", "-m", "summarizeaudio.alert_window"]
