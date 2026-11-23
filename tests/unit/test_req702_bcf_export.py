"""REQ-702: fail-Prüfergebnisse als BCF 2.1-Topics (Export-Modul, ADR-0005)."""

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime

from sni.export.bcf import bcf_bytes, topic_guid

DISCLAIMER = "DISCLAIMER"
RULE_ID = "sia:rule/syn1-2020/gf-summe"
OTHER_RULE_ID = "sia:rule/syn1-2020/gf-produkt"
FIXED_DATE = datetime(2026, 1, 15, 9, 30, tzinfo=UTC)
GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _check(rule_id: str, status: str, **overrides: object) -> dict[str, object]:
    """Schemakonformer Check-Eintrag (synthetisch, G4)."""
    entry: dict[str, object] = {
        "rule_id": rule_id,
        "status": status,
        "reason": "Synthetische Begründung (Platzhalter, kein Norminhalt).",
        "value": 150.0,
        "claimed": 200.0,
        "unit": "m2",
        "missing_inputs": [],
        "derived_from": ["sia:statement/syn1-2020/4.1/1"],
    }
    entry.update(overrides)
    return entry


def _namelist(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.namelist()


def _read(data: bytes, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(name)


def test_req702_topic_guid_is_deterministic_guid() -> None:
    guid = topic_guid(RULE_ID)
    assert GUID_RE.fullmatch(guid)  # GUID-Format (BCF GuidType)
    assert guid == topic_guid(RULE_ID)  # deterministisch
    assert guid != topic_guid(OTHER_RULE_ID)


def test_req702_bcf_bytes_contains_version_and_fail_topic_only() -> None:
    checks = [_check(RULE_ID, "fail"), _check(OTHER_RULE_ID, "pass")]
    data = bcf_bytes(checks, FIXED_DATE, DISCLAIMER)
    assert _namelist(data) == ["bcf.version", f"{topic_guid(RULE_ID)}/markup.bcf"]


def test_req702_bcf_bytes_without_fails_contains_only_version() -> None:
    checks = [_check(RULE_ID, "pass"), _check(OTHER_RULE_ID, "insufficient_data")]
    data = bcf_bytes(checks, FIXED_DATE, DISCLAIMER)
    assert _namelist(data) == ["bcf.version"]
    assert _namelist(bcf_bytes([], FIXED_DATE, DISCLAIMER)) == ["bcf.version"]


def test_req702_version_file_is_bcf_2_1_xml() -> None:
    data = bcf_bytes([], FIXED_DATE, DISCLAIMER)
    version = _read(data, "bcf.version").decode("utf-8")
    assert version.startswith("<?xml")
    assert '<Version VersionId="2.1">' in version
    assert "<DetailedVersion>2.1</DetailedVersion>" in version


def test_req702_bcf_bytes_are_deterministic() -> None:
    checks = [_check(RULE_ID, "fail")]
    assert bcf_bytes(checks, FIXED_DATE, DISCLAIMER) == bcf_bytes(
        [_check(RULE_ID, "fail")], FIXED_DATE, DISCLAIMER
    )


def test_req702_topic_child_elements_in_xsd_order() -> None:
    data = bcf_bytes([_check(RULE_ID, "fail")], FIXED_DATE, DISCLAIMER)
    topic = ET.fromstring(_read(data, f"{topic_guid(RULE_ID)}/markup.bcf"))
    assert [child.tag for child in topic] == [
        "Guid",
        "Title",
        "CreationDate",
        "CreationAuthor",
        "Description",
    ]


def test_req702_topic_content_matches_adr() -> None:
    data = bcf_bytes([_check(RULE_ID, "fail")], FIXED_DATE, DISCLAIMER)
    topic = ET.fromstring(_read(data, f"{topic_guid(RULE_ID)}/markup.bcf"))

    def text(tag: str) -> str:
        element = topic.find(tag)
        assert element is not None
        return element.text or ""

    assert text("Guid") == topic_guid(RULE_ID)
    assert text("Title") == RULE_ID
    assert text("CreationDate") == "2026-01-15T09:30:00Z"  # UTC, xsd:dateTime
    assert text("CreationAuthor") == "sni@localhost"
    description = text("Description")
    assert "Synthetische Begründung (Platzhalter, kein Norminhalt)." in description
    assert "Fundstelle: sia:statement/syn1-2020/4.1/1" in description
    assert "value=150.0" in description
    assert "claimed=200.0" in description
    assert "unit=m2" in description
    assert DISCLAIMER in description


def test_req702_multiple_fails_produce_one_topic_each() -> None:
    checks = [_check(RULE_ID, "fail"), _check(OTHER_RULE_ID, "fail")]
    data = bcf_bytes(checks, FIXED_DATE, DISCLAIMER)
    names = _namelist(data)
    assert names == [
        "bcf.version",
        f"{topic_guid(RULE_ID)}/markup.bcf",
        f"{topic_guid(OTHER_RULE_ID)}/markup.bcf",
    ]


def test_req702_description_escapes_xml_special_characters() -> None:
    reason = "Ableitung & Lieferung <150 m2 inkonsistent"
    data = bcf_bytes([_check(RULE_ID, "fail", reason=reason)], FIXED_DATE, DISCLAIMER)
    markup = _read(data, f"{topic_guid(RULE_ID)}/markup.bcf")
    assert b"&amp;" in markup  # rohes & wäre XML-Ungültiges
    assert b"&lt;" in markup
    topic = ET.fromstring(markup)  # muss parsen
    description = topic.find("Description")
    assert description is not None
    assert (description.text or "").startswith(f"{reason}; ")  # Round-Trip: Escaping korrekt


def test_req702_missing_values_are_omitted_in_description() -> None:
    checks = [_check(RULE_ID, "fail", value=None, claimed=None, unit=None)]
    data = bcf_bytes(checks, FIXED_DATE, DISCLAIMER)
    topic = ET.fromstring(_read(data, f"{topic_guid(RULE_ID)}/markup.bcf"))
    description = topic.find("Description")
    assert description is not None
    assert description.text is not None
    assert "value=" not in description.text
    assert "claimed=" not in description.text
    assert "unit=" not in description.text
    assert "Synthetische Begründung (Platzhalter, kein Norminhalt)." in description.text
    assert DISCLAIMER in description.text
