# OPEN_QUESTIONS

Format pro Eintrag:

```
## OQ-<nr>: <Kurztitel>
- Kontext: Norm / Ziffer / REQ-ID / Datei
- Frage: <eine präzise Frage>
- Optionen: A) ... B) ...
- Empfehlung Agent: <Option + Begründung>
- Blockiert: <REQ-IDs>
- Status: offen | beantwortet (durch, Datum) | verworfen
- Antwort: ...
```

## OQ-001: Export-Formate für M7 – nur Turtle/SKOS oder zusätzlich I14Y-JSON?
- Kontext: docs/03_ARCHITECTURE.md (GET /v1/export/catalog), docs/08_REFERENCES.md (KBOB SchemaForge, I14Y-Bundle)
- Frage: Soll M7 neben Turtle/SKOS zusätzlich ein I14Y-orientiertes JSON-Bundle als Export-Target liefern?
- Optionen: A) v1 nur Turtle/SKOS (wie in 03_ARCHITECTURE.md geplant); I14Y als Follow-up
  B) Turtle/SKOS + I14Y-JSON in v1
- Empfehlung Agent: A – I14Y-Konformität (inkl. Testing) ist zusätzlicher Aufwand; der
  konkrete Bedarf an I14Y-kompatiblen Imports auf Seiten des Datenkatalogs ist nicht
  bekannt. Nachträgliche Ergänzung ist möglich (Export ist additiv).
- Blockiert: – (betrifft M7)
- Status: beantwortet (Empfehlung A übernommen, 2026-11-23)
- Antwort: M7 liefert in v1 nur Turtle/SKOS; I14Y-JSON-Bundle ist ein dokumentiertes
  Follow-up, sobald der konkrete Import-Bedarf beim Datenkatalog-Projekt besteht.
  Der Export ist additiv, die Nachrüstung kostet dann kein Datenmodell-Update.

## OQ-002: CatalogSnapshot-Format (M1-Import)
- Kontext: 05_MILESTONES.md M1 (REQ-100/101), 03_ARCHITECTURE.md (data/catalog/),
  concept.schema.json (Feld `catalog_snapshot`), 00_VISION.md ("Es definiert den Katalog nicht.")
- Frage: Welches exakte Format hat der CatalogSnapshot (JSON), den das SIA-Datenkatalog-
  Projekt liefert? Das Format ist bisher nirgends definiert.
- Optionen: A) Minimale Consumer-Seiten-Hülle `{"snapshot_id": "<string>", "concepts": [Concept …]}`,
  Concepts validiert gegen concept.schema.json – wird ab M1 so umgesetzt
  B) M1 blockiert bis das Datenkatalog-Projekt das Format definiert
  C) Zusätzlich `catalog_snapshot.schema.json` in schemas/ auf nehmen (braucht ADR)
- Empfehlung Agent: A jetzt (technisches Consumer-Kontrakt, keine fachlichen Inhalte;
  Anpassung bleibt lokal in src/sni/catalog/snapshot.py). Abgleich mit dem
  Datenkatalog-Projekt; C, falls das Format verbindlich wird.
- Blockiert: – (M1 läuft mit A weiter)
- Status: beantwortet (Empfehlung A übernommen, 2026-11-23)
- Antwort: Der Consumer-Seiten-Kontrakt `{"snapshot_id": "<string>", "concepts": [Concept …]}`
  (Concepts gegen concept.schema.json validiert) bleibt in Kraft, bis das
  Datenkatalog-Projekt sein Format definiert. Anpassung bleibt lokal in
  src/sni/catalog/snapshot.py. Falls das Format verbindlich wird: zusätzlich
  `catalog_snapshot.schema.json` in schemas/ (braucht ADR, Option C).

## OQ-003: Format der realen Normdokumente und Extraktionsweg (M2/Ingest)
- Kontext: 05_MILESTONES.md M2 (REQ-200), ADR-0003 ("vorgeschlagen", keine
  lizenzierten Texte im Repo), src/sni/ingest/pipeline.py (synthetisches
  document.json-Format unter data/norms/<norm-id>/)
- Frage: In welchem Format liegen die echten SIA-Normdokumente vor (PDF?
  strukturiert?), und wie werden sie in das document.json-Format
  (Ziffern, Tabellen, Formeln, Concept-Zuordnung) überführt – regelbasiert,
  LLM-gestützt oder beides?
- Optionen: A) Regelbasierter Parser pro Dokumentformat (deterministisch,
  aber format-spezifischer Aufwand)
  B) LLM-gestützte Extraktion mit der Review Queue als Sicherheitsnetz
  (Kandidaten = candidate, Mensch prüft Fundstelle und Aussageklasse)
  C) Eigenes Eingabeformat definieren und eine externe Vorverarbeitungsstufe
  (z. B. OCR/LLM) vorsehen
- Empfehlung Agent: B – passt zur M2-Mission "Ingest mit Review": die LLM
  erzeugt Kandidaten mit review_status="candidate" (G3), der Mensch verifiziert
  Fundstelle und Aussageklasse vor der Freigabe. Guardrail G4 bleibt gewahrt:
  lizenzierte Texte wandern nicht ins Repo, Logs oder Fixtures.
- Blockiert: – (M2 läuft mit synthetischem Platzhalter-Format weiter)
- Status: offen
- Antwort:

## OQ-004: Vertrag für die Antwort von POST /v1/check (M5)
- Kontext: 05_MILESTONES.md M5 (REQ-501), 04_DATA_MODEL.md (Kernobjekte-Tabelle),
  schemas/ (6 Schemas, keins für Prüfergebnisse), AGENTS.md §6 (DoD: jedes neue
  Datenobjekt wird gegen sein JSON-Schema validiert) + §8 (Schemas nur mit ADR)
- Frage: Welches JSON-Vertrag liefert `POST /v1/check`, und wird dafür ein neues
  Schema in `schemas/` ergänzt (braucht ADR-0004)?
- Optionen: A) Neues Schema `check_result.schema.json`: Top-Level
  `{"checks": [{"rule", "status": pass|fail|insufficient_data, "reason",
  "value"?, "missing_inputs"?}], "gaps": [GapReport], "disclaimer"}` –
  das Check-Resultat als eigenständiges Objekt (für REQ-702 BCF-Export
  wird ein stabiles Vertrag-Format ohnehin nötig)
  B) Laufzeit-Objekt ohne Schema – verstösst gegen die Definition of Done
- Empfehlung Agent: A – DoD verlangt ein Schema, und REQ-702 (Prüfergebnisse
  `fail` als BCF-Topic exportierbar) setzt ein stabiles, versionierbares
  Format voraus.
- Blockiert: REQ-501 (sowie die Integration der REQ-502-Gaps in die Antwort)
- Status: offen
- Antwort:

## OQ-005: Semantik von pass/fail bei der Projektdaten-Prüfung (M5)
- Kontext: 05_MILESTONES.md M5 (REQ-501), M7 (REQ-702: `fail` als BCF-Topic),
  schemas/rule.schema.json (kein Vergleichs-/Grenzwertfeld), PROGRESS.md M3
  ("Ausdrucks-Sprache hat (noch) keine Bedingungen/Grenzwert-Vergleiche –
  Erweiterungspunkt für M4+")
- Frage: Wogegen kann eine Regel `pass` oder `fail` sein? Regeln berechnen in
  v1 nur Werte (z. B. `Gesamtfläche = Teilsfläche A + Teilsfläche B`); ein
  Grenz- oder Vergleichswert ist im Regelmodell nicht vorgesehen.
- Optionen: A) Konsistenzprüfung (M5, ohne Schema-Änderung): Das Projekt
  liefert die Inputs UND einen Wert für das Output-Konzept; die Regel
  berechnet; gleich → `pass`, unterschiedlich → `fail`, fehlende Inputs oder
  fehlender Output-Wert → `insufficient_data`
  B) `rule.schema.json` um ein Constraint-Feld erweitern (z. B.
  `{"check": {"expression": "gesamtflaeche <= 5000"}}`; ADR + Schema-Änderung)
  – Prüfung gegen echte Grenzwerte; M5 mit A, B als Follow-up
  C) `pass` = Regel lässt sich fehlerfrei auswerten (Engine-Status `ok`),
  `fail` = Engine-Fehler – schwächste Lesart, keine fachliche Prüfung
- Empfehlung Agent: A für M5 (arbeitet mit bestehenden Verträgen; die
  Engine liefert bereits alle nötigen Status), B als Follow-up-ADR, sobald
  Grenzwert-Regeln fachlich konkret werden (z. B. "GF ≤ 5000 m2").
- Blockiert: REQ-501
- Status: offen
- Antwort:
