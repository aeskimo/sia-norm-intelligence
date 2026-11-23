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
- Blockiert: – (beantwortet; REQ-501 umgesetzt in M5)
- Status: beantwortet (Empfehlung A übernommen, 2026-11-23)
- Antwort: ADR-0004 (2026-11-23): neues Schema `schemas/check_result.schema.json`
  (`$id: sni:check_result`, Draft 2020-12). `POST /v1/check` liefert
  `{"checks": [...], "gaps": [...], "disclaimer": ...}`; pro Regel `rule_id`,
  `status` (pass|fail|insufficient_data), `reason` (Begründung, REQ-501),
  `value`/`claimed`/`unit`, `missing_inputs`, `derived_from` (Fundstelle der
  Regel). `gaps` = GapReports `missing_project_data` (REQ-502). Nur approved
  Regeln werden geprüft (G3). Stateless API: GAP-IDs pro Antwort fortlaufend
  vergeben; Persistenz mit stabilen IDs = M7 (REQ-702, BCF-Export).

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
- Blockiert: – (beantwortet; REQ-501 umgesetzt in M5)
- Status: beantwortet (Empfehlung A übernommen, 2026-11-23)
- Antwort: ADR-0004 (2026-11-23): Konsistenzprüfung für M5. Das Projekt
  liefert die Pflicht-Inputs der Regel und einen Wert für das
  Output-Konzept; die M3-Engine leitet den Wert ab. Gleich
  (math.isclose, rel_tol 1e-6, abs_tol 1e-9) → pass, unterschiedlich →
  fail, fehlende Werte (Pflicht-Input oder Output-Wert) →
  insufficient_data; Engine-Fehler (Einheitenkonflikt, Ausdrucksdefekt) →
  fail mit Engine-Bericht als Begründung. `pass` bedeutet Konsistenz der
  Projektdaten mit der Regel, keine Normkonformität; Constraint-/
  Grenzwertfelder in rule.schema.json (Option B) = Follow-up-ADR, sobald
  fachlich konkret (z. B. "GF ≤ 5000 m2").

## OQ-006: Technisches Design des M7-Export-Moduls (Abhängigkeiten, Endpunkte)
- Kontext: 05_MILESTONES.md M7 (REQ-700/701/702); AGENTS.md §5 (keine neuen
  Laufzeit-Abhängigkeiten ohne ADR); 03_ARCHITECTURE.md (Export-Endpoints ab
  M7, `api/` ohne Fachlogik). Verifizierte Zielformate (2026-11-23,
  Quellen): BCF 2.1 = XML in ZIP, offizielle Spec buildingSMART/BCF-XML
  (release_2_1, XSDs geprüft: `bcf.version` VersionId="2.1", optionale
  `project.bcfp`, `<topic-guid>/markup.bcf` mit Pflichtfeldern
  Guid/Title/CreationDate/CreationAuthor; File-Extension `.bcf`); IDS 1.0
  = XML, buildingSMART/IDS (v1.0.0, ids.xsd geprüft: `<ids>` mit `<info>`
  + `<specifications>`, je `<specification name ifcVersion identifier>`
  mit `<applicability>` + `<requirements>`, Facets entity/partOf/
  classification/attribute/property/material, cardinality
  required|optional|prohibited, Werte-Einschränkungen via
  xs:restriction, keine arithmetischen Ausdrücke); KBOB natdd-core.ttl
  (CC0) als Turtle-Stil-Vorbild.
- Frage: Welches technische Design für die drei Exporte: welche
  Laufzeit-Abhängigkeiten, welche Modulstruktur, welche API-Endpunkte?
- Optionen: A) Keine neuen Laufzeit-Abhängigkeiten: handgeschriebene
  Serialisierer in neuem Modul `src/sni/export/` (`skos.py`, `ids.py`,
  `bcf.py`), stdlib-only (`json`, `zipfile`, `xml.etree.ElementTree`);
  `api/` verdrahtet nur die Endpunkte.
    - REQ-700: `GET /v1/export/catalog?format=json|ttl[&snapshot=<id>]`;
      JSON = Array schemakonformer Concepts + `disclaimer`; TTL =
      handgeschriebenes Turtle (SKOS-Mapping nach OQ-007).
    - REQ-702: `POST /v1/export/bcf` mit CheckPayload (wie `POST
      /v1/check`); Endpoint läuft die Prüfung intern (approved Regeln,
      G3) und exportiert nur `fail`-Ergebnisse als BCF-Topics; Response:
      binäre `.bcf`-Datei (ZIP); `reason`, `derived_from` (Fundstelle),
      value/claimed/unit und G6-Disclaimer in `Description` des Topics;
      `pass`/`insufficient_data`-Ergebnisse werden nicht exportiert.
    - REQ-701: `POST /v1/export/ids` mit `{"rule_ids": [...]}` (leer =
      alle approved Regeln); Response: JSON `{"ids_xml": <IDS-XML-String
      oder null>, "gaps": [GapReport], "disclaimer"}` (Kriterien:
      OQ-008).
    - Nur `approved`-Objekte werden exportiert (G3, wie Check-Service).
  B) Laufzeit-Abhängigkeiten ergänzen (z. B. `rdflib` für Turtle/SKOS,
  `bettercorrectfast` für BCF); weniger handgeschriebener Code, aber neue
  Abhängigkeiten (ADR-Pflicht gemäss AGENTS.md §5) und
  Abhängigkeitsketten (BetterCorrectFast = lokal vendorer Fork der
  IfcOpenShell-bcf-Bibliothek).
- Empfehlung Agent: A – AGENTS.md §5 verbietet neue Laufzeit-Abhängigkeiten
  ohne ADR, und keines der drei Formate verlangt sie: BCF 2.1 = drei
  kleine XML-Dateien (XSD-geprüft), IDS 1.0 = eine XML-Datei
  (XSD-geprüft), Turtle = handgeschreibbar (KBOB-Vorbild, CC0). stdlib
  `zipfile` + `ElementTree` genügen; die exakten Felder dokumentiert
  ADR-0005.
- Blockiert: – (beantwortet; Umsetzung in M7, REQ-700/701/702)
- Status: beantwortet (User-Entscheid Option A, 2026-11-23)
- Antwort: ADR-0005 (2026-11-23), Option A: keine neuen
  Laufzeit-Abhängigkeiten; neues Modul `src/sni/export/`
  (`skos.py`, `ids.py`, `bcf.py`, nur stdlib: `json`, `zipfile`,
  `xml.etree.ElementTree`); `api/` verdrahtet nur die Endpunkte:
  `GET /v1/export/catalog?format=json|ttl[&snapshot=<id>]`
  (REQ-700), `POST /v1/export/bcf` mit CheckPayload – läuft die
  Prüfung intern (approved Regeln, G3) und exportiert nur
  `fail`-Ergebnisse als BCF 2.1-Topics (binäre `.bcf`-ZIP-Response)
  (REQ-702), `POST /v1/export/ids` mit `{"rule_ids": [...]}`
  (leer = alle approved) – Response `{"ids_xml", "gaps",
  "disclaimer"}` (REQ-701). Nur approved-Objekte werden exportiert
  (G3); jede Export-Antwort trägt den G6-Disclaimer.

## OQ-007: SKOS/RDF-Mapping und Namespace für den TTL-Export (REQ-700)
- Kontext: schemas/concept.schema.json (name/definition mehrsprachig
  de/fr/it, abbreviation, quantity_type, unit, relations mit fünf Typen
  part_of/has_part/specialization_of/derived_from/related_to, mappings
  als freies Objekt, catalog_snapshot); KBOB natdd-core.ttl (CC0: eigenes
  Vokabular `dd:` für Nicht-SKOS-Felder, skos/dcterms/dcat als
  Standardvokabular, provisorischer Namespace mit dokumentierter
  Migrations-Policy); 08_REFERENCES.md Punkt 4 (Standardvokabular
  wiederverwenden: DCAT, Dublin Core, SKOS, PROV-O, QUDT).
- Frage: Wie werden die fünf Relationstypen und die Zusatzfelder (unit,
  quantity_type, mappings, catalog_snapshot) auf RDF abgebildet, und
  welche Namespace-IRIs werden für die Prefixe `sia:` (Concept-IDs) und
  `sni:` (eigene Properties) verwendet?
- Optionen: A) Standardvokabular dort, wo eine 1:1-Semantik besteht,
  sonst eigenes `sni:`:
    - name → `skos:prefLabel` (sprachgetaggt @de/@fr/@it)
    - definition → `skos:definition` (sprachgetaggt)
    - abbreviation → `skos:altLabel`
    - specialization_of → `skos:broader` (spezialisierter Concept zeigt
      auf den allgemeineren)
    - part_of → `dcterms:isPartOf`; has_part → `dcterms:hasPart`
    - derived_from → `prov:wasDerivedFrom`
    - related_to → `skos:related`
    - unit → `sni:unit`; quantity_type → `sni:quantityType` (Strings)
    - mappings → `sni:mappings` auf Blank-Node mit je einer Property pro
      Key (z. B. `sni:ifc`, `sni:bsdd`)
    - catalog_snapshot → `sni:catalogSnapshot`
    - Concept-IRI: Prefix `sia:` → `https://sia-norm-intelligence.dev/sia/`
      (Concept-IDs sind dadurch bereits IRIs); Header: je Snapshot ein
      `skos:ConceptScheme` (IRI ab Snapshot-ID) + `dcterms:title`,
      Concepts via `skos:inScheme`.
  B) Minimal: nur `skos:Concept` + `skos:prefLabel` + `skos:definition`
  standardisiert; alle übrigen Felder (inkl. aller fünf Relationstypen)
  als `sni:`-Eigendefinitionen.
- Empfehlung Agent: A – 08_REFERENCES.md Punkt 4 weist explizit auf
  Wiederverwendung von Standardvokabularen (insb. PROV-O für Herleitung,
  Dublin Core für Teil-von-Relationen); jeder der fünf Relationstypen
  hat eine vertretbare Standard-Gegenstelle ohne Semantik-Verzerrung;
  `sni:` beschränkt sich auf die vier Felder ohne Standard-Gegenstück
  (KBOB-Vorbild: eigenes Vokabular für Nicht-SKOS-Felder). Namespaces:
  `sia:` → `https://sia-norm-intelligence.dev/sia/`, `sni:` →
  `https://sia-norm-intelligence.dev/ns/`, beide provisorisch mit
  dokumentierter Migrations-Policy (KBOB-Vorbild: Namespace kann vor
  Publikation migrieren; Migrationsweg via IRI-Aliase in ADR + TTL-Header).
- Blockiert: – (beantwortet; Umsetzung in M7, REQ-700)
- Status: beantwortet (User-Entscheid Option A, 2026-11-23)
- Antwort: ADR-0005 (2026-11-23), Option A: Standardvokabular,
  wo 1:1-Semantik besteht, sonst `sni:`: name →
  `skos:prefLabel` (@de/@fr/@it), definition → `skos:definition`,
  abbreviation → `skos:altLabel`, specialization_of →
  `skos:broader`, part_of → `dcterms:isPartOf`, has_part →
  `dcterms:hasPart`, derived_from → `prov:wasDerivedFrom`,
  related_to → `skos:related`, unit → `sni:unit`,
  quantity_type → `sni:quantityType`, mappings → `sni:mappings`
  (Blank-Node mit je einer Property pro Key),
  catalog_snapshot → `sni:catalogSnapshot`. Namespaces
  (provisorisch, Migrations-Policy gemäss KBOB-Vorbild): `sia:` →
  `https://sia-norm-intelligence.dev/sia/` (Concept-IDs sind
  dadurch IRIs), `sni:` → `https://sia-norm-intelligence.dev/ns/`;
  je Snapshot ein `skos:ConceptScheme`, Concepts via
  `skos:inScheme`.

## OQ-008: IDS-Mappier-Kriterium für Regeln (REQ-701)
- Kontext: 05_MILESTONES.md M7 REQ-701 ("wo abbildbar, sonst GapReport
  `not_ids_expressible`"); schemas/rule.schema.json (inputs/output =
  concept + unit, expression, applicability, derived_from); IDS 1.0
  (buildingSMART/IDS v1.0.0): `<specification>` mit `<applicability>` +
  `<requirements>`, Facets entity/attribute/property (propertySet +
  baseName)/material/partOf/classification mit cardinality und
  xs:restriction-Werteinschränkungen – **keine arithmetischen
  Ausdrücke**, abgeleitete Größen (z. B. `Teilsfläche A + Teilsfläche
  B`) sind in IDS nicht maschinenprüfbar; concept.schema.json `mappings`
  = freies Objekt (Benchmark-Concepts aktuell ohne ifc-Mapping);
  gap_report.schema.json kennt `not_ids_expressible` + target_layer
  `mapping` (keine Schema-Änderung nötig).
- Frage: Wann gilt eine Regel als "abbildbar", welche Form muss die
  IFC-Mapping-Information eines Concepts haben, und wie verlaufen
  nicht-abbildbare Regeln?
- Optionen: A) Abbildbar = alle Input-Concepts UND das Output-Concept
  tragen die IFC-Mapping-Form
  `mappings.ifc = {"entity": "…", "property_set": "…", "base_name": "…"}`
  (Dreier-Tupel, IFC4). Export pro abbildbaren Regeln: je ein
  `<specification name=<Rule-ID> identifier=<Rule-ID>
  ifcVersion="IFC4">` mit applicability = entity-Facet des
  Output-Concepts; requirements = property-Facet (cardinality=required)
  je Input- und Output-Concept; Herleitung (expression),
  applicability-Text, Fundstelle (derived_from) und G6-Disclaimer in
  `description`/`instructions` (menschenlesbar, in IDS nicht
  maschinenprüfbar). Alle übrigen Regeln → GapReport
  `not_ids_expressible` (target_layer=mapping, evidence=[Rule-ID],
  description = benennt die Concepts ohne vollständiges ifc-Mapping).
  Endpoint: `POST /v1/export/ids` (OQ-006), Response enthält `ids_xml`
  (alle abbildbaren Regeln in einer Datei) + `gaps`.
  B) Maximale Teilabbildung: jede Regel wird IDS-Specification (so viele
  Facets wie möglich; fehlendes Mapping → kein Facet, Hinweis im
  description); Gap nur, wenn kein Concept abbildbar ist.
  C) Konservativ: v1 keine Regel abbildbar (alle approved Regeln ohne
  vollständiges ifc-Mapping) → immer GapReport; Mapping = Follow-up.
- Empfehlung Agent: A – maschinenprüfbar abbilden, wo die Daten es
  zulassen, sonst ehrlicher Gap (G5: schwächere Klasse bei Zweifel). Das
  Kriterium ist deterministisch, und beide Zweige sind testbar: Gap-Zweig
  mit der bestehenden approved-Benchmark-Regel
  `sia:rule/syn1-2020/gf-summe` (deren Concepts haben kein
  ifc-Mapping); abbildbarer Zweig mit neuem synthetischen Fixture
  (Concepts mit ifc-Mapping, z. B. `IfcSpace`/`Pset_SpaceCommon`/
  `GrossFloorArea` – Platzhalter, G4). Die Tuple-Form von `mappings.ifc`
  dokumentiert ADR-0005; das freie `mappings`-Objekt bleibt
  schema-unverändert.
- Blockiert: – (beantwortet; Umsetzung in M7, REQ-701)
- Status: beantwortet (User-Entscheid Option A, 2026-11-23)
- Antwort: ADR-0005 (2026-11-23), Option A: eine Regel ist
  abbildbar, wenn alle Input-Concepts UND das Output-Concept
  `mappings.ifc = {"entity", "property_set", "base_name"}`
  (Dreier-Tupel, IFC4) tragen. Je abbildbarer approved Regel ein
  `<specification ifcVersion="IFC4" name=<Rule-ID>
  identifier=<Rule-ID>>`: applicability = entity-Facet des
  Output-Concepts; requirements = property-Facet (cardinality
  required) je Input- und Output-Concept; expression,
  applicability-Text, Fundstelle (derived_from) und G6-Disclaimer
  in `description`/`instructions` (menschenlesbar, in IDS nicht
  maschinenprüfbar). Alle übrigen approved Regeln → GapReport
  `not_ids_expressible` (target_layer=mapping, evidence=[Rule-ID],
  description benennt die betroffenen Concepts). Keine
  Teilabbildung (G5: schwächere Klasse bei Zweifel).
