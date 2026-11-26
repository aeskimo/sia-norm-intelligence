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
- REQ-817: Packaging-Smoke in M8.1: minimale App (Hello Window) wird in der CI auf ubuntu/macos/windows gebaut und gestartet (PyInstaller + pywebview; WebView2/WebKitGTK); echte (unsigned) Installer in M8.6 (Code-Signing/Notarization ausgelagert: OQ-014, TODO)

## M9 – Echte Normdokumente: PDF-Extraktion (OQ-003, ADR-0010)
- REQ-900: Given ein PDF unter `data/norms/<norm-id>/document.pdf` When `make extract NORM=<norm-id>` Then entsteht `document.draft.json` mit Ziffern-Skelett (Ziffernnummern am Zeilenanfang, deterministisch) und extrahiertem Ziffern-Text; Fachfelder bleiben leer; der Entwurf ist validiert gegen `document_draft.schema.json`
- REQ-901: Extraktion ist atomar: alle Fehler werden gesammelt als Bericht geliefert; bei Fehlern wird keine Datei geschrieben (KBOB-Muster)
- REQ-902: G4: Fehlerbericht und CLI-Ausgabe enthalten nur Norm-ID, Ziffern, Feldnamen und Zählungen – nie Normtexte
- REQ-903: Given ein extrahierter Entwurf When die Fachperson die `document.json` vervollständigt (Stufe 2, manuell) Then erzeugt die bestehende Ingest-Pipeline (M2) unverändert Kandidaten mit Fundstelle

## Post-v1-Milestones (geplant, 25.11.2026 — User-Entscheid: offene Fäden aus der v1-Abschliessung als Meilensteine festschreiben)

## M10 – Distribution-Readiness: Code-Signing & Notarization (OQ-014)
Voraussetzung (User, extern): Apple-Developer-Programm (Developer ID Application) + Windows-Code-Signing-Zertifikat (OV oder EV); Credentials als CI-Secrets (nie im Repo).
- REQ-1000: macOS: die `.app` wird mit Developer ID signiert (Binary-Level + App-Level), notarisiert (`notarytool`: submit → wait → Log-Verifikation) und gestapelt; Akzeptanz: Start auf einem frischen macOS ohne Gatekeeper-Warnung und ohne Quarantäne-Block
- REQ-1001: Windows: EXE wird Authenticode-signiert; Akzeptanz: SmartScreen zeigt den bekannten Publisher (OV: nach Schwellenwert, EV: ab dem ersten Start)
- REQ-1002: CI: der `installers`-Job signiert nur bei vorhandenen Secrets (bedingte Steps); ohne Secrets bleibt der M8.6-Zustand (unsigned + Doku-Hinweis 09 §11) — die Pipeline wird nie an fehlenden Credentials gehängt
- REQ-1003: Nachvollziehbarkeit: Signing-/Notarization-Logs werden als zusätzliches Artifact hochgeladen; 09 §11 + OQ-014 (09 §16) auf «entschieden/umgesetzt» aktualisiert

## M11 – Vollständiger Pilot-Satz: echte Normen mit Textschicht (ADR-0010 Stufe 1+2, OQ-015-Rest)
Voraussetzung (extern): SIA-Neuexport der 8 textlosen PDFs mit Textschicht (User-Anfrage, 09 §15).
- REQ-1100: When die neuen PDFs vorhanden sind Then Re-Extraktion aller 9 Pilot-Normen (`make extract`); Akzeptanz: Ziffern-Skelette stabil gegen die Druckausgabe (nur Zählungen/Ziffernvergleich, G4), keine Regression gegen die M9-Baseline
- REQ-1101: Stufe 2 (manuell): `document.draft.json` → `document.json` für alle 9 Normen vervollständigen, `make ingest` pro Norm; Akzeptanz: alle 9 Normen `FULLTEXT_READY` in der Registry, Suche/RAG (REQ-804) über den vollen Pilot-Satz nutzbar
- REQ-1102: Falls die SIA keine Textschicht liefern kann: Entscheid M12 (OCR) wird dokumentiert und das Milestone schliesst mit dem dokumentierten Fallback

## M12 – OCR für PDFs ohne Textschicht (nur bei M11-REQ-1102-Fallback)
- REQ-1200: ADR für die OCR-Engine (Lizenzprüfung gemäss AGENTS.md §5, Qualitäts-Baseline gegen den Textschicht-Weg); ausschliesslich lokale Verarbeitung (G4: kein Normtext über das Netzwerk)
- REQ-1201: `make extract NORM=<id> --ocr` (explizites Opt-in): nur für PDFs ohne Textschicht; mit Textschicht bleibt der M9-Weg unverändert
- REQ-1202: Akzeptanz: ≥ 8 von 9 Pilot-Normen liefern ein Ziffern-Skelett, das der Textschicht-Extraktion qualitativ entspricht; Fehlerbericht G4-konform (nur Zählungen/Feldnamen)

## M13 – Stufe 3: LLM-gestützte Vervollständigung (ADR-0010 Stufe 3, eigener Meilenstein gemäss ADR)
Voraussetzung (extern): ADR-0003-Freigabe (SIA: Endpoint ohne Trainingsnutzung, Konfiguration `SNI_LLM_ENDPOINT`) — erfüllt (akzeptiert 2026-11-26, freigegebener Endpunkt: gibb).
- REQ-1300: LLM-Tool schlägt die Stufe-2-Fachfelder (Aussageklasse, Obligation, Zusammenfassung, Konzepte) aus dem Ziffern-Text des Entwurfs vor; Akzeptanz: nichts landet ohne menschliche Freigabe in der `document.json` (G1/G3)
- REQ-1301: ausschliesslich freigegebene Modelle/Endpunkte (ADR-0003); Normtext verlässt die lokale Umgebung nur Richtung des konfigurierten Endpoints
- REQ-1302: ADR-0003 auf «akzeptiert» führen, Stufe 3 in ADR-0010 umsetzen und dokumentieren
- REQ-1303: Consumer-App-Endpunkt `POST /v1/ingest/llm-complete` + Intelligence-View-Karte (M13.1): Stufe 3 über die App-Einstellungen (gibb-Provider aus `workspace.json` + Keyring) statt `SNI_LLM_*`-Env; Akzeptanz: Vorschlag `document.llm.json`, `document.json` und Review Queue unberührt (G3), Antwort ohne Normtexte (G4)

Implementierung (M13, 2026-11-26): `make llm NORM=<norm-id>` (`python -m sni.ingest llm <norm-id>`, `src/sni/ingest/llm_complete.py`). Konfiguration: `SNI_LLM_ENDPOINT` (Basis-URL, z. B. `https://chat.gibb.ch/api`), `SNI_LLM_MODEL` (Modell-ID), `SNI_LLM_API_KEY` (Bearer-Schlüssel; Fallback: Keyring-Account `gibb-api-key`); HTTPS-Zwang (HTTP nur Loopback). Input: `document.draft.json` (Stufe 1) — `norm`/`edition` müssen bereits manuell (Stufe 2) belegt sein; pro Ziffer geht ausschliesslich der Ziffern-Text plus Concept-Katalog an den Endpunkt. Manuell vollstaendig belegte Ziffern werden uebernommen (keine Ueberschreibung); Ziffern ohne Text, teilweise belegte Fachfelder und nicht im Katalog existierende Concept-IDs sind Fehler (KBOB: nichts wird geschrieben). Output: `document.llm.json` (Vorschlag, gegen den document.json-Vertrag validiert per Ingest gegen temporäre Queue); Uebernahme als `document.json` und `make ingest` bleiben menschliche Akte (G3).

Implementierung (M13.1, 2026-11-26): `POST /v1/ingest/llm-complete` (`src/sni/app/api.py`) — 1:1 `make llm`, Konfiguration aus den App-Einstellungen statt Env: Provider muss `gibb` sein (ADR-0003, sonst 400), Basis-URL/Modell aus `workspace.json` (Defaults wie Assistent), API-Key aus `GIBB_API_KEY`/Keyring `gibb-api-key`; `norm_id` = product_id des lokalen Dokuments, Mount wie beim Semantik-Export (`norm_id_for`). Intelligence-View: neue Karte «LLM-Vervollstaendigung (Stufe 3, Vorschlag)» (Norm-Auswahl teilt `/v1/documents` mit dem Semantik-Export, Report mit Zaehlungen, G3-Hinweis in der Karte); `ConceptStore.db_path`-Property fuers Katalog-Pfad. Provider-Fehler (HTTP-Status, Netzwerk) werden pro Ziffer als KBOB-Fehler gesammelt (400 mit Bericht statt 500; KBOB: nichts geschrieben). 12 Endpunkt-Tests (REQ-1303): 401/404/400-Konfigpfade, Happy Path (Vorschlag geschrieben, document.json/Queue unberuehrt, G4-Marker), manuell belegte Ziffer ohne LLM-Aufruf, G1-Concept-Abbruch (nichts geschrieben), Keyring-Key-Pfad, Provider-Fehler → 400 (statt 500); + 3 KBOB-Tests im Kern (REQ-1300).
