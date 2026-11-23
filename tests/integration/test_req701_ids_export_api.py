"""REQ-701: POST /v1/export/ids liefert Regel als IDS-Spezifikation, sonst GapReport."""

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sni.api.main import create_app
from sni.catalog.snapshot import load_snapshot

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_RULE = ROOT / "tests" / "benchmark" / "knowledge" / "sia_rule_syn1-2020_gf-summe.json"

SNAPSHOT_ID = "sia:catalog/ids@1.0.0"
PLACEHOLDER = "Synthetischer Testbegriff (Platzhalter, kein Norminhalt)."
IFC = {"entity": "IfcSpace", "property_set": "Pset_SpaceCommon", "base_name": "NetFloorArea"}
ZONE_A = "sia:concept/zona-a"
ZONE_B = "sia:concept/zona-b"
ZONE_OUT = "sia:concept/zona-gesamt"
ZONE_RULE = "sia:rule/syn1-2020/zone-summe"
GF_RULE = "sia:rule/syn1-2020/gf-summe"


def _concept(concept_id: str, ifc: dict[str, str] | None) -> dict[str, object]:
    """Synthetisches Concept (G4: Platzhalter-Werte, kein Norminhalt)."""
    concept: dict[str, object] = {
        "id": concept_id,
        "name": {"de": concept_id.rsplit("/", 1)[-1].replace("-", " ").title()},
        "definition": {"de": PLACEHOLDER},
        "catalog_snapshot": SNAPSHOT_ID,
    }
    if ifc is not None:
        concept["mappings"] = {"ifc": ifc}
    return concept


def _zone_rule(rule_id: str = ZONE_RULE, status: str = "approved") -> dict[str, object]:
    rule: dict[str, object] = {
        "id": rule_id,
        "derived_from": ["sia:statement/syn1-2020/4.1/1"],
        "inputs": [
            {"concept": ZONE_A, "unit": "m2"},
            {"concept": ZONE_B, "unit": "m2"},
        ],
        "output": {"concept": ZONE_OUT, "unit": "m2"},
        "expression": "zona_a + zona_b",
        "applicability": "Synthetische Bedingung (Platzhalter, kein Norminhalt).",
        "review_status": status,
    }
    if status == "approved":
        rule["approved_by"] = "Fachperson Test (synthetisch)"
        rule["approved_at"] = "2026-11-23"
    return rule


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """App mit 2 Regeln (zone-summe abbildbar, gf-summe -> Gap) und 6 Catalog-Concepts."""
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "sia_rule_syn1-2020_zone-summe.json").write_text(
        json.dumps(_zone_rule(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutil.copy(BENCHMARK_RULE, rules_dir)  # Dateiname = sanierte Regel-ID
    app = create_app(tmp_path / "catalog.db", tmp_path / "keine-wissensbasis", rules_dir=rules_dir)
    store = app.state.store
    store.import_snapshot(
        load_snapshot(
            {
                "snapshot_id": SNAPSHOT_ID,
                "concepts": [
                    _concept(ZONE_A, IFC),
                    _concept(ZONE_B, IFC),
                    _concept(ZONE_OUT, IFC),
                    _concept("sia:concept/teilsflaeche-a", None),
                    _concept("sia:concept/teilsflaeche-b", None),
                    _concept("sia:concept/gesamtflaeche", None),
                ],
            }
        )
    )
    try:
        yield TestClient(app)
    finally:
        store.close()


def test_req701_api_ids_export_default_all_approved(client: TestClient) -> None:
    res = client.post("/v1/export/ids", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["disclaimer"]  # G6
    xml = body["ids_xml"]
    assert xml  # zone-summe ist abbildbar
    assert 'ifcVersion="IFC4"' in xml
    assert f'name="{ZONE_RULE}"' in xml
    assert GF_RULE not in xml  # nicht abbildbar -> kein Specification
    gaps = body["gaps"]
    assert len(gaps) == 1
    assert gaps[0]["gap_type"] == "not_ids_expressible"
    assert gaps[0]["target_layer"] == "mapping"
    assert gaps[0]["evidence"] == [GF_RULE]
    assert gaps[0]["priority"] == "medium"
    assert gaps[0]["status"] == "open"
    assert str(gaps[0]["id"]).startswith("GAP-")


def test_req701_api_ids_export_explicit_rule_ids(client: TestClient) -> None:
    res = client.post("/v1/export/ids", json={"rule_ids": [ZONE_RULE]})
    assert res.status_code == 200
    body = res.json()
    assert f'name="{ZONE_RULE}"' in body["ids_xml"]
    assert body["gaps"] == []


def test_req701_api_ids_export_only_gap_rule_yields_null_xml(client: TestClient) -> None:
    res = client.post("/v1/export/ids", json={"rule_ids": [GF_RULE]})
    assert res.status_code == 200
    body = res.json()
    assert body["ids_xml"] is None
    assert [gap["evidence"] for gap in body["gaps"]] == [[GF_RULE]]


def test_req701_api_ids_export_unknown_rule_id_is_400(client: TestClient) -> None:
    res = client.post("/v1/export/ids", json={"rule_ids": ["sia:rule/unknown/x"]})
    assert res.status_code == 400
    assert "unknown/x" in res.json()["error"]
    assert res.json()["disclaimer"]  # G6 auch bei Fehler


def test_req701_api_ids_export_non_approved_rule_id_is_400(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "sia_rule_syn1-2020_zone-review.json").write_text(
        json.dumps(_zone_rule("sia:rule/syn1-2020/zone-review", "reviewed"), ensure_ascii=False),
        encoding="utf-8",
    )
    app = create_app(tmp_path / "catalog.db", tmp_path / "leer", rules_dir=rules_dir)
    try:
        res = TestClient(app).post(
            "/v1/export/ids", json={"rule_ids": ["sia:rule/syn1-2020/zone-review"]}
        )
    finally:
        app.state.store.close()
    assert res.status_code == 400
    assert "reviewed" in res.json()["error"]
    assert res.json()["disclaimer"]


def test_req701_api_ids_export_wrong_rule_ids_type_is_422(client: TestClient) -> None:
    res = client.post("/v1/export/ids", json={"rule_ids": "x"})
    assert res.status_code == 422


def test_req701_api_ids_export_unloadable_rules_is_500(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "broken_rule.json").write_text("{", encoding="utf-8")
    app = create_app(tmp_path / "catalog.db", tmp_path / "leer", rules_dir=rules_dir)
    try:
        res = TestClient(app).post("/v1/export/ids", json={})
        assert res.status_code == 500
        assert "broken_rule.json" in res.json()["error"]
        assert res.json()["disclaimer"]  # G6
    finally:
        app.state.store.close()
