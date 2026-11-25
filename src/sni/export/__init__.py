"""Export-Serialisierer (M7, REQ-700/701/702; ADR-0005).

Neue Schicht `export` zwischen `service` und `rules`: handgeschriebene
Serialisierer für SKOS/Turtle (``skos.py``), IDS 1.0 (``ids.py``) und
BCF 2.1 (``bcf.py``) – stdlib-only, keine neuen Laufzeit-Abhängigkeiten.
``api/`` verdrahtet nur die Endpunkte.

Zusätzlich (M8.5, REQ-810): ``semantic.py`` – deterministischer
Semantik-Export aus Volltextseiten ins ``document.json``-Format.
"""
