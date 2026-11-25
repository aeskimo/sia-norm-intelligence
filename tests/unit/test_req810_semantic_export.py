"""REQ-810: Semantik-Export — ``sni/export/semantic.py`` + ``POST /v1/ingest/semantic-export``.

KATs 1:1 aus dem Java-Selftest ``SemanticExporterSelfTest`` (Norm-ID,
Ziffer-Erkennung, Modalverben, Aussageklassen, Konzept-Matching,
Export-End-to-End inkl. document.json-Rundweg). API-Endpunkt: 1:1
``IntelligencePanel.runExport`` — Konzepte aus dem Katalog,
Volltextseiten aus dem Index, Ingest in-process; Antwort nur IDs,
Zählungen und Gründe (kein Normtext, G4). Synthetische Testdaten (G4).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sni.app import api as app_api
from sni.app.server import build_app
from sni.app.shop import ShopState
from sni.catalog.snapshot import load_snapshot
from sni.export.semantic import (
    clause_numbers,
    export,
    matched_concepts,
    norm_id_for,
    normalize,
    obligation_of,
    statement_type_of,
)
from sni.search.page_source import PageSource
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
BASE = "http://127.0.0.1:8126"
HDRS = {"x-sia-token": TOKEN}

# Lokal: prod-101 mit <Jahr> (Ingest verlangt nicht-leere Edition; die
# gemeinsame Fixture hat kein Jahr → Norm-ID ohne Ausgabe).
LICENSE_XML_2020 = LICENSE_XML.replace(
    "<Dateiname>101_2020_dSIA.srd</Dateiname>",
    "<Dateiname>101_2020_dSIA.srd</Dateiname>\n    <Jahr>2020</Jahr>",
)

CONCEPTS: list[tuple[str, str]] = [
    ("sia:concept/tragende-konstruktion", "Tragende Konstruktion"),
    ("sia:concept/feuerwiderstandsklasse", "Feuerwiderstandsklasse"),
    ("sia:concept/brandabschnitt", "Brandabschnitt"),
]

PAGE_TEXT = """\
4.1 Brandschutzanforderungen
Tragende Konstruktion muss die Feuerwiderstandsdauer erfuellen.
Tabelle 1 Feuerwiderstandsklasse der Bauteile
REI 60 / REI 90
4.2 Nachweise
Die Feuerwiderstandsklasse wird nachgewiesen, siehe Ziffer 5.
4.3 Geltungsbereich
Diese Forderung gilt fur Neubauten.
4.4 Sonderfall
Die Anordnung kann abweichen.
"""

# PDF-Text für den API-Happy-Path (ASCII; pro Zeile ein PDF-Textzug).
NORM_PDF = make_pdf(
    [
        "4.1 Brandschutzanforderungen",
        "Tragende Konstruktion muss die Feuerwiderstandsdauer nachweisen.",
        "4.2 Nachweise",
        "Die Feuerwiderstandsklasse wird nachgewiesen, siehe Ziffer 5.",
    ]
)


# ------------------------------------------------------- KAT: Norm-ID (Java 1:1)


def test_req810_norm_id_with_year() -> None:
    assert norm_id_for("SIA 416", "2003") == "sia416-2003"


def test_req810_norm_id_without_year() -> None:
    assert norm_id_for("SIA 118", "") == "sia118"


def test_req810_norm_id_rejects_blank_number() -> None:
    with pytest.raises(ValueError):
        norm_id_for("   ", "2003")


# ------------------------------------------------ KAT: Ziffer-Erkennung (Java 1:1)


def test_req810_clause_recognition() -> None:
    numbers = clause_numbers(
        "4.1 Brandschutz\n"
        "Tragende Konstruktion muss REI 60 erfuellen.\n"
        "4.1.2 Details\n"
        "4 Einleitung\n"
        "2003 Ausgabe\n"
        "5 Schluss"
    )
    assert "4.1" in numbers
    assert "4.1.2" in numbers
    assert "4" not in numbers
    assert "2003" not in numbers


# ------------------------------------------------- KAT: Obligation (Java 1:1)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Tragende Konstruktion muss REI 60 erfuellen.", "muss"),
        ("Tragende Konstruktionen muessen nachgewiesen werden.", "muss"),
        ("Bauteile sollen geprueft werden.", "soll"),
        ("Dokumentationen sollen aufbewahrt werden.", "soll"),
        ("Die Abweichung kann zugelassen werden.", "kann"),
        ("Abweichungen koennen genehmigt werden.", "kann"),
        ("Das Bauteil kann abweichen, muss aber nachweisen.", "muss"),
        ("Das Muster zeigt die Anordnung.", "informativ"),
        ("Diese Forderung gilt fur Neubauten.", "informativ"),
    ],
)
def test_req810_obligation(text: str, expected: str) -> None:
    assert obligation_of(text) == expected


# ----------------------------------------------- KAT: Aussageklassen (Java 1:1)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Der Nachweis erfolgt gemass Tabelle 1, siehe Ziffer 5.", "reference"),
        ("Zusaetzliches vgl. SIA 112.", "reference"),
        ("Ausgenommen sind Kleingebaeude.", "exception"),
        ("Die Feuerwiderstandsklasse heisst die Klassifikation nach Dauer.", "definition"),
        ("Tragende Konstruktion muss die Feuerwiderstandsdauer erfuellen.", "requirement"),
        ("Diese Forderung gilt fur Neubauten.", None),
    ],
)
def test_req810_statement_type(text: str, expected: str | None) -> None:
    assert statement_type_of(text) == expected


# -------------------------------------------- KAT: Konzept-Matching (Java 1:1)


def test_req810_concept_name_found() -> None:
    text = normalize("Tragende Konstruktion muss die Feuerwiderstandsdauer erfuellen.")
    matched = matched_concepts(text, CONCEPTS)
    assert "sia:concept/tragende-konstruktion" in matched
    assert "sia:concept/brandabschnitt" not in matched


def test_req810_concept_word_boundary_no_subword() -> None:
    text = normalize("Feuerwiderstandsklassen werden gefordert.")
    assert matched_concepts(text, CONCEPTS) == []


def test_req810_concept_slug_found() -> None:
    text = normalize("Anforderung an die tragende-konstruktion.")
    assert "sia:concept/tragende-konstruktion" in matched_concepts(text, CONCEPTS)


def test_req810_concept_typo_no_match() -> None:
    assert matched_concepts(normalize("siehe feuuerwiderstandsfaehigkeit"), CONCEPTS) == []


# ----------------------------------------------- KAT: Export End-to-End (Java 1:1)


def test_req810_export_end_to_end(tmp_path: Path) -> None:
    pages = [PageSource("doc-1", "SIA 416", "2003", 1, "", PAGE_TEXT)]
    result = export(tmp_path / "norms", "SIA 416", "2003", pages, CONCEPTS)
    assert result.norm_id == "sia416-2003"
    assert result.clauses == 2
    assert result.tables == 1
    assert result.skipped == 2
    assert len(result.skipped_reasons) == 2
    assert "4.3" in result.skipped_reasons[0]
    assert "4.4" in result.skipped_reasons[1]

    # document.json-Rundweg (Java: Strukturprüfung über den JSON-Parser)
    document = cast(
        "dict[str, object]", json.loads(result.document_file.read_text(encoding="utf-8"))
    )
    assert document["norm"] == "SIA 416"
    assert document["norm_id"] == "sia416-2003"
    assert document["edition"] == "2003"
    clauses = cast("list[dict[str, object]]", document["clauses"])
    assert len(clauses) == 2
    c1 = clauses[0]
    assert c1["number"] == "4.1"
    assert c1["statement_type"] == "requirement"
    assert c1["obligation"] == "muss"
    assert "sia:concept/tragende-konstruktion" in cast("list[str]", c1["concepts"])
    tables = cast("list[dict[str, object]]", c1["tables"])
    assert len(tables) == 1  # Tabelle hängt an der vorangehenden Ziffer
    assert tables[0]["number"] == "T 1"
    assert tables[0]["statement_type"] == "classification"
    c2 = clauses[1]
    assert c2["number"] == "4.2"
    assert c2["statement_type"] == "reference"


def test_req810_export_table_before_any_clause_is_skipped(tmp_path: Path) -> None:
    pages = [
        PageSource(
            "doc-1",
            "SIA 416",
            "2003",
            1,
            "",
            "Tabelle 1 Feuerwiderstandsklasse der Bauteile\nREI 60 / REI 90\n",
        )
    ]
    result = export(tmp_path / "norms", "SIA 416", "2003", pages, CONCEPTS)
    assert result.clauses == 0
    assert result.tables == 0
    assert result.skipped == 1
    assert result.skipped_reasons == ["1 Tabelle(n) ohne vorangehende Ziffer übersprungen"]


# ------------------------------------------------------------------- App-Endpunkt


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FastAPI]:
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "keychain"))
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    monkeypatch.delenv("GIBB_API_KEY", raising=False)
    # Hermetik: Norm-Mount und Review-Queue in den tmp-Pfad (statt Repo-data/).
    monkeypatch.setattr(app_api, "DEFAULT_NORMS_DIR", tmp_path / "norms")
    monkeypatch.setattr(app_api, "DEFAULT_QUEUE_DIR", tmp_path / "queue")
    client = FakeSoapClient(
        login_result_ok(),
        make_mro(LICENSE_XML_2020),
        document_result_ok("101_2020_dSIA.srd"),
        make_srd("prod-101", NORM_PDF),
    )
    shop = ShopState(client_factory=lambda profile: client, data_dir=tmp_path / "data")
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token=TOKEN,
        mode="window",
        port=8126,
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


def _wait_for_job(client: TestClient, job_id: str, wanted: set[str]) -> dict[str, object]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        jobs = client.get("/v1/jobs", headers=HDRS).json()
        for job in jobs:
            if job["id"] == job_id and job["status"] in wanted:
                return cast("dict[str, object]", job)
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} nicht in Status {sorted(wanted)} nach 15 s")


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


def _import_concepts(app: FastAPI) -> None:
    """Katalog-Concepts importieren (Name ``de`` = Titel-Slug, 1:1 conftest)."""
    store = app.state.store
    snapshot = make_snapshot(
        concept_ids=(
            "sia:concept/tragende-konstruktion",
            "sia:concept/feuerwiderstandsklasse",
        )
    )
    assert store.import_snapshot(load_snapshot(snapshot)) == 2


def test_req810_api_requires_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.post("/v1/ingest/semantic-export", headers=HDRS, json={"norm_id": "prod-101"})
    assert res.status_code == 401


def test_req810_api_unknown_document_is_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    _login(client)
    res = client.post("/v1/ingest/semantic-export", headers=HDRS, json={"norm_id": "prod-999"})
    assert res.status_code == 404
    assert "Unbekanntes lokales Dokument" in res.json()["error"]


def test_req810_api_empty_catalog_is_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    _login(client)
    _download(client, "prod-101")
    _analyze(client, "prod-101")
    res = client.post("/v1/ingest/semantic-export", headers=HDRS, json={"norm_id": "prod-101"})
    assert res.status_code == 400
    assert "Katalog ist leer" in res.json()["error"]


def test_req810_api_no_fulltext_pages_is_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = _build(tmp_path, monkeypatch)
    _import_concepts(app)
    _login(client)
    _download(client, "prod-101")
    # keine Analyse → keine Volltextseiten
    res = client.post("/v1/ingest/semantic-export", headers=HDRS, json={"norm_id": "prod-101"})
    assert res.status_code == 400
    assert "Keine Volltextseiten" in res.json()["error"]


def test_req810_api_happy_path_exports_and_ingests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = _build(tmp_path, monkeypatch)
    _import_concepts(app)
    _login(client)
    _download(client, "prod-101")
    _analyze(client, "prod-101")
    res = client.post("/v1/ingest/semantic-export", headers=HDRS, json={"norm_id": "prod-101"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["norm_id"] == "sia101-2020"
    candidates = cast("list[str]", data["candidates"])
    assert len(candidates) == 2
    assert all(":statement/" in c for c in candidates)
    assert data["skipped"] == []
    assert data["gaps"] == []
    assert "disclaimer" in data
    # document.json im (gepatchten) Norm-Mount
    document_file = tmp_path / "norms" / "sia101-2020" / "document.json"
    assert document_file.is_file()
    # Ingest in-process: Kandidaten stehen in der (gepatchten) Review-Queue
    queue_files = sorted((tmp_path / "queue").glob("*.json"))
    assert len(queue_files) == 2
    queue_candidate = json.loads(queue_files[0].read_text(encoding="utf-8"))
    assert queue_candidate["review_status"] == "candidate"
    # G4: Antwort enthält keine Normtexte (nur IDs/Zählungen/Gründe)
    assert "Feuerwiderstandsdauer" not in res.text
