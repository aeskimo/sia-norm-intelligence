# 00 – Vision, Scope, Non-Goals

## Problem
Fragen zu Normen mit Fundstelle zu beantworten ist technisch gelöst. Ungelöst ist der
**Nachweis**, wann eine maschinelle Antwort fachlich belastbar ist und wo ihre Aussagekraft endet.

## Ziel
Eine Referenzimplementierung, die
1. Normtext in **semantische Objekte** zerlegt (Konzept, Aussage, Regel, Quelle),
2. diese Objekte **versioniert und quellengebunden** speichert,
3. Normfragen beantwortet und jede Antwort einer **Aussageklasse** zuordnet,
4. **Projektdaten** gegen Regeln prüft,
5. alles über eine **dokumentierte API** bereitstellt,
6. ihre Verlässlichkeit über einen **Benchmark messbar** macht.

## Verhältnis zum Projekt SIA-Datenkatalog
Das Projekt SIA-Datenkatalog erarbeitet die konzeptionelle, technologieunabhängige Grundlage
(Begriffe, Merkmale, Beziehungen, Namespace-Prinzip, Mehrsprachigkeit) und umfasst bewusst
keine technische Umsetzung. Dieses Projekt ist die **technische Erprobung**: Es konsumiert
einen versionierten Katalog-Snapshot und liefert strukturierte Gap-Meldungen zurück
(`GapReport`, siehe `04_DATA_MODEL.md`). Es definiert den Katalog nicht.

## Scope v1
- Pilotnormen: SIA 416:2003, SIA 2024:2015
- Sprachen: de (Datenmodell mehrsprachig vorbereitet: de/fr/it/en)
- Projektdaten: IFC 4.x, CSV/Excel-Flächenlisten

## Non-Goals v1
- Kein eigener Datenkatalog-Standard, kein Ersatz für bSDD/IFC/IDS
- Keine Benutzeroberfläche ausser OpenAPI-Doku und einfacher Demo-Seite
- Keine rechtsverbindliche Auskunft; keine Haftungsübernahme
- Keine Normen ausserhalb der Pilotnormen
- Kein Fine-Tuning von Modellen

## Erfolgsmetriken (gemessen durch `make eval`)
| Metrik | Ziel v1 |
|---|---|
| Critical Failure Rate (falsch, aber als `normativ_belegt` ausgegeben) | 0 % |
| Klassenkorrektheit Aussageklasse | ≥ 90 % |
| Fundstellenkorrektheit (Norm + Ausgabe + Ziffer) | ≥ 95 % bei `normativ_belegt` |
| Korrekte Enthaltung bei nicht beantwortbaren Fällen | ≥ 90 % |
| Regelberechnung korrekt (deterministische Fälle) | 100 % |
