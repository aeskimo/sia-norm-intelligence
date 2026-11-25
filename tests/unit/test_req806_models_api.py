"""REQ-806: Ollama-Modell-Endpunkte (09 §6.2) — Liste, Pull (async Job), Delete.

Login-unabhängig (lokale Modelle, wie Java in separater App); Pull-Jobs
erscheinen in ``/v1/jobs``; ``/v1/status`` trägt das ``ollama``-Feld
(``sni:status``). Loopback-Mock-Server (kein echter Ollama, 09 §12).
Synthetische Testdaten (G4).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from sni.app import api as api_module
from sni.app.server import build_app
from sni.app.shop import ShopState
from sni.state.workspace import save_workspace_json
from tests.conftest import loopback_server

TOKEN = "app-test-token"
BASE = "http://127.0.0.1:8135"
HDRS = {"x-sia-token": TOKEN}

TAGS_BODY = (
    '{"models":[{"name":"qwen3:4b","modified_at":"2026-09-15T08:00:00Z",'
    '"size":123456789},{"name":"embedding-test","size":42}]}'
)


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, ShopState]:
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "keychain"))
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    shop = ShopState(data_dir=tmp_path / "data")
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token=TOKEN,
        mode="window",
        port=8135,
        shop=shop,
    )
    return TestClient(app, base_url=BASE), shop


def _wait_pull_job(client: TestClient, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for job in client.get("/v1/jobs", headers=HDRS).json():
            if job["id"] == job_id and job["status"] in {"done", "error"}:
                return cast("dict[str, object]", job)
        time.sleep(0.02)
    raise AssertionError(f"Pull-Job {job_id} nach 10 s nicht fertig")


def _submit_pull(client: TestClient, name: str) -> dict[str, object]:
    res = client.post(f"/v1/models/ollama/{name}/pull", headers=HDRS)
    assert res.status_code == 202, res.text
    return cast("dict[str, object]", res.json()["job"])


# ------------------------------------------------------------------ Liste


def test_req806_models_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    with loopback_server({"/api/tags": lambda _body: (200, TAGS_BODY)}) as server:
        monkeypatch.setattr(api_module, "OLLAMA_URL", server.url)
        res = client.get("/v1/models/ollama", headers=HDRS)
    assert res.status_code == 200
    data = res.json()
    assert data["available"] is True
    assert data["models"] == [
        {
            "name": "qwen3:4b",
            "size_bytes": 123456789,
            "modified_at": "2026-09-15T08:00:00Z",
        },
        {"name": "embedding-test", "size_bytes": 42, "modified_at": ""},
    ]


def test_req806_models_list_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    with loopback_server({"/api/tags": lambda _body: (500, "kaputt")}) as server:
        monkeypatch.setattr(api_module, "OLLAMA_URL", server.url)
        res = client.get("/v1/models/ollama", headers=HDRS)
    assert res.status_code == 200
    assert res.json() == {"available": False, "models": []}


# ------------------------------------------------------------------ Pull


def test_req806_pull_job_runs_to_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    with loopback_server(
        {"/api/pull": lambda _body: (200, '{"status":"pulling manifest"}\n{"status":"success"}\n')}
    ) as server:
        monkeypatch.setattr(api_module, "OLLAMA_URL", server.url)
        job = _submit_pull(client, "qwen3:4b")
        assert job["kind"] == "pull"
        final = _wait_pull_job(client, cast(str, job["id"]))
    assert final["status"] == "done"
    assert final["progress"] == "Modell lokal installiert"


def test_req806_pull_job_without_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Lokale Modelle sind Login-unabhängig (Java: separate Modell-App).
    client, _ = _build(tmp_path, monkeypatch)
    with loopback_server({"/api/pull": lambda _body: (200, '{"status":"success"}\n')}) as server:
        monkeypatch.setattr(api_module, "OLLAMA_URL", server.url)
        job = _submit_pull(client, "qwen3:4b")
        final = _wait_pull_job(client, cast(str, job["id"]))
        assert client.get("/v1/status", headers=HDRS).json()["login"] is None
    assert final["status"] == "done"


def test_req806_pull_invalid_name_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.post("/v1/models/ollama/bad%20model/pull", headers=HDRS)
    assert res.status_code == 400
    assert "Ungültiger Modellname" in res.json()["error"]


def test_req806_pull_job_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    with loopback_server({"/api/pull": lambda _body: (500, "oops")}) as server:
        monkeypatch.setattr(api_module, "OLLAMA_URL", server.url)
        job = _submit_pull(client, "qwen3:4b")
        final = _wait_pull_job(client, cast(str, job["id"]))
    assert final["status"] == "error"
    assert "Modell-Download: HTTP 500" in cast(str, final["error"])


def test_req806_pull_job_progress_via_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Der Laufzeit-Fortschritt ist per Polling in /v1/jobs sichtbar
    # (langsamer Mock → Startphase sicher observierbar).
    client, _ = _build(tmp_path, monkeypatch)

    def slow_pull(_body: bytes) -> tuple[int, str]:
        time.sleep(0.3)
        return 200, '{"status":"pulling manifest"}\n{"status":"success"}\n'

    with loopback_server({"/api/pull": slow_pull}) as server:
        monkeypatch.setattr(api_module, "OLLAMA_URL", server.url)
        job = _submit_pull(client, "qwen3:4b")
        job_id = cast(str, job["id"])
        seen: set[str] = set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for j in client.get("/v1/jobs", headers=HDRS).json():
                if j["id"] != job_id:
                    continue
                if j["progress"]:
                    seen.add(cast(str, j["progress"]))
                if j["status"] in {"done", "error"}:
                    assert j["status"] == "done"
                    assert "Modell wird geladen …" in seen
                    return
            time.sleep(0.02)
        raise AssertionError("Pull-Job nach 10 s nicht fertig")


# ------------------------------------------------------------------ Delete


def test_req806_delete_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    bodies: list[bytes] = []

    def delete_handler(body: bytes) -> tuple[int, str]:
        bodies.append(body)
        return 200, "{}"

    with loopback_server({"/api/delete": delete_handler}) as server:
        monkeypatch.setattr(api_module, "OLLAMA_URL", server.url)
        res = client.delete("/v1/models/ollama/qwen3:4b", headers=HDRS)
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert bodies == [b'{"name":"qwen3:4b"}']


def test_req806_delete_invalid_name_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.delete("/v1/models/ollama/bad%20model", headers=HDRS)
    assert res.status_code == 400


def test_req806_delete_ollama_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    with loopback_server({"/api/delete": lambda _body: (500, "kaputt")}) as server:
        monkeypatch.setattr(api_module, "OLLAMA_URL", server.url)
        res = client.delete("/v1/models/ollama/qwen3:4b", headers=HDRS)
    assert res.status_code == 502


# ------------------------------------------------------------------ Status


def test_req806_status_ollama_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, shop = _build(tmp_path, monkeypatch)
    save_workspace_json({"provider": "ollama", "generation_model": "qwen3:8b"}, shop.data_dir)
    with loopback_server({"/api/tags": lambda _body: (200, TAGS_BODY)}) as server:
        monkeypatch.setattr(api_module, "OLLAMA_URL", server.url)
        data = client.get("/v1/status", headers=HDRS).json()
    assert data["ollama"] == {"reachable": True, "model": "qwen3:8b"}


def test_req806_status_ollama_model_null_for_gibb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, shop = _build(tmp_path, monkeypatch)
    save_workspace_json({"provider": "gibb"}, shop.data_dir)
    with loopback_server({"/api/tags": lambda _body: (200, TAGS_BODY)}) as server:
        monkeypatch.setattr(api_module, "OLLAMA_URL", server.url)
        data = client.get("/v1/status", headers=HDRS).json()
    assert data["ollama"] == {"reachable": True, "model": None}
