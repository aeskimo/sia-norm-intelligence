"""Lokaler Such-Stack der Consumer-App (REQ-804, ADR-0011).

1:1-Port von ``ch.sia.assistant.search`` (Java-Referenz): Volltext-
Inverted-Index, Vektorindex (Kosinus) und Hybrid-Fusion via
Reciprocal Rank Fusion. Keine neue Dependency (reines Python).
"""
