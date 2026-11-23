"""BCF 2.1-Export (M7, REQ-702, ADR-0005).

Jeder ``fail``-Check-Eintrag wird zu einem BCF-Topic
(``<guid>/markup.bcf``) in einem ZIP-Archiv; ``pass`` und
``insufficient_data`` werden nicht exportiert. Das Archiv enthält
zusätzlich ``bcf.version``. Keine Viewpoints, keine ``project.bcfp``
(ADR-0005, Punkt 4; bekannte Limitation v1: Topics sind ohne
Viewpoints nicht im 3D-Kontext verortbar). Die Topic-Guids sind
deterministisch (``uuid5`` über die Rule-ID), damit BCF-Dateien bei
identischen Eingaben vergleichbar bleiben. stdlib-only (``zipfile``,
``xml.etree.ElementTree``, ``uuid``).
"""

from __future__ import annotations

import io
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

BCF_VERSION = "2.1"
AUTHOR = "sni@localhost"
VERSION_XML = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    f'<Version VersionId="{BCF_VERSION}">'
    f"<DetailedVersion>{BCF_VERSION}</DetailedVersion></Version>"
)
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # festes Eintragsdatum -> deterministische ZIP
_CREATION_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class BcfExportError(RuntimeError):
    """BCF-Archiv konnte nicht gebaut werden (intern, z. B. fehlende Rule-ID)."""


def topic_guid(rule_id: str) -> str:
    """Deterministischer Topic-Guid: uuid5 über die Rule-ID (ADR-0005)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, rule_id))


def _creation_date(creation_date: datetime) -> str:
    """BCF-2.1-Datum (xsd:dateTime, UTC) als ISO-8601-Zeichenkette."""
    return creation_date.astimezone(UTC).strftime(_CREATION_DATE_FORMAT)


def _description(check: Mapping[str, object], disclaimer: str) -> str:
    """Topic-Description gemäß ADR-0005: reason, Fundstelle, Werte, G6-Disclaimer."""
    reason: object = check.get("reason")
    parts: list[str] = [reason if isinstance(reason, str) else ""]
    derived: object = check.get("derived_from")
    if isinstance(derived, list):
        refs = [ref for ref in derived if isinstance(ref, str) and ref]
        if refs:
            parts.append(f"Fundstelle: {', '.join(refs)}")
    metrics: list[str] = []
    for key in ("value", "claimed"):
        number: object = check.get(key)
        if isinstance(number, (int, float)) and not isinstance(number, bool):
            metrics.append(f"{key}={number}")
    unit: object = check.get("unit")
    if isinstance(unit, str) and unit:
        metrics.append(f"unit={unit}")
    if metrics:
        parts.append(", ".join(metrics))
    parts.append(disclaimer)
    return "; ".join(parts)


def _topic_bytes(check: Mapping[str, object], creation_date: datetime, disclaimer: str) -> bytes:
    """Markup-Datei eines Topics; Element-Reihenfolge folgt der BCF-2.1-XSD."""
    rule_id: object = check.get("rule_id")
    if not isinstance(rule_id, str) or not rule_id:
        raise BcfExportError(f"Check-Eintrag ohne Rule-ID (status={check.get('status')!r})")
    root = ET.Element("Topic")
    ET.SubElement(root, "Guid").text = topic_guid(rule_id)
    ET.SubElement(root, "Title").text = rule_id
    ET.SubElement(root, "CreationDate").text = _creation_date(creation_date)
    ET.SubElement(root, "CreationAuthor").text = AUTHOR
    ET.SubElement(root, "Description").text = _description(check, disclaimer)
    xml_bytes = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    if not isinstance(xml_bytes, bytes):
        raise BcfExportError("Unerwarteter Serialisierungs-Typ (intern)")
    return xml_bytes


def _write_entry(archive: zipfile.ZipFile, name: str, data: str | bytes) -> None:
    info = zipfile.ZipInfo(filename=name, date_time=_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


def bcf_bytes(
    checks: Sequence[Mapping[str, object]],
    creation_date: datetime,
    disclaimer: str,
) -> bytes:
    """BCF-2.1-ZIP: ``bcf.version`` plus je ``fail`` ein ``<guid>/markup.bcf``.

    ``checks``: Check-Einträge (Form von ``check_result.schema.json``,
    wie von ``sni.service.checker.check`` geliefert). ``creation_date``:
    Exportzeitpunkt (UTC). ``disclaimer``: G6-Disclaimer, der in jede
    Topic-Description übernommen wird. Die Reihenfolge im Archiv ist
    deterministisch (Version, dann Fails in übergebener Reihenfolge).
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        _write_entry(archive, "bcf.version", VERSION_XML)
        for check in checks:
            if check.get("status") != "fail":
                continue
            rule_id: object = check.get("rule_id")
            if not isinstance(rule_id, str) or not rule_id:
                raise BcfExportError("Fail-Eintrag ohne Rule-ID (intern)")
            _write_entry(
                archive,
                f"{topic_guid(rule_id)}/markup.bcf",
                _topic_bytes(check, creation_date, disclaimer),
            )
    return buf.getvalue()
