"""RAG-Antwortmodelle (REQ-805, ADR-0011 Punkt 5).

1:1-Port von ``ch.sia.assistant.ai`` (Java-Referenz): ``ollama.py``
(lokales Ollama, ``/api/generate``, NDJSON, Loopback-only) und
``gibb.py`` (OpenAI-kompatibel, ``/chat/completions``, SSE, Bearer,
HTTPS-only).
"""
