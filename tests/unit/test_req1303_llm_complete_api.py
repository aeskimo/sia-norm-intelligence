"""REQ-1303 (M13.1): Web-UI-Endpunkt ``POST /v1/ingest/llm-complete``.

Stufe 3 (M13, ADR-0010) über die Consumer-App: gibb-Konfiguration aus den
App-Einstellungen (``workspace.json`` + Keyring ``gibb-api-key``) statt
``SNI_LLM_*``-Env; dasselbe Kern-Tool wie ``make llm``. Vorschlag
``document.llm.json`` — ``document.json`` und Review Queue bleiben unberührt
(G3); die Antwort enthält keine Normtexte (G4).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sni.app.server import build_app
from sni.app.shop import ShopState
from sni.catalog.snapshot import load_snapshot
from sni.ingest import llm_complete
from tests.conftest import (
    LICENSE_XML,
    FakeSoapClient,
    document_result_ok,
    login_result_ok,
    make_mro,
    make_pdf,
    make_snapshot,
    make_srd,
)

TOKEN = "app-test-token"
BASE = "http://127.0.0.1:8127"
HDRS = {"x-sia-token": TOKEN}

# Lokal: prod-101 mit <Jahr> → Mount "sia101-2020" (1:1 REQ-810-Fixture).
LICENSE_XML_2020 = LICENSE_XML.replace(
    "<Dateiname>101_2020_dSIA.srd</Dateiname>",
    "<Dateiname>101_2020_dSIA.srd</Dateiname>\n    <Jahr>2020</Jahr>",
)

MOUNT_ID = "sia101-2020"
CONCEPT = "sia:concept/tragende-konstruktion"
PDF = make_pdf(["Synthetischer Test."])
MARKER = "MARKER-NORMTEXT-GEHEIM-42"


class FakeLlm:
    """LLM-Double (G4: kein echter Endpunkt): liefert pro Prompt dieselbe Antwort."""

    def __init__(self, response: str | None) -> None:
        self._response = response
        self.prompts: list[tuple[str, str]] = []

    def generate(self, system: str, prompt: str) -> str | None:
        self.prompts.append((system, prompt))
        return self._response


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FastAPI]:
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "keychain"))
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    monkeypatch.delenv("GIBB_API_KEY", raising=False)
    # Hermetik: Core-Daten-Mount in den tmp-Pfad (statt Repo-data/, M8.6).
    monkeypatch.setenv("SIA_CORE_DATA_DIR", str(tmp_path))
    client = FakeSoapClient(
        login_result_ok(),
        make_mro(LICENSE_XML_2020),
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
        port=8127,
        shop=shop,
    )
    return TestClient(app, base_url=BASE), app


def _login(client: TestClient) -> None:
    res = client.post(
        "/v1/session/login",
        headers=HDRS,
        json={"provider": "sia", "customer": "kunde1", "password": "geheim", "device_id": "dev-1"},
    )
    assert res.status_code == 200, res.text


def _download(client: TestClient, product_id: str) -> None:
    res = client.post("/v1/documents/download", headers=HDRS, json={"product_id": product_id})
    assert res.status_code == 202, res.text
    job = cast("dict[str, object]", res.json()["job"])
    job_id = cast(str, job["id"])
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for item in client.get("/v1/jobs", headers=HDRS).json():
            if item["id"] == job_id and item["status"] in ("done", "error"):
                final = cast("dict[str, object]", item)
                assert final["status"] == "done", f"Download fertig, erhalten {final}"
                return
        time.sleep(0.02)
    raise AssertionError(f"Download-Job {job_id} nicht fertig nach 15 s")


def _import_concepts(app: FastAPI) -> None:
    """Katalog-Concepts importieren (1:1 REQ-810: Name de = Titel-Slug)."""
    store = app.state.store
    snapshot = make_snapshot(concept_ids=(CONCEPT,))
    assert store.import_snapshot(load_snapshot(snapshot)) == 1


def _configure_gibb(client: TestClient, *, key: str | None = None) -> None:
    """Provider gibb + Modell in den Einstellungen; Key optional via Keyring."""
    payload: dict[str, str] = {"provider": "gibb", "gibb_model": "qwen3"}
    if key is not None:
        payload["gibb_key"] = key
    res = client.put("/v1/settings", headers=HDRS, json=payload)
    assert res.status_code == 200, res.text


def _clause(text: str, **overrides: object) -> dict[str, object]:
    clause: dict[str, object] = {
        "number": "1",
        "text": text,
        "statement_type": "",
        "obligation": "",
        "summary": "",
        "concepts": [],
    }
    clause.update(overrides)
    return clause


def _write_draft(tmp_path: Path, clauses: list[dict[str, object]]) -> Path:
    draft: dict[str, object] = {
        "norm_id": MOUNT_ID,
        "norm": "SYN 9",
        "edition": "2020",
        "source_file": "document.pdf",
        "page_count": 1,
        "clauses": clauses,
    }
    norm_dir = tmp_path / "norms" / MOUNT_ID
    norm_dir.mkdir(parents=True, exist_ok=True)
    path = norm_dir / "document.draft.json"
    path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    return path


def _valid_llm_json(concepts: tuple[str, ...] = (CONCEPT,)) -> str:
    return json.dumps(
        {
            "statement_type": "requirement",
            "obligation": "muss",
            "summary": "Synthetische Zusammenfassung.",
            "concepts": list(concepts),
        }
    )


def _patch_llm(monkeypatch: pytest.MonkeyPatch, response: str | None) -> FakeLlm:
    """REQ-1303-Isolierung: Provider-Aufrösung ersetzt, Kern-Tool läuft echt."""
    fake = FakeLlm(response)
    monkeypatch.setattr(llm_complete, "_provider_from_env", lambda env: fake)
    return fake


def _call(client: TestClient, norm_id: str = "prod-101") -> httpx.Response:
    return cast(
        "httpx.Response",
        client.post("/v1/ingest/llm-complete", headers=HDRS, json={"norm_id": norm_id}),
    )


def _proposal_path(tmp_path: Path) -> Path:
    return tmp_path / "norms" / MOUNT_ID / "document.llm.json"


def test_req1303_api_requires_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = _call(client)
    assert res.status_code == 401


def test_req1303_api_unknown_document_is_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    _login(client)
    res = _call(client, "prod-999")
    assert res.status_code == 404
    assert "Unbekanntes lokales Dokument" in res.json()["error"]


def test_req1303_api_provider_not_gibb_is_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    _login(client)
    _download(client, "prod-101")
    res = _call(client)
    assert res.status_code == 400
    assert "gibb-Endpunkt" in res.json()["error"]


def test_req1303_api_missing_gibb_model_is_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    _login(client)
    _download(client, "prod-101")
    res = client.put("/v1/settings", headers=HDRS, json={"provider": "gibb"})
    assert res.status_code == 200, res.text
    res = _call(client)
    assert res.status_code == 400
    assert "gibb-Modell" in res.json()["error"]


def test_req1303_api_missing_key_is_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    _login(client)
    _download(client, "prod-101")
    _configure_gibb(client)  # kein Key: GIBB_API_KEY delenv, Keychain leer
    res = _call(client)
    assert res.status_code == 400
    assert "gibb-API-Key fehlt" in res.json()["error"]


def test_req1303_api_draft_missing_is_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    _login(client)
    _download(client, "prod-101")
    _configure_gibb(client, key="aus-keychain")
    res = _call(client)
    assert res.status_code == 400
    assert "Entwurf nicht gefunden" in res.json()["error"]


def test_req1303_api_happy_path_writes_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = _build(tmp_path, monkeypatch)
    _import_concepts(app)
    _login(client)
    _download(client, "prod-101")
    _write_draft(tmp_path, [_clause(text="Die Feuerwiderstandsdauer muss REI 90 erreichen.")])
    _configure_gibb(client)
    monkeypatch.setenv("GIBB_API_KEY", "umgebungs-key")
    _patch_llm(monkeypatch, _valid_llm_json())
    res = _call(client)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["norm_id"] == MOUNT_ID
    assert data["clauses_suggested"] == 1
    assert data["clauses_kept"] == 0
    assert data["proposal"] == "document.llm.json"
    assert "disclaimer" in data
    # G3: Vorschlag geschrieben; document.json und Review Queue unberührt
    proposal = _proposal_path(tmp_path)
    assert proposal.is_file()
    proposal_doc = json.loads(proposal.read_text(encoding="utf-8"))
    assert proposal_doc["norm_id"] == MOUNT_ID
    assert not (tmp_path / "norms" / MOUNT_ID / "document.json").is_file()
    assert sorted((tmp_path / "review_queue").glob("*.json")) == []
    # G4: Antwort enthält keinen Normtext
    assert "REI 90" not in res.text


def test_req1303_api_manually_filled_clause_kept_without_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = _build(tmp_path, monkeypatch)
    _import_concepts(app)
    _login(client)
    _download(client, "prod-101")
    _write_draft(
        tmp_path,
        [
            _clause(
                text="Die Feuerwiderstandsdauer muss REI 90 erreichen.",
                statement_type="requirement",
                obligation="muss",
                summary="Eigen",
                concepts=[CONCEPT],
            )
        ],
    )
    _configure_gibb(client, key="aus-keychain")
    fake = _patch_llm(monkeypatch, _valid_llm_json())
    res = _call(client)
    assert res.status_code == 200, res.text
    assert res.json()["clauses_suggested"] == 0
    assert res.json()["clauses_kept"] == 1
    assert fake.prompts == []  # manuell belegt → nichts an den Endpunkt


def test_req1303_api_g1_unknown_concept_is_400_and_no_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = _build(tmp_path, monkeypatch)
    _import_concepts(app)
    _login(client)
    _download(client, "prod-101")
    _write_draft(tmp_path, [_clause(text="Die Feuerwiderstandsdauer muss REI 90 erreichen.")])
    _configure_gibb(client, key="aus-keychain")
    _patch_llm(monkeypatch, _valid_llm_json(concepts=("sia:concept/fremd",)))
    res = _call(client)
    assert res.status_code == 400
    assert "nicht im Katalog" in res.json()["error"]
    assert not _proposal_path(tmp_path).is_file()  # KBOB: bei Fehler nichts geschrieben


def test_req1303_api_g4_no_normtext_in_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = _build(tmp_path, monkeypatch)
    _import_concepts(app)
    _login(client)
    _download(client, "prod-101")
    _write_draft(tmp_path, [_clause(text=f"Text mit {MARKER} für den G4-Check.")])
    _configure_gibb(client, key="aus-keychain")
    _patch_llm(monkeypatch, "kein JSON, nur Freitext")
    res = _call(client)
    assert res.status_code == 400
    assert "kein gültiges JSON-Objekt" in res.json()["error"]
    assert MARKER not in res.text
    assert not _proposal_path(tmp_path).is_file()


def test_req1303_api_key_from_keyring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Key-Auflösung über den Keyring (wie die Einstellungen-UI, G4)."""
    client, app = _build(tmp_path, monkeypatch)
    _import_concepts(app)
    _login(client)
    _download(client, "prod-101")
    _write_draft(tmp_path, [_clause(text="Die Feuerwiderstandsdauer muss REI 90 erreichen.")])
    _configure_gibb(client, key="aus-keychain")  # GIBB_API_KEY bleibt delenv
    _patch_llm(monkeypatch, _valid_llm_json())
    res = _call(client)
    assert res.status_code == 200, res.text
    assert res.json()["norm_id"] == MOUNT_ID
