# 05 – Milestones mit Akzeptanzkriterien

Jeder Milestone ist erst fertig, wenn alle Kriterien als Test existieren und grün sind.

## M0 – Gerüst
- REQ-000: `make setup|check|eval|run` existieren und laufen auf leerem Projekt
- REQ-001: CI-Pipeline führt `make check` bei jedem Commit aus
- REQ-002: Alle Dateien in `/schemas` sind gültige JSON-Schemas (Draft 2020-12)

## M1 – Katalog-Import
- REQ-100: Given ein CatalogSnapshot (JSON) When importiert Then sind alle Concepts per ID abrufbar
- REQ-101: Ungültige Objekte werden mit Fehlerbericht abgelehnt, Import ist atomar
- REQ-102: `GET /v1/concepts/{id}` liefert Concept inkl. Relationen

## M2 – Normwissen (Ingest mit Review)
- REQ-200: Given ein lokal gemountetes Normdokument When `make ingest NORM=sia416-2003` Then entstehen NormStatement-Kandidaten mit Fundstelle
- REQ-201: Jeder Kandidat verweist auf ≥1 Concept-ID oder erzeugt einen GapReport `missing_concept`
- REQ-202: Kandidaten landen in `data/review_queue/`, nie direkt als `approved`
- REQ-203: Tabellen und Formeln werden als eigene Objekte mit Tabellen-/Formelnummer erfasst

## M3 – Regel-Engine
- REQ-300: Regeln werden aus `rule.schema.json` geladen und ohne `eval()` ausgewertet
- REQ-301: Fehlende Inputs ergeben Status `insufficient_data`, nie einen Default-Wert
- REQ-302: Einheiten werden geprüft; Einheitenkonflikt = Fehler

## M4 – Antwortservice
- REQ-400: `POST /v1/answer` liefert schemakonforme `Answer`
- REQ-401: Verifier stuft jede nicht belegte Behauptung herab
- REQ-402: Critical Failure Rate im Benchmark = 0
- REQ-403: Jede Antwort enthält Norm, Ausgabe, Fundstelle oder begründete Enthaltung

## M5 – Projektdaten-Prüfung
- REQ-500: IFC- und CSV-Adapter liefern normalisierte Werte mit Herkunft (Datei, GUID/Zeile)
- REQ-501: `POST /v1/check` liefert pro Regel `pass|fail|insufficient_data` mit Begründung
- REQ-502: Fehlende Projektdaten erzeugen GapReport `missing_project_data`

## M6 – Benchmark & Bericht
- REQ-600: `make eval` berechnet alle Metriken aus `00_VISION.md`
- REQ-601: Bericht listet jeden Fehlschlag mit Fall-ID, erwarteter und tatsächlicher Klasse

## M7 – Anschlussfähigkeit
- REQ-700: Export Katalogausschnitt als JSON und Turtle (SKOS)
- REQ-701: Regel → IDS-Spezifikation (wo abbildbar), sonst GapReport `not_ids_expressible`
- REQ-702: Prüfergebnisse `fail` als BCF-Topic exportierbar

## M8 – Echte Normdokumente: PDF-Extraktion (OQ-003, ADR-0006)
- REQ-800: Given ein PDF unter `data/norms/<norm-id>/document.pdf` When `make extract NORM=<norm-id>` Then entsteht `document.draft.json` mit Ziffern-Skelett (Ziffernnummern am Zeilenanfang, deterministisch) und extrahiertem Ziffern-Text; Fachfelder bleiben leer; der Entwurf ist validiert gegen `document_draft.schema.json`
- REQ-801: Extraktion ist atomar: alle Fehler werden gesammelt als Bericht geliefert; bei Fehlern wird keine Datei geschrieben (KBOB-Muster)
- REQ-802: G4: Fehlerbericht und CLI-Ausgabe enthalten nur Norm-ID, Ziffern, Feldnamen und Zählungen – nie Normtexte
- REQ-803: Given ein extrahierter Entwurf When die Fachperson die `document.json` vervollständigt (Stufe 2, manuell) Then erzeugt die bestehende Ingest-Pipeline (M2) unverändert Kandidaten mit Fundstelle
