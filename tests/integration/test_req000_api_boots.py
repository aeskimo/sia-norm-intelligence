"""REQ-000: `make run` startet die API (FastAPI-Boilerplate mit Health-Check)."""

from fastapi.testclient import TestClient

from sni.api.main import app


def test_req000_api_boots_and_healthz_is_ok() -> None:
    client = TestClient(app)
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
