"""REQ-804: App-Analyse-Endpunkte (09 §6.2) — ``POST /v1/documents/{id}/analyze``
(async Analyse-Job) und ``GET /v1/documents/{id}`` (Detail inkl. Job-State).

End-to-End über ``build_app`` mit injiziertem ShopState (Fake-SOAP-Client);
Keyless-Betrieb → Index-Cache passiv, kein Klartext auf Disk (G4).
Synthetische Testdaten (G4).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from sni.app.server import build_app
from sni.app.shop import ShopState
from tests.conftest import (
    LICENSE_XML,
    FakeSoapClient,
    document_result_ok,
    login_result_ok,
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


# ------------------------------------------------------------------ Analyse-Job


def test_req804_analyze_full_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build(tmp_path, monkeypatch)
    with client:
        _login(client)
        _download(client, "prod-101")
        res = client.post("/v1/documents/prod-101/analyze", headers=HDRS, json={})
        assert res.status_code == 202, res.text
        job = cast("dict[str, object]", res.json()["job"])
        assert cast(str, job["kind"]) == "analyze"
        done = _wait_for_job(client, cast(str, job["id"]), {"done", "error"})
        assert done["status"] == "done", done
        assert done["progress"] == "Volltextindex bereit"

        documents = client.get("/v1/documents", headers=HDRS).json()
        entry = next(d for d in documents if d["product_id"] == "prod-101")
        assert entry["status"] == "FULLTEXT_READY"
        assert entry["embeddings_ready"] is False
        assert entry["indexed_pages"] == 1
        assert entry["detail"] == "Volltextindex bereit"

        # Keyless: Index-Cache passiv — kein Klartext auf Disk (G4).
        assert list((tmp_path / "data").rglob("*.sniidx")) == []


def test_req804_analyze_detail_includes_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _build(tmp_path, monkeypatch)
    with client:
        _login(client)
        _download(client, "prod-101")
        res = client.post("/v1/documents/prod-101/analyze", headers=HDRS, json={})
        job = cast("dict[str, object]", res.json()["job"])
        _wait_for_job(client, cast(str, job["id"]), {"done", "error"})

        detail = client.get("/v1/documents/prod-101", headers=HDRS)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["product_id"] == "prod-101"
        assert body["status"] == "FULLTEXT_READY"
        kinds = {j["kind"] for j in body["jobs"]}
        assert kinds == {"download", "analyze"}
        assert all(j["document_id"] == "prod-101" for j in body["jobs"])


def test_req804_analyze_without_body_defaults_to_fulltext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _build(tmp_path, monkeypatch)
    with client:
        _login(client)
        _download(client, "prod-101")
        res = client.post("/v1/documents/prod-101/analyze", headers=HDRS)
        assert res.status_code == 202, res.text
        job = cast("dict[str, object]", res.json()["job"])
        done = _wait_for_job(client, cast(str, job["id"]), {"done", "error"})
        assert done["status"] == "done"
        assert done["progress"] == "Volltextindex bereit"


# ------------------------------------------------------------------ Fehlerfälle


def test_req804_analyze_unknown_document_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _build(tmp_path, monkeypatch)
    with client:
        _login(client)
        res = client.post("/v1/documents/prod-999/analyze", headers=HDRS, json={})
        assert res.status_code == 404
        assert res.json()["error"] == "Dokument nicht in der lokalen Registry"


def test_req804_analyze_without_login_401(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build(tmp_path, monkeypatch)
    with client:
        res = client.post("/v1/documents/prod-101/analyze", headers=HDRS, json={})
        assert res.status_code == 401


def test_req804_detail_unknown_document_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _build(tmp_path, monkeypatch)
    with client:
        _login(client)
        res = client.get("/v1/documents/prod-999", headers=HDRS)
        assert res.status_code == 404


def test_req804_detail_without_login_401(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build(tmp_path, monkeypatch)
    with client:
        res = client.get("/v1/documents/prod-101", headers=HDRS)
        assert res.status_code == 401
