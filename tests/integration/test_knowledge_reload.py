"""Integration: die Wissensbasis wird pro Request geladen (Anbindung M3.2).

Eine Freigabe in der knowledge_dir muss ohne Neustart der App wirken –
entsprechend dem etablierten Muster der Regeln (lokale Mounts, kein
Startup-State, ADR-konform).
"""

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sni.api.main import create_app
from sni.catalog.snapshot import load_snapshot

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = ROOT / "tests" / "benchmark"
QUESTION = "Was ist die Gesamtfläche?"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """App mit Benchmark-Katalog, aber leerer Wissensbasis."""
    app = create_app(tmp_path / "catalog.db", tmp_path / "knowledge")
    try:
        raw: object = json.loads(
            (BENCHMARK_DIR / "catalog_snapshot.json").read_text(encoding="utf-8")
        )
        assert isinstance(raw, dict)
        app.state.store.import_snapshot(load_snapshot(raw))
        yield TestClient(app)
    finally:
        app.state.store.close()


def test_knowledge_becomes_visible_without_restart(client: TestClient, tmp_path: Path) -> None:
    res = client.post("/v1/answer", json={"question": QUESTION})
    assert res.status_code == 200
    assert res.json()["answer_class"] == "nicht_eindeutig"

    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    for path in (BENCHMARK_DIR / "knowledge").glob("*.json"):
        shutil.copy(path, knowledge / path.name)

    res = client.post("/v1/answer", json={"question": QUESTION})
    assert res.status_code == 200
    assert res.json()["answer_class"] == "normativ_belegt"
