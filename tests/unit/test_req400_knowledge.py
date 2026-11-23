"""REQ-400: KnowledgeBase – approved NormStatements + Rules, atomares Laden."""

import json
import re
from pathlib import Path

import pytest

from sni.knowledge.store import KnowledgeBase, KnowledgeLoadError, load_knowledge


def _statement(obj_id: str = "sia:statement/syn1-2020/3.1/1") -> dict[str, object]:
    return {
        "id": obj_id,
        "source": {"norm": "SYN 1", "edition": "2020", "clause": "3.1"},
        "concepts": ["sia:concept/gesamtflaeche"],
        "statement_type": "definition",
        "obligation": "informativ",
        "summary": "Synthetische Definition (Platzhalter, kein Norminhalt).",
        "review_status": "candidate",
    }


def _rule(obj_id: str = "sia:rule/syn1-2020/gf-summe") -> dict[str, object]:
    return {
        "id": obj_id,
        "derived_from": ["sia:statement/syn1-2020/3.1/1"],
        "inputs": [{"concept": "sia:concept/teilsflaeche-a", "unit": "m2"}],
        "output": {"concept": "sia:concept/gesamtflaeche", "unit": "m2"},
        "expression": "teilsflaeche_a",
        "review_status": "candidate",
    }


def _sanitize(obj_id: str) -> str:
    return re.sub(r"[:/@]", "_", obj_id)


def _write(directory: Path, obj: dict[str, object], name: str | None = None) -> None:
    obj_id = str(obj["id"])
    directory.mkdir(parents=True, exist_ok=True)
    filename = name or f"{_sanitize(obj_id)}.json"
    (directory / filename).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_req400_missing_directory_is_empty(tmp_path: Path) -> None:
    kb = load_knowledge(tmp_path / "existiert-nicht")
    assert kb == KnowledgeBase(statements={}, rules={})


def test_req400_loads_statements_and_rules(tmp_path: Path) -> None:
    _write(tmp_path, _statement())
    _write(tmp_path, _rule())
    kb = load_knowledge(tmp_path)
    assert "sia:statement/syn1-2020/3.1/1" in kb.statements
    assert "sia:rule/syn1-2020/gf-summe" in kb.rules
    assert kb.object("sia:rule/syn1-2020/gf-summe") is not None
    assert kb.object("sia:statement/syn1-2020/3.1/1") is not None
    assert kb.object("sia:statement/syn1-2020/9.9/9") is None


def test_req400_invalid_object_collects_all_errors(tmp_path: Path) -> None:
    broken = _statement()
    del broken["obligation"]  # Pflichtfeld fehlt
    broken["concepts"] = []  # minItems: 1 verletzt
    _write(tmp_path, broken)
    with pytest.raises(KnowledgeLoadError) as excinfo:
        load_knowledge(tmp_path)
    assert len(excinfo.value.report) >= 2  # alle Fehler gesammelt, nicht nur der erste


def test_req400_id_filename_mismatch_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _statement(), name="falscher-dateiname.json")
    with pytest.raises(KnowledgeLoadError, match="passt nicht zum Dateinamen"):
        load_knowledge(tmp_path)


def test_req400_unknown_object_type_rejected(tmp_path: Path) -> None:
    foreign: dict[str, object] = {"id": "sia:foo/syn1-2020/x", "review_status": "candidate"}
    _write(tmp_path, foreign)
    with pytest.raises(KnowledgeLoadError, match="unbekannter Objekttyp"):
        load_knowledge(tmp_path)


def test_req400_not_json_rejected(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "sia_statement_syn1-2020_3.1_1.json").write_text("{ kaputt", encoding="utf-8")
    with pytest.raises(KnowledgeLoadError, match="kein gültiges JSON"):
        load_knowledge(tmp_path)


def test_req400_approved_requires_release_metadata(tmp_path: Path) -> None:
    """G3: approved-Objekte brauchen Freigabe-Metadaten (Schema if/then)."""
    obj = _statement()
    obj["review_status"] = "approved"
    _write(tmp_path, obj)
    with pytest.raises(KnowledgeLoadError, match="approved_by"):
        load_knowledge(tmp_path)


def test_req400_approved_with_metadata_loads(tmp_path: Path) -> None:
    obj = _statement()
    obj["review_status"] = "approved"
    obj["approved_by"] = "Fachperson Test (synthetisch)"
    obj["approved_at"] = "2026-11-23"
    _write(tmp_path, obj)
    kb = load_knowledge(tmp_path)
    assert kb.statements["sia:statement/syn1-2020/3.1/1"]["review_status"] == "approved"


def test_req400_valid_file_not_discarded_by_other_error(tmp_path: Path) -> None:
    """Atomar: eine fehlerhafte Datei verdirbt die gesamte Ladung (KBOB)."""
    _write(tmp_path, _statement())
    broken = _rule()
    del broken["expression"]
    _write(tmp_path, broken)
    with pytest.raises(KnowledgeLoadError):
        load_knowledge(tmp_path)
