"""M13 (Stufe 3, ADR-0010): LLM-gestuetzte Vervollstaendigung der Fachfelder.

REQ-1300: Vorschlaege fuer Aussageklasse/Obligation/Summary/Concepts aus
dem Ziffern-Text des Entwurfs; nichts landet ohne menschlichen Akt in der
``document.json`` (G1/G3) — das Tool schreibt nur ``document.llm.json``.
REQ-1301: ausschliesslich der konfigurierte Endpunkt
(``SNI_LLM_ENDPOINT``/``SNI_LLM_MODEL``/``SNI_LLM_API_KEY``, Keychain-
Fallback ``gibb-api-key``); Normtext verlaesst die Maschine nur Richtung
dieses Endpunkts; HTTPS-Zwang.
REQ-1302: ADR-0003 auf «akzeptiert» (Doku, kein Test).

Keine echten Norminhalte (G4): alle Texte sind synthetische Platzhalter
mit Markern, die in Fehlermeldungen/Ausgaben nicht erscheinen duerfen.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from sni.catalog.snapshot import load_snapshot
from sni.catalog.store import ConceptStore
from sni.ingest import llm_complete
from sni.ingest.cli import main
from sni.ingest.llm_complete import (
    ENV_API_KEY,
    ENV_ENDPOINT,
    ENV_MODEL,
    PROPOSAL_FILENAME,
    LlmCompleteError,
    LlmCompleteResult,
    run_llm_complete,
)
from sni.ingest.pipeline import ingest_document
from tests.conftest import (
    CONCEPT_A,
    CONCEPT_B,
    loopback_server,
    make_snapshot,
    source_of,
)

NORM_ID = "syn1-2020"
MARKER_TEXT = "MUSTERTEXT-7331-UNIKAT"
MARKER_SUMMARY = "MUSTERSUMMARY-8221-UNIKAT"


# ------------------------------------------------------------------ Helfer


class FakeLlm:
    """LLM-Double (G4: kein echter Endpunkt): liefert Antworten pro Prompt."""

    def __init__(self, responder: Callable[[str, str], str | None]) -> None:
        self._responder = responder
        self.prompts: list[tuple[str, str]] = []

    def generate(self, system: str, prompt: str) -> str | None:
        self.prompts.append((system, prompt))
        return self._responder(system, prompt)


def make_clause(number: str, text: str, **overrides: object) -> dict[str, object]:
    clause: dict[str, object] = {
        "number": number,
        "text": text,
        "statement_type": "",
        "obligation": "",
        "summary": "",
        "concepts": [],
    }
    clause.update(overrides)
    return clause


def make_draft(
    clauses: list[dict[str, object]],
    *,
    norm: str = "SYN 9",
    edition: str = "2020",
    norm_id: str = NORM_ID,
) -> dict[str, object]:
    return {
        "norm_id": norm_id,
        "norm": norm,
        "edition": edition,
        "source_file": "document.pdf",
        "page_count": 1,
        "clauses": clauses,
    }


def write_draft(norms_dir: Path, norm_id: str, draft: dict[str, object]) -> Path:
    norm_dir = norms_dir / norm_id
    norm_dir.mkdir(parents=True, exist_ok=True)
    path = norm_dir / "document.draft.json"
    path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    return path


def valid_response(
    summary: str = "Synthetische Zusammenfassung.", concepts: list[str] | None = None
) -> str:
    return json.dumps(
        {
            "statement_type": "requirement",
            "obligation": "muss",
            "summary": summary,
            "concepts": [CONCEPT_A] if concepts is None else concepts,
        }
    )


def response_with(**overrides: object) -> str:
    base = json.loads(valid_response())
    base.update(overrides)
    return json.dumps(base)


@pytest.fixture
def catalog_db(tmp_path: Path) -> Path:
    """Katalog-DB mit den Standard-Test-Concepts (CONCEPT_A/B), Pfad als Ergebnis."""
    db_path = tmp_path / "catalog.db"
    store = ConceptStore(db_path)
    store.import_snapshot(load_snapshot(make_snapshot()))
    store.close()
    return db_path


def _run(
    norms_dir: Path,
    catalog_db: Path,
    client: FakeLlm,
    draft: dict[str, object] | None = None,
) -> LlmCompleteResult:
    if draft is not None:
        write_draft(norms_dir, NORM_ID, draft)
    return run_llm_complete(
        NORM_ID,
        norms_dir,
        catalog_db,
        {},  # client wird injiziert: keine Umgebungsvariablen noetig
        client=client,
    )


# ------------------------------------------------------------------ REQ-1300: Vorschlag


def test_req1300_llm_complete_writes_proposal(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, p: valid_response())
    result = _run(
        tmp_path / "norms",
        catalog_db,
        client,
        make_draft(
            [
                make_clause("1", "Erste Ziffer. " + MARKER_TEXT),
                make_clause("2", "Zweite Ziffer."),
            ]
        ),
    )
    assert result.norm_id == NORM_ID
    assert result.clauses_suggested == 2
    assert result.clauses_kept == 0
    proposal = tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME
    assert proposal.is_file()
    document = json.loads(proposal.read_text(encoding="utf-8"))
    assert document["norm"] == "SYN 9"
    assert document["edition"] == "2020"
    assert len(document["clauses"]) == 2
    for clause in document["clauses"]:
        assert clause["statement_type"] == "requirement"
        assert clause["obligation"] == "muss"
        assert clause["summary"] == "Synthetische Zusammenfassung."
        assert clause["concepts"] == [CONCEPT_A]
        # G4/Vertrag: kein 'text'-Feld im document.json-Format.
        assert "text" not in clause
    # G3: document.json wird vom Tool nie angefasst.
    assert not (tmp_path / "norms" / NORM_ID / "document.json").exists()


def test_req1300_proposal_is_ingestable_candidates_only(tmp_path: Path, catalog_db: Path) -> None:
    """Akzeptanz: Vorschlag ist eine valide document.json; Ingest erzeugt
    ausschliesslich Kandidaten (review_status=candidate, G3)."""
    client = FakeLlm(lambda _s, _p: valid_response())
    _run(
        tmp_path / "norms",
        catalog_db,
        client,
        make_draft([make_clause("1", "Erste Ziffer. " + MARKER_TEXT)]),
    )
    # Menschliche Uebernahme (G3: der Akt, der document.json entstehen laesst).
    norms_dir = tmp_path / "norms" / NORM_ID
    proposal = json.loads((norms_dir / PROPOSAL_FILENAME).read_text(encoding="utf-8"))
    (norms_dir / "document.json").write_text(json.dumps(proposal), encoding="utf-8")
    catalog = ConceptStore(catalog_db)
    try:
        result = ingest_document(proposal, catalog, tmp_path / "queue")
    finally:
        catalog.close()
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate["review_status"] == "candidate"  # G3: nie approved
    source = source_of(candidate)
    assert source["verified"] is False  # G6


def test_req1300_keeps_manually_filled_clause(tmp_path: Path, catalog_db: Path) -> None:
    """Menschliche Belegung geht vor: vollstaendig belegte Ziffern werden
    uebernommen, das LLM wird dafuer nicht gerufen."""
    manual = make_clause(
        "1",
        "Manuell belegt. " + MARKER_TEXT,
        statement_type="definition",
        obligation="informativ",
        summary="Manuelle Zusammenfassung.",
        concepts=[CONCEPT_B],
    )
    client = FakeLlm(lambda _s, _p: valid_response())
    result = _run(
        tmp_path / "norms",
        catalog_db,
        client,
        make_draft([manual, make_clause("2", "Zweite Ziffer.")]),
    )
    assert result.clauses_suggested == 1
    assert result.clauses_kept == 1
    assert len(client.prompts) == 1  # nur fuer Ziffer 2.
    document = json.loads(
        (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).read_text(encoding="utf-8")
    )
    first = document["clauses"][0]
    assert first["number"] == "1"
    assert first["statement_type"] == "definition"
    assert first["summary"] == "Manuelle Zusammenfassung."
    assert first["concepts"] == [CONCEPT_B]


def test_req1300_partially_filled_clause_is_error(tmp_path: Path, catalog_db: Path) -> None:
    partial = make_clause("1", "Teilweise belegt.", statement_type="requirement")
    client = FakeLlm(lambda _s, _p: valid_response())
    with pytest.raises(LlmCompleteError) as exc:
        _run(tmp_path / "norms", catalog_db, client, make_draft([partial]))
    assert any("teilweise" in line for line in exc.value.report)
    assert len(client.prompts) == 0  # LLM ueberschreibt menschliche Eintraege nicht
    assert not (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).exists()


# ------------------------------------------------------------------ REQ-1300: G1 (keine Erfindung)


def test_req1300_g1_unknown_concept_rejected(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, _p: response_with(concepts=["sia:concept/erfunden"]))
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer.")]),
        )
    assert any("nicht im Katalog (G1)" in line for line in exc.value.report)
    assert not (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).exists()


def test_req1300_invalid_statement_type_rejected(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, _p: response_with(statement_type="meine_erfindung"))
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer.")]),
        )
    assert any("statement_type" in line for line in exc.value.report)
    assert not (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).exists()


def test_req1300_invalid_obligation_rejected(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, _p: response_with(obligation="sollte-wahrscheinlich"))
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer.")]),
        )
    assert any("obligation" in line for line in exc.value.report)


def test_req1300_empty_summary_rejected(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, _p: response_with(summary="   "))
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer.")]),
        )
    assert any("summary" in line for line in exc.value.report)


def test_req1300_clause_without_text_rejected(tmp_path: Path, catalog_db: Path) -> None:
    """G1: ohne lokal extrahierten Text ist kein Vorschlag moeglich."""
    client = FakeLlm(lambda _s, _p: valid_response())
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "")]),
        )
    assert any("kein extrahierter Text" in line for line in exc.value.report)
    assert len(client.prompts) == 0
    assert not (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).exists()


def test_req1300_missing_norm_field_rejected(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, _p: valid_response())
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer.")], norm=""),
        )
    assert any("'norm'" in line for line in exc.value.report)


def test_req1300_missing_edition_rejected(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, _p: valid_response())
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer.")], edition=""),
        )
    assert any("'edition'" in line for line in exc.value.report)


# ---------------------------- REQ-1300: Modellantwort-Robustheit


def test_req1300_non_json_response_rejected(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, _p: "Das ist kein JSON.")
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer.")]),
        )
    assert any("kein gültiges JSON-Objekt" in line for line in exc.value.report)


def test_req1300_code_fence_parsed(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, _p: "```json\n" + valid_response() + "\n```")
    _run(
        tmp_path / "norms",
        catalog_db,
        client,
        make_draft([make_clause("1", "Erste Ziffer.")]),
    )
    assert (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).is_file()


def test_req1300_no_content_response_rejected(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, _p: None)
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer.")]),
        )
    assert any("keinen Inhalt" in line for line in exc.value.report)


def test_req1300_provider_http_error_rejected(
    tmp_path: Path, catalog_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provider-Fehler (gibb.py RuntimeError, z. B. HTTP 422) → KBOB-Fehler.

    Die Meldung des Providers ist G4-sicher (HTTP-Status, kein Normtext);
    der Bericht darf trotzdem keinen Ziffern-Text enthalten.
    """
    monkeypatch.setattr(llm_complete, "RETRY_DELAY_SECONDS", 0.0)

    def boom(_s: str, _p: str) -> str:
        raise RuntimeError("Modellanfrage fehlgeschlagen (HTTP 422)")

    client = FakeLlm(boom)
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer. " + MARKER_TEXT)]),
        )
    report = exc.value.report
    assert any("Ziffer 1" in line and "HTTP 422" in line for line in report)
    for line in report:
        assert MARKER_TEXT not in line
    assert not (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).exists()


def test_req1300_provider_network_error_rejected(
    tmp_path: Path, catalog_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Netzwerkfehler (httpx) → KBOB-Fehler, nichts wird geschrieben."""
    monkeypatch.setattr(llm_complete, "RETRY_DELAY_SECONDS", 0.0)

    def boom(_s: str, _p: str) -> str:
        raise httpx.ConnectError("connection refused")

    client = FakeLlm(boom)
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer.")]),
        )
    assert any("Ziffer 1" in line and "Netzwerkfehler" in line for line in exc.value.report)
    assert not (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).exists()


def test_req1300_provider_error_aborts_whole_draft(
    tmp_path: Path, catalog_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein Provider-Fehler (auch nach Retry) → Vorschlag wird verworfen (KBOB)."""
    monkeypatch.setattr(llm_complete, "RETRY_DELAY_SECONDS", 0.0)
    calls = {"n": 0}

    def responder(_s: str, p: str) -> str:
        calls["n"] += 1
        if "Ziffernnummer: 1" in p:  # Ziffer 1: beide Versuche fehlerhaft
            raise RuntimeError("Modellanfrage fehlgeschlagen (HTTP 503)")
        return valid_response()

    client = FakeLlm(responder)
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer."), make_clause("2", "Zweite Ziffer.")]),
        )
    assert any("Ziffer 1" in line and "HTTP 503" in line for line in exc.value.report)
    assert calls["n"] == 3  # Ziffer 1: 2 Versuche, Ziffer 2: 1 — alle abgearbeitet
    assert not (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).exists()


def test_req1300_transient_provider_error_retried_once(
    tmp_path: Path, catalog_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transienter Provider-Fehler (HTTP 422) → einmaliger Retry → Lauf gelingt."""
    monkeypatch.setattr(llm_complete, "RETRY_DELAY_SECONDS", 0.0)
    calls = {"n": 0}

    def responder(_s: str, _p: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Modellanfrage fehlgeschlagen (HTTP 422)")
        return valid_response()

    client = FakeLlm(responder)
    _run(
        tmp_path / "norms",
        catalog_db,
        client,
        make_draft([make_clause("1", "Erste Ziffer.")]),
    )
    assert calls["n"] == 2  # erst Retry, dann Erfolg
    assert (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).is_file()


def test_req1300_kbob_collects_all_errors(tmp_path: Path, catalog_db: Path) -> None:
    """KBOB: Fehler aller Ziffern werden gesammelt; nichts wird geschrieben."""
    calls = {"n": 0}

    def responder(_s: str, _p: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return response_with(concepts=["sia:concept/erfunden"])
        return response_with(statement_type="kaputt")

    client = FakeLlm(responder)
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft(
                [
                    make_clause("1", "Erste Ziffer. " + MARKER_TEXT),
                    make_clause("2", "Zweite Ziffer."),
                ]
            ),
        )
    report = exc.value.report
    assert any("Ziffer 1" in line for line in report)
    assert any("Ziffer 2" in line for line in report)
    assert calls["n"] == 2
    assert not (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).exists()


# ------------- REQ-1300: Tabellen/Formeln (v1: nur Ziffern)


def test_req1300_incomplete_table_rejected(tmp_path: Path, catalog_db: Path) -> None:
    clause = make_clause(
        "1",
        "Erste Ziffer. " + MARKER_TEXT,
        tables=[
            {
                "number": "T 3",
                "statement_type": "",
                "obligation": "",
                "summary": "",
                "concepts": [],
            }
        ],
    )
    client = FakeLlm(lambda _s, _p: valid_response())
    with pytest.raises(LlmCompleteError) as exc:
        _run(tmp_path / "norms", catalog_db, client, make_draft([clause]))
    assert any("Tabelle T 3" in line and "nur Ziffern" in line for line in exc.value.report)
    assert not (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).exists()


def test_req1300_complete_table_passed_through(tmp_path: Path, catalog_db: Path) -> None:
    clause = make_clause(
        "1",
        "Erste Ziffer. " + MARKER_TEXT,
        tables=[
            {
                "number": "T 3",
                "statement_type": "calculation",
                "obligation": "muss",
                "summary": "Manuelle Tabellen-Zusammenfassung.",
                "concepts": [CONCEPT_B],
            }
        ],
    )
    client = FakeLlm(lambda _s, _p: valid_response())
    _run(tmp_path / "norms", catalog_db, client, make_draft([clause]))
    document = json.loads(
        (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).read_text(encoding="utf-8")
    )
    tables = document["clauses"][0]["tables"]
    assert tables == [
        {
            "number": "T 3",
            "statement_type": "calculation",
            "obligation": "muss",
            "summary": "Manuelle Tabellen-Zusammenfassung.",
            "concepts": [CONCEPT_B],
        }
    ]


# ------------------------------------------------------------------ REQ-1300: Entwurfspruefung


def test_req1300_missing_draft_rejected(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, _p: valid_response())
    (tmp_path / "norms" / NORM_ID).mkdir(parents=True)
    with pytest.raises(LlmCompleteError) as exc:
        _run(tmp_path / "norms", catalog_db, client)
    assert any("Entwurf nicht gefunden" in line for line in exc.value.report)


def test_req1300_draft_norm_id_mismatch_rejected(tmp_path: Path, catalog_db: Path) -> None:
    client = FakeLlm(lambda _s, _p: valid_response())
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer.")], norm_id="andere-norm"),
        )
    assert any("passt nicht zum Mount-Verzeichnis" in line for line in exc.value.report)


def test_req1300_invalid_norm_id_rejected(tmp_path: Path, catalog_db: Path) -> None:
    with pytest.raises(LlmCompleteError) as exc:
        run_llm_complete(
            "../evil", tmp_path / "norms", catalog_db, {}, client=FakeLlm(lambda _s, _p: None)
        )
    assert any("Ungültige Norm-ID" in line for line in exc.value.report)


# ------------------------------------------------------------------ REQ-1301: Konfiguration & G4


def test_req1301_endpoint_required(tmp_path: Path, catalog_db: Path) -> None:
    write_draft(
        tmp_path / "norms",
        NORM_ID,
        make_draft([make_clause("1", "Erste Ziffer.")]),
    )
    with pytest.raises(LlmCompleteError) as exc:
        run_llm_complete(NORM_ID, tmp_path / "norms", catalog_db, {})
    assert any(f"{ENV_ENDPOINT} fehlt" in line for line in exc.value.report)


def test_req1301_model_required(tmp_path: Path, catalog_db: Path) -> None:
    write_draft(
        tmp_path / "norms",
        NORM_ID,
        make_draft([make_clause("1", "Erste Ziffer.")]),
    )
    with pytest.raises(LlmCompleteError) as exc:
        run_llm_complete(
            NORM_ID, tmp_path / "norms", catalog_db, {ENV_ENDPOINT: "https://chat.gibb.ch/api"}
        )
    assert any(f"{ENV_MODEL} fehlt" in line for line in exc.value.report)


def test_req1301_key_required(
    tmp_path: Path, catalog_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "kc-leer"))
    write_draft(
        tmp_path / "norms",
        NORM_ID,
        make_draft([make_clause("1", "Erste Ziffer.")]),
    )
    with pytest.raises(LlmCompleteError) as exc:
        run_llm_complete(
            NORM_ID,
            tmp_path / "norms",
            catalog_db,
            {ENV_ENDPOINT: "https://chat.gibb.ch/api", ENV_MODEL: "m1"},
        )
    assert any("API-Schlüssel fehlt" in line for line in exc.value.report)


def test_req1301_https_forced_outside_loopback(tmp_path: Path, catalog_db: Path) -> None:
    write_draft(
        tmp_path / "norms",
        NORM_ID,
        make_draft([make_clause("1", "Erste Ziffer.")]),
    )
    with pytest.raises(LlmCompleteError) as exc:
        run_llm_complete(
            NORM_ID,
            tmp_path / "norms",
            catalog_db,
            {
                ENV_ENDPOINT: "http://chat.gibb.ch/api",
                ENV_MODEL: "m1",
                ENV_API_KEY: "test-key",
            },
        )
    assert any("Nur HTTPS-Endpunkte erlaubt" in line for line in exc.value.report)


def test_req1301_g4_no_clause_text_in_error_report(tmp_path: Path, catalog_db: Path) -> None:
    """G4: Ziffern-Text und Modell-Summary tauchen nie im Fehlerbericht auf."""
    client = FakeLlm(
        lambda _s, _p: response_with(summary=MARKER_SUMMARY, concepts=["sia:concept/erfunden"])
    )
    with pytest.raises(LlmCompleteError) as exc:
        _run(
            tmp_path / "norms",
            catalog_db,
            client,
            make_draft([make_clause("1", "Erste Ziffer. " + MARKER_TEXT)]),
        )
    for line in exc.value.report:
        assert MARKER_TEXT not in line
        assert MARKER_SUMMARY not in line


def test_req1301_norm_text_only_to_endpoint(tmp_path: Path, catalog_db: Path) -> None:
    """REQ-1301: der Prompt (und damit der Normtext) geht nur an den
    konfigurierten Endpunkt; der Prompt enthaelt Ziffern-Text + Katalog."""
    seen_prompts: list[str] = []

    def responder(_s: str, p: str) -> str:
        seen_prompts.append(p)
        return valid_response()

    client = FakeLlm(responder)
    _run(
        tmp_path / "norms",
        catalog_db,
        client,
        make_draft([make_clause("1", "Erste Ziffer. " + MARKER_TEXT)]),
    )
    assert len(seen_prompts) == 1
    prompt = seen_prompts[0]
    assert MARKER_TEXT in prompt
    assert CONCEPT_A in prompt  # Katalog wird als Bezug vorgelegt
    assert NORM_ID not in prompt  # nur Ziffern-Text, kein uebriges Dokument


# ------- REQ-1301/1300: CLI End-to-End (Loopback)


def _loopback_chat_handler(bodies: list[bytes]) -> Callable[[bytes], tuple[int, str]]:
    def chat(payload: bytes) -> tuple[int, str]:
        bodies.append(payload)
        content = json.dumps(
            {
                "statement_type": "requirement",
                "obligation": "muss",
                "summary": "E2E-Zusammenfassung.",
                "concepts": [CONCEPT_A],
            }
        )
        return (
            200,
            '{"choices":[{"message":{"content":'
            + json.dumps(content)
            + '},"finish_reason":"stop"}]}',
        )

    return chat


def test_req1301_cli_end_to_end_via_loopback(
    tmp_path: Path,
    catalog_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_draft(
        tmp_path / "norms",
        NORM_ID,
        make_draft([make_clause("1", "E2E-Ziffer. " + MARKER_TEXT)]),
    )
    bodies: list[bytes] = []
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "kc-leer"))
    monkeypatch.setenv(ENV_MODEL, "m1")
    monkeypatch.setenv(ENV_API_KEY, "test-key")
    with loopback_server({"/chat/completions": _loopback_chat_handler(bodies)}) as server:
        monkeypatch.setenv(ENV_ENDPOINT, server.url)
        exit_code = main(
            ["llm", NORM_ID],
            norms_dir=tmp_path / "norms",
            catalog_db=catalog_db,
        )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert len(bodies) == 1
    # REQ-1301: Normtext verlaesst die Maschine nur Richtung Endpunkt.
    assert MARKER_TEXT.encode("utf-8") in bodies[0]
    assert CONCEPT_A.encode("utf-8") in bodies[0]
    assert b'"model":"m1"' in bodies[0]
    # G4: Ausgabe ohne Normtexte; nur ID, Ziffern, Zaehlungen, Dateiname.
    assert MARKER_TEXT not in captured.out
    assert "[llm]" in captured.out
    assert f"{NORM_ID}: 1 Ziffern vorgeschlagen" in captured.out
    assert PROPOSAL_FILENAME in captured.out
    assert (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).is_file()


def test_req1301_cli_key_from_keychain(
    tmp_path: Path, catalog_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schluesselfallback: Keychain-Account gibb-api-key (opt-in)."""
    write_draft(
        tmp_path / "norms",
        NORM_ID,
        make_draft([make_clause("1", "E2E-Ziffer. " + MARKER_TEXT)]),
    )
    keychain = tmp_path / "kc" / "ch.sia.normenassistent"
    keychain.mkdir(parents=True)
    key = "sk-test-123"
    payload = base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")
    (keychain / "gibb-api-key").write_text(payload, encoding="utf-8")
    bodies: list[bytes] = []
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "kc"))
    monkeypatch.setenv(ENV_MODEL, "m1")
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    with loopback_server({"/chat/completions": _loopback_chat_handler(bodies)}) as server:
        monkeypatch.setenv(ENV_ENDPOINT, server.url)
        exit_code = main(
            ["llm", NORM_ID],
            norms_dir=tmp_path / "norms",
            catalog_db=catalog_db,
        )
    assert exit_code == 0
    assert len(bodies) == 1
    assert (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).is_file()


def test_req1301_cli_usage_error(tmp_path: Path) -> None:
    assert main(["llm"]) == 2


def test_req1301_cli_error_exit_code(
    tmp_path: Path,
    catalog_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_draft(
        tmp_path / "norms",
        NORM_ID,
        make_draft([make_clause("1", "E2E-Ziffer. " + MARKER_TEXT)]),
    )
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "kc-leer"))
    monkeypatch.delenv(ENV_ENDPOINT, raising=False)
    monkeypatch.delenv(ENV_MODEL, raising=False)
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    exit_code = main(
        ["llm", NORM_ID],
        norms_dir=tmp_path / "norms",
        catalog_db=catalog_db,
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert f"FEHLER: {ENV_ENDPOINT} fehlt" in captured.err
    assert not (tmp_path / "norms" / NORM_ID / PROPOSAL_FILENAME).exists()
