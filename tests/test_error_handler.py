from summarizeaudio.error_handler import format_error, friendly_message


def test_friendly_message_maps_cloud_sync_timeout():
    msg = friendly_message(
        "transcriber.py → faster_whisper",
        "[Errno 60] Operation timed out: '/Users/surya/OneDrive/file.mp3'",
        "av.error.TimeoutError: [Errno 60] Operation timed out",
    )
    assert "cloud-synced location" in msg


def test_format_error_hides_traceback_and_uses_log_hint():
    rendered = format_error(
        "transcriber.py → faster_whisper",
        "[Errno 60] Operation timed out",
        "traceback line 1\ntraceback line 2",
    )
    assert "traceback line 1" not in rendered
    assert "traceback line 2" not in rendered
    assert "Technical details were saved" in rendered


def test_format_error_preserves_already_friendly_cloud_sync_message():
    rendered = format_error(
        "pipeline.py",
        "SummarizeAudio could not read that audio file because it appears to be in a "
        "cloud-synced location or otherwise unavailable locally.",
        "",
    )
    assert "cloud-synced location" in rendered
    assert "Something went wrong" not in rendered


def test_format_error_preserves_no_usable_audio_message():
    rendered = format_error(
        "pipeline.py",
        "The recording captured no usable audio. Check your input device in System Settings "
        "→ Sound → Input.",
        "",
    )
    assert "captured no usable audio" in rendered
    assert "Something went wrong" not in rendered


def test_format_error_preserves_configured_recording_device_message():
    rendered = format_error(
        "tray.py → recorder",
        "Configured recording device 'Multi-input device' was not found.",
        "traceback line",
    )
    assert "Configured recording device 'Multi-input device' was not found." in rendered
    assert "Something went wrong" not in rendered
    assert "traceback line" not in rendered
