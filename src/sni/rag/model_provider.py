"""Austauschbare Antwortmodelle (REQ-805, Java: ``ModelProvider``).

``generate_streaming`` liefert die Antwort tokenweise über den Callback;
die Standard-Implementierung fällt auf die blockierende ``generate``
zurück und meldet das Endergebnis in einem einzigen Chunk (Java-
Default-Method 1:1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class ModelProvider(ABC):
    """Schnittstelle für lokale/entfernte Antwortmodelle (Java 1:1)."""

    @abstractmethod
    def id(self) -> str:
        """Eindeutige Modell-Bezeichnung (Java: ``id()``)."""
        ...

    @abstractmethod
    def available(self) -> bool:
        """Erreichbarkeits-Healthcheck (wirft nie)."""
        ...

    @abstractmethod
    def generate(self, system: str, prompt: str) -> str | None:
        """Blockierende Generierung; ``None``, wenn kein Inhalt geliefert."""
        ...

    def generate_streaming(
        self, system: str, prompt: str, on_token: Callable[[str], None]
    ) -> str | None:
        """Tokenweise Generierung (Java-Default: Rückfall auf ``generate``)."""
        full = self.generate(system, prompt)
        if full is not None:
            on_token(full)
        return full
