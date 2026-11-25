"""Review-Queue (REQ-809, ADR-0008): Kandidaten + Gaps, Freigabe/Ablehnung.

Die Review-Queue ist SNI-Kerndaten (lokaler Mount, G4): Die Ingest-Pipeline
(M2) schreibt Kandidaten (``sni:norm_statement``) und GapReports
(``sni:gap_report``, IDs ``GAP-####``) nach ``data/review_queue/``.
Freigabe ist ein **menschlicher Akt** (G3) und bewegt das NormStatement
atomar nach ``data/extracted/`` (Wissensbasis, M4): ``approved`` +
``approved_by`` + ``approved_at`` (UTC-Datum, Schema ``format: date``) +
``source.verified=true``.

Java 1:1: ``IntelligencePanel`` (``approveSelected``/``rejectSelected``) —
nur ``:statement/``-IDs werden freigegeben, Fundstelle muss vollständig
sein (norm/edition/clause), Konzepte nicht leer; Ablehnen entfernt die
Datei aus der Queue (Kandidaten und Gaps) und schreibt eine Audit-Zeile
(ID + Zeitstempel, kein Normtext, G4).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from jsonschema.exceptions import ValidationError
from jsonschema.validators import Draft202012Validator

from sni.core.schemas import make_validator
from sni.state.paths import core_data_dir


def default_queue_dir() -> Path:
    """``SIA_CORE_DATA_DIR``/review_queue, sonst ``<repo>/data/review_queue``.

    Call-time aufgelöst (M8.6, REQ-813): die frozen App setzt die Variable
    im Launcher, nach den Modul-Imports.
    """
    return core_data_dir() / "review_queue"


def default_extracted_dir() -> Path:
    """``SIA_CORE_DATA_DIR``/extracted, sonst ``<repo>/data/extracted``."""
    return core_data_dir() / "extracted"


_GAP_ID_RE = re.compile(r"GAP-\d{4}")


class ReviewError(RuntimeError):
    """Review-Aktion fehlgeschlagen (Einzelfehler → API 400); Meldung user-sicher."""


def sanitize_id(obj_id: str) -> str:
    """Macht eine Objekt-ID dateisystem-sicher (gleiche Regel wie M2/M3)."""
    return re.sub(r"[:/@]", "_", obj_id)


def _utc_today() -> str:
    """``approved_at``: UTC-Datum (Schema ``format: date``, ADR-0008)."""
    return datetime.now(UTC).date().isoformat()


def _queue_file(queue_dir: Path, obj_id: str) -> Path | None:
    name = sanitize_id(obj_id)
    if ".." in name or name.startswith("."):
        return None
    return queue_dir / f"{name}.json"


def _load_object(queue_file: Path, obj_id: str) -> dict[str, object]:
    try:
        raw: object = json.loads(queue_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"Queue-Datei nicht lesbar: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("id") != obj_id:
        raise ReviewError("Objekt-ID und Dateiname passen nicht zusammen.")
    return raw


def list_queue(
    queue_dir: Path | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Liest die Queue: Kandidaten (``review_status=candidate``) + offene Gaps.

    Unlesbare Dateien und unbekannte Objekttypen werden übersprungen
    (best-effort; eine kaputte Datei blockiert die Queue nicht).
    """
    directory = default_queue_dir() if queue_dir is None else queue_dir
    candidates: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    if not directory.is_dir():
        return candidates, gaps
    for path in sorted(directory.glob("*.json")):
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[review] Queue-Datei nicht lesbar ({path.name}): {exc}", file=sys.stderr)
            continue
        if not isinstance(raw, dict):
            continue
        obj_id: object = raw.get("id")
        if not isinstance(obj_id, str):
            continue
        if ":statement/" in obj_id and raw.get("review_status") == "candidate":
            candidates.append(raw)
        elif _GAP_ID_RE.fullmatch(obj_id):
            gaps.append(raw)
    return candidates, gaps


def approve(
    obj_id: str,
    approved_by: str,
    queue_dir: Path | None = None,
    extracted_dir: Path | None = None,
) -> dict[str, object]:
    """Gibt einen Kandidaten frei (G3: menschlicher Akt).

    Java-1:1-Prüfungen vor dem Move: nur ``:statement/``-IDs, Fundstelle
    vollständig (norm/edition/clause), Konzepte nicht leer. Setzt
    ``approved`` + ``approved_by`` + ``approved_at`` + ``source.verified``,
    validiert gegen ``norm_statement.schema.json`` und verschiebt die
    Datei atomar nach ``extracted/`` (Ziel schreiben → Quelle löschen;
    bei Fehlschlag bleibt der Kandidat in der Queue).
    """
    directory = default_queue_dir() if queue_dir is None else queue_dir
    target_dir = default_extracted_dir() if extracted_dir is None else extracted_dir
    if not isinstance(obj_id, str) or not obj_id.strip():
        raise ReviewError("Ungültige Objekt-ID.")
    queue_file = _queue_file(directory, obj_id)
    if queue_file is None:
        raise ReviewError("Ungültige Objekt-ID.")
    if ":statement/" not in obj_id:
        raise ReviewError("Nur NormStatements können freigegeben werden.")
    approver = approved_by.strip()
    if not approver:
        raise ReviewError("Keine Freigabeperson angegeben.")
    if not queue_file.is_file():
        raise ReviewError(f"Objekt nicht in der Review-Queue: {obj_id}")
    obj = _load_object(queue_file, obj_id)
    if obj.get("review_status") != "candidate":
        raise ReviewError("Objekt ist kein Kandidat (review_status ungleich 'candidate').")
    concepts: object = obj.get("concepts")
    if not isinstance(concepts, list) or not concepts:
        raise ReviewError("Kandidat ohne Konzepte – Freigabe nicht möglich.")
    source: object = obj.get("source")
    if not isinstance(source, dict):
        raise ReviewError("Fundstelle unvollständig (source fehlt) – Freigabe nicht möglich.")
    for key in ("norm", "edition", "clause"):
        value: object = source.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ReviewError(f"Fundstelle unvollständig ({key}) – Freigabe nicht möglich.")
    obj["review_status"] = "approved"
    obj["approved_by"] = approver
    obj["approved_at"] = _utc_today()
    source["verified"] = True
    validator: Draft202012Validator = make_validator("norm_statement.schema.json")
    try:
        validator.validate(obj)
    except ValidationError as exc:
        raise ReviewError(f"Schema-Verletzung nach Freigabe: {exc.message}") from exc
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / queue_file.name
    target.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    queue_file.unlink()
    return obj


def reject(obj_id: str, queue_dir: Path | None = None) -> str:
    """Verwirft ein Queue-Objekt (Java 1:1: Kandidaten und Gaps).

    Die Datei wird aus der Queue entfernt; eine Audit-Zeile (ID +
    UTC-Zeitstempel, kein Normtext, G4) geht auf stderr.
    """
    directory = default_queue_dir() if queue_dir is None else queue_dir
    if not isinstance(obj_id, str) or not obj_id.strip():
        raise ReviewError("Ungültige Objekt-ID.")
    queue_file = _queue_file(directory, obj_id)
    if queue_file is None:
        raise ReviewError("Ungültige Objekt-ID.")
    if not queue_file.is_file():
        raise ReviewError(f"Objekt nicht in der Review-Queue: {obj_id}")
    _load_object(queue_file, obj_id)
    queue_file.unlink()
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"[review] abgelehnt {obj_id} am {stamp}", file=sys.stderr)
    return obj_id
