from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen

log = logging.getLogger(__name__)


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
