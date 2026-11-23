"""REQ-400: Antwort-Pipeline – schemakonforme Answers mit korrekter Aussageklasse.

REQ-403: Jede Antwort enthält Norm + Ausgabe + Ziffer (``sources``) oder eine
begründete Enthaltung (``missing_information``).
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from sni.catalog.snapshot import load_snapshot
from sni.catalog.store import ConceptStore
from sni.core.schemas import make_validator
from sni.knowledge.store import KnowledgeBase, load_knowledge
from sni.service.answerer import AnswerError, AnswerInputError, AnswerRequest, answer

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = ROOT / "tests" / "benchmark"

CONCEPT_A = "sia:concept/teilsflaeche-a"
CONCEPT_B = "sia:concept/teilsflaeche-b"
CALCULATION_QUESTION = "Wie gross ist die Gesamtfläche für die gegebenen Projektwerte?"

FULL_PROJECT_DATA: dict[str, dict[str, object]] = {
    CONCEPT_A: {"value": 100, "unit": "m2"},
    CONCEPT_B: {"value": 50, "unit": "m2"},
}

SCENARIOS: list[tuple[str, dict[str, dict[str, object]] | None, str]] = [
    ("Was ist die Gesamtfläche?", None, "normativ_belegt"),
    (CALCULATION_QUESTION, FULL_PROJECT_DATA, "abgeleitet"),
    (
        CALCULATION_QUESTION,
        {CONCEPT_A: {"value": 100, "unit": "m2"}},
        "nicht_eindeutig",
    ),
    ("Was schreibt SYN 1 zum Bauwerk?", None, "nicht_eindeutig"),
    ("Welche Mindestwerte gelten für die Bauphysik?", None, "nicht_eindeutig"),
]


@pytest.fixture
def knowledge_base() -> KnowledgeBase:
    return load_knowledge(BENCHMARK_DIR / "knowledge")


@pytest.fixture
def catalog(tmp_path: Path) -> Iterator[ConceptStore]:
    store = ConceptStore(tmp_path / "catalog.db")
    raw: object = json.loads((BENCHMARK_DIR / "catalog_snapshot.json").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    store.import_snapshot(load_snapshot(raw))
    yield store
    store.close()


@pytest.mark.parametrize(("question", "project_data", "expected_class"), SCENARIOS)
def test_req400_answer_schema_conformant_and_correct_class(
    knowledge_base: KnowledgeBase,
    catalog: ConceptStore,
    question: str,
    project_data: dict[str, dict[str, object]] | None,
    expected_class: str,
) -> None:
    result = answer(AnswerRequest(question, project_data), knowledge_base, catalog)
    # REQ-400: schemakonforme Answer
    make_validator("answer.schema.json").validate(result)
    assert result["answer_class"] == expected_class
    assert result["question"] == question
    assert result["disclaimer"]  # G6: jede Antwort trägt einen Disclaimer
    # REQ-403: Fundstelle oder begründete Enthaltung
    sources = cast(list[object], result.get("sources") or [])
    missing = cast(list[object], result.get("missing_information") or [])
    assert sources or missing
    if expected_class in ("normativ_belegt", "abgeleitet"):
        assert sources


def test_req400_calculation_yields_value(
    knowledge_base: KnowledgeBase, catalog: ConceptStore
) -> None:
    result = answer(AnswerRequest(CALCULATION_QUESTION, FULL_PROJECT_DATA), knowledge_base, catalog)
    claims = cast(list[dict[str, object]], result["claims"])
    assert any("150 m2" in str(claim.get("claim")) for claim in claims)


def test_req400_sources_carry_norm_edition_clause(
    knowledge_base: KnowledgeBase, catalog: ConceptStore
) -> None:
    result = answer(AnswerRequest("Was ist die Gesamtfläche?"), knowledge_base, catalog)
    sources = cast(list[dict[str, object]], result["sources"])
    assert sources
    for source in sources:
        assert source.get("norm") == "SYN 1"
        assert source.get("edition") == "2020"
        assert source.get("clause")


def test_req400_empty_question_raises(knowledge_base: KnowledgeBase, catalog: ConceptStore) -> None:
    with pytest.raises(AnswerError):
        answer(AnswerRequest("   "), knowledge_base, catalog)


def test_req400_invalid_project_data_raises(
    knowledge_base: KnowledgeBase, catalog: ConceptStore
) -> None:
    bad: dict[str, dict[str, object]] = {CONCEPT_A: {"value": "viel", "unit": "m2"}}
    with pytest.raises(AnswerInputError):
        answer(AnswerRequest(CALCULATION_QUESTION, bad), knowledge_base, catalog)


def test_req400_missing_unit_raises(knowledge_base: KnowledgeBase, catalog: ConceptStore) -> None:
    bad: dict[str, dict[str, object]] = {CONCEPT_A: {"value": 100}}
    with pytest.raises(AnswerInputError):
        answer(AnswerRequest(CALCULATION_QUESTION, bad), knowledge_base, catalog)
