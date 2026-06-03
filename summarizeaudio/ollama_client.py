from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen

import requests

log = logging.getLogger(__name__)

# A tiny known statement the model is asked to echo back. A non-empty reply
# confirms the model is loaded into memory and responding before the real
# (much larger) summarization request is sent.
PREWARM_STATEMENT = "Prewarm check: SummarizeAudio is ready."


@dataclass(frozen=True)
class ModelInfo:
    name: str
    family: str | None


def list_installed_models(host: str, timeout: float = 2.0) -> list[ModelInfo] | None:
    """Return installed Ollama models, or None if Ollama is unreachable.

    Hits GET <host>/api/tags. Returns [] when Ollama is up but no models are
    installed. Returns None on connection refused / timeout / malformed JSON.
    """
    url = host.rstrip("/") + "/api/tags"
    try:
        with urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (URLError, ConnectionRefusedError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        log.debug("ollama list failed: %s", exc)
        return None

    raw_models = data.get("models", []) if isinstance(data, dict) else []
    if not isinstance(raw_models, list):
        return None

    out: list[ModelInfo] = []
    for entry in raw_models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        details = entry.get("details") or {}
        family = details.get("family") if isinstance(details, dict) else None
        if family is not None and not isinstance(family, str):
            family = None
        out.append(ModelInfo(name=name, family=family))
    return out


def prewarm(host: str, model: str, timeout: float = 60.0) -> bool:
    """Load `model` into Ollama's memory ahead of the real summarization request.

    The model is asked to echo a tiny known statement verbatim; a non-empty
    response confirms it is loaded and responding. Returns True on a confirmed
    reply, False on any error or timeout. Never raises — prewarming is
    best-effort and must not break the surrounding workflow.
    """
    prompt = (
        "Output the following text verbatim, with no commentary or quotes:\n"
        f"{PREWARM_STATEMENT}"
    )
    try:
        response = requests.post(
            host.rstrip("/") + "/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        log.debug("ollama prewarm failed (model=%s): %s", model, exc)
        return False

    reply = (data.get("response") if isinstance(data, dict) else "") or ""
    ok = bool(reply.strip())
    log.info("ollama prewarm %s (model=%s)", "ok" if ok else "empty", model)
    return ok


def prewarm_async(host: str, model: str) -> threading.Thread:
    """Fire-and-forget prewarm on a daemon thread so model loading overlaps with
    recording/transcription rather than delaying the real request."""
    thread = threading.Thread(
        target=prewarm, args=(host, model), name="ollama-prewarm", daemon=True
    )
    thread.start()
    return thread
