"""REQ-401: Der Verifier stuft jede nicht belegte Behauptung herab (G5)."""

import json
import re
from pathlib import Path
from typing import cast

from sni.knowledge.store import KnowledgeBase, load_knowledge
from sni.service.answerer import (
    CLASS_ABGELEITET,
    CLASS_NICHT_EINDEUTIG,
    CLASS_NORMATIV_BELEGT,
    verify_answer,
)

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_KNOWLEDGE = ROOT / "tests" / "benchmark" / "knowledge"

STATEMENT_31 = "sia:statement/syn1-2020/3.1/1"
STATEMENT_41 = "sia:statement/syn1-2020/4.1/1"
STATEMENT_55 = "sia:statement/syn1-2020/5.5/1"
RULE_GF = "sia:rule/syn1-2020/gf-summe"
SOURCE_31: dict[str, object] = {
    "norm": "SYN 1",
    "edition": "2020",
    "clause": "3.1",
    "verified": True,
}
SOURCE_41: dict[str, object] = {
    "norm": "SYN 1",
    "edition": "2020",
    "clause": "4.1",
    "verified": True,
}
SOURCE_55: dict[str, object] = {
    "norm": "SYN 1",
    "edition": "2020",
    "clause": "5.5",
    "verified": False,
}


def _kb() -> KnowledgeBase:
    return load_knowledge(BENCHMARK_KNOWLEDGE)


def _draft(
    supported_by: list[str],
    answer_class: str,
    sources: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "question": "Testfrage",
        "answer_class": answer_class,
        "text": "Testantwort",
        "claims": [{"claim": "Testbehauptung", "supported_by": supported_by, "verified": True}],
        "sources": sources,
        "disclaimer": "Test",
    }


def _claims(final: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], final["claims"])


def test_req401_unknown_object_downgrades() -> None:
    draft = _draft(["sia:statement/syn1-2020/9.9/9"], CLASS_NORMATIV_BELEGT, [SOURCE_31])
    final = verify_answer(draft, _kb())
    assert final["answer_class"] == CLASS_NICHT_EINDEUTIG
    assert _claims(final)[0]["verified"] is False
    assert cast(list[str], final.get("missing_information") or [])


def test_req401_candidate_statement_downgrades() -> None:
    """Ein nur candidate Statement ist kein Beleg (G3)."""
    draft = _draft([STATEMENT_55], CLASS_NORMATIV_BELEGT, [SOURCE_55])
    final = verify_answer(draft, _kb())
    assert final["answer_class"] == CLASS_NICHT_EINDEUTIG
    assert _claims(final)[0]["verified"] is False


def test_req401_valid_normativ_belegt_stays() -> None:
    draft = _draft([STATEMENT_31], CLASS_NORMATIV_BELEGT, [SOURCE_31])
    final = verify_answer(draft, _kb())
    assert final["answer_class"] == CLASS_NORMATIV_BELEGT
    assert _claims(final)[0]["verified"] is True
    assert final.get("missing_information") in (None, [])


def test_req401_source_not_from_support_downgrades() -> None:
    """Fundstelle muss von einem der freigegebenen Belege stammen (G2)."""
    fake: dict[str, object] = {"norm": "XXX", "edition": "1900", "clause": "9.9"}
    draft = _draft([STATEMENT_31], CLASS_NORMATIV_BELEGT, [fake])
    final = verify_answer(draft, _kb())
    assert final["answer_class"] == CLASS_NICHT_EINDEUTIG
    assert any("Fundstelle" in line for line in cast(list[str], final["missing_information"]))


def test_req401_unverified_source_downgrades(tmp_path: Path) -> None:
    """normativ_belegt verlangt source.verified (04_DATA_MODEL.md)."""
    statement: dict[str, object] = {
        "id": "sia:statement/syn1-2020/6.1/1",
        "source": {"norm": "SYN 1", "edition": "2020", "clause": "6.1", "verified": False},
        "concepts": ["sia:concept/gesamtflaeche"],
        "statement_type": "definition",
        "obligation": "informativ",
        "summary": "Synthetisch (Platzhalter, kein Norminhalt).",
        "review_status": "approved",
        "approved_by": "Fachperson Test (synthetisch)",
        "approved_at": "2026-11-23",
    }
    filename = re.sub(r"[:/@]", "_", str(statement["id"])) + ".json"
    (tmp_path / filename).write_text(
        json.dumps(statement, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    kb = load_knowledge(tmp_path)
    source: dict[str, object] = {
        "norm": "SYN 1",
        "edition": "2020",
        "clause": "6.1",
        "verified": False,
    }
    draft = _draft(["sia:statement/syn1-2020/6.1/1"], CLASS_NORMATIV_BELEGT, [source])
    final = verify_answer(draft, kb)
    assert final["answer_class"] == CLASS_NICHT_EINDEUTIG
    assert any(
        "verifizierte Fundstellen" in line for line in cast(list[str], final["missing_information"])
    )


def test_req401_valid_abgeleitet_stays() -> None:
    draft = _draft([RULE_GF, STATEMENT_41], CLASS_ABGELEITET, [SOURCE_41])
    final = verify_answer(draft, _kb())
    assert final["answer_class"] == CLASS_ABGELEITET
    assert all(c["verified"] is True for c in _claims(final))


def test_req401_normativ_belegt_without_claims_downgrades() -> None:
    draft = _draft([STATEMENT_31], CLASS_NORMATIV_BELEGT, [SOURCE_31])
    draft["claims"] = []
    final = verify_answer(draft, _kb())
    assert final["answer_class"] == CLASS_NICHT_EINDEUTIG


def test_req401_nicht_eindeutig_stays() -> None:
    draft = _draft([], CLASS_NICHT_EINDEUTIG, [])
    draft["missing_information"] = ["begründete Enthaltung"]
    final = verify_answer(draft, _kb())
    assert final["answer_class"] == CLASS_NICHT_EINDEUTIG
