# 08 – Externe Referenzprojekte

Nicht bindende Referenzmaterialien. Für jedes Projekt die Fragen: **Was können wir
lernen? Was können wir übernehmen?** (Kein Code-Übernehmen ohne Lizenz-Prüfung.)

Stand der Recherche: 2026-11-23.

## 1. KBOB Data Dictionary (github.com/KBOB-admin)

Drei Repositories für Data Dictionaries im Bauwesen (Schweiz, LINDAS-Umfeld):

| Repo | Rolle | Lizenz |
|---|---|---|
| `KBOB-data-dictionary` | Excel-Vorlagen + Validierungs-Pipeline (GitHub Actions), Statusmodell WIP/SHARED/PUBLISHED/ARCHIVED | LICENSE.md prüfen |
| `KBOB-data-dictionary-schema` | Normative Quelle: RDF-Kernvokabular "NatDD" (Turtle), 0.1 Public Review Draft | CC0-1.0 |
| `KBOB-data-dictionary-schemaforge` | Publikationspipeline: validierte Mappen → RDF/Turtle (LINDAS) + I14Y-JSON-Bundle | prüfen |

### Strukturen, die an uns erinnern (Vergleich)

- Statusmodell `WIP → SHARED → PUBLISHED → ARCHIVED` (an ISO 19650 angelehnt) ↔ unser
  `review_status` `candidate → reviewed → approved` (+ `rejected`).
- Separation: Validator prüft **Struktur**, Schema-Repo definiert **Bedeutung** (RDF) ↔
  unsere Trennung `schemas/` (Vertrag) vs. Kataloginhalt (Bedeutung, gehört zum
  Datenkatalog-Projekt, nicht zu uns).
- Aufbau der Struktur orientiert sich an ISO 23386 (Data Dictionary), ISO 23387
  (Metadaten), ISO 12006 (FM-Klassifikation), DCAT.

### Was wir lernen können (mit Bezug zu unseren Milestones)

1. **Append-only-Versionierung (→ M1, M7).** DCAT-Modell: `dcat:DatasetSeries` als
   stabile Reihe, `dcat:Dataset` als unveränderliches Release, SemVer in der
   Release-IRI, `dcat:hasVersion` / `isVersionOf` / `previousVersion`. Bewusst **kein**
   veränderlicher `hasCurrentVersion`-Zeiger (veränderliche Metadaten gehören nicht in
   Append-only-Artefakte; "aktuell" aus der SemVer-Reihenfolge bestimmen). Das ist genau
   unser Prinzip aus `04_DATA_MODEL.md` ("IDs sind unveränderlich, Änderungen erzeugen
   neue Versionen") – KBOB zeigt, wie es maschinenlesbar sauber umgesetzt wird.
2. **Validierung als CI mit maschinenlesbaren Berichten (→ M1, REQ-101).** Validierung
   läuft per GitHub Actions pro Commit, erzeugt JSON- und Markdown-Berichte als
   Artefakte plus eine validierte Arbeitsmappe mit system-generierten Rückschreibungen
   (abgeleitete IDs, Normalisierungen). Muster für unseren Import: atomar ablehnen mit
   strukturiertem Fehlerbericht.
3. **Trennung von validiert und publiziert (→ M2, M7).** Publikation ist ein expliziter,
   standardmäßig **Dry-Run**-Schritt; echte Publikation nur mit explizitem Befehl und
   Zugangsdaten. Passt zu G3 (Mensch gibt frei) und G4 (Lizenz).
4. **Standardvokabulare wiederverwenden statt neu erfinden (→ M7).** RDF, RDFS, OWL,
   DCAT, Dublin Core, **SKOS**, **PROV-O**, **QUDT**. Unser M7-Plan (Turtle/SKOS-Export)
   und QUDT für Einheiten/Merkmale (unser `unit`-Feld) sind damit direkt anschlussfähig.
   PROV-O als Muster für unsere Provenienz (`SourceReference`).
5. **I14Y-JSON-Bundle als Exportformat (→ M7, offen).** SchemaForge exportiert ein
   I14Y-orientiertes JSON-Bundle für Katalog-/Import-Workflows. I14Y ist ein offener
   Standard für semantische Datenbeschreibungen im Bauwesen – möglicher zweiter
   Export-Target neben Turtle/SKOS (siehe OQ-001).
6. **Reproduzierbarkeitsprinzipien (→ Projektorganisation).** Im Repo nur Artefakte mit
   Reproduzierbarkeitswert; keine venvs, keine generierten Outputs, keine Caches. Wir
   machen dasselbe (`reports/eval_*.json` gitignoriert, `data/norms/` gar nicht im Repo).
7. **Namespace-Policy (→ M7).** Provisorischer Namespace mit dokumentierter
   Migrations-Verpflichtung und "kein stilles Wiederverwenden". Vorbild für unsere
   `sia:`-Namespace-Regeln, falls sich der Datenkatalog-Namespace noch ändert.

### Was wir nicht übernehmen

- Excel-basierte Erfassung (unsere Verträge sind JSON/YAML, `schemas/` ist die Wahrheit).
- RDF als Speicherformat (Speicher bleibt JSON/YAML + SQLite; RDF nur als Export).
- LINDAS-spezifische Publikation (für uns nicht relevant).

## 2. AEC Open Source Directory (opensource-construction/osc-directory)

Kuratiertes Verzeichnis + Web-App (MIT) für Open-Source-Projekte im AEC-Umfeld
(Architecture, Engineering, Construction). 44 Stars, aktiv gepflegt (800+ Commits).
Beitrag via GitHub-Issue-Form (`docs/submit-a-project.md`).

### Was wir lernen / tun können

- **Beitrags-Workflow als Muster** (Issue-Form → Review → Aufnahme in kuratierte
  Tabelle): übertragbar auf unser GapReport-Feedback an das Datenkatalog-Projekt.
- **Verteilkanal:** SIA Norm Intelligence (und ggf. das Datenkatalog-Projekt) kann sich
  dort eintragen lassen – Sichtbarkeit im AEC-OSS-Umfeld.

### Relevante Projekte aus dem Verzeichnis

| Projekt | Relevanz für uns |
|---|---|
| **bSDD-Toolkit** (c-mellueh, Nachfolger von SOM-Toolkit) | bSDD-Alignment; unser `concept.schema.json` kennt bereits `mappings: {ifc, bsdd}` → zentral für M7-Mappings/Export |
| **ifc-ids-mcp** (IfcOpenShell) | IDS (IFC-based Specification) + IfcTester als MCP-Server → Referenz für M5 (IFC-Adapter) und Regelprüfung gegen Projektdaten |
| **BetterCorrectFast** | BCF (BIM Collaboration Format) in Python → direkt relevant für **REQ-702** (Prüfergebnisse als BCF-Topic exportieren) |
| **IfcOpenShell** | Bereits festgeschrieben in ADR-0002 – Verzeichnis bestätigt die De-facto-Standardstellung |
| **bim-open-schema** (ara3d) | BIM-Daten als Parquet → nur für spätere Großdaten-Ansätze interessant |
| **Speckle2Graph** | Pipeline Speckle → Graph-Datenbank (RDF/Neo4j) → Muster für M7-Graph-Export |
| **MagmaWorks Taxonomy** | Taxonomie-Interfaces für statische Objekte → Referenz, wie `Concept`/`Property`/`Relation`-Strukturen in anderen Domänen aussehen |
| **BIMserver** | Java-BIM-Plattform; nur als Ökosystem-Referenz |

## 3. Entscheidungsnotizen

- **Keine Code-Übernahme für M1–M4** geplant; alle Referenzen sind Muster/Anschlussstellen.
- **Beim Start von M7 (Export):** zuerst anschauen (a) KBOB `schemaforge`-Skripte
  (`map_to_rdf.py`, `export_i14y_json.py`), (b) bSDD-Toolkit, (c) KBOB
  `natdd-core.ttl` als Vorbild für saubere Turtle-Strukturierung.
- **Beim Start von M5 (IFC-Adapter):** `ifc-ids-mcp` (IfcTester-Integration) und
  IfcOpenShell-Beispiele.
- **Bei REQ-702 (BCF-Export):** `BetterCorrectFast` als Referenzimplementierung.
- **Lizenzen:** KBOB-Schema-Repo ist CC0 (uneingeschränkt nutzbar); die übrigen KBOB-
  Repos und alle osc-Verweise einzeln prüfen, bevor auch nur Dateien kopiert werden.
