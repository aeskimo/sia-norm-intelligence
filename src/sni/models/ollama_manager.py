"""Ollama-Modellverwaltung (REQ-806).

1:1-Port von ``ch.sia.reader.product.ai.OllamaModelManager`` +
``OllamaJson`` + ``LocalModelInfo`` (Java-Referenz):

- Externe Hosts werden im Konstruktor abgewiesen (nur
  ``127.0.0.1``/``localhost``/``::1``, ``Nur lokale Modellendpunkte erlaubt``).
- ``available``: Healthcheck ``GET /api/tags`` (3 s) → HTTP 200.
- ``list_installed``: ``GET /api/tags`` (10 s) → Modell-Metadaten.
- ``pull``: ``POST /api/pull`` mit 2-h-Timeout (wie Java); NDJSON-
  Statuszeilen werden an ``progress`` weitergereicht.
- ``delete``: ``DELETE /api/delete`` (30 s) mit JSON-Body.
- Modellnamen: ``[A-Za-z0-9._:/-]{1,200}`` (Vollmatch wie Java).

``esc``/``string_field`` sind die Java-JSON-Helper (1:1); der
RAG-Provider (:mod:`sni.rag.providers.ollama`) importiert sie von hier
(Java: ``OllamaProvider`` nutzt ``OllamaJson`` im selben Paket).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

#: Zeitlimits in Sekunden (Java 1:1: connect 3 s; Availability 3 s;
#: /api/tags 10 s; Delete 30 s; Pull 2 h).
CONNECT_TIMEOUT = 3.0
AVAILABLE_TIMEOUT = 3.0
TAGS_TIMEOUT = 10.0
DELETE_TIMEOUT = 30.0
PULL_TIMEOUT = 2 * 60 * 60.0

_MODEL_RE = re.compile(r"[A-Za-z0-9._:/-]{1,200}")


@dataclass(frozen=True, slots=True)
class LocalModelInfo:
    """Metadaten eines lokal installierten Modells (Java: ``LocalModelInfo``)."""

    name: str
    size_bytes: int
    modified_at: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Modellname fehlt")


#: C0-Steuerzeichen, die ``esc`` zusätzlich zum Java-Satz escapen muss.
_C0_RE = re.compile(r"[\x00-\x1f]")


def esc(value: str) -> str:
    """JSON-String-Escapes (Java: ``OllamaProvider.esc``, 1:1).

    Zusätzlich zum Java-Satz (Backslash, Quote, LF, CR, TAB) werden alle
    übrigen C0-Steuerzeichen als ``\\uXXXX`` escaped: RFC 8259 verbietet
    rohe C0-Zeichen in JSON-Strings. Die Java-Lücke hat beim gibb-Endpunkt
    HTTP 422 ausgelöst (Dry-Run M13.1: PDF-Text mit Font-Artefakt
    enthielt U+0003).
    """
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return _C0_RE.sub(lambda m: f"\\u{ord(m.group()):04x}", escaped)


def string_field(json: str, field: str) -> str | None:
    """Liest ein JSON-String-Feld und dekodiert alle Escape-Sequenzen.

    Java: ``OllamaProvider.stringField`` (1:1); ``None``, wenn das Feld
    fehlt oder kein String ist. Unvollständige Sequenzen werfen
    ``ValueError`` (Java: ``IllegalArgumentException``).
    """
    k = json.find(f'"{field}"')
    if k < 0:
        return None
    c = json.find(":", k + len(field) + 2)
    if c < 0:
        return None
    i = c + 1
    while i < len(json) and json[i].isspace():
        i += 1
    if i >= len(json) or json[i] != '"':
        return None
    out: list[str] = []
    i += 1
    while i < len(json):
        x = json[i]
        i += 1
        if x == '"':
            return "".join(out)
        if x != "\\":
            out.append(x)
            continue
        if i >= len(json):
            raise ValueError("JSON-String unvollständig")
        e = json[i]
        i += 1
        if e == "u":
            if i + 4 > len(json):
                raise ValueError("JSON-String unvollständig")
            out.append(chr(int(json[i : i + 4], 16)))
            i += 4
        elif e == "n":
            out.append("\n")
        elif e == "r":
            out.append("\r")
        elif e == "t":
            out.append("\t")
        elif e == "b":
            out.append("\b")
        elif e == "f":
            out.append("\f")
        else:
            # Java default: '"' / "\\" / "/" / unbekannt → Zeichen wie-is.
            out.append(e)
    raise ValueError("JSON-String unvollständig")


def _long_field(json: str, field: str) -> int:
    """Liest ein JSON-Ganzzahlen-Feld (Java: ``OllamaJson.longField``, 1:1)."""
    k = json.find(f'"{field}"')
    if k < 0:
        return 0
    c = json.find(":", k + len(field) + 2)
    if c < 0:
        return 0
    i = c + 1
    while i < len(json) and json[i].isspace():
        i += 1
    j = i
    while j < len(json) and json[j].isdigit():
        j += 1
    if j > i:
        try:
            return int(json[i:j])
        except ValueError:
            return 0
    return 0


def _parse_models(json: str) -> list[LocalModelInfo]:
    """Liest die Modell-Objekte des ``models``-Arrays (Java: ``OllamaJson.models``, 1:1)."""
    out: list[LocalModelInfo] = []
    at = json.find('"models"')
    array = json.find("[", at) if at >= 0 else -1
    if array < 0:
        return out
    i = array + 1
    depth = 0
    start = -1
    quoted = False
    escaped = False
    while i < len(json):
        c = json[i]
        if quoted:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                quoted = False
            i += 1
            continue
        if c == '"':
            quoted = True
        elif c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                obj = json[start : i + 1]
                name = string_field(obj, "name")
                modified = string_field(obj, "modified_at")
                size = _long_field(obj, "size")
                if name is not None and name.strip():
                    out.append(LocalModelInfo(name, size, modified or ""))
                start = -1
        elif c == "]" and depth == 0:
            break
        i += 1
    return out


class OllamaModelManager:
    """Verwaltung lokal installierter Modelle. Kein externer Host ist zulässig."""

    def __init__(self, base_url: str) -> None:
        host = urlparse(base_url).hostname or ""
        if not (host == "127.0.0.1" or host.lower() == "localhost" or host == "::1"):
            raise PermissionError("Nur lokale Modellendpunkte erlaubt")
        self._base = base_url

    def available(self) -> bool:
        """Healthcheck: ``GET /api/tags`` (3 s) → HTTP 200."""
        try:
            with httpx.Client(
                timeout=httpx.Timeout(AVAILABLE_TIMEOUT, connect=CONNECT_TIMEOUT)
            ) as client:
                response = client.get(urljoin(self._base, "/api/tags"))
            return response.status_code == 200
        except Exception:
            return False

    def list_installed(self) -> list[LocalModelInfo]:
        """Installierte Modelle (``GET /api/tags``, 10 s; sonst ``RuntimeError``)."""
        with httpx.Client(timeout=httpx.Timeout(TAGS_TIMEOUT, connect=CONNECT_TIMEOUT)) as client:
            response = client.get(urljoin(self._base, "/api/tags"))
        if response.status_code != 200:
            raise RuntimeError(f"Modellliste: HTTP {response.status_code}")
        return _parse_models(response.text)

    def pull(self, model: str, progress: Callable[[str], None] | None = None) -> None:
        """Modell laden (2-h-Timeout wie Java); NDJSON-Status → ``progress``."""
        self._require_model(model)
        body = '{"name":"' + esc(model.strip()) + '","stream":true}'
        with (
            httpx.Client(timeout=httpx.Timeout(PULL_TIMEOUT, connect=CONNECT_TIMEOUT)) as client,
            client.stream(
                "POST",
                urljoin(self._base, "/api/pull"),
                content=body,
                headers={"Content-Type": "application/json"},
            ) as response,
        ):
            if response.status_code != 200:
                response.read()
                raise RuntimeError(f"Modell-Download: HTTP {response.status_code}")
            for line in response.iter_lines():
                if line:
                    status = string_field(line, "status")
                    if status is not None and progress is not None:
                        progress(status)

    def delete(self, model: str) -> None:
        """Modell löschen (``DELETE /api/delete``, 30 s, JSON-Body)."""
        self._require_model(model)
        body = '{"name":"' + esc(model.strip()) + '"}'
        with httpx.Client(timeout=httpx.Timeout(DELETE_TIMEOUT, connect=CONNECT_TIMEOUT)) as client:
            response = client.request(
                "DELETE",
                urljoin(self._base, "/api/delete"),
                content=body,
                headers={"Content-Type": "application/json"},
            )
        if response.status_code != 200:
            raise RuntimeError(f"Modell löschen: HTTP {response.status_code}")

    @staticmethod
    def _require_model(model: str) -> None:
        """Modellname validieren (Java: ``requireModel``, 1:1)."""
        if not _MODEL_RE.fullmatch(model):
            raise ValueError("Ungültiger Modellname")
