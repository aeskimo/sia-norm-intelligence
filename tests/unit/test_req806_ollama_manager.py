"""REQ-806: Ollama-Modellverwaltung (1:1 Java: ``OllamaModelManagerSelfTest``).

Loopback-Zwang (externe Hosts sind nicht zulässig), Modell-Liste
(``/api/tags``), Modell-Download (``/api/pull``, 2-h-Timeout, NDJSON-
Fortschritt) und Modell-Löschen (``DELETE /api/delete`` mit JSON-Body).
Loopback-Mock-Server (kein echter Ollama, 09 §12). Synthetische
Testdaten (G4).
"""

from __future__ import annotations

import json
import socket

import pytest

from sni.models.ollama_manager import (
    LocalModelInfo,
    OllamaModelManager,
    esc,
    string_field,
)
from tests.conftest import loopback_server

TAGS_BODY = (
    '{"models":[{"name":"qwen3:4b","modified_at":"2026-09-15T08:00:00Z",'
    '"size":123456789},{"name":"embedding-test","size":42}]}'
)


def _closed_port_url() -> str:
    """URL auf einen port, an dem niemand lauscht (Connection Refused)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{probe.getsockname()[1]}"


# ------------------------------------------------------------------ Sicherheit


def test_req806_remote_host_blocked() -> None:
    with pytest.raises(PermissionError, match="Nur lokale Modellendpunkte erlaubt"):
        OllamaModelManager("https://example.com")


def test_req806_loopback_hosts_allowed() -> None:
    for url in ("http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"):
        OllamaModelManager(url)  # kein Exception


def test_req806_invalid_model_name_rejected() -> None:
    manager = OllamaModelManager("http://127.0.0.1:11434")
    for bad in ("", "  ", "../bad model", "a" * 201, "modell mit leerstelle"):
        with pytest.raises(ValueError, match="Ungültiger Modellname"):
            manager.pull(bad)
        with pytest.raises(ValueError, match="Ungültiger Modellname"):
            manager.delete(bad)


def test_req806_longest_valid_name_accepted() -> None:
    manager = OllamaModelManager("http://127.0.0.1:11434")
    manager._require_model("a" * 200)  # kein Exception


# ------------------------------------------------------------------ available


def test_req806_available_true() -> None:
    with loopback_server({"/api/tags": lambda _body: (200, TAGS_BODY)}) as server:
        assert OllamaModelManager(server.url).available() is True


def test_req806_available_false_when_down() -> None:
    assert OllamaModelManager(_closed_port_url()).available() is False


def test_req806_available_false_on_error_status() -> None:
    with loopback_server({"/api/tags": lambda _body: (500, "kaputt")}) as server:
        assert OllamaModelManager(server.url).available() is False


# ------------------------------------------------------------------ list


def test_req806_list_installed() -> None:
    with loopback_server({"/api/tags": lambda _body: (200, TAGS_BODY)}) as server:
        models = OllamaModelManager(server.url).list_installed()
    assert len(models) == 2
    assert models[0].name == "qwen3:4b"
    assert models[0].size_bytes == 123456789
    assert models[0].modified_at == "2026-09-15T08:00:00Z"
    assert models[1] == LocalModelInfo("embedding-test", 42, "")  # modified_at fehlt → ""


def test_req806_list_non200_raises() -> None:
    with (
        loopback_server({"/api/tags": lambda _body: (500, "kaputt")}) as server,
        pytest.raises(RuntimeError, match="Modellliste: HTTP 500"),
    ):
        OllamaModelManager(server.url).list_installed()


def test_req806_list_blank_name_skipped() -> None:
    body = '{"models":[{"name":"  ","size":1},{"name":"ok","size":2}]}'
    with loopback_server({"/api/tags": lambda _body: (200, body)}) as server:
        models = OllamaModelManager(server.url).list_installed()
    assert [m.name for m in models] == ["ok"]


def test_req806_list_scanner_handles_braces_and_quotes_in_strings() -> None:
    # Scanner-Kanten: geschweifte Klammern + Zitate in String-Feldern.
    body = (
        r'{"models":[{"name":"a:b","size":7,"description":"{\"x\": 1} mit '
        r'\"{klammer}\" und {weitere} Klammern"},{"name":"c","size":8}]}'
    )
    with loopback_server({"/api/tags": lambda _body: (200, body)}) as server:
        models = OllamaModelManager(server.url).list_installed()
    assert [m.name for m in models] == ["a:b", "c"]
    assert models[0].size_bytes == 7


def test_req806_list_without_models_key() -> None:
    with loopback_server({"/api/tags": lambda _body: (200, '{"other":1}')}) as server:
        assert OllamaModelManager(server.url).list_installed() == []


def test_req806_local_model_info_requires_name() -> None:
    with pytest.raises(ValueError, match="Modellname fehlt"):
        LocalModelInfo("", 1)
    with pytest.raises(ValueError, match="Modellname fehlt"):
        LocalModelInfo("   ", 1)


# ------------------------------------------------------------------ pull


def test_req806_pull_sends_model_and_reads_progress() -> None:
    bodies: list[bytes] = []

    def pull_handler(body: bytes) -> tuple[int, str]:
        bodies.append(body)
        return 200, '{"status":"pulling manifest"}\n{"status":"success"}\n'

    with loopback_server({"/api/pull": pull_handler}) as server:
        progress: list[str] = []
        OllamaModelManager(server.url).pull("qwen3:4b", progress.append)
    assert progress == ["pulling manifest", "success"]
    assert len(bodies) == 1
    assert b'{"name":"qwen3:4b","stream":true}' in bodies[0]


def test_req806_pull_non200_raises_and_no_progress() -> None:
    progress: list[str] = []
    with (
        loopback_server({"/api/pull": lambda _body: (500, "oops")}) as server,
        pytest.raises(RuntimeError, match="Modell-Download: HTTP 500"),
    ):
        OllamaModelManager(server.url).pull("qwen3:4b", progress.append)
    assert progress == []


def test_req806_pull_ignores_lines_without_status() -> None:
    with loopback_server(
        {"/api/pull": lambda _body: (200, '{"status":"a"}\n{}\n{"other":1}\n{"status":"b"}\n')}
    ) as server:
        progress: list[str] = []
        OllamaModelManager(server.url).pull("qwen3:4b", progress.append)
    assert progress == ["a", "b"]


def test_req806_pull_invalid_model_blocked() -> None:
    called = False

    def pull_handler(_body: bytes) -> tuple[int, str]:
        nonlocal called
        called = True
        return 200, "{}\n"

    with (
        loopback_server({"/api/pull": pull_handler}) as server,
        pytest.raises(ValueError, match="Ungültiger Modellname"),
    ):
        OllamaModelManager(server.url).pull("../bad model")
    assert called is False


# ------------------------------------------------------------------ delete


def test_req806_delete_sends_body() -> None:
    bodies: list[bytes] = []

    def delete_handler(body: bytes) -> tuple[int, str]:
        bodies.append(body)
        return 200, "{}"

    with loopback_server({"/api/delete": delete_handler}) as server:
        OllamaModelManager(server.url).delete("qwen3:4b")
    assert bodies == [b'{"name":"qwen3:4b"}']


def test_req806_delete_non200_raises() -> None:
    with (
        loopback_server({"/api/delete": lambda _body: (404, "not found")}) as server,
        pytest.raises(RuntimeError, match="Modell löschen: HTTP 404"),
    ):
        OllamaModelManager(server.url).delete("qwen3:4b")


# ------------------------------------------------------------------ JSON-Helper


def test_req806_esc_matches_java() -> None:
    assert esc('a"b\\c') == 'a\\"b\\\\c'
    assert esc("x\ny\rz\tw") == "x\\ny\\rz\\tw"


def test_req806_esc_escapes_remaining_c0_chars() -> None:
    """RFC 8259: C0-Steuerzeichen (z. B. U+0003 aus PDF-Font-Artefakten)
    dürfen nie roh im JSON-Body stehen — sonst HTTP 422 am gibb-Endpunkt
    (Dry-Run M13.1)."""
    out = esc("a\x03b\x08c\x15d")
    assert "\x03" not in out and "\x08" not in out and "\x15" not in out
    assert json.loads(f'"{out}"') == "a\x03b\x08c\x15d"


def test_req806_string_field_escapes() -> None:
    assert string_field(r'{"s":"a\nb\"c"}', "s") == 'a\nb"c'
    assert string_field(r'{"s":"\u0041"}', "s") == "A"
    assert string_field("{}", "s") is None
    assert string_field('{"s":42}', "s") is None  # kein String


def test_req806_string_field_incomplete_raises() -> None:
    with pytest.raises(ValueError, match="JSON-String unvollständig"):
        string_field('{"s":"abc', "s")
