from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from summarizeaudio.ollama_client import ModelInfo, list_installed_models


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
