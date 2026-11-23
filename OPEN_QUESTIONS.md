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
- Status: offen
- Antwort:
