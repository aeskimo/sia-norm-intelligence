"""REQ-803/M8.2: App-Endpunkte (``sni.app.api``) — Login, Katalog, Download,
Dokumente, Jobs, Status.

End-to-End über ``build_app`` mit injiziertem ShopState (Fake-SOAP-Client)
und Fake-Keychain (``SIA_FAKE_KEYCHAIN``). Prüft auch die neuen Schemas
``sni:catalog_item``, ``sni:local_document``, ``sni:job``. Synthetische
Testdaten (G4).
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from sni.app.server import build_app
from sni.app.shop import ShopState
from sni.shop.models import LoginStatus
from tests.conftest import (
    LICENSE_XML,
    FakeSoapClient,
    document_result_ok,
    login_result_failure,
    login_result_ok,
    make_mro,
    make_pdf,
    make_srd,
)

TOKEN = "app-test-token"
BASE = "http://127.0.0.1:8124"
HDRS = {"x-sia-token": TOKEN}
SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"

PDF = make_pdf(["SYN 1  Testnorm"])


def _schema(name: str) -> Draft202012Validator:
    raw = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(raw)
    return Draft202012Validator(raw)


def _build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: FakeSoapClient,
) -> tuple[TestClient, ShopState]:
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "keychain"))
    shop = ShopState(client_factory=lambda profile: client)
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token=TOKEN,
        mode="window",
        port=8124,
        shop=shop,
    )
    return TestClient(app, base_url=BASE), shop


def _standard_client() -> FakeSoapClient:
    return FakeSoapClient(
        login_result_ok(),
        make_mro(LICENSE_XML),
        document_result_ok("101_2020_dSIA.srd"),
        make_srd("prod-101", PDF),
    )


def _login(client: TestClient, remember: bool = False) -> None:
    res = client.post(
        "/v1/session/login",
        headers=HDRS,
        json={
            "provider": "sia",
            "customer": "kunde1",
            "password": "geheim",
            "device_id": "dev-1",
            "remember": remember,
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


# ------------------------------------------------------------------ Login


def test_req803_app_login_success_keyring_and_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, shop = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        res = client.post(
            "/v1/session/login",
            headers=HDRS,
            json={
                "provider": "sia",
                "customer": "kunde1",
                "password": "geheim",
                "device_id": "dev-1",
                "remember": True,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["message"] == "1 Katalogwarnungen"  # Produkt ohne ID
        assert data["provider"] == "SIA-Reader"
        assert data["customer"] == "kunde1"
        assert data["device_id"] == "dev-1"
        assert data["keyring"] == "ok"
        assert len(data["catalog"]) == 2
        _schema("catalog_item.schema.json").validate(data["catalog"][0])
        # remember=True → Eintrag im (Fake-)Keyring, Payload-Format 1:1 (REQ-802)
        entry = tmp_path / "keychain" / "ch.sia.normenassistent" / "sia-login"
        assert entry.is_file()
        cust_b64, sep, pwd_b64 = entry.read_text(encoding="utf-8").partition("|")
        assert sep
        assert base64.urlsafe_b64decode(cust_b64 + "=" * (-len(cust_b64) % 4)) == b"kunde1"
        # /v1/status: Login-Sitzung sichtbar (ohne Passwort)
        status = client.get("/v1/status", headers=HDRS).json()
        assert status["login"] == {
            "provider": "SIA-Reader",
            "customer": "kunde1",
            "device_id": "dev-1",
        }
        assert status["documents"] == 0
        assert shop.is_logged_in


def test_req803_app_login_failure_protocol_code_1_to_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeSoapClient(
        login_result_failure(LoginStatus.INVALID_PASSWORD, "Passwort ist falsch.")
    )
    client, shop = _build(tmp_path, monkeypatch, fake)
    with client:
        res = client.post(
            "/v1/session/login",
            headers=HDRS,
            json={
                "provider": "sia",
                "customer": "kunde1",
                "password": "falsch",
                "device_id": "dev-1",
            },
        )
        assert res.status_code == 401
        data = res.json()
        assert data["error"] == "INVALID_PASSWORD: Passwort ist falsch."
        assert data["protocol"] == "Fail_Wrong_PWD"  # G6: 1:1-Protokollcode
        assert shop.is_logged_in is False


def test_req803_app_login_unknown_provider_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        res = client.post(
            "/v1/session/login",
            headers=HDRS,
            json={
                "provider": "xyz",
                "customer": "kunde1",
                "password": "geheim",
                "device_id": "dev-1",
            },
        )
        assert res.status_code == 400
        assert "Unbekannter Provider" in res.json()["error"]


def test_req803_app_login_empty_fields_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        res = client.post(
            "/v1/session/login",
            headers=HDRS,
            json={
                "provider": "sia",
                "customer": "  ",
                "password": "geheim",
                "device_id": "dev-1",
            },
        )
        assert res.status_code == 400


def test_req803_app_login_remember_false_no_keyring_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        res = client.post(
            "/v1/session/login",
            headers=HDRS,
            json={
                "provider": "sia",
                "customer": "kunde1",
                "password": "geheim",
                "device_id": "dev-1",
                "remember": False,
            },
        )
        assert res.status_code == 200
        assert res.json()["keyring"] is None
        entry = tmp_path / "keychain" / "ch.sia.normenassistent" / "sia-login"
        assert not entry.exists()


# ------------------------------------------------------------------ Katalog


def test_req803_app_catalog_requires_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        assert client.get("/v1/catalog", headers=HDRS).status_code == 401


def test_req803_app_catalog_items_and_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        _login(client)
        res = client.get("/v1/catalog", headers=HDRS)
        assert res.status_code == 200
        items = res.json()
        assert [d["product_id"] for d in items] == ["prod-101", "prod-102"]
        for item in items:
            _schema("catalog_item.schema.json").validate(item)
        by_id = {d["product_id"]: d for d in items}
        assert by_id["prod-102"]["view_allowed"] is False


# ------------------------------------------------------------------ Download


def test_req803_app_download_full_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        _login(client)
        res = client.post(
            "/v1/documents/download",
            headers=HDRS,
            json={"product_id": "prod-101"},
        )
        assert res.status_code == 202
        job = res.json()["job"]
        assert job["kind"] == "download"
        assert job["document_id"] == "prod-101"
        assert job["status"] in ("queued", "running", "done")
        _schema("job.schema.json").validate(job)
        _wait_for_job(client, job["id"], {"done", "error"})

        docs = client.get("/v1/documents", headers=HDRS).json()
        assert len(docs) == 1
        _schema("local_document.schema.json").validate(docs[0])
        assert docs[0]["status"] == "CACHED"
        assert docs[0]["status_label"] == "Heruntergeladen"
        assert docs[0]["detail"] == "PDF im verschlüsselten Sitzungscache"

        pdf = client.get("/v1/documents/prod-101/pdf", headers=HDRS)
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content == PDF
        assert "101_2020_dSIA.srd" in pdf.headers["content-disposition"]

        status = client.get("/v1/status", headers=HDRS).json()
        assert status["documents"] == 1
        assert "Eingeloggt" in status["summary"]


def test_req803_app_download_unknown_product_job_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        _login(client)
        res = client.post(
            "/v1/documents/download",
            headers=HDRS,
            json={"product_id": "unbekannt"},
        )
        assert res.status_code == 202
        job = res.json()["job"]
        _wait_for_job(client, job["id"], {"done", "error"})
        jobs = client.get("/v1/jobs", headers=HDRS).json()
        final = [j for j in jobs if j["id"] == job["id"]][0]
        assert final["status"] == "error"
        assert final["error"] == "Produkt nicht im Katalog"
        assert client.get("/v1/documents", headers=HDRS).json() == []


def test_req803_app_document_pdf_missing_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        _login(client)
        assert client.get("/v1/documents/prod-101/pdf", headers=HDRS).status_code == 404
        assert client.get("/v1/catalog", headers=HDRS).status_code == 200  # Kontrolle


def test_req803_app_document_pdf_requires_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        assert client.get("/v1/documents/prod-101/pdf").status_code == 401  # kein Token


# ------------------------------------------------------------------ Entfernen


def test_req803_app_document_remove_clears_cache_and_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        _login(client)
        res = client.post("/v1/documents/download", headers=HDRS, json={"product_id": "prod-101"})
        _wait_for_job(client, res.json()["job"]["id"], {"done", "error"})
        assert client.get("/v1/documents", headers=HDRS).json() != []

        removed = client.delete("/v1/documents/prod-101", headers=HDRS)
        assert removed.status_code == 200
        assert client.get("/v1/documents", headers=HDRS).json() == []
        assert client.get("/v1/documents/prod-101/pdf", headers=HDRS).status_code == 404


def test_req803_app_document_remove_unknown_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        _login(client)
        assert client.delete("/v1/documents/unbekannt", headers=HDRS).status_code == 404


# ------------------------------------------------------------------ Logout


def test_req803_app_logout_zeroing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, shop = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        _login(client, remember=True)
        res = client.post("/v1/documents/download", headers=HDRS, json={"product_id": "prod-101"})
        _wait_for_job(client, res.json()["job"]["id"], {"done", "error"})

        out = client.post("/v1/session/logout", headers=HDRS)
        assert out.status_code == 200
        assert shop.is_logged_in is False

        status = client.get("/v1/status", headers=HDRS).json()
        assert status["login"] is None
        assert status["documents"] == 0
        assert client.get("/v1/documents", headers=HDRS).json() == []
        assert client.get("/v1/catalog", headers=HDRS).status_code == 401
        assert client.get("/v1/documents/prod-101/pdf", headers=HDRS).status_code == 401
        # Keyring-Eintrag bleibt (Java: Logout löscht nicht gespeicherte Zugangsdaten)
        entry = tmp_path / "keychain" / "ch.sia.normenassistent" / "sia-login"
        assert entry.is_file()


def test_req803_app_status_before_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch, _standard_client())
    with client:
        status = client.get("/v1/status", headers=HDRS).json()
        assert status["login"] is None
        assert status["documents"] == 0
        assert "Bitte im Normenkatalog einloggen" in status["summary"]
