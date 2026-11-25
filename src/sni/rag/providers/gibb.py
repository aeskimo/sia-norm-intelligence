"""OpenAI-kompatibles Antwortmodell, z. B. gibb (REQ-805).

1:1-Port von ``ch.sia.assistant.ai.OpenAiCompatibleProvider``
(Java-Referenz; Basis-URL ``https://chat.gibb.ch/api``):

- Nur HTTPS; HTTP ist ausschliesslich gegen Loopback erlaubt, damit
  der API-Schlüssel nie unverschlüsselt übertragen wird (Tests).
- Authentifizierung: ``Authorization: Bearer <API-Schlüssel>``.
- ``available``: ``GET {base}models`` (5 s) → 200; ``list_models``
  parst die Modell-IDs per Hand (Java-Scanner 1:1).
- ``generate``: ``POST {base}chat/completions`` (10 min) →
  ``content``-Feld, sonst ``Modellantwort enthielt keinen Inhalt``.
- ``generate_streaming``: Server-Sent-Events (``data:``-Zeilen,
  Endmarke ``[DONE]``) mit ``choices[0].delta.content`` pro Ereignis.

Suche und Vektoren bleiben ausschliesslich lokal; nur der
Antwort-Prompt mit den zitierten Quellen geht an die Plattform.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from sni.rag.model_provider import ModelProvider
from sni.rag.providers.ollama import esc, string_field

#: Zeitlimits in Sekunden (Java: connect 5 s; available 5 s; models 10 s; Generierung 10 min).
CONNECT_TIMEOUT = 5.0
AVAILABLE_TIMEOUT = 5.0
LIST_MODELS_TIMEOUT = 10.0
GENERATE_TIMEOUT = 600.0


class OpenAiCompatibleProvider(ModelProvider):
    """OpenAI-kompatibler Chat-Endpunkt (Java 1:1; HTTPS-only)."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        parsed = urlparse(base_url)
        scheme = (parsed.scheme or "").lower()
        host = parsed.hostname or ""
        loopback = host == "127.0.0.1" or host.lower() == "localhost" or host == "::1"
        if not (scheme == "https" or (loopback and scheme == "http")):
            raise PermissionError("Nur HTTPS-Endpunkte erlaubt (http ausschliesslich Loopback)")
        if not api_key.strip():
            raise ValueError("API-Schlüssel fehlt")
        if not model.strip():
            raise ValueError("Modell fehlt")
        # Abschliessender Schrägstrich, damit relative Pfade (models,
        # chat/completions) an der Basis-URL bleiben (Java: URI.resolve).
        self._base = base_url if base_url.endswith("/") else base_url + "/"
        self._api_key = api_key
        self._model = model

    def id(self) -> str:
        return (urlparse(self._base).hostname or "") + ":" + self._model

    def available(self) -> bool:
        """Healthcheck: Modellliste abrufen (HTTP 200)."""
        try:
            with httpx.Client(
                timeout=httpx.Timeout(AVAILABLE_TIMEOUT, connect=CONNECT_TIMEOUT)
            ) as client:
                response = client.get(
                    self._base + "models",
                    headers={"Authorization": "Bearer " + self._api_key},
                )
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Liefert die verfügbaren Modell-IDs (GET /models)."""
        with httpx.Client(
            timeout=httpx.Timeout(LIST_MODELS_TIMEOUT, connect=CONNECT_TIMEOUT)
        ) as client:
            response = client.get(
                self._base + "models",
                headers={"Authorization": "Bearer " + self._api_key},
            )
        if response.status_code != 200:
            raise RuntimeError(f"Modellliste nicht verfügbar (HTTP {response.status_code})")
        body = response.text
        ids: list[str] = []
        data = body.find('"data"')
        i = 0 if data < 0 else body.find("[", data)
        if i < 0:
            return ids
        while True:
            k = body.find('"id"', i)
            if k < 0:
                break
            c = body.find(":", k + 4)
            if c < 0:
                break
            s = c + 1
            while s < len(body) and body[s].isspace():
                s += 1
            if s >= len(body) or body[s] != '"':
                continue
            e = s + 1
            while e < len(body) and body[e] != '"':
                e += 1
            if e >= len(body):
                break
            ids.append(body[s + 1 : e])
            i = e
        return ids

    def generate(self, system: str, prompt: str) -> str | None:
        body = _messages_body(self._model, system, prompt, stream=False)
        with httpx.Client(
            timeout=httpx.Timeout(GENERATE_TIMEOUT, connect=CONNECT_TIMEOUT)
        ) as client:
            response = client.post(
                self._base + "chat/completions",
                content=body.encode("utf-8"),
                headers={
                    "Authorization": "Bearer " + self._api_key,
                    "Content-Type": "application/json",
                },
            )
        if response.status_code != 200:
            raise RuntimeError(f"Modellanfrage fehlgeschlagen (HTTP {response.status_code})")
        content = string_field(response.text, "content")
        if content is None:
            raise RuntimeError("Modellantwort enthielt keinen Inhalt")
        return content

    def generate_streaming(
        self, system: str, prompt: str, on_token: Callable[[str], None]
    ) -> str | None:
        """Tokenweiser SSE-Stream (Java 1:1); Rückgabe = vollständiges Ergebnis."""
        body = _messages_body(self._model, system, prompt, stream=True)
        parts: list[str] = []
        with (
            httpx.Client(
                timeout=httpx.Timeout(GENERATE_TIMEOUT, connect=CONNECT_TIMEOUT)
            ) as client,
            client.stream(
                "POST",
                self._base + "chat/completions",
                content=body.encode("utf-8"),
                headers={
                    "Authorization": "Bearer " + self._api_key,
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
            ) as response,
        ):
            if response.status_code != 200:
                raise RuntimeError(f"Modell-Streaming fehlgeschlagen (HTTP {response.status_code})")
            for line in response.iter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                piece = string_field(data, "content")
                if piece:
                    parts.append(piece)
                    on_token(piece)
        return "".join(parts)


def _messages_body(model: str, system: str, prompt: str, *, stream: bool) -> str:
    """Java ``messagesBody`` 1:1: ``{"model","stream","messages":[system,user]}``."""
    return (
        '{"model":"'
        + esc(model)
        + '","stream":'
        + ("true" if stream else "false")
        + ',"messages":[{"role":"system","content":"'
        + esc(system)
        + '"}'
        + ',{"role":"user","content":"'
        + esc(prompt)
        + '"}]}'
    )
