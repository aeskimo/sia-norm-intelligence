# 09 – Consumer-App (M8): Web-UI auf dem SNI-Kern

**Stand:** 25.11.2026 · **Status:** beschlossen (User-Entscheide OQ-009…012, ADR-0007/0008/0009 akzeptiert 24.11.2026; OQ-015 entschieden 25.11.2026 — M8.3 mit `sia101-2020` + Fixtures)

M8 macht aus dem SNI-Sidecar die vollständige, cross-platform Consumer-App
"SIA-Normenassistent": ein lokales Python/FastAPI-Kern-Programm mit Web-UI,
das die gesamte Java-App (`/SIA-Normenassistent-M2.9`) ersetzt. Die
App läuft auf **Windows, macOS und Linux**, bleibt **local-first** (G4:
lizenzierte Inhalte verlassen die Maschine nicht; einzige Ausnahme ist die
SIA-Shop-Anbindung für Login/Download) und übernimmt die Guardrails
**G1–G7** unverändert.

Basis: Bestandsaufnahmen beider Repos (24.11.2026), Schemas/Endpunkte sind
die Wahrheit (AGENTS.md). Alle hier definierten neuen Endpunkte/Schema/
Abhängigkeiten laufen über **ADR-0007/0008/0009** (Status: vorgeschlagen).

---

## 1. Ziel und Nicht-Ziele

**Ziele**
- Ein installierbares Consumer-Programm pro OS (Doppelklick → Fenster → läuft).
- Eine Codebasis (Python) für Backend und UI — kein zweites Sprach-Team.
- Vollständige Überführung aller Java-Features (siehe §8 Mapping).
- `make check` bleibt die einzige Qualitäts-Tür; CI auf 3 OS.

**Nicht-Ziele (M8)**
- Kein Multi-User, kein Auth-System (Single-User, Loopback-only, G4).
- Kein Cloud-Sync, kein Auto-Update, kein Mobile.
- Kein LLM im Deterministik-Kern (ADR-0003 bleibt gültig).
- Die Java-App bekommt ab M8 **keine** neuen Features mehr (Legacy, §14).

## 2. Produkt-Definition (Consumer)

- **Nutzer:** Fachpersonen (Bauingenieurwesen), keine Entwickler-Affinität
  nötig. Kein Terminal, keine Umgebungsvariablen im Normalbetrieb.
- **Erster Lauf:** Installer → Icon starten → Fenster mit UI → Onboarding
  (SIA-Login, optional: Ollama-Erkennung mit Link zur Installation,
  optional: gibb-API-Key).
- **Sprache:** Deutsch.
- **Darf dauern:** Downloads/Analysen sind explizite Jobs mit Status
  (kein tot wirkendes Fenster).
- **Kein Datenverlust:** Einstellungen, Arbeitssets, Index überleben
  Neustart (wie heute, verschlüsselt bzw. im User-Verzeichnis).

## 3. Ziel-Architektur

```
┌────────────────────────── SIA-Normenassistent (1 Prozess) ──────────────────────────┐
│  python -m sni.app                                                                  │
│  ┌────────────────┐      ┌──────────────────────────────────────────────────────┐  │
│  │ Main-Thread    │      │ Hintergrund-Thread (asyncio/uvicorn)                │  │
│  │ pywebview-     │ HTTP │  FastAPI-App (app_mode=True)                        │  │
│  │ Fenster        ├──────┤  ┌────────────┐  ┌─────────────┐  ┌──────────────┐  │  │
│  │ (127.0.0.1:8000)│      │  │ sni/api    │  │ sni/app     │  │ sni/*        │  │  │
│  │  oder Browser   │      │  │ (Kern-API, │  │ (App-API +  │  │ (shop,        │  │  │
│  │  oder headless  │      │  │  8 End-    │  │  static UI, │  │  documents,   │  │  │
│  └────────────────┘      │  │  punkte,   │  │  SSE)       │  │  extract,     │  │  │
│                           │  │  unverändert│ │             │  │  search, rag, │  │  │
│                           │  └────────────┘  └─────────────┘  │  models,      │  │  │
│                           │  HTTP-Ausläufe (alle Loopback     │  state,       │  │  │
│                           │  ausser SIA-Shop + gibb):          │  secrets,     │  │  │
│                           │  Ollama :11434 · shop.sia.ch ·    │  review,      │  │  │
│                           │  chat.gibb.ch                      │  export/)     │  │  │
│                           └──────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────┘
        │                                              │
        ▼                                              ▼
  User-Datenv. ~/.sia-normenassistent/        Ollama (lokal, separat installiert)
  (Katalog-DB, Knowledge, Regeln, Queue,      SIA-Shop (HTTPS), gibb (HTTPS, opt.)
   Normen-Mount, Index, workspace.json)
```

**Prozess-Modell**
- Ein Prozess. `sni/app/launcher.py`: Main-Thread = Fenster-Loop
  (pywebview; auf macOS muss das Main-Thread sein), Hintergrund-Thread =
  `uvicorn.Server` für die FastAPI-App mit `app_mode=True`.
  Modi: Standard (Fenster), `--browser` (Standardbrowser öffnen),
  `--headless` (nur API, für CI/Tests).
- UI und API sind **same-origin** (UI wird von derselben FastAPI-App
  ausgeliefert; `127.0.0.1` mit **zufälligem freien Port** im
  Fenster-/Browser-Modus, `PORT`/8000 nur in `--headless`) →
  **kein CORS**, keine fixe Port, keine Origin-Probleme. Sicherheit
  der App-API: §10.2 (Session-Token, Host/Origin-Check).
- **Schichten-Regel bleibt erhalten** (03_ARCHITECTURE.md): `sni/app`
  (UI-Delivery + App-API) hängt von `sni/api` und den Fachmodulen ab;
  `sni/api/main.py` bleibt die Kern-API und wird in M8 nicht breiter als
  um die Mount-Vorbereitung. Die 8 bestehenden Endpunkte bleiben
  unverändert (Verträge stehen).

**Neue Module** (`src/sni/`, alle mit Unit-Tests, mypy --strict):

| Modul | Inhalt (Port von Java / neu) |
|---|---|
| `sni/app/` | Launcher (Fenster/Browser/headless), `api.py` (App-Router, §6), `static/` (UI, §5) |
| `sni/shop/` | SIA-Soap-Port: `soap.py` (ECHO/getLizenzDatei/getDocument_Byte, SOAP 1.2 via httpx), `decrypt.py` (DES/CBC, statische Key — Protokoll-Kompatibilität), `catalog_xml.py` (Lizenz-XML → CatalogItems), `providers.py` (SIA/VSS/PHGR/SWKI), `models.py` |
| `sni/documents/` | `registry.py` (Status `CACHED→INDEXING→FULLTEXT_READY/HYBRID_READY/ERROR`), `pdfcache.py` (AES-256-GCM In-Memory, AAD=product_id, Zeroing beim Schliessen — wie Java), `downloads.py` (Job `.srd`→PDF) |
| `sni/extract/` | PDF-Textextraktion: `pdfminer.six` mit `LAParams` (Seiten-Formfeed-Split, Abschnittserkennung) — ersetzt `pdftotext`-Binary |
| `sni/search/` | `fulltext.py` (invertierter TF-Index, Präfixsuche), `vectors.py` (Kosinus), `hybrid.py` (RRF k=60, Evidenz `LEXICAL/SEMANTIC/BOTH`) |
| `sni/rag/` | `grounded.py` (Prompt `[Qn]`-Quellenblöcke, Zitat-Validierung, Klassen `DIRECTLY_SUPPORTED/DERIVED_FROM_MULTIPLE_SOURCES/INSUFFICIENT_EVIDENCE`, Abweisung ohne Zitate), `providers/ollama.py` (`/api/generate` NDJSON→SSE), `providers/gibb.py` (SSE, Bearer, HTTPS-only) |
| `sni/models/` | Ollama-Manager (`/api/tags`, `/api/pull`, `/api/delete`), Loopback-Zwang |
| `sni/state/` | `workspace.py` (workspace.json lesen/schreiben, atomar), `settings.py`, `worksets.py`, `migrate.py` (Import `workspace.state` SIASST1 + `.siaidx` SIAIDX01, §9.4) |
| `sni/secrets/` | `keyring_store.py` (Service `ch.sia.normenassistent`, Accounts `sia-login`/`gibb-api-key`/`state-key` — gleiche Namen wie Java, §10) |
| `sni/review/` | Queue-Service (List/Approve/Reject, G3, ADR-0008) |
| `sni/export/semantic.py` | Semantik-Export-Port (deterministisch, G1/G5) + Ingest-Aufruf in-process |

## 4. Technology-Stack (Entscheidung)

| Schicht | Wahl | Begründung | Abgeworfen |
|---|---|---|---|
| Backend | FastAPI (bestehend, ADR-0002) | steht, getestet | — |
| HTTP-Client (runtime) | **httpx** | modern, synchron+async, MockTransport für Tests | requests (veraltet im Ökosystem) |
| Frontend | **statisches HTML/CSS/JS + HTMX** (vendor-bundled, kein npm) | kein Build-Schritt, passt zu server-gedrehtem FastAPI, offline-fähig, 1 JS-Datei (HTMX) + ~300 Zeilen Vanilla-JS (Streaming, pdf.js-Dialog) | React/Vue+Vite (zweite Toolchain + npm in einem Python-Repo), Jinja-Templates (zu statisch für Streaming/Interaktivität), Electron (Fussabdruck) |
| App-Shell | **pywebview** (System-Webview: WKWebView/WebView2/WebKitGTK) | natives Fenster ohne Rust/Electron, 1 pip-Paket, offline | **Tauri v2** (besser poliert, aber Rust-Toolchain + 2. Build-System → Eskalations-Option, OQ-009), reiner Browser-Tab (kein App-Gefühl; bleibt als `--browser`-Modus) |
| PDF-Extraktion | **pypdfium2 und pdfminer.six** im Fixture-Gate (REQ-804) | beide ohne System-Binary (pypdfium2: Binaries im Wheel, schneller; pdfminer: pure Python, Layout-Parameter wie `pdftotext -layout`); das Gate (Ziffern-Erkennungs-Rate vs. Java-Baseline) entscheidet, welche bleibt | **PyMuPDF ausgeschlossen (AGPL, User-Entscheid)**; Poppler-`pdftotext` (System-Dependency pro OS) |
| Krypto | **cryptography** | AES-256-GCM (App-Daten, wie Java) + DES-CBC (SIA-Protokoll) in einem Paket | stdlib-kein-DES, pycryptodome (2. Paket für 1 Algorithmus) |
| Credentials | **keyring** | cross-platform (macOS Keychain, Windows Credential Manager, Linux Secret Service/KWallet) + File-Fallback | Eigenbau (Fehlerfläche), nur-Datei (unsicher) |
| PDF im Browser | **pdf.js** (vendor-bundled, eine Datei) | ersetzt `TemporaryPdfViewer` (Temp-Datei + OS-App); Bytes bleiben im Prozess | Browser-nativ (unsicher im Webview), pdfium (Native-Abhängigkeit) |
| Streaming | **SSE** (`text/event-stream`) | einfach, durch Proxies stabil, reicht für Token-Stream + Job-Updates; NDJSON (Ollama) und SSE (gibb) werden serverseitig normalisiert | WebSocket (komplexer, kein Mehrwert hier) |
| Packaging | **PyInstaller** (Build-Abhängigkeit, kein Runtime) | pro OS: EXE (Windows), .app (macOS), AppImage (Linux); venv-basiert | Briefcase (jünger), bare venv-Shortcuts (kein Consumer-Erlebnis) |

**Neue Laufzeit-Abhängigkeiten (Gesamt, via ADR-0007):**
`httpx`, `cryptography` (gepinnte Version — (3-)DES-Verfügbarkeit,
§15), `pdfminer.six` **und** `pypdfium2` (REQ-804-Gate entscheidet,
welche bleibt; die andere wird danach entfernt), `keyring`,
`pywebview`.
Dev-Extras: `playwright` (UI-Tests), `pyinstaller` (Build).

## 5. UI

### 5.1 Routen (spiegeln die 6 Java-Tabs)

| Route | Java-Vorgänger | Inhalt |
|---|---|---|
| `/catalog` | Tab 1 Normenkatalog | Login-Card (Provider SIA/VSS/PHGR/SWKI, Kunde, Passwort, Device-ID, "Merken"), Katalog-Tabelle (Norm/Titel/Jahr/Sprache/Gültig bis), Statusfilter, Statuszeile |
| `/norms` | Tab 2 Meine Normen | Lokale Dokumente mit Status + Aktionen (Öffnen [pdf.js-Modal], Analysieren, Entfernen), Cache-Zusammenfassung |
| `/assistant` | Tab 3 Normenassistent | Links: Doku-Liste + Arbeitsset-Verwaltung; rechts: Fragefeld, Antwort-Fläche (Token-Streaming), Quellenliste mit Zitat-Navigation |
| `/intelligence` | Tab 4 Norm Intelligence | Normfrage → Antwort (Klasse-Chip, Claims, Fundstellen, Disclaimer); Semantik-Export; Review-Queue (Freigeben/Ablehnen, G3); Projektdaten (Zeilen, CSV/IFC-Upload, Prüfen, BCF/IDS speichern) |
| `/models` | Tab 5 Lokale Modelle | Ollama-Liste, Pull, Delete, aktives Modell setzen; Ollama-fehlt-Notice mit Installationshinweis (ollama.com; kein Hyperlink — REQ-814 verbietet externe Resources in den UI-Dateien) |
| `/settings` | Tab 6 Einstellungen | Fragemodell, Embeddingmodell, Provider (lokal/gibb), gibb-URL/Modell/API-Key (→ Keyring), Freigabename (G3), Datenverzeichnis, Statusschlüssel-Info |

Navigation: schmale Sidebar (Icon + Label), wie bei modernen Consumer-Apps;
Statuszeile pro Seite (semantischer Farbpunkt, wie `SiaDesign.Status`).

**Bereichshilfe / Onboarding pro View:** Jeder der 6 Arbeitsbereiche
(ohne die Onboarding-View, die selbst die Hilfe ist) trägt einen
«Hilfe»-Button im View-Header, der ein statisches Hilfe-Panel für den
Bereich öffnet (Zweck, typischer Ablauf, häufige Meldungen/Grenzen).
Beim ersten Besuch einer View öffnet sich das Panel automatisch mit
einem Kurz-Hinweis; «Verstanden» merkt sich die Bestätigung pro Bereich
(localStorage), danach bleibt der Button der Zugriff. Der Inhalt ist
statisch und versioniert (`static/help.js`) — kein Backend, offline-
konform (REQ-814: keine externen Resources in den UI-Dateien).

### 5.2 Design-System (SIA-Design → CSS)

Die existierende Java-Design-Schicht wird 1:1 als **CSS Custom Properties**
übersetzt (einheitliche Quelle der Werte):

```css
:root {
  --window: #F5F5F7; --surface: #FFFFFF; --content: #FFFFFF;
  --text: #1D1D1F; --text-secondary: #6E6E73; --hairline: #D2D2D7;
  --accent: #0066E6; --accent-bright: #007AFF;
  --success: #34C759; --warning: #FF9500; --error: #FF3B30;
}
@media (prefers-color-scheme: dark) { /* DARK-Palette identisch zu Java */ }
```

Komponenten (alle als kleine CSS-Klassen, keine Framework-Abhängigkeit):
- **Cards:** Radius 12 px, Surface-Fill, 1 px Hairline, Titel bold 13 pt
- **Buttons:** flach, Accent (weiss auf `#0066E6`) für Primäraktionen,
  sonst dezent (Surface + Hairline); `:hover`/`:active`/`:focus-visible`
  (Fokus-Ring nur tastaturbasiert, `:focus-visible`)
- **Statuszeile:** `●` mit semantischer Farbe (Erfolg/Fehler/Warnung/neutral),
  Klassifikation wie in Java (Fehler-Keywords zuerst, `…` = neutral)
- **Chips** für Aussageklassen (`normativ_belegt` grün, `abgeleitet` blau,
  `fachliche_interpretation`/`projektfestlegung` orange, `nicht_eindeutig` rot)
- **Tabellen:** 26 px Zeilen, horizontale Hairlines nur, Header bold
- **Modals** (PDF-Vorschau, Bestätigungen), **Toasts** (Fehler/Success),
  **Fortschrittsbalken** für Jobs (Download/Analyse/Pull)
- **Dark Mode:** rein via `prefers-color-scheme` (System folgt, kein
  Polling-Thread mehr nötig — der 2-s-Lag entfällt)
- **Schrift:** System-Font-Stack (`-apple-system, "Segoe UI", Roboto,
  "Helvetica Neue", sans-serif`), Basis 14 px

### 5.3 Barrierefreiheit & Grösse (REQ-814)

- WCAG 2.1 AA: Kontrast ≥ 4.5:1 (alle Kombinationen im Test berechnet,
  wie im Java-GUI-Selftest), Mindestfont 12 px (Praxis 14 px),
  Tastaturbedienbarkeit, `aria-live` für Statuszeile/Streaming.
- Mindestfenster 1200×800, responsive bis 1024 px Breite.

## 6. API

### 6.1 Bestehend (unverändert, Verträge stehen)

`GET /healthz`, `GET /v1/concepts/{id}`, `POST /v1/answer`,
`POST /v1/check`, `POST /v1/projectdata`, `GET /v1/export/catalog`,
`POST /v1/export/ids`, `POST /v1/export/bcf`.

### 6.2 Neue App-Endpunkte (ADR-0007/0008/0009)

Alle nur in `app_mode=True` gemountet (`sni/app/api.py`), Loopback-only.
Sicherheit: §10.2 (zufälliger Port, Session-Token, Host/Origin-Check).

| Methode | Pfad | Zweck |
|---|---|---|
| `GET` | `/` + `/static/*` | UI (HTML/CSS/JS/vendor) |
| `GET` | `/v1/status` | App-Zustand: Ollama erreichbar?, Login-Sitzung?, Doku-Zählung, Jobs, Versions-String → `sni:status` |
| `POST` | `/v1/session/login` | `{provider, customer, password, device_id, remember}` → ECHO+Login → `{status, catalog[]}`; `remember=true` → Keyring; Fehler-Codes des SIA-Protokolls 1:1 (`Fail_NO_User`, `Fail_Wrong_PWD`, `Unkown_Device_ID` [sic], `Account_disabled`, `Account_deleted`, `Max_allowed_Device_IDs`) |
| `POST` | `/v1/session/logout` | Sitzungs-Authentifizierung verwerfen (Zeroing) |
| `GET` | `/v1/catalog` | Katalog der aktuellen Sitzung → `[sni:catalog_item]` |
| `POST` | `/v1/documents/download` | `{product_id}` → async Job (`.srd`→DES→PDF in Session-Cache) |
| `GET` | `/v1/documents` | Registry → `[sni:local_document]` |
| `GET` | `/v1/documents/{id}` | Detail inkl. Job-State |
| `DELETE` | `/v1/documents/{id}` | Cache + Index entfernen |
| `POST` | `/v1/documents/{id}/analyze` | async Job: Extraktion → Volltext- → Vektorindex (ohne Body → konfiguriertes Embedding-Modell; leeres `embedding_model` → nur Volltext) |
| `GET` | `/v1/documents/{id}/pdf` | Session-PDF-Bytes (`application/pdf`) — nur während Sitzung (G4-Policy bleibt) |
| `POST` | `/v1/ask` | `{question, scope: {document_ids?, workset_id?}}` → **SSE**: `token`-Events, finales `answer`-Event (`sni:rag_answer`) |
| `GET/POST` | `/v1/worksets`, `PUT/DELETE /v1/worksets/{id}` | Arbeitssets → `sni:workset` |
| `GET` | `/v1/models/ollama` | `GET /api/tags` weiterreichen |
| `POST` | `/v1/models/ollama/{name}/pull` | async Job (2-h-Timeout wie Java) |
| `DELETE` | `/v1/models/ollama/{name}` | Modell löschen |
| `GET` | `/v1/models/gibb` | gibb-Modellliste (OpenAI `models`, Bearer aus Keyring; 1:1 Java-«Modelle auflisten»: nur Key + Basis-URL nötig, Modell-Platzhalter `temp`) → `{available, models[]}` |
| `GET/PUT` | `/v1/settings` | `sni:settings` (Modelle, Provider, gibb-URL/Modell, Freigabename); gibb-Key nie als Antwort (nur `gibb_key_set: true`) |
| `POST` | `/v1/ingest/semantic-export` | `{norm_id}` (product_id des lokalen Dokuments) → deterministischer Export → `document.json` → Ingest in-process → `{norm_id, candidates[], skipped[], gaps[]}` |
| `GET` | `/v1/review/queue` | Kandidaten (`norm_statement`, `review_status=candidate`) + GAPs |
| `POST` | `/v1/review/{id}/approve` | `{approved_by?}` → `approved` + `approved_at` + `source.verified=true`, Move nach `extracted/` (G3, ADR-0008) |
| `POST` | `/v1/review/{id}/reject` | Kandidat verwerfen (G3) |
| `GET` | `/v1/jobs` | Job-Queue → `[sni:job]` (UI pollt alle 2 s) |

**Semantik-Export-Antwort (`/v1/ingest/semantic-export`):** `norm_id`
maschinenlesbar (z. B. `sia416-2003`); `candidates` = Kandidaten-IDs,
`skipped` = Übersprungs-Gründe (Ziffer-/Tabelle-Nummer + Grund), `gaps` =
GAP-IDs — nie Normtexte (G4). Export und Ingest laufen in-process auf dem
gleichen Daten-Mount wie die Kern-CLI (`data/norms/`, `data/review_queue/`).
Voraussetzungen: Login, Dokument in der lokalen Registry, Katalog nicht
leer, Norm indexiert (Volltextseiten vorhanden).

**Streaming-Vertrag (`/v1/ask`):** ein SSE-Stream mit Event-Typen
`token` (Text-Zeilstück), `sources` (Quellenblöcke), `answer`
(final, `sni:rag_answer`), `error`. Ollama-NDJSON und gibb-SSE werden
serverseitig in diese Form normalisiert (1 Stream-Adapter pro Provider).

**Jobs:** eine Queue, max. 1 paralleler Analyse-Job (Consumer-Maschine);
`{id, kind: download|analyze|pull, document_id?, status: queued|running|
done|error, progress?, error?}`; Status per Polling (genug für Consumer;
keine WebSocket-Komplexität).

### 6.3 Neue Schemas (`schemas/`, Draft 2020-12, `$id: sni:*`)

`sni:status`, `sni:catalog_item`, `sni:local_document`, `sni:job`,
`sni:workset`, `sni:settings`, `sni:rag_answer`.
(Review-Queue-Wiedergabe reusing `sni:norm_statement`/`sni:gap_report` —
keine neuen Schemas.) Alle fachlichen Antworten tragen `disclaimer` (G6).

## 7. Verbindungen & Anschlüsse (Integrations-Matrix)

| Gegenstelle | Protokoll | Richtung | Sicherheit |
|---|---|---|---|
| Browser/Shell | same-origin HTTP auf `127.0.0.1:<zufälliger Port>` | einseitig | Loopback-Bindung + Session-Token + Host/Origin-Validierung (§10.2), CSP `self` |
| Ollama | HTTP `127.0.0.1:11434` (`/api/tags`, `/api/embed` Batch 32, `/api/generate` NDJSON, `/api/pull`, `/api/delete`) | aus | Loopback-Zwang (Code-Check wie Java, `SecurityError` bei anderem Host) |
| SIA-Shop | **SOAP 1.2** `https://shop.sia.ch/Secure_Webservice/` (`srDefault.asmx` ECHO; `srLizenz.asmx` getLizenzDatei; `srDokument.asmx` getDocument_Byte), Provider-Profile SIA/VSS/PHGR/SWKI | aus (die einzige externe Fach-Verbindung) | HTTPS; Credentials im SOAP-Body (Protokoll); DES/CBC-Kette `.mro`/`.srd` (statische Key — **Protokoll-Kompatibilität**, dokumentierte bekannte Schwäche, kein einseitiges Ändern); Device-ID stabil (UUID in workspace.json, "Max_allowed_Device_IDs" beachten) |
| gibb | HTTPS `https://chat.gibb.ch/api` (`GET /models`, `POST /chat/completions` SSE, Bearer) | aus (opt.) | HTTPS-only, Key aus Keyring, **Key wird nie an die UI ausgeliefert** (Backend-Proxy) |
| Dateisystem | User-Datenv. (§9) | — | App-Daten verschlüsselt (Index), Nonce je Speicherung, atomare Schreibweise |

## 8. Logik-Migration (Java → Python, 1:1)

| Java (Klasse) | Python (Modul) | UI-Element | Ende |
|---|---|---|---|
| `SiaSoapClient`, `SiaProductService`, `CatalogParser`, `ProviderProfile` | `sni/shop/*` | Login-Card, Katalog-Tabelle | `POST /v1/session/login`, `GET /v1/catalog` |
| `SessionDocumentCache` (AES-GCM, AAD) | `sni/documents/pdfcache.py` | (intern) | `GET /v1/documents/{id}/pdf` |
| `TemporaryPdfViewer` | pdf.js-Modal | "Öffnen"-Dialog | dito |
| `LocalDocumentRegistry/State/Status` | `sni/documents/registry.py` | "Meine Normen"-Liste | `GET /v1/documents` |
| `PdftotextExtractor` (Poppler) | `sni/extract/` (pdfminer.six) | Analyse-Job | `POST /v1/documents/{id}/analyze` |
| `LocalFullTextIndex`, `LocalVectorIndex`, `HybridSearchService` (RRF k=60) | `sni/search/*` | (intern, Trefferbasis) | — |
| `DocumentEmbeddingService` (Chunk 600/60, Batch 32), `OllamaEmbeddingProvider` | `sni/search/vectors.py` + `sni/models/` | (intern) | — |
| `GroundedQa` ([Qn]-Prompt, Zitat-Validierung, Abweisung) | `sni/rag/grounded.py` | Fragefeld, Antwort, Quellen | `POST /v1/ask` (SSE) |
| `OllamaProvider` (NDJSON), `OpenAiCompatibleProvider` (gibb SSE) | `sni/rag/providers/*` | Token-Streaming | dito |
| `OllamaModelManager` | `sni/models/` | "Lokale Modelle"-Tab | `GET/POST/DELETE /v1/models/ollama/*` |
| `AppModelSettings`, `WorksetStore`, `WorkspaceCodec` | `sni/state/*` | "Einstellungen", Arbeitssets | `GET/PUT /v1/settings`, `/v1/worksets` |
| `CredentialStore`/`GibbApiKeyStore`/`KeychainStateKeyProvider` (+`SecurityCommand`) | `sni/secrets/keyring_store.py` | "Merken"-Checkboxen, Auto-Fill | via `login`/`settings` (Keyring) |
| `SemanticExporter` (deterministisch) | `sni/export/semantic.py` | "Semantik-Export"-Button | `POST /v1/ingest/semantic-export` |
| `SniRepo` (Subprocess `sni.ingest`/`sni.catalog`) | **in-process**-Aufruf (`sni.ingest.pipeline`) | (entfällt als Subprocess) | dito |
| Review-Queue (Dateibewegung von Hand) | `sni/review/` (Endpoints) | Review-Queue-Liste + Freigeben/Ablehnen | `GET /v1/review/queue`, approve/reject |
| `IntelligenceClient` (7 Methoden) | Browser ruft die Kern-API **direkt** auf (same-origin) | "Norm Intelligence"-Tab | `/v1/answer`, `/v1/check`, `/v1/projectdata`, `/v1/export/*` |
| `ProjectDataCsv` | existiert bereits (`sni/projectdata/csv_adapter.py`) | CSV/IFC-Upload-Dialog | `POST /v1/projectdata` |
| `SiaDesign` (749 Zeilen Swing) | CSS-Design-Tokens + HTMX-Komponenten (§5) | alles | — |

**Nicht migriert (wegfällt):** `.app`-Bash-Launcher, Dark-Mode-Polling-
Thread, Java-Selftest-Harness (→ pytest, §12), Demo-Apps
(`AssistantDemoApp`, `LocalNormWorkspace`, `ModelManagerApp`,
`LoginProbeCli` → CLI-Äquivalent bleibt optional in `sni/app/cli.py`).

## 9. Datenlayout & Persistenz

### 9.1 User-Datenverzeichnis (ADR-0009)

Ein Verzeichnis auf allen drei OS (Migration-kompatibel zu Java):
`~/.sia-normenassistent/` (Windows: `%USERPROFILE%\.sia-normenassistent`,
Linux: `$HOME/.sia-normenassistent`), Override `SIA_DATA_DIR`.

```
~/.sia-normenassistent/
├── catalog/catalog.db            # SQLite (sni:concept), wie im Repo
├── extracted/*.json              # approved NormStatements/Regeln
├── rules/*.json                  # Regeln
├── review_queue/*.json           # Kandidaten (G3)
├── norms/<norm-id>/document.json # Semantik-Export-Zwischenformat (lokal)
├── index/<product_id>.sniidx     # verschlüsselter Index (AES-256-GCM, AAD=product_id)
└── workspace.json                # Einstellungen + Arbeitssets + device_id (non-secret)
```

`create_app()` wird beim App-Start mit diesen Pfaden gefüttert
(Parameter existieren bereits: `db_path`, `knowledge_dir`, `rules_dir`;
Queue/Norms-Dir analog). Das Repo-`data/` bleibt für Entwicklung/CLI.

### 9.2 Policy (bleibt, Lizenzposition nicht ändern)

- **PDF-Bytes: session-only** (In-Memory, verschlüsselt, Zeroing) — wie
  Java; keine Platten-Persistenz (Status-Quo, OQ-012/013 entschieden
  24.11.2026).
- **Index: persistiert, verschlüsselt** (enthält Seitentext — G4).
- **workspace.json: non-secret** (Modellnamen, Arbeitssets) → Klartext-
  JSON, atomar (temp+move). Der Java-`SIASST1`-Verschlüsselungszweck
  (Konfig-Schutz) entfällt dadurch; der State-Key wird weiterhin
  für den Index gebraucht.

### 9.3 Key-Kette

Env `SIA_STATE_KEY_B64` → sonst Keyring (Account `state-key`).
Neu erzeugen: Button in `/settings` (wie Java), Base64-32-Byte.

### 9.4 Migration vom Java-Stand (REQ-815)

Beim ersten Start der App (wenn `workspace.json` fehlt, aber
`workspace.state`/`*.siaidx` existieren):
1. `workspace.state` (MAGIC `SIASST1`, AES-GCM) dechiffrieren →
   `workspace.json` schreiben (Modellnamen, Arbeitssets).
2. `*.siaidx` (MAGIC `SIAIDX01`, Zeilen `doc=/pages=/page=/model=/
   vectors=/vector=`, float32-Big-Endian) → Byte-kompatiblen Importer
   (gleicher Codec, neuer Dateiname `.sniidx`) — Test: Roundtrip +
   Fixture-Gleichheit.
3. Keychain-Einträge: **nur auf macOS relevant** (Java schrieb via
   `security`-Binary; Windows/Linux hatten keinen Keychain-Store) —
   Details und 3-OS-Test in §10.1.

### 9.5 Lizenz-Policy: Status-Quo (entschieden 24.11.2026)

Die Lizenz-Linie wird **genau so weitergeführt wie bis jetzt** —
entschieden durch den Produkt-Owner (Mitglied der Arbeitsgruppe
SIA-Datenkatalog, 24.11.2026); **keine separate Nachfrage bei der
SIA** (OQ-012/013 beantwortet):

- **Lizenzierte PDFs: session-only** (In-Memory, verschlüsselt,
  Zeroing) — keine Platten-Persistenz.
- **Verschlüsselter Index (enthält Seitentext): persistent** in
  `~/.sia-normenassistent/index/` — wie der Java-Ist-Zustand.
- Konsequenz: kein Persistenz-Feature in M8; der Java-Migrations-
  Pfad (REQ-815) bleibt wie definiert (Index-Import, keine
  PDF-Übernahme).

## 10. Credentials & Security

### 10.1 Keyring (ADR-0009)

Service `ch.sia.normenassistent`, Accounts `sia-login` (Payload
`b64url(customer)|b64url(password)` — gleiches Format wie Java),
`gibb-api-key`, `state-key`. Fallback ohne Secret-Service (Linux
minimal): `keyring`-File-Backend mit Warnung in `/settings`.

**Migration (REQ-802):** Java schrieb Credentials nur auf macOS (via
`security`-Binary). macOS → Einträge unter gleichem Service/Account
lesbar (Test). Windows/Linux → keine Java-Einträge vorhanden (Test
dokumentiert die Abwesenheit). **Keine Annahme, sondern gesicherter
3-OS-Test in M8.3.**

### 10.2 App-API-Sicherheit (REQ-816)

`127.0.0.1` schützt nicht vor anderen lokalen Prozessen und nicht
vor Browser-Tabs (CSRF, DNS-Rebinding). Die App-API (nur
`app_mode=True`) ist deshalb dreifach abgesichert:

1. **Zufälliger freier Port** pro Start (Fenster-/Browser-Modus,
   `socket.bind(0)`); `--headless` verwendet `PORT`/8000 für Tests.
   Vermeidet zusätzlich Port-Konflikte mit anderen lokalen Diensten.
2. **Session-Token:** Der Launcher erzeugt `sia_token =
   secrets.token_urlsafe(32)` und übergibt es an die UI als
   `?sia_token=` (bleibt erhalten, da die UI same-origin ist). Alle
   `/v1/*`-Endpunkte (Kern- und App-API) verlangen das Token als
   Query-Parameter oder Header `X-Sia-Token`; fehlend/falsch → 401.
   Query-Parameter, weil SSE (`EventSource`) keine Header setzen
   kann. Die UI hält das Token nur in JS-Memory (nicht
   localStorage) — es lebt bis zum App-Neustart. Static-UI und `/`
   brauchen kein Token (das Token kommt über die URL).
3. **Host/Origin-Validierung (Middleware):** Der `Host`-Header muss
   `127.0.0.1:<Port>` bzw. `localhost:<Port>` sein — eine
   DNS-Rebinding-Domain, die auf 127.0.0.1 zeigt, taucht im
   `Host`-Header unter ihrem Namen auf → 403. Ein vorhandener
   `Origin`-Header muss same-origin sein (CSRF via fremder
   Webseite) → sonst 403. `/healthz` bleibt offen (kein Inhalt).

Ohne `app_mode` (reine Sidecar-Nutzung in Dev/CLI) ist der
Token-Check inaktiv (Rückwärtskompatibilität zu REQ-000…702).

### 10.3 Loopback-G4

Server bindet nur `127.0.0.1`; Ollama-/SNI-Zugriffe prüfen den Host
wie Java; SIA-Shop + gibb sind die einzigen externen HTTPS-Ziele
(Fachdaten bleiben lokal; gibb erhält nur Prompt mit
Quellen-Zitaten — Policy wie heute). **CSP** `default-src 'self'`
auf der UI (keine externen Resources — läuft komplett offline).

### 10.4 Sekrete in API-Antworten

Nie: gibb-Key nur als `gibb_key_set: true`; SIA-Passwort nur im
Login-Request, danach im Keyring bzw. verworfen (Zeroing).

### 10.5 DES-CBC (SIA-Protokoll)

Bekannt schwach, aber einseitig nicht änderbar (shop.sia.ch);
dokumentiert in `sni/shop/decrypt.py`. App-seitige Krypto bleibt
AES-256-GCM. **Auflösendes Ergebnis (2026-11-24, REQ-801):**
pyca/cryptography bietet keinen öffentlichen Single-DES (Klasse in
neueren Versionen entfernt, auf 50.0.2 verifiziert); der Port nutzt
die dokumentierte Äquivalente `TripleDES` mit 24-Byte-Schlüssel
`k + k + k` (EDE mit identischen Teilkeys ≡ Single DES) — nicht
betroffen von der 45.0.0er-Deprecation für 8/16-Byte-Keys.
`cryptography>=46,<51` ist **gepinnt** (Obergrenze gegen künftige
TripleDES-Entfernung). Protokoll-Kompatibilität sichert der
Known-Answer-Test mit Java-Referenzwerten (Vektoren erzeugt von
`SrdKeyUnwrapper`/`DES/CBC/PKCS5Padding` unter JDK 25, synthetische
`.mro`/`.srd`-Fixtures — G4: keine echten Lizenzdateien) — grün auf
cryptography 50.0.2 ohne Warnungen (`test_req801_des_kat.py`).

**Leniente US-ASCII-Klartextsemantik (Produktionsbefund 2026-11-25):**
`unwrap_srd_value` liest den DES-Klartext exakt wie die Java-Referenz:
`new String(plain, US_ASCII)` — Bytes ≥ 0x80 werden stillschweigend zu
`?` (0x3F) und sind **kein Fehler**. Nachgewiesen: Java- und
Python-Client erhalten vom Produktivportal byte-identisches
Schlüsselmaterial (Ciphertext- und Klartext-SHA-256 über beide Clients
deckungsgleich, geräte-/zeitunabhängig), der individuelle Schlüssel des
Testkunden enthält genau ein nicht-ASCII-Byte, und die Java-App
entschlüsselt die Norm-PDFs korrekt mit dem `?`-ersetzen Schlüssel —
die Legacy-Pipeline (Portal-PDF-Verschlüsselung + 2015er-Reader)
verwendet durchgängig diese Semantik. Der frühe strikte ASCII-Check war
eine Port-Abweichung und hat funktionierende Portal-Logins blockiert;
die 1:1-Regel ist per KAT (KatGen2-Vektor, Output der echten
Java-`unwrap()` per SHA-256 kreuzverifiziert) abgesichert.

## 11. Cross-Platform

| Thema | macOS | Windows | Linux |
|---|---|---|---|
| Fenster | WKWebView (pywebview) | WebView2 (in Win11 enthalten) | WebKit2GTK (Paket-Hinweis in Doku) |
| Keyring | Keychain | Credential Manager | Secret Service/KWallet (Fallback File) |
| Daten | `~/.sia-normenassistent` | dito (`%USERPROFILE%`) | dito |
| Installer | PyInstaller `.app` (onedir, unsigned) | PyInstaller onefile EXE (unsigned; NSIS = Option) | PyInstaller onedir + AppImage (unsigned) |
| Ollama | separat installiert (Onboarding-Link) | dito | dito |

**CI** (`.github/workflows/ci.yml`): Matrix `ubuntu-latest`,
`macos-latest`, `windows-latest` (Windows via `make.cmd`, existiert) —
alle mit `make check`. Zusätzlich ab **M8.1** der Packaging-Smoke-Test
(REQ-817): minimale App (Hello Window) wird auf jedem Matrix-OS gebaut
und gestartet — das Packaging-Risiko (PyInstaller + pywebview,
WebView2/WebKitGTK) fällt so in Woche 1 auf, nicht nach
fünf Feature-Steps.

**Unsigned-Installer (M8.6, OQ-014 ausgelagert):** Ab M8.6 baut die CI
die echten Installer (`.app` / onefile-EXE / AppImage) auf allen drei
OS, aber **ohne Code-Signing und Notarization** (User-Entscheid
25.11.2026: Signing komplett auslagern, OQ-014 bleibt offen/TODO und
ist als M10 in 05_MILESTONES.md geplant).
Folgen für die Erstnutzung:

- **macOS:** Gatekeeper meldet «unverifizierter Entwickler» →
  Rechtsklick auf die App → «Öffnen», einmalig bestätigen.
- **Windows:** SmartScreen zeigt «unbekannter Herausgeber» →
  «Weitere Informationen» → «Trotzdem ausführen».
- **Linux:** AppImage zusätzlich `chmod +x` (Standard, signing-unabhängig).

**M10-Signing-Setup (CI-Gerüst vorhanden, Credentials TODO):** Die
Signing-Steps stehen in der CI (`installers`-Job, zwischen Build und
Smoke) und greifen nur, wenn die zugehörigen Flags gesetzt sind
(Setup in Repo-Settings → Settings → Security → Secrets and variables →
Actions):

- **macOS (REQ-1000):** Variablen `MACOS_SIGNING_ENABLED=true`,
  `MACOS_SIGNING_IDENTITY` (z. B. `Developer ID Application: NAME
  (TEAMID)`), `APPLE_TEAM_ID`; Secrets `MACOS_SIGNING_CERT`
  (base64-`.p12`), `MACOS_SIGNING_CERT_PASSWORD`, `APPLE_ID`,
  `APPLE_APP_PASSWORD`. Skript: `packaging/sign/macos_sign.sh`
  (Temp-Keychain → codesign hardened-runtime → notarytool `--wait` →
  staple; Notarization-JSON → Artefact).
- **Windows (REQ-1001):** Variable `WINDOWS_SIGNING_ENABLED=true`;
  Secrets `WINDOWS_SIGNING_CERT` (base64-`.pfx`),
  `WINDOWS_SIGNING_CERT_PASSWORD`. Skript:
  `packaging/sign/windows_sign.sh` (signtool SHA-256 + TSA;
  verify-Ausgabe → Artefact).

Ohne Flags bleibt der M8.6-Zustand (unsigned + o. Hinweise)
bestehen; die Pipeline wird nie an fehlenden Credentials gehängt
(REQ-1002).

**Credential-Erstellung (M10):**
- **macOS:** Schlüsselverwaltung → «Developer ID Application: NAME»
  (mit privatem Schlüssel) → als `.p12` exportieren (Passwort setzen)
  → `base64 -i cert.p12` → `MACOS_SIGNING_CERT`. Identity-String und
  Team-ID: `security find-identity -v -p codesigning` (bzw.
  developer.apple.com → Members → Team ID). App-spezifisches
  Passwort: appleid.apple.com → «Anmeldung und Sicherheit» →
  «App-spezifische Passwörter».
- **Windows:** Zertifikat mit privatem Schlüssel als `.pfx`
  exportieren (Zertifikatsmanager / `certutil -exportpfx`) →
  base64-codieren → `WINDOWS_SIGNING_CERT`. Hinweis: EV-Zertifikate
  liegen oft auf Hardware-Token — dann muss im
  `packaging/sign/windows_sign.sh` der zugehörige signtool-Provider
  ergänzt werden (Teil des M10-Akzeptanzlaufs).

## 12. Teststrategie

- **Unit/Integration (pytest, existierendes Muster):** je Modul;
  HTTP-Abhängigkeiten via `httpx.MockTransport` bzw. lokaler
  Mock-Server auf `127.0.0.1:0` (wie die Java-Selftests).
- **Portierte Java-Selftests (27 Klassen) → pytest-Module:**
  login-SOAP (Mock, Retry), Produkt-Inkremente, Ollama-Manager (Mock),
  Unified-QA (Halluzinations-Abweisung!), PDF-Extraktion (synthetische
  Fixture), Embedding/Chunking, Hybrid-RRF, Ollama-Streaming (Mock),
  gibb-SSE (Mock), Pipeline, Navigation/Zitate, Worksets, Registry,
  Statusfilter, verschlüsselte Persistenz (Roundtrip), Index-Cache
  (Codec + Migration-Importer), Keyring (Fake-Backend, analog
  `SIA_FAKE_KEYCHAIN`), Keyring-Migration 3-OS (REQ-802), GUI-Checks
  → Playwright.
- **Extraktions-Gate (OQ-010):** synthetische Norm-PDF-Fixture (wie
  `test-data/synthetic/sample-standard.pdf`); **pypdfium2 und
  pdfminer.six** müssen der Java-`pdftotext`-Baseline gleichwertig
  sein (Ziffern-Erkennungs-Rate auf der Fixture, Test gesichert); das
  Gate entscheidet, welche Engine bleibt.
- **DES-Roundtrip (Known-Answer-Test, REQ-801):** synthetische
  `.mro`/`.srd`-Fixtures (G4: keine echten lizenzierten Dateien im
  Repo) mit Werten aus der Java-Implementierung (bekannte statische
  Key/IV) → sichert die Protokoll-Kompatibilität trotz gepinnter
  `cryptography`-Version.
- **UI (Playwright, Dev-Extra):** 5 Flows — Login→Katalog,
  Download→Analyse (Job-Status), Frage→gestreamte Antwort mit Quellen,
  Review-Freigabe (G3), Dark-Mode-Switch; plus Design-Baseline-Checks
  (Kontrast ≥ 4.5:1, Mindest-Font, 1200×800-Fit) analog zum
  Java-GUI-Selftest (43 Checks → übertragbar als Playwright-Assertions).
- **Gate:** `make check` (ruff, ruff format, mypy --strict, pytest,
  Schema-Validierung, Coverage `sni.core` ≥ 90 %). Neue Module:
  Coverage-Ziel 90 % analog (OQ: in PROGRESS dokumentieren).

## 13. Milestones (Details in 05_MILESTONES.md M8)

| Step | Inhalt | REQ |
|---|---|---|
| M8.1 | App-Shell (3 Modi), UI-Gerüst 6 Routen, Design-Tokens, Dark Mode, `/v1/status`, **App-API-Sicherheit** (Port/Token/Host/Origin) + **Packaging-Smoke auf 3 OS in CI** (Hello Window) | 800, 814, 816, 817 |
| M8.2 | SIA-Login (SOAP-Port), Keyring, Katalog, Download + Session-PDF + Registry | 801, 802, 803 |
| M8.3 | Analyse-Pipeline (Extraktions-Gate pypdfium2 vs. pdfminer.six, Indexe, RRF), RAG-QA + Streaming, Migration-Import + Keyring-3-OS-Test | 802, 804, 805, 815 |
| M8.4 | Ollama-Manager, gibb-Provider, Einstellungen/Arbeitssets | 806, 807, 808 |
| M8.5 | SNI-Kern in der App: Review-Queue (G3), Semantik-Export, Projektdaten-UI, Intelligence-UI | 809–812 |
| M8.6 | Cross-Platform-CI (3 OS), echte Installer (PyInstaller: EXE / .app / AppImage, **unsigned** — Signing/Notarization ausgelagert: OQ-014), Onboarding — Packaging-Grundrisiko bereits in M8.1 verifiziert | 813 |

**DoD pro Step:** alle REQ als Test grün, `make check` auf 3 OS,
PROGRESS.md aktualisiert, ADRs akzeptiert, Screenshots/UI-Checks wie
im Java-Projekt (Screenshot + nicht-blank).

## 14. Disposition Java-App

- `SIA-Normenassistent-M2.9` wird **Legacy/Referenz**: keine neuen
  Features; dokumentiert in deren `DEVELOPMENT-STATUS.md`.
- Sie bleibt als Laufzeit-Referenz für das Migrations-Verhalten (z. B.
  SOAP-Protokoll-Verhalten) bis M8.6 fertig; danach nur noch Support.
- Das `.app`-Bundle/Bash-Launcher wird durch den M8-Installer ersetzt.

## 15. Risiken & Mitigation

| Risiko | Mitigation |
|---|---|
| PDF-Extraktion < Java-Baseline (Semantik-Export bröckelt) | Fixture-Gate in M8.3 mit pypdfium2 **und** pdfminer.six; Fallback: Verlierer-Engine tauschen → Poppler-Option → Re-Decision (OQ-010) |
| 8 von 9 Pilot-PDFs ohne Textschicht (reine Vektorgrafik, 0 extrahierbare Zeichen; nur `sia101-2020` liefert Text) | M9-Pilot-Befund 2026-11-23 (OQ-015, ADR-0010): REQ-804 (M8.3) ist für diese 8 Normen blockiert — weder pypdfium2 noch pdfminer.six kompensieren eine fehlende Textschicht; OCR ist v1-ausserhalb (ADR-0010). **Entschieden 2026-11-25 (User, OQ-015):** M8.3 fährt mit `sia101-2020` (die 1 Norm mit Textschicht) + synthetischen Fixtures; die 8 textlosen Normen bleiben als blockiert/`ERROR` in der Dokument-Registry (sichtbarer Status in der UI). SIA-Neuexport mit Textschicht bleibt offenes externes Thema (User-Anfrage), ohne dass M8.3 darauf wartet; geplant als M11 (OCR-Fallback: M12). M8.2 und M8.4–M8.5 sind davon nicht betroffen |
| SIA-Protokoll-Drift (SOAP, DES, Timeouts) | Protokoll-Tests mit Mock (Java-Verhalten referenziert); Retry-Logik 1:1 (1× nach 500 ms); DES per Known-Answer-Test gegen Java-Werte gesichert (REQ-801) |
| `cryptography` entfernt (3-)DES (auf 50.x verifiziert: Single-DES-Klasse weg) | **Gelöst (REQ-801):** `TripleDES(k+k+k)` mit 24-Byte-Key ≡ Single DES, kein Deprecation-Pfad; `cryptography>=46,<51` gepinnt; KAT gegen Java-Referenzwerte grün (2026-11-24) |
| Keyring ohne Secret-Service (Linux) | File-Fallback + sichtbare Warnung; Doku |
| Keyring-Migration Windows/Linux (Java schrieb nur macOS) | Expliziter 3-OS-Test in M8.3 (REQ-802); wo kein Java-Eintrag existiert, ist nichts zu migrieren — dokumentiert statt angenommen |
| Packaging (PyInstaller + pywebview, WebView2/WebKitGTK, Signing) | Früh-Test M8.1 (REQ-817, 3-OS-CI, Hello Window) statt Erst-Test in M8.6; Signing/Notarization = OQ-014 |
| pywebview/WebKitGTK-Versionen (Linux) | CI-Matrix + Mindestversions-Hinweis; `--browser`-Modus als Ausweichweg |
| gibb-Key/Externe-Abhängigkeit | App läuft vollständig ohne gibb (Ollama-only-Pfad bleibt) |
| Lizenz-Policy (PDF-Persistenz + verschlüsselter Index) | Status-Quo entschieden (OQ-012/013, 24.11.2026): PDFs session-only, Index persistent; keine SIA-Nachfrage, kein Stillstand-Risiko |
| Grosser Migrationsumfang | 6 kleine Steps mit je eigenem DoD; Java-App bleibt als Referenz bis M8.6 |

## 16. Verweise

- ADR-0007 (Web-UI-Stack) · ADR-0008 (Review-Queue-API) ·
  ADR-0009 (Datenlayout/Credentials) — alle akzeptiert 24.11.2026
  per User-Entscheid
- OQ-009…OQ-013 (beantwortet, User-Entscheide 24.11.2026) ·
  OQ-014 (Code-Signing/Notarization: **ausgelagert**, User-Entscheid
  25.11.2026 — M8.6 baut unsigned Installer, Signing = TODO, geplant als
  M10; Gatekeeper/SmartScreen-Hinweise in §11) ·
  OQ-015 (beantwortet, User-Entscheid 25.11.2026: M8.3 mit
  `sia101-2020` + Fixtures, 8 textlose Normen als blockiert/ERROR)
- 03_ARCHITECTURE.md (Schichten) · 04_DATA_MODEL.md (Lebenszyklen) ·
  07_GUARDRAILS.md (G1–G7) · AGENTS.md (§5 Abhängigkeiten, §6 DoD)
