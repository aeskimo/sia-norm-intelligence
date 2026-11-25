"""REQ-202: Kandidaten landen in der Human Review Queue (data/review_queue/),
nie direkt als `approved` (Guardrail G3)."""

import json
from pathlib import Path

import pytest

from sni.catalog.snapshot import load_snapshot
from sni.catalog.store import ConceptStore
from sni.ingest.cli import main
from sni.ingest.pipeline import default_queue_dir
from sni.state import paths as state_paths
from tests.conftest import load_synthetic_norm, make_snapshot


def _write_mount(norms_dir: Path) -> None:
    norm_dir = norms_dir / "syn1-2020"
    norm_dir.mkdir(parents=True)
    (norm_dir / "document.json").write_text(
        json.dumps(load_synthetic_norm(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _seed_catalog(db: Path) -> None:
    store = ConceptStore(db)
    try:
        store.import_snapshot(load_snapshot(make_snapshot()))
    finally:
        store.close()


def _run_cli(tmp_path: Path) -> tuple[int, Path, Path]:
    norms_dir = tmp_path / "norms"
    _write_mount(norms_dir)
    db = tmp_path / "catalog.db"
    _seed_catalog(db)
    queue = tmp_path / "review_queue"
    rc = main(["syn1-2020"], norms_dir=norms_dir, queue_dir=queue, catalog_db=db)
    return rc, queue, db


def test_req202_cli_end_to_end_candidates_in_queue(tmp_path: Path) -> None:
    rc, queue, _ = _run_cli(tmp_path)
    assert rc == 0
    files = sorted(queue.glob("*.json"))
    assert len(files) == 7  # 5 Kandidaten + 2 GapReports
    candidates = 0
    for path in files:
        obj = json.loads(path.read_text(encoding="utf-8"))
        obj_id: object = obj["id"]
        assert isinstance(obj_id, str)
        if obj_id.startswith("sia:statement/"):
            candidates += 1
            assert obj["review_status"] == "candidate"  # G3: nie approved
        else:
            assert obj_id.startswith("GAP-")
            assert obj["status"] == "open"
    assert candidates == 5


def test_req202_never_approved_in_queue(tmp_path: Path) -> None:
    rc, queue, _ = _run_cli(tmp_path)
    assert rc == 0
    for path in queue.glob("*.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        for key in ("review_status", "status"):
            assert obj.get(key) != "approved"


def test_req202_reingest_is_idempotent(tmp_path: Path) -> None:
    norms_dir = tmp_path / "norms"
    _write_mount(norms_dir)
    db = tmp_path / "catalog.db"
    _seed_catalog(db)
    queue = tmp_path / "review_queue"
    rc1 = main(["syn1-2020"], norms_dir=norms_dir, queue_dir=queue, catalog_db=db)
    files1 = sorted(p.name for p in queue.glob("*.json"))
    rc2 = main(["syn1-2020"], norms_dir=norms_dir, queue_dir=queue, catalog_db=db)
    files2 = sorted(p.name for p in queue.glob("*.json"))
    assert rc1 == 0 and rc2 == 0
    assert files1 == files2


def test_req202_conflicting_queue_file_rejected_atomically(tmp_path: Path) -> None:
    norms_dir = tmp_path / "norms"
    _write_mount(norms_dir)
    db = tmp_path / "catalog.db"
    _seed_catalog(db)
    queue = tmp_path / "review_queue"
    queue.mkdir()
    conflict = {
        "id": "sia:statement/syn1-2020/3.1/1",
        "source": {"norm": "SYN 1", "edition": "2020", "clause": "3.1", "verified": False},
        "concepts": ["sia:concept/geschossflaeche"],
        "statement_type": "requirement",
        "obligation": "muss",
        "summary": "anderer Inhalt",
        "review_status": "reviewed",
    }
    (queue / "sia_statement_syn1-2020_3.1_1.json").write_text(
        json.dumps(conflict, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rc = main(["syn1-2020"], norms_dir=norms_dir, queue_dir=queue, catalog_db=db)
    assert rc == 1
    # atomar: trotz Konflikt wurden keine neuen Dateien geschrieben
    assert sorted(p.name for p in queue.glob("*.json")) == ["sia_statement_syn1-2020_3.1_1.json"]


def test_req202_default_queue_dir_is_review_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: ohne ``SIA_CORE_DATA_DIR`` = ``<repo>/data/review_queue``
    (nicht ``src/data/``); M8.6: call-time-Auflösung über ``core_data_dir()``."""
    monkeypatch.delenv("SIA_CORE_DATA_DIR", raising=False)
    root = Path(state_paths.__file__).resolve().parents[3]
    assert default_queue_dir() == root / "data" / "review_queue"
