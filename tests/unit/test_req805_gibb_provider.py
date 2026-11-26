"""REQ-805: OpenAI-kompatibler Provider, z. B. gibb
(1:1-Port ``ch.sia.assistant.ai.OpenAiCompatibleProvider``).

HTTPS-Zwang (HTTP nur Loopback), Bearer-Authentifizierung,
``/models``-Healthcheck und -Liste (Hand-Scanner),
``/chat/completions`` (blockiert + SSE-Streaming mit ``[DONE]``).
"""

from __future__ import annotations

import json

import pytest

from sni.rag.providers.gibb import OpenAiCompatibleProvider
from tests.conftest import loopback_server

MODEL = "gibb-chat-1"
KEY = "test-key"


def _provider(base_url: str, api_key: str = KEY, model: str = MODEL) -> OpenAiCompatibleProvider:
    return OpenAiCompatibleProvider(base_url, api_key, model)


# ------------------------------------------------------------------ Sicherheit


def test_req805_gibb_requires_https_outside_loopback() -> None:
    with pytest.raises(
        PermissionError, match="Nur HTTPS-Endpunkte erlaubt \\(http ausschliesslich Loopback\\)"
    ):
        OpenAiCompatibleProvider("http://chat.gibb.ch/api", KEY, MODEL)
    with pytest.raises(PermissionError, match="Nur HTTPS-Endpunkte erlaubt"):
        OpenAiCompatibleProvider("ftp://chat.gibb.ch/api", KEY, MODEL)
    _provider("https://chat.gibb.ch/api")  # HTTPS: erlaubt
    _provider("http://127.0.0.1:9999/api")  # HTTP + Loopback: erlaubt (Tests)


def test_req805_gibb_requires_key_and_model() -> None:
    with pytest.raises(ValueError, match="API-Schlüssel fehlt"):
        OpenAiCompatibleProvider("https://chat.gibb.ch/api", "  ", MODEL)
    with pytest.raises(ValueError, match="Modell fehlt"):
        OpenAiCompatibleProvider("https://chat.gibb.ch/api", KEY, "")


def test_req805_gibb_id_and_base_normalization() -> None:
    provider = _provider("http://127.0.0.1:9999")  # ohne Pfad
    assert provider.id() == f"127.0.0.1:{MODEL}"


# ------------------------------------------------------------------ available / list_models


def test_req805_gibb_available_checks_models_endpoint() -> None:
    with loopback_server({"/models": lambda _body: (200, '{"data":[]}')}) as server:
        assert _provider(server.url).available() is True
    with loopback_server({"/models": lambda _body: (401, "nein")}) as server:
        assert _provider(server.url).available() is False
    assert _provider("http://127.0.0.1:1/api").available() is False  # down


def test_req805_gibb_list_models_scans_ids() -> None:
    body = '{"data":[{"id":"model-a"},{"id":"model-b"}],"object":"list"}'
    with loopback_server({"/models": lambda _body: (200, body)}) as server:
        assert _provider(server.url).list_models() == ["model-a", "model-b"]


def test_req805_gibb_list_models_empty_and_error() -> None:
    with loopback_server({"/models": lambda _body: (200, '{"object":"list"}')}) as server:
        assert _provider(server.url).list_models() == []
    with (
        loopback_server({"/models": lambda _body: (503, "nein")}) as server,
        pytest.raises(RuntimeError, match="Modellliste nicht verfügbar \\(HTTP 503\\)"),
    ):
        _provider(server.url).list_models()


# ------------------------------------------------------------------ generate


def test_req805_gibb_generate_returns_content() -> None:
    body = '{"choices":[{"message":{"role":"assistant","content":"Antwort \\"ok\\""}}]}'
    with loopback_server({"/chat/completions": lambda _b: (200, body)}) as server:
        assert _provider(server.url).generate("system", "prompt") == 'Antwort "ok"'


def test_req805_gibb_generate_error_status() -> None:
    with (
        loopback_server({"/chat/completions": lambda _b: (500, "nein")}) as server,
        pytest.raises(RuntimeError, match="Modellanfrage fehlgeschlagen \\(HTTP 500\\)"),
    ):
        _provider(server.url).generate("s", "p")


def test_req805_gibb_generate_without_content() -> None:
    with (
        loopback_server({"/chat/completions": lambda _b: (200, '{"choices":[]}')}) as server,
        pytest.raises(RuntimeError, match="Modellantwort enthielt keinen Inhalt"),
    ):
        _provider(server.url).generate("s", "p")


def test_req805_gibb_generate_c0_chars_yield_valid_json_body() -> None:
    """C0-Steuerzeichen im Prompt (z. B. U+0003 aus PDF-Font-Artefakten)
    dürfen nie roh im Request-Body stehen — der gibb-Endpunkt verwarf
    solche Bodies deterministisch mit HTTP 422 (Dry-Run M13.1)."""
    prompt = 'Ziffer mit Steuerzeichen \x03 und \x15 und Quote " '
    seen: list[bytes] = []

    def handler(body: bytes) -> tuple[int, str]:
        seen.append(body)
        return 200, '{"choices":[{"message":{"content":"ok"}}]}'

    with loopback_server({"/chat/completions": handler}) as server:
        assert _provider(server.url).generate("s", prompt) == "ok"

    assert len(seen) == 1
    parsed = json.loads(seen[0])  # gültiges JSON (vor Fix: JSONDecodeError)
    assert parsed["messages"][1]["content"] == prompt


def test_req805_gibb_messages_body_shape() -> None:
    captured: list[bytes] = []

    def handler(body: bytes) -> tuple[int, str]:
        captured.append(body)
        return 200, '{"choices":[{"message":{"content":"ok"}}]}'

    with loopback_server({"/chat/completions": handler}) as server:
        _provider(server.url).generate('Ziel "D"', "Frage\nMit Zeile")

    body = captured[0].decode("utf-8")
    assert body.startswith('{"model":"gibb-chat-1","stream":false')
    assert '"messages":[{"role":"system","content":"Ziel \\"D\\""' in body
    assert '{"role":"user","content":"Frage\\nMit Zeile"}]}' in body


# ------------------------------------------------------------------ Streaming (SSE)


def test_req805_gibb_streaming_sse_tokens() -> None:
    sse = (
        'data: {"choices":[{"delta":{"role":"assistant","content":"Hei "}}]}\n'
        "\n"
        'data: {"choices":[{"delta":{"content":"Dir!"}}]}\n'
        "\n"
        "data: [DONE]\n"
        "\n"
    )
    with loopback_server({"/chat/completions": lambda _b: (200, sse)}) as server:
        provider = _provider(server.url)
        tokens: list[str] = []
        full = provider.generate_streaming("s", "p", tokens.append)
    assert full == "Hei Dir!"
    assert tokens == ["Hei ", "Dir!"]


def test_req805_gibb_streaming_stops_at_done_ignores_rest() -> None:
    sse = (
        'data: {"choices":[{"delta":{"content":"A"}}]}\n'
        "data: [DONE]\n"
        'data: {"choices":[{"delta":{"content":"B"}}]}\n'
    )
    with loopback_server({"/chat/completions": lambda _b: (200, sse)}) as server:
        full = _provider(server.url).generate_streaming("s", "p", lambda _t: None)
    assert full == "A"


def test_req805_gibb_streaming_skips_non_data_lines() -> None:
    sse = ': Kommentar\nevent: ping\ndata: {"choices":[{"delta":{"content":"X"}}]}\ndata: [DONE]\n'
    with loopback_server({"/chat/completions": lambda _b: (200, sse)}) as server:
        full = _provider(server.url).generate_streaming("s", "p", lambda _t: None)
    assert full == "X"


def test_req805_gibb_streaming_error_status() -> None:
    with (
        loopback_server({"/chat/completions": lambda _b: (502, "nein")}) as server,
        pytest.raises(RuntimeError, match="Modell-Streaming fehlgeschlagen \\(HTTP 502\\)"),
    ):
        _provider(server.url).generate_streaming("s", "p", lambda _t: None)
