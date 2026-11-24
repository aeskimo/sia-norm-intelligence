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

## M8 – Consumer-App (Web-UI auf dem SNI-Kern; siehe 09_CONSUMER_APP.md)
- REQ-800: `python -m sni.app` startet die UI als Fenster (pywebview), Browser (`--browser`) und Headless (`--headless`); UI und API same-origin auf `127.0.0.1` (kein CORS)
- REQ-801: SIA-Login (SOAP-Port: ECHO, `getLizenzDatei`, `getDocument_Byte`; Provider SIA/VSS/PHGR/SWKI; stabile Device-ID) liefert den Katalog inkl. Status; Protokoll-Fehlercodes werden 1:1 weitergegeben
- REQ-802: Zugangsdaten und Schlüssel liegen im cross-platform Keyring (Service `ch.sia.normenassistent`, Accounts `sia-login`/`gibb-api-key`/`state-key`); "Merken" ist opt-in und beim Start wird automatisch eingetragen; Keyring-Migration ist ein expliziter 3-OS-Test (macOS: Java-Einträge unter gleichem Service/Account lesbar; Windows/Linux: keine Java-Einträge — Java schrieb nur auf macOS)
- REQ-803: Dokument-Download (`.srd`→DES→PDF) landet im verschlüsselten Session-Cache; Registry mit Statusfluss `CACHED→INDEXING→FULLTEXT_READY/HYBRID_READY/ERROR`; Entfernen löscht Cache und Index
- REQ-804: Analyse-Pipeline (PDF-Extraktion via Fixture-Gate: **pypdfium2 und pdfminer.six** laufen gegen dieselbe Java-Baseline, das Gate entscheidet welche bleibt; PyMuPDF ausgeschlossen, AGPL; invertierter Volltext-Index, Vektorindex via Ollama `/api/embed` Batch 32, Chunk 600/60, Hybrid RRF k=60); verschlüsselte Index-Persistenz; Extraktionsqualität ≥ Java-Baseline (Ziffern-Erkennungs-Rate auf Fixtures)
- REQ-805: RAG-QA mit `[Qn]`-Quellenblöcken, Zitat-Validierung, Aussageklassen und Abweisung zitatabweissloser Antworten; Streaming via SSE
- REQ-806: Ollama-Modellverwaltung (List/Pull/Delete) mit Loopback-Zwang
- REQ-807: gibb-Provider (HTTPS-only, Bearer aus Keyring, `/models` + `/chat/completions` SSE); der API-Key verlässt das Backend nie
- REQ-808: Einstellungen und Arbeitssets persistent im User-Datenverzeichnis (`workspace.json`, atomar)
- REQ-809: Review-Queue-API + UI: Kandidaten listen, Freigeben (menschlicher Akt, `approved_by`+`approved_at`, `source.verified=true`, Move nach `extracted/`), Ablehnen; nie automatisch (G3); `approved_by` = konfigurierte Freigabeperson (Settings), wenn nicht gesetzt einmalige Frage beim ersten Freigeben (OS-Username allein gilt als schwacher Audit-Eintrag), optionaler Override im Dialog
- REQ-810: Semantik-Export (deterministischer Port, G1/G5) erzeugt `document.json` und triggert den Ingest in-process → Kandidaten + Gaps
- REQ-811: Projektdaten-UI: CSV/IFC-Upload → `POST /v1/projectdata` → `POST /v1/check` → BCF-/IDS-Export
- REQ-812: Norm-Intelligence-UI: Frage → `POST /v1/answer` mit Aussageklasse-Chip, Claims, Fundstellen und Disclaimer
- REQ-813: CI auf ubuntu/macos/windows (jeweils `make check`) + Installer via PyInstaller (EXE / .app / AppImage)
- REQ-814: Design-Baseline: SIA-Design-Tokens (CSS), WCAG 2.1 AA (Kontrast ≥ 4.5:1, Mindest-Font 12 px), Dark Mode via `prefers-color-scheme`, Fenster-Fit 1200×800
- REQ-815: Migration des Java-Stands beim ersten Start: `workspace.state` (SIASST1) → `workspace.json`, `*.siaidx` (SIAIDX01) → `.sniidx` (Byte-kompatibler Importer); Keychain-Einträge: macOS lesbar unter gleichem Service/Account (Test), Windows/Linux ohne Java-Einträge (dokumentierte Abwesenheit)
- REQ-816: App-API-Sicherheit (nur `app_mode`): zufälliger freier Port pro Start (Fenster-/Browser-Modus), Session-Token (Launcher → UI, Pflicht auf `/v1/*`), `Host`-Header muss loopback sein, nicht-same-origin `Origin` wird abgelehnt (Schutz gegen CSRF/DNS-Rebinding, G4)
- REQ-817: Packaging-Smoke in M8.1: minimale App (Hello Window) wird in der CI auf ubuntu/macos/windows gebaut und gestartet (PyInstaller + pywebview; WebView2/WebKitGTK); echte Installer inkl. Code-Signing/Notarization (OQ-014) in M8.6

## M9 – Echte Normdokumente: PDF-Extraktion (OQ-003, ADR-0010)
- REQ-900: Given ein PDF unter `data/norms/<norm-id>/document.pdf` When `make extract NORM=<norm-id>` Then entsteht `document.draft.json` mit Ziffern-Skelett (Ziffernnummern am Zeilenanfang, deterministisch) und extrahiertem Ziffern-Text; Fachfelder bleiben leer; der Entwurf ist validiert gegen `document_draft.schema.json`
- REQ-901: Extraktion ist atomar: alle Fehler werden gesammelt als Bericht geliefert; bei Fehlern wird keine Datei geschrieben (KBOB-Muster)
- REQ-902: G4: Fehlerbericht und CLI-Ausgabe enthalten nur Norm-ID, Ziffern, Feldnamen und Zählungen – nie Normtexte
- REQ-903: Given ein extrahierter Entwurf When die Fachperson die `document.json` vervollständigt (Stufe 2, manuell) Then erzeugt die bestehende Ingest-Pipeline (M2) unverändert Kandidaten mit Fundstelle
