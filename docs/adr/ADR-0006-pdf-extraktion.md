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
     Ziffern-Text je Ziffer. Der Ziffern-Text ist eine lokale
     Arbeitshilfe für die Vervollständigung und kein Teil des
     document.json-Vertrags (dort gilt: `summary` = eigene
     Zusammenfassung, kein Normzitat). Der gesamte Entwurf wird
     gegen ein neues Schema validiert (siehe unten in diesem Punkt).
      **Fachliche Felder werden
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

## Addendum (2026-11-23): Pilot-Korrektur Stufe 1

Status unverändert: **vorgeschlagen** – das Addendum dokumentiert die
Pilot-Korrektur der Stufe-1-Heuristik am echten Dokument `sia101-2020`
(48 Seiten, lokaler Mount, G4). Der Pilot hat den ursprünglichen
Zeilen-Regex-Entwurf als unbrauchbar identifiziert: 31 erkannte „Ziffern“,
davon 22 Laufzeilen-Footer (Seitenzahl + Dokumententitel), 25 wiederholte
Mehreseiten-Tabellenzeilen (Zeilenköpfe `4.3.1` … `4.3.6`), 1 Tabellenwert
`4.3.0` und Inhaltsverzeichnis-Zeilen; 2. Spalte Tabellen mit führenden
Nullen (`4.3.01` …). Verifizierter Befund (nur Ziffern, Positionen,
Font-Namen, Längen – G4): 73 bold-Kandidaten = 22 Footer + 25 wiederholte
Tabellenzeilen + 1× `4.3.0` + 25 echte Überschriften; die einzige karge
Überschrift (ganze Zeile = Ziffer) ist `2.4`; die echten Footers sitzen
alle im unteren Seitenband (y ≈ 34 Punkte); Content-Stream-Ordnung ≠
visuelle Lesereihenfolge (Seite 15).

Entscheidung (ersetzt die Stufe-1-Heuristik):

1. **Visitor-basierte Extraktion:** Zeilen entstehen aus den
   `visitor_text`-Chunks `(text, x, y, font)`; device-Koordinaten =
   Textmatrix × CTM; Zeilengrenzen = `\n` im Chunk-Text. Verifiziert:
   Chunk-Konkatenation == `extract_text()`-Output auf allen 48 Seiten
   (0 Mismatches), d. h. keine Text-Information geht verloren.
2. **F1 – Bold-Filter:** Kandidat nur, wenn das erste Segment der Zeile
   bold ist (BaseFont enthält „Bold“, Substitutions-`+`-Namensraum
   beachtet) – aber nur wenn das Dokument überhaupt bold-Runs kennt;
   einfontige Dokumente fallen zurück auf F2/F4/F5/F6 (synthetische
   Test-PDFs bleiben damit lauffähig).
3. **F2 – Zahlenregeln:** keine 0-Komponente (`4.3.0`) und keine
   führenden Nullen (`0.8`, `08`) – solche Werte sind keine
   Ziffernnummern.
4. **F3 – Laufzeile:** einstufige Ziffer == Seitenzahl UND Zeile im
   unteren Seitenband (y < 60 Punkte) = Footer, abgewiesen. Bewusst nur
   das untere Band: echte Footers sitzen unten (Pilot: y ≈ 34), ein
   beidseitiges Band finge legitime Überschriften in Kopfzeilen.
5. **F4 – Wiederholung:** gleiche `(Ziffer, Restlänge)` auf ≥2 Seiten =
   wiederholte Tabellenzeile, abgewiesen (Two-Pass: F4 zählt alle
   Kandidaten, auch solche, die an anderen Filtern scheitern).
6. **F5 – TOC-Punktgürtel** wird beibehalten (Verteidigung in der Tiefe;
   im Pilot-Extrakt existierten die Punkte nicht, die TOC-Zeilen fielen
   über F1 raus).
7. **Karge Ziffern** (ganze Zeile ist die Ziffer, z. B. `2.4`) sind nur
   mit bold + linker Marge (x ≤ 120 Punkte) Kandidaten.
8. **Sequenz-Check in visueller Lesereihenfolge (Seite, -y, x), nicht in
   Content-Stream-Ordnung** (Pilot-Befund Seite 15). Der Entwurf wird
   zusätzlich nach der Ziffernnummer sortiert; die Stream-Ordnung wird
   nur für die Text-Zuordnung (Zeilen bis zur nächsten Ziffer) genutzt.

**Schema-Änderung** (`schemas/document_draft.schema.json`):
`clauses[].text` verliert `minLength: 1` – eine karge Überschrift ohne
Titel (Pilot: `2.4`) hat ein leeres Textfeld.

Ergebnis der Re-Extraktion `sia101-2020`: exakt 26 Ziffern
(1, 1.1–1.2, 2, 2.1–2.5, 3, 3.1–3.3, 4, 4.1–4.3, 5, 5.1–5.7, 6) – das
Ziel-Skelett; alle 47 Fehlkandidaten abgewiesen, die karge `2.4` erkannt.

Bekanntes Restrisiko (v1): ein boldes Tabellen-Element, das mit einer
gültigen Ziffernnummer beginnt, nicht wiederholt ist und zufällig die
Seitenzahl trägt, wäre ein Fehlkandidat – akzeptiert, weil die Stufe 2
(manuelle Vervollständigung) jedes Skelett prüft; bei Systematik folgt
eine weitere Regel.
