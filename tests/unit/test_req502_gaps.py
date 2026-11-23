"""REQ-502: Fehlende Projektdaten erzeugen GapReport missing_project_data."""

from sni.core.schemas import make_validator
from sni.projectdata.gaps import missing_project_data_gaps
from sni.projectdata.models import ProjectValue, Provenance


def _rule(rule_id: str, concepts: list[str], required: bool = True) -> dict[str, object]:
    return {
        "id": rule_id,
        "derived_from": ["sia:statement/syn1-2020/3.2/1"],
        "inputs": [
            {"concept": concept, "unit": "m2", "required": required} for concept in concepts
        ],
        "output": {"concept": "sia:concept/gesamtflaeche", "unit": "m2"},
        "expression": " + ".join(concepts) if concepts else "0",
        "review_status": "approved",
    }


def _value(concept: str) -> ProjectValue:
    return ProjectValue(
        concept=concept,
        value=1.0,
        unit="m2",
        provenance=Provenance(file="flaechen.csv", locator="Zeile 2"),
    )


def test_req502_missing_project_data_creates_gap_report() -> None:
    rules = [_rule("sia:rule/syn1-2020/gf-summe", ["sia:concept/teilsflaeche-a", "sia:concept/b"])]
    values = [_value("sia:concept/teilsflaeche-a")]

    gaps = missing_project_data_gaps(rules, values)

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["id"] == "GAP-0001"
    assert gap["gap_type"] == "missing_project_data"
    assert gap["target_layer"] == "projektdaten"
    assert gap["status"] == "open"
    assert gap["priority"] == "medium"
    assert gap["evidence"] == ["sia:rule/syn1-2020/gf-summe"]
    assert "sia:concept/b" in str(gap["description"])
    assert "sia:concept/teilsflaeche-a" not in str(gap["description"])


def test_req502_all_data_present_no_gaps() -> None:
    rules = [_rule("sia:rule/syn1-2020/gf-summe", ["sia:concept/a", "sia:concept/b"])]
    values = [_value("sia:concept/a"), _value("sia:concept/b")]

    assert missing_project_data_gaps(rules, values) == []


def test_req502_multiple_rules_same_missing_concept_one_gap() -> None:
    rules = [
        _rule("sia:rule/syn1-2020/regel-1", ["sia:concept/a", "sia:concept/fehlt"]),
        _rule("sia:rule/syn1-2020/regel-2", ["sia:concept/fehlt"]),
    ]
    values = [_value("sia:concept/a")]

    gaps = missing_project_data_gaps(rules, values)

    assert len(gaps) == 1
    assert gaps[0]["evidence"] == ["sia:rule/syn1-2020/regel-1", "sia:rule/syn1-2020/regel-2"]


def test_req502_gap_ids_continue_from_existing() -> None:
    rules = [_rule("sia:rule/syn1-2020/regel-1", ["sia:concept/fehlt"])]

    gaps = missing_project_data_gaps(rules, [], existing_gap_ids=("GAP-0042", "GAP-0007"))

    assert [g["id"] for g in gaps] == ["GAP-0043"]


def test_req502_optional_inputs_do_not_create_gaps() -> None:
    rules = [
        _rule("sia:rule/syn1-2020/regel-1", ["sia:concept/a", "sia:concept/b"], required=False)
    ]

    assert missing_project_data_gaps(rules, [_value("sia:concept/a")]) == []


def test_req502_multiple_missing_concepts_deterministic_order() -> None:
    rules = [
        _rule("sia:rule/syn1-2020/regel-1", ["sia:concept/zweite", "sia:concept/erste"]),
    ]

    gaps = missing_project_data_gaps(rules, [])

    assert [g["id"] for g in gaps] == ["GAP-0001", "GAP-0002"]
    assert "sia:concept/erste" in str(gaps[0]["description"])
    assert "sia:concept/zweite" in str(gaps[1]["description"])


def test_req502_gap_report_validates_against_schema() -> None:
    rules = [_rule("sia:rule/syn1-2020/regel-1", ["sia:concept/fehlt"])]
    validator = make_validator("gap_report.schema.json")

    for gap in missing_project_data_gaps(rules, []):
        validator.validate(gap)  # wirft ValidationError bei Abweichung
