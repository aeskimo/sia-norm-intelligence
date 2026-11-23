"""REQ-501: POST /v1/check liefert pro Regel pass|fail|insufficient_data.

ADR-0004: Konsistenzprüfung (``pass`` ≠ Normkonformität); REQ-502: fehlende
Projektdaten erzeugen GapReports im selben Ergebnis.
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sni.api.main import create_app
from sni.core.schemas import make_validator

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_RULE = ROOT / "tests" / "benchmark" / "knowledge" / "sia_rule_syn1-2020_gf-summe.json"
A = "sia:concept/teilsflaeche-a"
B = "sia:concept/teilsflaeche-b"
OUT = "sia:concept/gesamtflaeche"
CONSISTENT_DATA: dict[str, dict[str, object]] = {
    A: {"value": 100, "unit": "m2"},
    B: {"value": 50, "unit": "m2"},
    OUT: {"value": 150, "unit": "m2"},
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """App mit der approved Benchmark-Regel im tmp rules-Verzeichnis."""
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    shutil.copy(BENCHMARK_RULE, rules_dir / BENCHMARK_RULE.name)
    app = create_app(tmp_path / "catalog.db", tmp_path / "keine-wissensbasis", rules_dir=rules_dir)
    try:
        yield TestClient(app)
    finally:
        app.state.store.close()


def test_req501_api_check_pass_is_schema_conformant(client: TestClient) -> None:
    res = client.post("/v1/check", json={"project_data": CONSISTENT_DATA})
    assert res.status_code == 200
    body = res.json()
    make_validator("check_result.schema.json").validate(body)
    entry = body["checks"][0]
    assert entry["status"] == "pass"
    assert entry["value"] == 150.0
    assert entry["claimed"] == 150.0
    assert body["gaps"] == []
    assert body["disclaimer"]  # G6


def test_req501_api_check_inconsistent_data_fails(client: TestClient) -> None:
    data = dict(CONSISTENT_DATA)
    data[OUT] = {"value": 160, "unit": "m2"}
    res = client.post("/v1/check", json={"project_data": data})
    assert res.status_code == 200
    body = res.json()
    entry = body["checks"][0]
    assert entry["status"] == "fail"
    assert "Inkonsistent" in entry["reason"]


def test_req501_api_check_missing_data_insufficient_with_gaps(client: TestClient) -> None:
    data = {A: {"value": 100, "unit": "m2"}, OUT: {"value": 150, "unit": "m2"}}
    res = client.post("/v1/check", json={"project_data": data})
    assert res.status_code == 200
    body = res.json()
    make_validator("check_result.schema.json").validate(body)  # inkl. $ref gap_report
    entry = body["checks"][0]
    assert entry["status"] == "insufficient_data"
    assert entry["missing_inputs"] == [B]
    assert len(body["gaps"]) == 1
    assert body["gaps"][0]["gap_type"] == "missing_project_data"


def test_req501_api_check_empty_project_data_is_200(client: TestClient) -> None:
    res = client.post("/v1/check", json={"project_data": {}})
    assert res.status_code == 200
    body = res.json()
    make_validator("check_result.schema.json").validate(body)
    assert body["checks"][0]["status"] == "insufficient_data"
    assert len(body["gaps"]) == 2  # A und B fehlen
    # fehlendes Feld ist äquivalent (Pydantic-Default None)
    assert client.post("/v1/check", json={}).status_code == 200


def test_req501_api_check_invalid_project_data_is_400(client: TestClient) -> None:
    bad = {A: {"value": "viel", "unit": "m2"}}
    res = client.post("/v1/check", json={"project_data": bad})
    assert res.status_code == 400
    assert "value" in res.json()["error"]
    assert res.json()["disclaimer"]  # G6 auch bei Fehler


def test_req501_api_check_wrong_project_data_type_is_422(client: TestClient) -> None:
    res = client.post("/v1/check", json={"project_data": "kein-objekt"})
    assert res.status_code == 422


def test_req501_api_check_unloadable_rules_is_500(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "broken_rule.json").write_text("{", encoding="utf-8")
    app = create_app(tmp_path / "catalog.db", tmp_path / "leer", rules_dir=rules_dir)
    try:
        res = TestClient(app).post("/v1/check", json={})
        assert res.status_code == 500
        assert "broken_rule.json" in res.json()["error"]
        assert res.json()["disclaimer"]  # G6
    finally:
        app.state.store.close()
