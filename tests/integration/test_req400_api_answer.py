"""REQ-400: POST /v1/answer liefert schemakonforme Answers.

REQ-403: Jede Antwort enthält Norm + Ausgabe + Ziffer (``sources``) oder eine
begründete Enthaltung (``missing_information``).
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from sni.api.main import create_app
from sni.catalog.snapshot import load_snapshot
from sni.core.schemas import make_validator

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = ROOT / "tests" / "benchmark"
DEFINITION_QUESTION = "Was ist die Gesamtfläche?"
CALCULATION_QUESTION = "Wie gross ist die Gesamtfläche für die gegebenen Projektwerte?"
FULL_PROJECT_DATA: dict[str, dict[str, object]] = {
    "sia:concept/teilsflaeche-a": {"value": 100, "unit": "m2"},
    "sia:concept/teilsflaeche-b": {"value": 50, "unit": "m2"},
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """App mit Benchmark-Katalog und Benchmark-Wissensbasis."""
    app = create_app(tmp_path / "catalog.db", BENCHMARK_DIR / "knowledge")
    try:
        raw: object = json.loads(
            (BENCHMARK_DIR / "catalog_snapshot.json").read_text(encoding="utf-8")
        )
        assert isinstance(raw, dict)
        app.state.store.import_snapshot(load_snapshot(raw))
        yield TestClient(app)
    finally:
        app.state.store.close()


def _check_req403(body: dict[str, object]) -> None:
    """REQ-403: Fundstelle (norm + edition + clause) oder begründete Enthaltung."""
    sources = cast(list[object], body.get("sources") or [])
    missing = cast(list[object], body.get("missing_information") or [])
    assert sources or missing, "weder Fundstelle noch begründete Enthaltung (REQ-403)"
    if sources:
        for source in sources:
            assert isinstance(source, dict)
            for field_name in ("norm", "edition", "clause"):
                value = source.get(field_name)
                assert isinstance(value, str) and value.strip()


def test_req400_api_answer_is_schema_conformant(client: TestClient) -> None:
    res = client.post("/v1/answer", json={"question": DEFINITION_QUESTION})
    assert res.status_code == 200
    body = res.json()
    # REQ-400: schemakonforme Answer
    make_validator("answer.schema.json").validate(body)
    assert body["answer_class"] == "normativ_belegt"
    assert body["question"] == DEFINITION_QUESTION
    assert body["disclaimer"]  # G6
    _check_req403(body)


def test_req400_api_answer_with_project_data_is_derived(client: TestClient) -> None:
    res = client.post(
        "/v1/answer",
        json={"question": CALCULATION_QUESTION, "project_data": FULL_PROJECT_DATA},
    )
    assert res.status_code == 200
    body = res.json()
    make_validator("answer.schema.json").validate(body)
    assert body["answer_class"] == "abgeleitet"
    _check_req403(body)


def test_req400_api_missing_question_is_422(client: TestClient) -> None:
    res = client.post("/v1/answer", json={})
    assert res.status_code == 422


def test_req400_api_empty_question_is_400(client: TestClient) -> None:
    res = client.post("/v1/answer", json={"question": "   "})
    assert res.status_code == 400
    assert res.json()["disclaimer"]


def test_req400_api_invalid_project_data_is_400(client: TestClient) -> None:
    bad: dict[str, dict[str, object]] = {
        "sia:concept/teilsflaeche-a": {"value": "viel", "unit": "m2"}
    }
    res = client.post("/v1/answer", json={"question": CALCULATION_QUESTION, "project_data": bad})
    assert res.status_code == 400
    assert "value" in res.json()["error"]


def test_req403_api_abstention_is_reasoned(client: TestClient) -> None:
    res = client.post(
        "/v1/answer", json={"question": "Welche Mindestwerte gelten für die Bauphysik?"}
    )
    assert res.status_code == 200
    body = res.json()
    make_validator("answer.schema.json").validate(body)
    assert body["answer_class"] == "nicht_eindeutig"
    missing = cast(list[str], body.get("missing_information") or [])
    assert missing  # begründete Enthaltung (REQ-403)


def test_req400_api_empty_knowledge_base_abstains(tmp_path: Path) -> None:
    """Ohne freigegebene Objekte gibt es keine Fundstellen, nur begründete Enthaltung."""
    app = create_app(tmp_path / "catalog.db", tmp_path / "keine-wissensbasis")
    try:
        raw: object = json.loads(
            (BENCHMARK_DIR / "catalog_snapshot.json").read_text(encoding="utf-8")
        )
        assert isinstance(raw, dict)
        app.state.store.import_snapshot(load_snapshot(raw))
        client = TestClient(app)
        res = client.post("/v1/answer", json={"question": DEFINITION_QUESTION})
        assert res.status_code == 200
        body = res.json()
        make_validator("answer.schema.json").validate(body)
        assert body["answer_class"] == "nicht_eindeutig"
        assert body.get("sources") in (None, [])
        _check_req403(body)
    finally:
        app.state.store.close()
