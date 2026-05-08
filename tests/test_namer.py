# tests/test_namer.py
import queue
import threading
from datetime import date
from unittest.mock import patch

from summarizeaudio.namer import Namer, default_name


def test_default_name_for_recording():
    today = date.today().strftime("%m-%d-%y")
    assert default_name("recording") == f"Recording_{today}"


def test_default_name_for_file_stem():
    today = date.today().strftime("%m-%d-%y")
    assert default_name("meeting") == f"meeting_{today}"


def test_namer_resolves_with_user_input(ui_queue):
    namer = Namer(ui_queue, default="Recording_01-01-26")
    # Simulate user entering a name via the event
    def simulate_user():
        import time; time.sleep(0.05)
        namer._resolve("GTC Keynote")
    threading.Thread(target=simulate_user, daemon=True).start()
    result = namer.wait(timeout=2)
    assert result == "GTC Keynote"


def test_namer_falls_back_to_default_on_timeout(ui_queue):
    namer = Namer(ui_queue, default="Recording_01-01-26")
    result = namer.wait(timeout=0.05)
    assert result == "Recording_01-01-26"


def test_namer_returns_none_on_cancel(ui_queue):
    namer = Namer(ui_queue, default="Recording_01-01-26")
    namer._resolve(None)
    assert namer.wait(timeout=0.05) is None


def test_namer_posts_dialog_request_to_queue(ui_queue):
    namer = Namer(ui_queue, default="Recording_01-01-26")
    assert not ui_queue.empty()
    item = ui_queue.get_nowait()
    assert item[0] == "name_dialog"
    assert item[1] is namer  # dispatcher can call namer._resolve(name)
