"""REQ-805: RAG-Frage-Endpunkt ``POST /v1/ask`` (09 §6.2) — SSE-Stream.

Events ``token``/``sources``/``answer``/``error``; Provider und Modell
aus ``workspace.json`` (Standard: lokales Ollama mit ``qwen3:4b``);
Token über Query-Parameter ``sia_token`` (EventSource). End-to-End über
``build_app`` mit injiziertem ShopState (Fake-SOAP-Client) und
Loopback-Mock-Modellserver. Synthetische Testdaten (G4).
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from sni.api.main import DISCLAIMER
from sni.app.server import build_app
from sni.app.shop import ShopState
from sni.state.workspace import save_workspace_json
from tests.conftest import (
    LICENSE_XML,
    FakeSoapClient,
    document_result_ok,
    login_result_ok,
    loopback_server,
    make_mro,
    make_pdf,
    make_srd,
)

TOKEN = "app-test-token"
BASE = "http://127.0.0.1:8125"
HDRS = {"x-sia-token": TOKEN}
PDF = make_pdf(["SYN 1  Testnorm"])


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "keychain"))
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)  # Keyless: Cache passiv.
    monkeypatch.delenv("GIBB_API_KEY", raising=False)
    client = FakeSoapClient(
        login_result_ok(),
        make_mro(LICENSE_XML),
        document_result_ok("101_2020_dSIA.srd"),
        make_srd("prod-101", PDF),
    )
    shop = ShopState(client_factory=lambda profile: client, data_dir=tmp_path / "data")
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token=TOKEN,
        mode="window",
        port=8125,
        shop=shop,
    )
    return TestClient(app, base_url=BASE)


def _login(client: TestClient) -> None:
    res = client.post(
        "/v1/session/login",
        headers=HDRS,
        json={
            "provider": "sia",
            "customer": "kunde1",
            "password": "geheim",
            "device_id": "dev-1",
        },
    )
    assert res.status_code == 200, res.text


def _wait_for_job(client: TestClient, job_id: str, wanted: set[str]) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        jobs = client.get("/v1/jobs", headers=HDRS).json()
        for job in jobs:
            if job["id"] == job_id and job["status"] in wanted:
                return cast("dict[str, object]", job)
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} nicht in Status {sorted(wanted)} nach 10 s")


def _download(client: TestClient, product_id: str) -> None:
    res = client.post("/v1/documents/download", headers=HDRS, json={"product_id": product_id})
    assert res.status_code == 202, res.text
    job = cast("dict[str, object]", res.json()["job"])
    final = _wait_for_job(client, cast(str, job["id"]), {"done", "error"})
    assert final["status"] == "done", f"Voraussetzung: Download fertig, erhalten {final}"


def _analyze(client: TestClient, product_id: str) -> None:
    res = client.post(f"/v1/documents/{product_id}/analyze", headers=HDRS, json={})
    assert res.status_code == 202, res.text
    job = cast("dict[str, object]", res.json()["job"])
    final = _wait_for_job(client, cast(str, job["id"]), {"done", "error"})
    assert final["status"] == "done", f"Voraussetzung: Analyse fertig, erhalten {final}"


def _chat_handler(
    answer: str, captured: list[bytes] | None = None
) -> Callable[[bytes], tuple[int, str]]:
    """Mock-Ollama: Antwort als NDJSON-Zeile (``response``-Feld)."""

    def handler(body: bytes) -> tuple[int, str]:
        if captured is not None:
            captured.append(body)
        return 200, json.dumps({"model": "m", "response": answer, "done": True})

    return handler


@contextlib.contextmanager
def _mock_chat(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[bytes], tuple[int, str]]
) -> Iterator[object]:
    """Loopback-Mock-Modellserver; patcht ``sni.app.api.OLLAMA_URL``."""
    with loopback_server({"/api/generate": handler}) as server:
        monkeypatch.setattr("sni.app.api.OLLAMA_URL", server.url)
        yield server


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in body.strip().split("\n\n"):
        event: str | None = None
        data: str | None = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if event is not None and data is not None:
            events.append((event, cast("dict[str, object]", json.loads(data))))
    return events


# ------------------------------------------------------------------ Vollflow


def test_req805_ask_full_flow_sse_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build(tmp_path, monkeypatch)
    captured: list[bytes] = []
    with client:
        _login(client)
        _download(client, "prod-101")
        _analyze(client, "prod-101")
        answer = "Es gilt [Q1] für Testnorm."
        with _mock_chat(monkeypatch, _chat_handler(answer, captured)):
            res = client.post(
                "/v1/ask",
                headers=HDRS,
                json={"question": "Testnorm", "scope": {"document_ids": ["prod-101"]}},
            )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(res.text)
    assert [name for name, _data in events] == ["token", "sources", "answer"]

    assert events[0][1]["text"] == answer

    sources = cast(list[object], events[1][1]["sources"])
    assert len(sources) == 1
    source = cast(dict[str, object], sources[0])
    assert source["source_id"] == "prod-101:p1"
    assert source["page"] == 1
    assert source["text"] == "SYN 1 Testnorm"  # PageSource normalisiert Leerzeichen.

    final = events[2][1]
    assert final["text"] == answer
    assert final["status"] == "DIRECTLY_SUPPORTED"
    assert final["model_id"] == "ollama:qwen3:4b"  # workspace.json fehlt → Default
    assert final["disclaimer"] == DISCLAIMER
    assert len(cast(list[object], final["sources"])) == 1

    # Prompt-Vertrag: gestreamt, Quelle mit seite=1 im Prompt.
    prompt_body = captured[0].decode("utf-8")
    assert '"stream":true' in prompt_body
    assert "seite=1" in prompt_body
    assert "FRAGE:" in prompt_body


def test_req805_ask_no_hits_insufficient_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _build(tmp_path, monkeypatch)
    with client:
        _login(client)
        _download(client, "prod-101")
        _analyze(client, "prod-101")
        with _mock_chat(monkeypatch, _chat_handler("Antwort [Q1].")):
            # EventSource-Äquivalent: Token als Query-Parameter, ohne Header.
            res = client.post(f"/v1/ask?sia_token={TOKEN}", json={"question": "xyzqq"})
    assert res.status_code == 200, res.text
    events = _parse_sse(res.text)
    final = events[-1]
    assert final[0] == "answer"
    assert final[1]["status"] == "INSUFFICIENT_EVIDENCE"
    assert final[1]["text"] == "Keine ausreichende Grundlage."
    assert final[1]["sources"] == []


def test_req805_ask_unknown_workset_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build(tmp_path, monkeypatch)
    with client:
        _login(client)
        res = client.post(
            "/v1/ask",
            headers=HDRS,
            json={"question": "Testnorm", "scope": {"workset_id": "neu"}},
        )
    assert res.status_code == 400
    assert "Arbeitsset unbekannt" in res.json()["error"]


def test_req805_ask_gibb_without_key_error_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _build(tmp_path, monkeypatch)
    save_workspace_json(
        {
            "provider": "gibb",
            "gibb_model": "m",
            "gibb_base_url": "https://chat.gibb.ch/api",
        },
        tmp_path / "data",
    )
    with client:
        _login(client)
        _download(client, "prod-101")
        _analyze(client, "prod-101")
        res = client.post("/v1/ask", headers=HDRS, json={"question": "Testnorm"})
    assert res.status_code == 200, res.text
    events = _parse_sse(res.text)
    assert [name for name, _data in events] == ["error"]
    assert "gibb-API-Key fehlt" in cast(str, events[0][1]["error"])
    assert events[0][1]["disclaimer"] == DISCLAIMER


# ------------------------------------------------------------------ Fehlerfälle


def test_req805_ask_without_login_401(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build(tmp_path, monkeypatch)
    with client:
        res = client.post("/v1/ask", headers=HDRS, json={"question": "Testnorm"})
    assert res.status_code == 401


def test_req805_ask_empty_question_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build(tmp_path, monkeypatch)
    with client:
        _login(client)
        res = client.post("/v1/ask", headers=HDRS, json={"question": "   "})
    assert res.status_code == 400
