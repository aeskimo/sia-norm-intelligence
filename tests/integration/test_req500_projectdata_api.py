"""REQ-500: POST /v1/projectdata normalisiert CSV/IFC-Uploads (ADR-0006).

Die Uploads werden von den getesteten REQ-500-Adapters gelesen (csv_adapter,
ifc_adapter); die Antwort ist gegen ``project_values.schema.json`` validiert
(DoD, AGENTS.md §6). IFC verlangt ein Quantity-Mapping (explizit oder aus
dem Katalog abgeleitet; G5: ohne Mapping wird abgelehnt, nie geraten).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.api
import pytest
from fastapi.testclient import TestClient

from sni.api.main import create_app
from sni.catalog.snapshot import load_snapshot
from sni.core.schemas import make_validator

A = "sia:concept/teilsflaeche-a"
B = "sia:concept/teilsflaeche-b"
OUT = "sia:concept/gesamtflaeche"

CSV_VALID = f"concept,value,unit\n{A},100,m2\n{B},50,m2\n"
CSV_BROKEN = (
    "concept,value,unit\n"
    "sia:concept/a,viele,m2\n"  # keine Zahl
    ",1,m2\n"  # Concept fehlt
)

_SNAPSHOT: dict[str, object] = {
    "snapshot_id": "test-projectdata@1.0.0",
    "concepts": [
        {
            "id": OUT,
            "name": {"de": "Gesamtfläche"},
            "definition": {"de": "Synthetischer Testbegriff (Platzhalter, kein Norminhalt)."},
            "unit": "m2",
            "mappings": {
                "ifc": {
                    "entity": "IfcSpace",
                    "property_set": "Pset_SpaceCommon",
                    "base_name": "NetFloorArea",
                }
            },
            "catalog_snapshot": "test-projectdata@1.0.0",
        },
        {
            "id": A,
            "name": {"de": "Teilsfläche A"},
            "definition": {"de": "Synthetischer Testbegriff (Platzhalter, kein Norminhalt)."},
            "unit": "m2",
            "mappings": {
                "ifc": {
                    "entity": "IfcSpace",
                    "property_set": "Pset_SpaceCommon",
                    "base_name": "Area",
                }
            },
            "catalog_snapshot": "test-projectdata@1.0.0",
        },
    ],
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """App mit IFC-mapping-tragenden Concepts im tmp-Katalog (Konvention: app.state.store)."""
    app = create_app(
        tmp_path / "catalog.db",
        tmp_path / "keine-wissensbasis",
        rules_dir=tmp_path / "keine-regeln",
    )
    try:
        app.state.store.import_snapshot(load_snapshot(_SNAPSHOT))
        yield TestClient(app)
    finally:
        app.state.store.close()


def _bare_model() -> Any:
    """IFC4-Modell mit Project, aber ohne IfcUnitAssignment."""
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="Testprojekt")
    return f


def _base_model() -> Any:
    """Modell mit IfcUnitAssignment (METRE für LENGTH und AREA)."""
    f = _bare_model()
    length = ifcopenshell.api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT")
    area = ifcopenshell.api.run("unit.add_si_unit", f, unit_type="AREAUNIT")
    ifcopenshell.api.run("unit.assign_unit", f, units=[length, area])
    return f


def _add_wall(f: Any, name: str, quantities: dict[str, float]) -> Any:
    wall = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcWall", name=name)
    if quantities:
        qto = ifcopenshell.api.run("pset.add_qto", f, product=wall, name="Qto_WallBaseQuantities")
        ifcopenshell.api.run("pset.edit_qto", f, qto=qto, properties=quantities)
    return wall


def _write_model(tmp_path: Path, model: Any, name: str = "modell.ifc") -> Path:
    path = tmp_path / name
    model.write(str(path))
    return path


def _ifc_with_areas(tmp_path: Path, areas: dict[str, float]) -> Path:
    """IFC4-Modell (m/m2-Einheiten) mit einer Wand und Flächen-Mengen."""
    f = _base_model()
    _add_wall(f, "Wand 1", areas)
    return _write_model(tmp_path, f)


def _ifc_without_units(tmp_path: Path) -> Path:
    """IFC4-Modell mit Flächen-Menge, aber ohne IfcUnitAssignment."""
    f = _bare_model()
    _add_wall(f, "Wand 1", {"NetFloorArea": 150.0})
    return _write_model(tmp_path, f, name="keine-einheiten.ifc")


def test_req500_api_csv_upload_roundtrip(client: TestClient) -> None:
    res = client.post(
        "/v1/projectdata", files={"file": ("flaechen.csv", CSV_VALID.encode(), "text/csv")}
    )
    assert res.status_code == 200
    body = res.json()
    make_validator("project_values.schema.json").validate(body)
    assert body["format"] == "csv"
    assert body["file"] == "flaechen.csv"
    assert body["quantity_mapping"] is None
    assert body["disclaimer"]  # G6
    values = {v["concept"]: v for v in body["values"]}
    assert values[A]["value"] == 100.0
    assert values[A]["unit"] == "m2"
    assert values[A]["provenance"] == {"file": "flaechen.csv", "locator": "Zeile 2"}
    assert values[B]["value"] == 50.0
    assert values[B]["provenance"]["locator"] == "Zeile 3"


def test_req500_api_csv_broken_upload_reports_all_errors(client: TestClient) -> None:
    res = client.post(
        "/v1/projectdata", files={"file": ("kaputt.csv", CSV_BROKEN.encode(), "text/csv")}
    )
    assert res.status_code == 400
    body = res.json()
    # KBOB: beide Fehler im Bericht, nicht nur der erste
    assert "ist keine Zahl" in body["error"]
    assert "Concept fehlt" in body["error"]
    assert body["disclaimer"]


def test_req500_api_unknown_extension_rejected(client: TestClient) -> None:
    res = client.post(
        "/v1/projectdata", files={"file": ("daten.txt", b"concept,value,unit\n", "text/plain")}
    )
    assert res.status_code == 400
    assert "Format unbekannt" in res.json()["error"]


def test_req500_api_too_large_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sni.projectdata.upload.MAX_UPLOAD_BYTES", 10)
    res = client.post(
        "/v1/projectdata",
        files={"file": ("gross.csv", b"concept,value,unit\n" + b"x" * 20, "text/csv")},
    )
    assert res.status_code == 400
    assert "zu gross" in res.json()["error"]


def test_req500_api_empty_csv_upload_is_empty_200(client: TestClient) -> None:
    res = client.post("/v1/projectdata", files={"file": ("leer.csv", b"", "text/csv")})
    assert res.status_code == 200
    assert res.json()["values"] == []


def test_req500_api_missing_file_field_is_422(client: TestClient) -> None:
    res = client.post("/v1/projectdata")
    assert res.status_code == 422


def test_req500_api_ifc_upload_with_explicit_mapping(client: TestClient, tmp_path: Path) -> None:
    path = _ifc_with_areas(tmp_path, {"NetFloorArea": 150.0, "Area": 100.0, "WallArea": 50.0})
    mapping = {"NetFloorArea": OUT, "Area": A, "WallArea": B}
    res = client.post(
        "/v1/projectdata",
        files={"file": ("modell.ifc", path.read_bytes(), "application/octet-stream")},
        data={"quantity_mapping": json.dumps(mapping)},
    )
    assert res.status_code == 200
    body = res.json()
    make_validator("project_values.schema.json").validate(body)
    assert body["format"] == "ifc"
    assert body["file"] == "modell.ifc"
    assert body["quantity_mapping"] == mapping
    assert body["disclaimer"]
    values = {v["concept"]: v for v in body["values"]}
    assert values[OUT]["value"] == 150.0
    assert values[A]["value"] == 100.0
    assert values[B]["value"] == 50.0
    assert all(v["unit"] == "m2" for v in body["values"])
    # Herkunft: GUID des Bauelements (eine Wand, drei Mengen)
    assert len({v["provenance"]["locator"] for v in body["values"]}) == 1


def test_req500_api_ifc_mapping_derived_from_catalog(client: TestClient, tmp_path: Path) -> None:
    path = _ifc_with_areas(tmp_path, {"NetFloorArea": 150.0, "Area": 100.0, "WallArea": 50.0})
    res = client.post(
        "/v1/projectdata",
        files={"file": ("modell.ifc", path.read_bytes(), "application/octet-stream")},
    )
    assert res.status_code == 200
    body = res.json()
    # Aus dem Katalog abgeleitet (2 Concepts mit IFC-Mapping); WallArea bleibt unmapped
    assert body["quantity_mapping"] == {"NetFloorArea": OUT, "Area": A}
    values = {v["concept"]: v for v in body["values"]}
    assert set(values) == {OUT, A}
    assert values[OUT]["value"] == 150.0
    assert values[A]["value"] == 100.0


def test_req500_api_ifc_without_mapping_rejected(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / "leer.db",
        tmp_path / "keine-wissensbasis",
        rules_dir=tmp_path / "keine-regeln",
    )
    try:
        client = TestClient(app)
        path = _ifc_with_areas(tmp_path, {"NetFloorArea": 150.0})
        res = client.post(
            "/v1/projectdata",
            files={"file": ("modell.ifc", path.read_bytes(), "application/octet-stream")},
        )
    finally:
        app.state.store.close()
    assert res.status_code == 400
    assert "Mapping" in res.json()["error"]


def test_req500_api_ifc_invalid_mapping_json_rejected(client: TestClient, tmp_path: Path) -> None:
    path = _ifc_with_areas(tmp_path, {"NetFloorArea": 150.0})
    res = client.post(
        "/v1/projectdata",
        files={"file": ("modell.ifc", path.read_bytes(), "application/octet-stream")},
        data={"quantity_mapping": "{kaputt"},
    )
    assert res.status_code == 400
    assert "JSON" in res.json()["error"]


def test_req500_api_ifc_invalid_mapping_shape_rejected(client: TestClient, tmp_path: Path) -> None:
    path = _ifc_with_areas(tmp_path, {"NetFloorArea": 150.0})
    for bad in (json.dumps(["NetFloorArea"]), json.dumps({"NetFloorArea": 1})):
        res = client.post(
            "/v1/projectdata",
            files={"file": ("modell.ifc", path.read_bytes(), "application/octet-stream")},
            data={"quantity_mapping": bad},
        )
        assert res.status_code == 400
        assert "JSON-Objekt" in res.json()["error"]


def test_req500_api_ifc_invalid_file_rejected(client: TestClient) -> None:
    res = client.post(
        "/v1/projectdata",
        files={"file": ("kaputt.ifc", b"definitiv kein IFC", "application/octet-stream")},
        data={"quantity_mapping": json.dumps({"NetFloorArea": OUT})},
    )
    assert res.status_code == 400
    assert "ungültige IFC" in res.json()["error"]


def test_req500_api_ifc_without_unit_assignment_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    path = _ifc_without_units(tmp_path)
    res = client.post(
        "/v1/projectdata",
        files={"file": ("modell.ifc", path.read_bytes(), "application/octet-stream")},
        data={"quantity_mapping": json.dumps({"NetFloorArea": OUT})},
    )
    assert res.status_code == 400
    assert "keine Einheit" in res.json()["error"]
