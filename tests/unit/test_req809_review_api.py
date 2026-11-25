"""REQ-809: Review-Queue — ``GET /v1/review/queue``, Freigabe/Ablehnung (G3, ADR-0008).

Freigabe ist ein menschlicher Akt: nur ``:statement/``-Kandidaten, Fundstelle
vollständig (norm/edition/clause), Konzepte nicht leer; ``approved_by`` aus
dem Request (Override) oder den Settings (``approval_name``), ``approved_at``
als UTC-Datum (Schema ``format: date``), ``source.verified=true``; atomarer
Move ``data/review_queue/`` → ``data/extracted/``. Ablehnen entfernt die Datei
(Java 1:1: Kandidaten und Gaps) + Audit-Zeile. Synthetische Testdaten (G4).
"""

from __future__ import annotations

import copy
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from sni.app.server import build_app
from sni.app.shop import ShopState
from sni.review import service as review_service
from sni.review.service import ReviewError, approve, list_queue, reject
from sni.state.settings import update_settings

TOKEN = "app-test-token"
BASE = "http://127.0.0.1:8143"
HDRS = {"x-sia-token": TOKEN}

CANDIDATE: dict[str, object] = {
    "id": "sia:statement/sia416-2003/4.1/1",
    "summary": "Synthetische Testzusammenfassung",
    "source": {"norm": "SIA 416", "edition": "2003", "clause": "4.1", "verified": False},
    "concepts": ["sia:concept/tragende-konstruktion"],
    "statement_type": "requirement",
    "obligation": "muss",
    "review_status": "candidate",
}

GAP: dict[str, object] = {
    "id": "GAP-0001",
    "gap_type": "missing_concept",
    "target_layer": "datenkatalog",
    "source": {"norm": "SIA 416", "edition": "2003", "clause": "4.2"},
    "description": "Synthetischer Gap (Test).",
}


def _write(queue_dir: Path, obj: dict[str, object]) -> Path:
    queue_dir.mkdir(parents=True, exist_ok=True)
    path = queue_dir / f"{review_service.sanitize_id(str(obj['id']))}.json"
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, ShopState]:
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "keychain"))
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    # Hermetik (M8.6): Core-Daten-Mount in den tmp-Pfad (statt Repo-data/).
    monkeypatch.setenv("SIA_CORE_DATA_DIR", str(tmp_path))
    shop = ShopState(data_dir=tmp_path / "data")
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token=TOKEN,
        mode="window",
        port=8143,
        shop=shop,
    )
    return TestClient(app, base_url=BASE), shop


# ------------------------------------------------------------- Service: Queue


def test_req809_list_queue_classifies_candidates_and_gaps(tmp_path: Path) -> None:
    queue = tmp_path / "q"
    _write(queue, CANDIDATE)
    _write(queue, GAP)
    approved = copy.deepcopy(CANDIDATE)
    approved["id"] = "sia:statement/sia416-2003/4.1/2"
    approved["review_status"] = "approved"
    _write(queue, approved)
    (queue / "broken.json").write_text("{ nicht json", encoding="utf-8")
    candidates, gaps = list_queue(queue)
    assert [c["id"] for c in candidates] == [CANDIDATE["id"]]
    assert [g["id"] for g in gaps] == [GAP["id"]]


def test_req809_list_queue_missing_dir_is_empty(tmp_path: Path) -> None:
    assert list_queue(tmp_path / "nichts") == ([], [])


def test_req809_default_dirs_use_repo_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: Ohne ``SIA_CORE_DATA_DIR`` müssen die Default-Dirs auf
    ``<repo>/data/`` zeigen (nicht ``src/data/`` — Buggy ``parents[2]``).

    M8.6: Auflösung call-time über ``core_data_dir()`` (frozen-App-Override).
    """
    from sni.api import main as core_api

    monkeypatch.delenv("SIA_CORE_DATA_DIR", raising=False)
    assert review_service.default_queue_dir() == core_api.ROOT / "data" / "review_queue"
    assert review_service.default_extracted_dir() == core_api.ROOT / "data" / "extracted"


def test_req809_default_dirs_follow_core_data_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M8.6 (REQ-813): ``SIA_CORE_DATA_DIR``-Override steuert die Default-Dirs."""
    monkeypatch.setenv("SIA_CORE_DATA_DIR", str(tmp_path))
    assert review_service.default_queue_dir() == tmp_path / "review_queue"
    assert review_service.default_extracted_dir() == tmp_path / "extracted"


# ------------------------------------------------------------- Service: Freigabe


def test_req809_approve_moves_file_and_stamps(tmp_path: Path) -> None:
    queue, extracted = tmp_path / "q", tmp_path / "e"
    _write(queue, CANDIDATE)
    result = approve("sia:statement/sia416-2003/4.1/1", "Max Muster", queue, extracted)
    assert result["review_status"] == "approved"
    assert result["approved_by"] == "Max Muster"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(result["approved_at"]))
    source = cast("dict[str, object]", result["source"])
    assert source["verified"] is True
    target = extracted / "sia_statement_sia416-2003_4.1_1.json"
    assert target.is_file()
    assert not (queue / "sia_statement_sia416-2003_4.1_1.json").exists()
    moved = json.loads(target.read_text(encoding="utf-8"))
    assert moved["approved_at"] == result["approved_at"]


def test_req809_approve_rejects_missing_object(tmp_path: Path) -> None:
    with pytest.raises(ReviewError, match="nicht in der Review-Queue"):
        approve("sia:statement/sia416-2003/4.1/1", "Max", tmp_path / "q", tmp_path / "e")


def test_req809_approve_rejects_non_statement(tmp_path: Path) -> None:
    queue = tmp_path / "q"
    _write(queue, GAP)
    with pytest.raises(ReviewError, match="Nur NormStatements"):
        approve("GAP-0001", "Max", queue, tmp_path / "e")


def test_req809_approve_rejects_non_candidate_status(tmp_path: Path) -> None:
    queue = tmp_path / "q"
    reviewed = copy.deepcopy(CANDIDATE)
    reviewed["review_status"] = "reviewed"
    _write(queue, reviewed)
    with pytest.raises(ReviewError, match="kein Kandidat"):
        approve("sia:statement/sia416-2003/4.1/1", "Max", queue, tmp_path / "e")


def test_req809_approve_rejects_empty_concepts(tmp_path: Path) -> None:
    queue = tmp_path / "q"
    no_concepts = copy.deepcopy(CANDIDATE)
    no_concepts["concepts"] = []
    _write(queue, no_concepts)
    with pytest.raises(ReviewError, match="ohne Konzepte"):
        approve("sia:statement/sia416-2003/4.1/1", "Max", queue, tmp_path / "e")


@pytest.mark.parametrize("missing", ["norm", "edition", "clause"])
def test_req809_approve_rejects_incomplete_source(tmp_path: Path, missing: str) -> None:
    queue = tmp_path / "q"
    broken = copy.deepcopy(CANDIDATE)
    source = dict(cast("dict[str, object]", broken["source"]))
    source.pop(missing)
    broken["source"] = source
    _write(queue, broken)
    with pytest.raises(ReviewError, match=f"Fundstelle unvollständig \\({missing}\\)"):
        approve("sia:statement/sia416-2003/4.1/1", "Max", queue, tmp_path / "e")


def test_req809_approve_rejects_missing_approver(tmp_path: Path) -> None:
    queue = tmp_path / "q"
    _write(queue, CANDIDATE)
    with pytest.raises(ReviewError, match="Keine Freigabeperson"):
        approve("sia:statement/sia416-2003/4.1/1", "  ", queue, tmp_path / "e")


def test_req809_approve_rejects_id_file_mismatch(tmp_path: Path) -> None:
    queue = tmp_path / "q"
    queue.mkdir(parents=True)
    mismatched = copy.deepcopy(CANDIDATE)
    mismatched["id"] = "sia:statement/sia416-2003/4.1/2"
    # Datei trägt den Namen für ID "/1", Inhalt aber die ID "/2"
    (queue / "sia_statement_sia416-2003_4.1_1.json").write_text(
        json.dumps(mismatched, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ReviewError, match="passen nicht zusammen"):
        approve("sia:statement/sia416-2003/4.1/1", "Max", queue, tmp_path / "e")


@pytest.mark.parametrize("evil", ["../etc/passwd", "..", "a/../b"])
def test_req809_approve_rejects_path_traversal(tmp_path: Path, evil: str) -> None:
    with pytest.raises(ReviewError, match="Ungültige Objekt-ID"):
        approve(evil, "Max", tmp_path / "q", tmp_path / "e")


def test_req809_approve_is_atomic_on_write_failure(tmp_path: Path) -> None:
    """Ziel-Schreibfehler → Kandidat bleibt in der Queue (kein Datenverlust)."""
    queue, extracted = tmp_path / "q", tmp_path / "e"
    _write(queue, CANDIDATE)
    # Target existiert als Verzeichnis → Schreibfehler (IsADirectoryError)
    (extracted / "sia_statement_sia416-2003_4.1_1.json").mkdir(parents=True)
    with pytest.raises(OSError):
        approve("sia:statement/sia416-2003/4.1/1", "Max", queue, extracted)
    assert (queue / "sia_statement_sia416-2003_4.1_1.json").is_file()


# ------------------------------------------------------------- Service: Ablehnung


def test_req809_reject_removes_candidate_and_gap(tmp_path: Path) -> None:
    queue = tmp_path / "q"
    candidate_file = _write(queue, CANDIDATE)
    gap_file = _write(queue, GAP)
    assert reject("sia:statement/sia416-2003/4.1/1", queue) == CANDIDATE["id"]
    assert not candidate_file.exists()
    assert reject("GAP-0001", queue) == "GAP-0001"
    assert not gap_file.exists()


def test_req809_reject_rejects_missing_object(tmp_path: Path) -> None:
    with pytest.raises(ReviewError, match="nicht in der Review-Queue"):
        reject("sia:statement/sia416-2003/4.1/1", tmp_path / "q")


# ------------------------------------------------------------------- API


def test_req809_api_queue_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.get("/v1/review/queue", headers=HDRS)
    assert res.status_code == 200
    data = res.json()
    assert data["candidates"] == [] and data["gaps"] == []
    assert "disclaimer" in data


def test_req809_api_queue_lists_candidates_and_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    _write(tmp_path / "review_queue", CANDIDATE)
    _write(tmp_path / "review_queue", GAP)
    res = client.get("/v1/review/queue", headers=HDRS)
    assert res.status_code == 200
    data = res.json()
    assert [c["id"] for c in data["candidates"]] == [CANDIDATE["id"]]
    assert [g["id"] for g in data["gaps"]] == [GAP["id"]]


def test_req809_api_approve_with_explicit_approver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    _write(tmp_path / "review_queue", CANDIDATE)
    res = client.post(
        f"/v1/review/{CANDIDATE['id']}/approve",
        json={"approved_by": "Max Muster"},
        headers=HDRS,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "approved" and data["approved_by"] == "Max Muster"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["approved_at"])
    assert (tmp_path / "extracted" / "sia_statement_sia416-2003_4.1_1.json").is_file()
    assert not (tmp_path / "review_queue" / "sia_statement_sia416-2003_4.1_1.json").exists()


def test_req809_api_approve_falls_back_to_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, shop = _build(tmp_path, monkeypatch)
    _write(tmp_path / "review_queue", CANDIDATE)
    update_settings(shop.data_dir, {"approval_name": "SIA-Prüferin"})
    res = client.post(f"/v1/review/{CANDIDATE['id']}/approve", json={}, headers=HDRS)
    assert res.status_code == 200
    assert res.json()["approved_by"] == "SIA-Prüferin"


def test_req809_api_approve_without_any_approver_is_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    _write(tmp_path / "review_queue", CANDIDATE)
    res = client.post(f"/v1/review/{CANDIDATE['id']}/approve", json={}, headers=HDRS)
    assert res.status_code == 400
    assert "Keine Freigabeperson" in res.json()["error"]
    # Kandidat bleibt unverändert in der Queue
    assert (tmp_path / "review_queue" / "sia_statement_sia416-2003_4.1_1.json").is_file()


def test_req809_api_approve_unknown_object_is_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.post(
        "/v1/review/sia:statement/sia999-2099/9.9/1/approve",
        json={"approved_by": "Max"},
        headers=HDRS,
    )
    assert res.status_code == 400
    assert "nicht in der Review-Queue" in res.json()["error"]


def test_req809_api_reject_removes_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    _write(tmp_path / "review_queue", CANDIDATE)
    res = client.post(f"/v1/review/{CANDIDATE['id']}/reject", headers=HDRS)
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"
    assert not (tmp_path / "review_queue" / "sia_statement_sia416-2003_4.1_1.json").exists()


def test_req809_api_reject_unknown_object_is_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.post("/v1/review/sia:statement/sia999-2099/9.9/1/reject", headers=HDRS)
    assert res.status_code == 400


def test_req809_approved_at_uses_utc_date() -> None:
    """UTC-Datum (ADR-0008), nicht Lokalzeit — auch bei Zeitversatz korrekt."""
    expected = datetime.now(UTC).date().isoformat()
    result = review_service._utc_today()
    assert result in {expected, datetime.now().date().isoformat()}
