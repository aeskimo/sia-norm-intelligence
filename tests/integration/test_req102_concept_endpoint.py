"""REQ-102: GET /v1/concepts/{id} liefert Concept inkl. Relationen."""

from pathlib import Path

from fastapi.testclient import TestClient

from sni.api.main import create_app
from sni.catalog.snapshot import load_snapshot
from tests.conftest import CONCEPT_A, CONCEPT_B


def test_req102_concept_incl_relations(
    tmp_path: Path, snapshot_with_relations: dict[str, object]
) -> None:
    app = create_app(tmp_path / "catalog.db")
    try:
        app.state.store.import_snapshot(load_snapshot(snapshot_with_relations))
        client = TestClient(app)
        res = client.get(f"/v1/concepts/{CONCEPT_A}")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == CONCEPT_A
        assert body["relations"] == [{"type": "related_to", "target": CONCEPT_B}]
        assert body["disclaimer"]  # Guardrail G6: jede API-Antwort trägt Disclaimer
    finally:
        app.state.store.close()


def test_req102_unknown_concept_is_404(
    tmp_path: Path, synthetic_snapshot: dict[str, object]
) -> None:
    app = create_app(tmp_path / "catalog.db")
    try:
        app.state.store.import_snapshot(load_snapshot(synthetic_snapshot))
        client = TestClient(app)
        res = client.get("/v1/concepts/sia:concept/nicht-dort")
        assert res.status_code == 404
        assert "disclaimer" in res.json()  # G6
    finally:
        app.state.store.close()
