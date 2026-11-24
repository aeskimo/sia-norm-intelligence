"""Katalog-CLI: ``python -m sni.catalog import <snapshot.json>`` (Anbindung M3.2)."""

import json
from pathlib import Path

from sni.catalog.__main__ import main
from sni.catalog.store import ConceptStore

SNAPSHOT = {
    "snapshot_id": "test-cli-snap",
    "concepts": [
        {
            "id": "sia:concept/testbegriff",
            "name": {"de": "Testbegriff"},
            "definition": {"de": "Synthetischer Testbegriff."},
            "catalog_snapshot": "test-cli-snap",
        }
    ],
}


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_cli_import_writes_concepts(tmp_path: Path) -> None:
    file = _write(tmp_path / "snap.json", SNAPSHOT)
    db = tmp_path / "catalog.db"
    assert main(["import", str(file)], catalog_db=db) == 0
    store = ConceptStore(db)
    try:
        assert store.get_concept("sia:concept/testbegriff") is not None
    finally:
        store.close()


def test_cli_import_idempotent(tmp_path: Path) -> None:
    file = _write(tmp_path / "snap.json", SNAPSHOT)
    db = tmp_path / "catalog.db"
    assert main(["import", str(file)], catalog_db=db) == 0
    assert main(["import", str(file)], catalog_db=db) == 0


def test_cli_import_conflict_rejected(tmp_path: Path) -> None:
    file = _write(tmp_path / "snap.json", SNAPSHOT)
    other = {
        "snapshot_id": "test-cli-snap-2",
        "concepts": [
            {
                "id": "sia:concept/testbegriff",
                "name": {"de": "Anderer Begriff"},
                "definition": {"de": "Widerspruechlicher Inhalt."},
                "catalog_snapshot": "test-cli-snap-2",
            }
        ],
    }
    file2 = _write(tmp_path / "snap2.json", other)
    db = tmp_path / "catalog.db"
    assert main(["import", str(file)], catalog_db=db) == 0
    assert main(["import", str(file2)], catalog_db=db) == 1


def test_cli_import_invalid_snapshot_is_rejected(tmp_path: Path) -> None:
    bad = {"snapshot_id": "test", "concepts": [{"id": "sia:concept/x", "name": "kein-ml"}]}
    file = _write(tmp_path / "bad.json", bad)
    assert main(["import", str(file)], catalog_db=tmp_path / "catalog.db") == 1


def test_cli_usage_and_missing_file(tmp_path: Path) -> None:
    assert main([]) == 2
    assert main(["import"]) == 2
    assert main(["falsches", "untersubkommando"]) == 2
    assert main(["import", str(tmp_path / "fehlt.json")], catalog_db=tmp_path / "db") == 1
