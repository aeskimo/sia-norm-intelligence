"""FastAPI-Boilerplate (M0). Fachliche Endpunkte kommen ab M1 (docs/03_ARCHITECTURE.md)."""

from fastapi import FastAPI

app = FastAPI(title="SIA Norm Intelligence", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness-Check für `make run` und Monitoring."""
    return {"status": "ok"}
