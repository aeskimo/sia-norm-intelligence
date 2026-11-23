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
