from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from unittest.mock import MagicMock

from summarizeaudio.ollama_client import ModelInfo, list_installed_models, prewarm, prewarm_async


def _fake_response(payload: dict):
    body = json.dumps(payload).encode("utf-8")
    class _Resp:
        def __enter__(self_inner):
            return self_inner
        def __exit__(self_inner, *_a):
            return False
        def read(self_inner):
            return body
    return _Resp()


def test_list_installed_models_parses_name_and_family():
    payload = {
        "models": [
            {"name": "gemma3:4b", "details": {"family": "gemma3"}},
            {"name": "nomic-embed-text:latest", "details": {"family": "bert"}},
        ]
    }
    with patch("summarizeaudio.ollama_client.urlopen", return_value=_fake_response(payload)):
        models = list_installed_models("http://localhost:11434")

    assert models == [
        ModelInfo(name="gemma3:4b", family="gemma3"),
        ModelInfo(name="nomic-embed-text:latest", family="bert"),
    ]


def test_list_installed_models_returns_none_on_connection_refused():
    with patch("summarizeaudio.ollama_client.urlopen", side_effect=ConnectionRefusedError()):
        assert list_installed_models("http://localhost:11434") is None


def test_list_installed_models_returns_empty_list_when_no_models():
    payload = {"models": []}
    with patch("summarizeaudio.ollama_client.urlopen", return_value=_fake_response(payload)):
        assert list_installed_models("http://localhost:11434") == []


def test_list_installed_models_returns_none_on_malformed_json():
    class _BadResp:
        def __enter__(self):
            return self
        def __exit__(self, *_a):
            return False
        def read(self):
            return b"not-json{{{"
    with patch("summarizeaudio.ollama_client.urlopen", return_value=_BadResp()):
        assert list_installed_models("http://localhost:11434") is None


def test_list_installed_models_handles_missing_details():
    payload = {"models": [{"name": "llama3:8b"}]}
    with patch("summarizeaudio.ollama_client.urlopen", return_value=_fake_response(payload)):
        assert list_installed_models("http://localhost:11434") == [
            ModelInfo(name="llama3:8b", family=None)
        ]


def _post_returning(payload: dict, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return MagicMock(return_value=resp)


def test_prewarm_returns_true_on_nonempty_response():
    post = _post_returning({"response": "Prewarm check: SummarizeAudio is ready."})
    with patch("summarizeaudio.ollama_client.requests.post", post):
        assert prewarm("http://localhost:11434", "gemma3:4b") is True


def test_prewarm_posts_tiny_nonstreaming_generate_request():
    post = _post_returning({"response": "ok"})
    with patch("summarizeaudio.ollama_client.requests.post", post):
        prewarm("http://localhost:11434", "gemma3:4b")
    args, kwargs = post.call_args
    assert args[0] == "http://localhost:11434/api/generate"
    assert kwargs["json"]["model"] == "gemma3:4b"
    assert kwargs["json"]["stream"] is False
    assert kwargs["json"]["prompt"]  # non-empty prompt


def test_prewarm_returns_false_on_empty_response():
    post = _post_returning({"response": "   "})
    with patch("summarizeaudio.ollama_client.requests.post", post):
        assert prewarm("http://localhost:11434", "gemma3:4b") is False


def test_prewarm_returns_false_and_swallows_errors():
    with patch("summarizeaudio.ollama_client.requests.post", side_effect=RuntimeError("boom")):
        assert prewarm("http://localhost:11434", "gemma3:4b") is False


def test_prewarm_async_runs_prewarm_on_background_thread():
    calls = []
    with patch("summarizeaudio.ollama_client.prewarm", lambda h, m: calls.append((h, m))):
        thread = prewarm_async("http://localhost:11434", "gemma3:4b")
        thread.join(timeout=2)
    assert thread.daemon is True
    assert calls == [("http://localhost:11434", "gemma3:4b")]
