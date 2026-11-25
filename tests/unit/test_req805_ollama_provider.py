"""REQ-805: Ollama-Antwortprovider (1:1-Port ``ch.sia.assistant.ai.OllamaProvider``).

Loopback-Zwang, ``/api/generate`` (stream:false + NDJSON-Streaming),
Hand-escaped Body, ``string_field``-Escape-Handling (inkl. ``\\uXXXX``),
Healthcheck ``/api/tags``.
"""

from __future__ import annotations

import pytest

from sni.rag.providers.ollama import OllamaChatProvider, esc, string_field
from tests.conftest import loopback_server

MODEL = "qwen3:4b"


# ------------------------------------------------------------------ Sicherheit


def test_req805_ollama_requires_loopback() -> None:
    with pytest.raises(PermissionError, match="Nur lokale Modellserver erlaubt"):
        OllamaChatProvider("http://example.com:11434", MODEL)
    with pytest.raises(PermissionError, match="Nur lokale Modellserver erlaubt"):
        OllamaChatProvider("https://chat.gibb.ch/api", MODEL)  # fremder Host
    OllamaChatProvider("http://127.0.0.1:11434", MODEL)  # Loopback: erlaubt
    OllamaChatProvider("http://localhost:11434", MODEL)  # Loopback: erlaubt


def test_req805_ollama_id_and_availability() -> None:
    with loopback_server({"/api/tags": lambda _body: (200, '{"models":[]}')}) as server:
        provider = OllamaChatProvider(server.url, MODEL)
        assert provider.id() == f"ollama:{MODEL}"
        assert provider.available() is True


def test_req805_ollama_available_false_when_down() -> None:
    provider = OllamaChatProvider("http://127.0.0.1:1", MODEL)
    assert provider.available() is False


def test_req805_ollama_available_false_on_error_status() -> None:
    with loopback_server({"/api/tags": lambda _body: (500, "kaputt")}) as server:
        assert OllamaChatProvider(server.url, MODEL).available() is False


# ------------------------------------------------------------------ generate


def test_req805_ollama_generate_returns_response_field() -> None:
    with loopback_server(
        {
            "/api/generate": lambda body: (
                200,
                r'{"model":"m","response":"Hallo \"Welt\"","done":true}',
            )
        }
    ) as server:
        provider = OllamaChatProvider(server.url, MODEL)
        assert provider.generate("system", "prompt") == 'Hallo "Welt"'


def test_req805_ollama_generate_unescapes_unicode() -> None:
    with loopback_server(
        {"/api/generate": lambda _body: (200, '{"response":"Gr\\u00fc\\u00dfe"}')}
    ) as server:
        assert OllamaChatProvider(server.url, MODEL).generate("s", "p") == "Grüße"


def test_req805_ollama_generate_error_status() -> None:
    with (
        loopback_server({"/api/generate": lambda _body: (500, "kaputt")}) as server,
        pytest.raises(RuntimeError, match="HTTP 500"),
    ):
        OllamaChatProvider(server.url, MODEL).generate("s", "p")


def test_req805_ollama_body_is_hand_escaped() -> None:
    captured: list[bytes] = []

    def handler(body: bytes) -> tuple[int, str]:
        captured.append(body)
        return 200, '{"response":"ok"}'

    with loopback_server({"/api/generate": handler}) as server:
        OllamaChatProvider(server.url, MODEL).generate('Ziel "D"', "Zeile\nBreak")

    body = captured[0].decode("utf-8")
    assert body.startswith('{"model":"qwen3:4b","stream":false')
    assert '"system":"Ziel \\"D\\""' in body
    assert '"prompt":"Zeile\\nBreak"' in body
    assert '"done' not in body  # kein Fremdmaterial im Body.


# ------------------------------------------------------------------ Streaming


def test_req805_ollama_streaming_ndjson_tokens() -> None:
    ndjson = (
        '{"model":"m","response":"Hei ","done":false}\n'
        '{"model":"m","response":"Dir","done":false}\n'
        '{"model":"m","done":true}\n'  # ohne response-Feld: kein Token.
    )
    with loopback_server({"/api/generate": lambda _body: (200, ndjson)}) as server:
        provider = OllamaChatProvider(server.url, MODEL)
        tokens: list[str] = []
        full = provider.generate_streaming("s", "p", tokens.append)
    assert full == "Hei Dir"
    assert tokens == ["Hei ", "Dir"]


def test_req805_ollama_streaming_error_status() -> None:
    with (
        loopback_server({"/api/generate": lambda _body: (500, "kaputt")}) as server,
        pytest.raises(RuntimeError, match="HTTP 500"),
    ):
        OllamaChatProvider(server.url, MODEL).generate_streaming("s", "p", lambda _t: None)


def test_req805_ollama_streaming_body_marks_stream() -> None:
    captured: list[bytes] = []

    def handler(body: bytes) -> tuple[int, str]:
        captured.append(body)
        return 200, '{"response":"x"}'

    with loopback_server({"/api/generate": handler}) as server:
        OllamaChatProvider(server.url, MODEL).generate_streaming("s", "p", lambda _t: None)

    assert b'"stream":true' in captured[0]


# ------------------------------------------------------------------ string_field


def test_req805_string_field_decodes_all_escapes() -> None:
    # \\ → Backslash, \" → Quote, \u0041 → A (Java 1:1).
    assert string_field(r'{"a":"x\ny\rz\tb\u0041\\\""}', "a") == 'x\ny\rz\tbA\\"'


def test_req805_string_field_missing_field_returns_none() -> None:
    assert string_field('{"a":"x"}', "b") is None
    assert string_field("{}", "a") is None


def test_req805_string_field_non_string_value_returns_none() -> None:
    assert string_field('{"a":1}', "a") is None
    assert string_field('{"a":"x"}', "a2") is None  # Feldname nur exakt.


def test_req805_string_field_incomplete_sequences_raise() -> None:
    with pytest.raises(ValueError, match="JSON-String unvollständig"):
        string_field('{"a":"abc\\', "a")
    with pytest.raises(ValueError, match="JSON-String unvollständig"):
        string_field('{"a":"abc\\u12', "a")
    with pytest.raises(ValueError, match="JSON-String unvollständig"):
        string_field('{"a":"offen', "a")


# ------------------------------------------------------------------ esc


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("a\\b", "a\\\\b"),
        ('a"b', 'a\\"b'),
        ("a\nb", "a\\nb"),
        ("a\rb", "a\\rb"),
        ("a\tb", "a\\tb"),
        ("klartext", "klartext"),
    ],
)
def test_req805_esc_matches_java(raw: str, escaped: str) -> None:
    assert esc(raw) == escaped
