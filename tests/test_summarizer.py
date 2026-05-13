# tests/test_summarizer.py
# fmt: off
# Regression fixture: realistic 22-sentence product meeting transcript.
# Key facts are asserted in test_summarizer_prompt_contains_full_transcript_content
# to catch prompt-template regressions that drop or truncate the transcript.
_REGRESSION_TRANSCRIPT = (
    "The team met to review the Q3 mobile checkout rollout. "
    "Sarah reported that checkout drop-off increased 18% after the last release. "
    "The billing screen redesign was identified as the primary cause. "
    "Marcus confirmed the new payment form has an extra confirmation step users find confusing. "
    "The UX team agreed to remove the redundant confirmation modal. "
    "Alice will update the billing screen wireframes by Friday. "
    "The iOS build is blocked on the App Store review, now in its third day. "
    "DevOps will escalate the review status with Apple support tomorrow. "
    "Backend latency on the payment endpoint spiked to 1.4 seconds during peak load. "
    "The SLA threshold is 800ms, so this is a critical issue. "
    "The backend team will profile the payment service and open a P1 ticket by end of day. "
    "Android shipped cleanly and has a 4.7-star rating on the Play Store this week. "
    "Marketing asked whether the iOS delay will affect the Q3 campaign launch date. "
    "The campaign is scheduled for September 15th, giving the team two weeks of buffer. "
    "Product confirmed the campaign can proceed if the App Store review clears by September 10th. "
    "Legal reviewed the updated terms and conditions and gave final sign-off. "
    "The data retention policy change goes live with the next release. "
    "Customer support flagged three recurring complaints about the order confirmation email format. "
    "Priya will audit the email templates and propose fixes before the next sprint. "
    "The team agreed to add an end-to-end checkout smoke test to the CI pipeline. "
    "James will own the smoke test implementation with a target of two weeks. "
    "The next review meeting is scheduled for September 8th at 10am."
)
# fmt: on
import json
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
        json.dumps({"response": text, "done": False}).encode(),
        b'{"response": "", "done": true}',
    ]
    return mock


def structured_summary(body: str = "- Great summary.") -> str:
    return (
        "**Key Points:**\n"
        f"{body}\n\n"
        "**Decisions / Action Items:**\n"
        "- None.\n\n"
        "**Notable Details:**\n"
        "- None.\n"
    )


def test_summarizer_calls_ollama_and_saves_md(tmp_path, ui_queue):
    s = make_summarizer(tmp_path, ui_queue)
    out_md = tmp_path / "summary.md"
    with patch("requests.post") as mock_post:
        mock_post.return_value = mock_ollama_response(structured_summary())
        s.summarize("my transcript text", out_md)
    assert out_md.exists()
    written = out_md.read_text()
    assert "**Key Points:**" in written
    assert "**Decisions / Action Items:**" in written
    assert "**Notable Details:**" in written


def test_summarizer_substitutes_transcript_into_prompt(tmp_path, ui_queue):
    s = make_summarizer(tmp_path, ui_queue)
    out_md = tmp_path / "summary.md"
    captured = {}
    def fake_post(url, json=None, stream=False, timeout=None):
        captured["prompt"] = json.get("prompt", "")
        return mock_ollama_response(structured_summary(" - one bullet."))
    with patch("requests.post", side_effect=fake_post):
        s.summarize("HELLO WORLD", out_md)
    assert "HELLO WORLD" in captured["prompt"]


def test_summarizer_chunks_long_transcript_and_combines_summaries(tmp_path, ui_queue):
    s = make_summarizer(tmp_path, ui_queue)
    out_md = tmp_path / "summary.md"
    prompts = []
    responses = iter(
        [
            mock_ollama_response(structured_summary("- Chunk summary one.")),
            mock_ollama_response(structured_summary("- Chunk summary two.")),
            mock_ollama_response(structured_summary("- Chunk summary three.")),
            mock_ollama_response(structured_summary("- Final combined summary.")),
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
    assert "Final combined summary." in out_md.read_text()
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


def test_summarizer_writes_malformed_summary_without_error(tmp_path, ui_queue):
    s = make_summarizer(tmp_path, ui_queue)
    out_md = tmp_path / "summary.md"
    with patch("requests.post") as mock_post:
        mock_post.return_value = mock_ollama_response("This is just a paragraph with no sections.")
        s.summarize("text", out_md)
    assert out_md.exists()
    assert out_md.read_text() == "This is just a paragraph with no sections."


def test_summarizer_prompt_contains_full_transcript_content(tmp_path, ui_queue):
    """Regression: prompt template must include the full transcript verbatim.

    If the template is changed in a way that drops, truncates, or garbles the
    transcript, at least one of these key-fact assertions will fail.
    """
    s = make_summarizer(tmp_path, ui_queue)
    out_md = tmp_path / "summary.md"
    captured_prompt = {}

    def fake_post(url, json=None, stream=False, timeout=None):
        captured_prompt["text"] = json.get("prompt", "")
        return mock_ollama_response(structured_summary("- Summary of meeting."))

    with patch("requests.post", side_effect=fake_post):
        s.summarize(_REGRESSION_TRANSCRIPT, out_md)

    prompt = captured_prompt["text"]

    # Core facts that must survive any prompt-template edit
    assert "18%" in prompt, "drop-off stat missing from prompt"
    assert "billing screen" in prompt, "root cause missing from prompt"
    assert "800ms" in prompt, "SLA threshold missing from prompt"
    assert "September 15th" in prompt, "campaign date missing from prompt"
    assert "Alice" in prompt, "assignee missing from prompt"
    assert "James" in prompt, "assignee missing from prompt"
    assert "smoke test" in prompt, "action item missing from prompt"
    assert "data retention" in prompt, "policy detail missing from prompt"


def test_summarizer_writes_raw_output_without_normalization(tmp_path, ui_queue):
    s = make_summarizer(tmp_path, ui_queue)
    out_md = tmp_path / "summary.md"
    raw = (
        "### Key Points:\n"
        "- One.\n"
        "\n\n"
        "## Decisions / Action Items\n"
        "- Two.\n"
        "\n"
        "**Notable Details:**\n"
        "- Three.\n"
    )
    with patch("requests.post") as mock_post:
        mock_post.return_value = mock_ollama_response(raw)
        s.summarize("text", out_md)
    written = out_md.read_text()
    assert "Key Points" in written
    assert "Decisions / Action Items" in written
    assert "Notable Details" in written
