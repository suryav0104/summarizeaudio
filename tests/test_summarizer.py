# tests/test_summarizer.py
import queue
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from summarizeaudio.summarizer import Summarizer, OllamaError
from summarizeaudio.config import OllamaConfig, SummarizationConfig, BehaviorConfig


def make_summarizer(tmp_path, ui_queue, show_override=False):
    ollama = OllamaConfig(host="http://localhost:11434", model="test-model")
    summ_cfg = SummarizationConfig(default_prompt="Summarize: {transcript}")
    beh = BehaviorConfig(show_override_dialog=show_override, auto_open_summary=False)
    return Summarizer(ollama=ollama, summ_cfg=summ_cfg, beh=beh, ui_queue=ui_queue)


def mock_ollama_response(text: str):
    mock = MagicMock()
    mock.status_code = 200
    mock.iter_lines.return_value = [
        f'{{"response": "{text}", "done": false}}'.encode(),
        b'{"response": "", "done": true}',
    ]
    return mock


def test_summarizer_calls_ollama_and_saves_md(tmp_path, ui_queue):
    s = make_summarizer(tmp_path, ui_queue)
    out_md = tmp_path / "summary.md"
    with patch("requests.post") as mock_post:
        mock_post.return_value = mock_ollama_response("Great summary.")
        s.summarize("my transcript text", out_md)
    assert out_md.exists()
    assert "Great summary." in out_md.read_text()


def test_summarizer_substitutes_transcript_into_prompt(tmp_path, ui_queue):
    s = make_summarizer(tmp_path, ui_queue)
    out_md = tmp_path / "summary.md"
    captured = {}
    def fake_post(url, json=None, stream=False, timeout=None):
        captured["prompt"] = json.get("prompt", "")
        return mock_ollama_response("ok")
    with patch("requests.post", side_effect=fake_post):
        s.summarize("HELLO WORLD", out_md)
    assert "HELLO WORLD" in captured["prompt"]


def test_summarizer_chunks_long_transcript_and_combines_summaries(tmp_path, ui_queue):
    s = make_summarizer(tmp_path, ui_queue)
    out_md = tmp_path / "summary.md"
    prompts = []
    responses = iter(
        [
            mock_ollama_response("Chunk summary one."),
            mock_ollama_response("Chunk summary two."),
            mock_ollama_response("Chunk summary three."),
            mock_ollama_response("Final combined summary."),
        ]
    )

    long_transcript = ("Mobile checkout drop-off is the main issue. Billing screen is confusing. " * 160).strip()
    assert len(long_transcript) > 8000

    def fake_post(url, json=None, stream=False, timeout=None):
        prompts.append(json.get("prompt", ""))
        return next(responses)

    with patch("requests.post", side_effect=fake_post):
        s.summarize(long_transcript, out_md)

    assert out_md.exists()
    assert out_md.read_text() == "Final combined summary."
    assert len(prompts) == 4
    assert "Chunk summary one." in prompts[-1]
    assert "Chunk summary two." in prompts[-1]
    assert "Chunk summary three." in prompts[-1]
    assert "Combine them into one final summary" in prompts[-1]


def test_summarizer_skips_on_override_dismissed(tmp_path, ui_queue):
    # The override event is posted INSIDE summarize(), so we must call
    # summarize() on a background thread and resolve the event from the test thread.
    import threading, time
    s = make_summarizer(tmp_path, ui_queue, show_override=True)
    out_md = tmp_path / "summary.md"

    def dismiss_from_main():
        item = ui_queue.get(timeout=2)  # wait for summarize() to post the event
        assert item[0] == "override_dialog"
        item[1]._resolve(None)  # user dismissed

    dismisser = threading.Thread(target=dismiss_from_main)
    dismisser.start()
    with patch("requests.post") as mock_post:
        s.summarize("text", out_md)  # blocks until dismiss_from_main resolves or times out
    dismisser.join(timeout=3)
    mock_post.assert_not_called()
    assert not out_md.exists()


def test_summarizer_ollama_connection_error_raises_ollama_error(tmp_path, ui_queue):
    s = make_summarizer(tmp_path, ui_queue)
    out_md = tmp_path / "summary.md"
    import requests
    with patch("requests.post", side_effect=requests.ConnectionError("refused")):
        with pytest.raises(OllamaError):
            s.summarize("text", out_md)
    assert not out_md.exists()
