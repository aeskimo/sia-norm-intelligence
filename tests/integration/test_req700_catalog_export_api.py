"""REQ-700: GET /v1/export/catalog liefert JSON und Turtle/SKOS (ADR-0005)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sni.api.main import create_app
from sni.catalog.snapshot import load_snapshot
from sni.core.schemas import make_validator
from tests.conftest import make_snapshot

SNAPSHOT_ID = "sia:catalog/test@1.0.0"
OTHER_SNAPSHOT_ID = "sia:catalog/other@2.0.0"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """App mit zwei Snapshots (2 + 1 Concept) im tmp-Katalog."""
    app = create_app(tmp_path / "catalog.db", tmp_path / "keine-wissensbasis")
    store = app.state.store
    store.import_snapshot(load_snapshot(make_snapshot()))
    store.import_snapshot(load_snapshot(make_snapshot(OTHER_SNAPSHOT_ID, ("sia:concept/other-x",))))
    try:
        yield TestClient(app)
    finally:
        store.close()


def test_req700_api_json_export_is_schema_conformant(client: TestClient) -> None:
    res = client.get("/v1/export/catalog", params={"format": "json"})
    assert res.status_code == 200
    body = res.json()
    assert body["disclaimer"]  # G6
    assert len(body["concepts"]) == 3
    validator = make_validator("concept.schema.json")
    for concept in body["concepts"]:
        validator.validate(concept)


def test_req700_api_json_export_is_default_format(client: TestClient) -> None:
    res = client.get("/v1/export/catalog")
    assert res.status_code == 200
    assert res.json()["concepts"]


def test_req700_api_json_export_snapshot_filter(client: TestClient) -> None:
    res = client.get("/v1/export/catalog", params={"format": "json", "snapshot": OTHER_SNAPSHOT_ID})
    assert res.status_code == 200
    body = res.json()
    assert [c["id"] for c in body["concepts"]] == ["sia:concept/other-x"]


def test_req700_api_ttl_export_structure(client: TestClient) -> None:
    res = client.get("/v1/export/catalog", params={"format": "ttl"})
    assert res.status_code == 200
    assert "text/turtle" in res.headers["content-type"]
    text = res.text
    assert "@prefix sia: <https://sia-norm-intelligence.dev/sia/> ." in text
    assert "a skos:ConceptScheme ;" in text
    assert "https://sia-norm-intelligence.dev/sia/concept/geschossflaeche" in text
    assert "Keine Rechtsauskunft." in text  # G6


def test_req700_api_ttl_export_snapshot_filter(client: TestClient) -> None:
    res = client.get("/v1/export/catalog", params={"format": "ttl", "snapshot": OTHER_SNAPSHOT_ID})
    assert res.status_code == 200
    assert "other-x" in res.text
    assert "geschossflaeche" not in res.text


def test_req700_api_unknown_format_is_400(client: TestClient) -> None:
    res = client.get("/v1/export/catalog", params={"format": "xml"})
    assert res.status_code == 400
    assert res.json()["disclaimer"]  # G6 auch bei Fehler


def test_req700_api_unknown_snapshot_is_400(client: TestClient) -> None:
    res = client.get(
        "/v1/export/catalog", params={"format": "json", "snapshot": "sia:catalog/x@0.0.1"}
    )
    assert res.status_code == 400
    assert "nicht im Katalog" in res.json()["error"]
    assert res.json()["disclaimer"]
