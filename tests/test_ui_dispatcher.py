# tests/test_ui_dispatcher.py
import queue
import threading
from unittest.mock import MagicMock, patch

from summarizeaudio.ui_dispatcher import UIDispatcher
from summarizeaudio.error_handler import post_error


def test_drain_calls_handler_for_queued_item():
    q = queue.Queue()
    handler = MagicMock()
    dispatcher = UIDispatcher(q)
    dispatcher.register("my_action", handler)
    q.put(("my_action", "arg1", "arg2"))
    dispatcher.drain()
    handler.assert_called_once_with("arg1", "arg2")


def test_drain_processes_all_items():
    q = queue.Queue()
    results = []
    dispatcher = UIDispatcher(q)
    dispatcher.register("push", lambda x: results.append(x))
    for i in range(3):
        q.put(("push", i))
    dispatcher.drain()
    assert results == [0, 1, 2]


def test_drain_ignores_unknown_action():
    q = queue.Queue()
    dispatcher = UIDispatcher(q)
    q.put(("unknown_action", "data"))
    dispatcher.drain()  # must not raise


def test_post_error_puts_error_tuple_on_queue():
    q = queue.Queue()
    post_error(q, "my_component.py", "something broke", "tb line 1\ntb line 2")
    item = q.get_nowait()
    assert item[0] == "error"
    assert item[1] == "my_component.py"
    assert "something broke" in item[2]


def test_post_error_includes_traceback_field():
    q = queue.Queue()
    post_error(q, "comp.py", "bad thing", "line 1\nline 2")
    item = q.get_nowait()
    assert len(item) == 4
    assert "line 1" in item[3]


def test_post_error_noop_when_queue_is_none():
    post_error(None, "x", "y", "z")  # must not raise


def test_drain_handler_exception_does_not_crash_drain_loop():
    q = queue.Queue()
    dispatcher = UIDispatcher(q)
    dispatcher.register("boom", lambda: (_ for _ in ()).throw(RuntimeError("handler crash")))
    q.put(("boom",))
    dispatcher.drain()  # must not raise — exception must be swallowed/logged
