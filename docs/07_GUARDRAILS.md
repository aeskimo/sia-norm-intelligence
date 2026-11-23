# 07 – Guardrails (nicht verhandelbar)

**G1 – Keine erfundenen Norminhalte.** Normtext, Zahlenwerte, Formeln, Tabellen und
Fundstellen stammen ausschliesslich aus dem lokal bereitgestellten Normdokument oder aus
`approved` Objekten. Nie aus dem Modellwissen des Agenten.

**G2 – Quelle oder Enthaltung.** Jede fachliche Aussage referenziert eine Objekt-ID mit
Fundstelle. Ohne Referenz: `nicht_eindeutig`.

**G3 – Mensch gibt frei.** Agenten erzeugen nur `candidate`. Freigabe (`approved`) erfolgt
durch benannte Fachpersonen; Freigabe-Metadaten (Person, Datum) sind Pflicht.

**G4 – Lizenz und Urheberrecht.** SIA-Normtexte sind lizenziert. Sie liegen nicht im Repo,
nicht in Fixtures, nicht in Logs und werden nur an Dienste übermittelt, die vom Projekt
freigegeben sind (siehe ADR-0003). Testfixtures verwenden synthetische Platzhaltertexte.

**G5 – Schwächere Klasse bei Zweifel.** Im Zweifel wird immer herabgestuft.

**G6 – Keine Rechtsauskunft.** Jede API-Antwort enthält das Feld `disclaimer`.

**G7 – Datenkatalog ist read-only.** Änderungswünsche nur als `GapReport`.
