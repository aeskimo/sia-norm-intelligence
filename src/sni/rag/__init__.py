"""RAG: beziehbare lokale Fragen mit Quellen-Validierung (REQ-805, ADR-0011).

1:1-Port von ``ch.sia.assistant.ai`` (Java-Referenz): ``GroundedQa``
(Prompt ``[Qn]``-Quellenblöcke, Zitat-Validierung, Aussageklassen) und
die austauschbaren Antwortmodelle unter ``providers/`` (Ollama lokal,
gibb/OpenAI-kompatibel).
"""
