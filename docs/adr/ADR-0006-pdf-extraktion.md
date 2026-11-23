# ADR-0006: Extraktionsweg für reale Normdokumente (PDF → document.json)
- Status: vorgeschlagen – Freigabe durch User erforderlich
- Datum: 2026-11-23
- Kontext: OQ-003 wurde mit User-Input beantwortet (2026-11-23): echte
  SIA-Normen liegen als **PDF (Print-Ausgabe)** vor und sind **nur über
  ein Online-Portal (Login)** verfügbar; ein Pilot-Dokument steht
  bereit. Die LLM-Freigabe nach ADR-0003 ist noch "vorgeschlagen" –
  bis dahin darf kein Normtext ein LLM-Modell verlassen. Die M2-
  Pipeline (`src/sni/ingest/pipeline.py`) erwartet ein strukturiertes
  `data/norms/<norm-id>/document.json` (lokaler Mount, gitignored,
  G4); der Vertrag ist stabil und wird durch diese ADR nicht
  geändert. Ziel: einen reproduzierbaren, guardrail-konformen Weg
  vom PDF zur document.json, bei dem kein lizenzierter Text das
  lokale Verließ (G4) verlässt und nichts fachlich erfunden wird
  (G1).
- Entscheidung:
  1. **Stufe 0 – Download (manuell, keine Funktionalität):** Der
     User lädt die PDFs selbst vom SIA-Portal herunter und legt sie
     als `data/norms/<norm-id>/document.pdf` ab (lokaler Mount,
     `data/norms/` ist gitignored, G4). Begründung: Portalcodes und
     Sessions dürfen nicht im Tool gepflegt werden (Credentials,
     2FA, Nutzungsbedingungen des Portals); die Pipeline bleibt
     vollständig offline (keine neue Netzwerk-Abhängigkeit).
  2. **Stufe 1 – Deterministische PDF-Extraktion (M8, neu):**
     `make extract NORM=<norm-id>` liest
     `data/norms/<norm-id>/document.pdf` und schreibt
     `data/norms/<norm-id>/document.draft.json`: Ziffern-Skelett
     (Ziffernnummern werden deterministisch aus dem Text erkannt,
     z. B. `3.1`, `4.2.1` am Zeilenanfang) plus extrahierter
     Ziffern-Text je Ziffer (lokal, nur für die Vervollständigung;
     kein Teil des Schemas `schemas/`). **Fachliche Felder werden
     nicht von der Maschine gesetzt** (G1): `statement_type`,
     `obligation`, `summary`, `concepts` bleiben im Entwurf leer –
     ihre Belegung ist Facharbeit (Mensch) bzw. LLM-Aufgabe nach
     Stufe 2. Tabellen und Formeln werden in v1 nicht automatisch
     erkannt (bekannte Limitation, wie M2: eigene Objekte mit
     Tabellen-/Formelnummer); sie wird der Mensch nach dem PDF
     ergänzen. Die Extraktion ist atomar (KBOB-Muster: alle Fehler
     gesammelt, bei Fehlern wird nichts geschrieben); Fehlermeldungen
     und Logs enthalten nur IDs, Ziffern und Feldnamen, nie
     Normtexte (G4). Der Entwurf wird gegen ein neues Schema
     `schemas/document_draft.schema.json` validiert (DoD, AGENTS.md
     §6).
  3. **Stufe 2 – Fachliche Vervollständigung (Mensch, ohne Tool-
     Änderung):** Der User vervollständigt `document.draft.json` zu
     einem gültigen `document.json` (norm, norm_id, edition,
     clauses mit statement_type/obligation/summary/concepts,
     tables, formulas) – im selben, bereits bestehenden Mount-
     Format. `make ingest NORM=<norm-id>` läuft danach unverändert
     (G3: Kandidaten immer `candidate`, Review Queue als
     Sicherheitsnetz).
  4. **Stufe 3 – LLM-gestützte Vervollständigung (erst nach
     ADR-0003-Freigabe, eigener Meilenstein):** Nach Freigabe der
     LLM-Nutzung (Endpoint ohne Trainingsnutzung, Konfiguration
     `SNI_LLM_ENDPOINT`, ADR-0003) kann die Stufe 2 durch ein
     LLM-Tool unterstützt werden, das vom Ziffern-Text des Entwurfs
     Summary/Concepts-Vorschläge erzeugt. Harte Grenzen: Input nur
     der lokal extrahierte Text (kein Repo-/Log-Zugriff), Output
     wird gegen den document.json-Vertrag validiert und bleibt
     Vorschlag (G3: Freigabe bleibt menschlicher Akt), keine
     Zugabe von Inhalten ausserhalb des vorgelegten Textes (G1).
     Diese Stufe ist in v1 nicht implementiert (YAGNI +
     ADR-0003-Status "vorgeschlagen").
  5. **Neue Laufzeit-Abhängigkeit (AGENTS.md §5):** `pypdf`
     (MIT, reine Python, keine nativen Dependencies) als PDF-
     Lesebibliothek für Stufe 1. Alternative `pdfplumber` (bessere
     Tabellenextraktion, mehr Dependencies) wird bewusst nicht
     gewählt, solange Tabellen v1 nicht automatisch extrahiert
     werden (Punkt 2).
- Konsequenzen:
  + Kein lizenzierter Text verlässt die Maschine (G4): PDF, Entwurf
    und document.json bleiben unter `data/norms/` (gitignored);
    Logs/Fehlerberichte nur IDs/Ziffern/Feldnamen.
  + Keine fachliche Erfindung (G1): die Maschine liefert nur
    Skelett + Text; Aussageklasse, obligation und Summary sind
    dokumentierte Facharbeit.
  + Bestehender M2-Vertrag (document.json, Ingest-Pipeline, Review
    Queue) bleibt unverändert – additive Änderung, kein Breaking
    Change.
  + Vollständig offline testbar: synthetische Test-PDFs (G4-
    Fixture), Pilot mit einem echten Dokument möglich, sobald der
    User es in den Mount legt.
  − Tabellen/Formeln werden v1 nicht automatisch erfasst
    (Limitation, wie in M2 dokumentiert; Follow-up nach Pilot).
  − Gescannte (nicht digital typografische) PDFs liefern ohne OCR
    keinen Text – OCR ist kein v1-Scope; falls ein Pilot-Dokument
    gescannt sein sollte, bleibt der manuelle Pfad (PDF-Text wird
    in die document.json handschriftlich übernommen).
  − Neue Laufzeit-Abhängigkeit `pypdf` (mit dieser ADR gedeckt).
