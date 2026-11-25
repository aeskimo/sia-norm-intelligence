"""Lokales Ollama-Antwortmodell (REQ-805).

1:1-Port von ``ch.sia.assistant.ai.OllamaProvider`` (Java-Referenz):

- Verbindungen ausserhalb Loopback werden abgewiesen
  (``Nur lokale Modellserver erlaubt``).
- ``generate``: ``POST /api/generate`` mit ``stream:false``, 10-min-
  Timeout; der Antwortinhalt kommt aus dem Feld ``response``.
- ``generate_streaming``: ``stream:true`` → NDJSON (JSON-Objekt pro
  Zeile mit den Feldern ``response`` und ``done``); jede Zeile mit
  ``response``-Feld ist ein Token.
- Der JSON-Body wird wie in Java per Hand escaped (keine
  Abhängigkeit vom Antwortformat); :func:`string_field` liest das
  Antwortfeld mit vollem Escape-Handling (auch in ``gibb.py``
  verwendet, Java: ``OllamaProvider.stringField``). Die Helper
  wohnen in :mod:`sni.models.ollama_manager` (Java: ``OllamaJson`` im
  selben Paket) und werden hier für die bestehenden Imports
  weitergeleitet.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx

from sni.models.ollama_manager import esc as esc  # noqa: PLC0414 — expliziter Re-Export
from sni.models.ollama_manager import string_field as string_field  # noqa: PLC0414
from sni.rag.model_provider import ModelProvider

#: Zeitlimits in Sekunden (Java: connect 3 s; /api/tags 3 s; Generierung 10 min).
CONNECT_TIMEOUT = 3.0
TAGS_TIMEOUT = 3.0
GENERATE_TIMEOUT = 600.0


class OllamaChatProvider(ModelProvider):
    """Lokales Ollama-Antwortmodell (Java 1:1; externe Hosts gesperrt)."""

    def __init__(self, base_url: str, model: str) -> None:
        host = urlparse(base_url).hostname or ""
        if not (host == "127.0.0.1" or host.lower() == "localhost" or host == "::1"):
            raise PermissionError("Nur lokale Modellserver erlaubt")
        self._base = base_url
        self._model = model

    def id(self) -> str:
        return "ollama:" + self._model

    def available(self) -> bool:
        try:
            with httpx.Client(
                timeout=httpx.Timeout(TAGS_TIMEOUT, connect=CONNECT_TIMEOUT)
            ) as client:
                response = client.get(urljoin(self._base, "/api/tags"))
            return response.status_code == 200
        except Exception:
            return False

    def generate(self, system: str, prompt: str) -> str | None:
        body = _generate_body(self._model, system, prompt, stream=False)
        with httpx.Client(
            timeout=httpx.Timeout(GENERATE_TIMEOUT, connect=CONNECT_TIMEOUT)
        ) as client:
            response = client.post(
                urljoin(self._base, "/api/generate"),
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        return string_field(response.text, "response")

    def generate_streaming(
        self, system: str, prompt: str, on_token: Callable[[str], None]
    ) -> str | None:
        """Tokenweiser NDJSON-Stream (Java 1:1); Rückgabe = vollständiges Ergebnis."""
        body = _generate_body(self._model, system, prompt, stream=True)
        parts: list[str] = []
        with (
            httpx.Client(
                timeout=httpx.Timeout(GENERATE_TIMEOUT, connect=CONNECT_TIMEOUT)
            ) as client,
            client.stream(
                "POST",
                urljoin(self._base, "/api/generate"),
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
            ) as response,
        ):
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            for line in response.iter_lines():
                line = line.strip()
                if not line:
                    continue
                piece = string_field(line, "response")
                if piece is not None:
                    parts.append(piece)
                    on_token(piece)
        return "".join(parts)


def _generate_body(model: str, system: str, prompt: str, *, stream: bool) -> str:
    """Java-Body 1:1: ``{"model","stream","system","prompt"}``."""
    return (
        '{"model":"'
        + esc(model)
        + '","stream":'
        + ("true" if stream else "false")
        + ',"system":"'
        + esc(system)
        + '","prompt":"'
        + esc(prompt)
        + '"}'
    )
