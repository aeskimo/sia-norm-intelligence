"""REQ-702: POST /v1/export/bcf liefert fail-Ergebnisse als BCF 2.1-ZIP."""

import io
import shutil
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sni.api.main import create_app
from sni.export.bcf import topic_guid

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_RULE = ROOT / "tests" / "benchmark" / "knowledge" / "sia_rule_syn1-2020_gf-summe.json"
RULE_ID = "sia:rule/syn1-2020/gf-summe"
A = "sia:concept/teilsflaeche-a"
B = "sia:concept/teilsflaeche-b"
OUT = "sia:concept/gesamtflaeche"
INCONSISTENT_DATA: dict[str, dict[str, object]] = {
    A: {"value": 100, "unit": "m2"},
    B: {"value": 50, "unit": "m2"},
    OUT: {"value": 200, "unit": "m2"},  # inkonsistent: 100 + 50 != 200
}
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


def _namelist(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.namelist()


def test_req702_api_bcf_export_fail_produces_topic(client: TestClient) -> None:
    res = client.post("/v1/export/bcf", json={"project_data": INCONSISTENT_DATA})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/octet-stream"
    assert "attachment" in res.headers["content-disposition"]
    guid = topic_guid(RULE_ID)
    assert _namelist(res.content) == ["bcf.version", f"{guid}/markup.bcf"]
    with zipfile.ZipFile(io.BytesIO(res.content)) as archive:
        markup = archive.read(f"{guid}/markup.bcf").decode("utf-8")
    assert f"<Guid>{guid}</Guid>" in markup
    assert f"<Title>{RULE_ID}</Title>" in markup
    assert "<CreationAuthor>sni@localhost</CreationAuthor>" in markup
    assert "<CreationDate>" in markup
    assert "Inkonsistent" in markup  # reason der Fail-Prüfung
    assert "Fundstelle: sia:statement/syn1-2020/4.1/1" in markup
    assert "Keine Rechtsauskunft" in markup  # G6-Disclaimer in der Description


def test_req702_api_bcf_export_consistent_data_has_no_topics(client: TestClient) -> None:
    res = client.post("/v1/export/bcf", json={"project_data": CONSISTENT_DATA})
    assert res.status_code == 200
    assert _namelist(res.content) == ["bcf.version"]


def test_req702_api_bcf_export_empty_project_data_has_no_topics(client: TestClient) -> None:
    res = client.post("/v1/export/bcf", json={"project_data": {}})
    assert res.status_code == 200
    assert _namelist(res.content) == ["bcf.version"]


def test_req702_api_bcf_export_invalid_project_data_is_400(client: TestClient) -> None:
    bad = {A: {"value": "viel", "unit": "m2"}}
    res = client.post("/v1/export/bcf", json={"project_data": bad})
    assert res.status_code == 400
    assert "value" in res.json()["error"]
    assert res.json()["disclaimer"]  # G6 auch bei Fehler


def test_req702_api_bcf_export_unloadable_rules_is_500(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "broken_rule.json").write_text("{", encoding="utf-8")
    app = create_app(tmp_path / "catalog.db", tmp_path / "leer", rules_dir=rules_dir)
    try:
        res = TestClient(app).post("/v1/export/bcf", json={})
        assert res.status_code == 500
        assert "broken_rule.json" in res.json()["error"]
        assert res.json()["disclaimer"]  # G6
    finally:
        app.state.store.close()
