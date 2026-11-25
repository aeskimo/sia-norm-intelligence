"""REQ-808: Arbeitssets — Store (1:1 Java ``WorksetStore``) + Endpunkte.

Unit: Name/ID-Validierung, Idempotenz (``computeIfAbsent``), Einfüge-
Reihenfolge, ``removeDocumentEverywhere``. Persistenz: ``workspace.json``
(best-effort, non-destruktiv). Endpunkte: ``GET/POST /v1/worksets``,
``PUT/DELETE /v1/worksets/{id}`` (09 §6.2); Dokument-DELETE entfernt die
Id aus allen Arbeitssets. Synthetische Testdaten (G4).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from sni.app.server import build_app
from sni.app.shop import ShopState
from sni.state.worksets import (
    WorksetStore,
    load_store,
    save_store,
    valid_document_id,
    valid_name,
)
from sni.state.workspace import load_workspace_json
from tests.conftest import (
    LICENSE_XML,
    FakeSoapClient,
    document_result_ok,
    login_result_ok,
    make_mro,
    make_pdf,
    make_srd,
)

TOKEN = "app-test-token"
BASE = "http://127.0.0.1:8141"
HDRS = {"x-sia-token": TOKEN}
PDF = make_pdf(["SYN 1  Testnorm"])


# ------------------------------------------------------------------ Validierung


def test_req808_valid_name_strips() -> None:
    assert valid_name("  Meins  ") == "Meins"


def test_req808_invalid_name_rejected() -> None:
    for bad in ("", "   ", "x" * 101):
        with pytest.raises(ValueError, match="Ungültiger Arbeitssetname"):
            valid_name(bad)


def test_req808_name_at_limit_accepted() -> None:
    assert valid_name("x" * 100) == "x" * 100


def test_req808_invalid_document_id_rejected() -> None:
    for bad in ("", "  ", "bad id", "a" * 161, "x/../y", "id/with/slash"):
        with pytest.raises(ValueError, match="Ungültige Dokument-ID"):
            valid_document_id(bad)


def test_req808_document_id_at_limit_accepted() -> None:
    # 154 + 6 = 160 Zeichen, alle aus [A-Za-z0-9._-]
    assert valid_document_id("A.b_c-d" * 22 + "A.b_c-") == "A.b_c-d" * 22 + "A.b_c-"


# ------------------------------------------------------------------ Store (1:1 Java)


def test_req808_create_idempotent() -> None:
    store = WorksetStore()
    store.create("ws")
    store.create("  ws  ")  # gestrippt → derselbe
    assert store.names() == ["ws"]


def test_req808_add_auto_creates_and_dedupes() -> None:
    store = WorksetStore()
    store.add("ws", "doc-1")
    store.add("ws", "doc-1")
    assert store.documents("ws") == ("doc-1",)
    assert store.names() == ["ws"]


def test_req808_documents_ordered_and_copy() -> None:
    store = WorksetStore()
    for doc in ("b", "a", "c"):
        store.add("ws", doc)
    assert store.documents("ws") == ("b", "a", "c")  # Einfüge-Reihenfolge
    assert store.documents("unbekannt") == ()


def test_req808_remove_and_delete_noop_when_absent() -> None:
    store = WorksetStore()
    store.remove("ws", "doc-1")  # kein Exception
    store.delete("ws")  # kein Exception
    store.add("ws", "doc-1")
    store.remove("ws", "doc-1")
    assert store.documents("ws") == ()


def test_req808_snapshot_is_copy() -> None:
    store = WorksetStore()
    store.add("ws", "doc-1")
    snap = store.snapshot()
    assert snap == {"ws": ("doc-1",)}
    assert isinstance(snap["ws"], tuple)  # unveränderlich


def test_req808_restore_clears_and_validates() -> None:
    store = WorksetStore()
    store.add("alt", "doc-1")
    store.restore({"neu": ["a", "b"]})
    assert store.names() == ["neu"]
    assert store.documents("neu") == ("a", "b")
    with pytest.raises(ValueError, match="Ungültiger Arbeitssetname"):
        store.restore({"": ["a"]})
    with pytest.raises(ValueError, match="Ungültige Dokument-ID"):
        store.restore({"ok": ["bad id"]})


def test_req808_remove_document_everywhere() -> None:
    store = WorksetStore()
    store.add("a", "doc-1")
    store.add("b", "doc-1")
    store.add("b", "doc-2")
    store.remove_document_everywhere("doc-1")
    assert store.documents("a") == ()
    assert store.documents("b") == ("doc-2",)


# ------------------------------------------------------------------ Persistenz


def test_req808_save_load_roundtrip(tmp_path: Path) -> None:
    store = WorksetStore()
    store.add("ws1", "doc-1")
    store.add("ws2", "doc-2")
    save_store(store, tmp_path)
    assert load_store(tmp_path).snapshot() == {"ws1": ("doc-1",), "ws2": ("doc-2",)}


def test_req808_save_preserves_other_keys(tmp_path: Path) -> None:
    from sni.state.workspace import save_workspace_json

    save_workspace_json({"provider": "ollama"}, tmp_path)
    save_store(WorksetStore(), tmp_path)
    state = load_workspace_json(tmp_path)
    assert state is not None
    assert state["provider"] == "ollama"
    assert state["worksets"] == {}


def test_req808_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_store(tmp_path / "fehlt").names() == []


def test_req808_load_skips_invalid_entries_non_destructively(tmp_path: Path) -> None:
    from sni.state.workspace import save_workspace_json

    state = {
        "worksets": {
            "": ["doc-1"],  # ungültiger Name → übersprungen
            "ok": ["doc-1", "bad id", 42],  # ungültige Id/Typ → übersprungen
        }
    }
    save_workspace_json(state, tmp_path)
    store = load_store(tmp_path)
    assert store.names() == ["ok"]
    assert store.documents("ok") == ("doc-1",)
    # Datei bleibt unverändert (non-destruktiv)
    assert load_workspace_json(tmp_path) == state


# ------------------------------------------------------------------ Endpunkte


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, ShopState]:
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "keychain"))
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    shop = ShopState(data_dir=tmp_path / "data")
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token=TOKEN,
        mode="window",
        port=8141,
        shop=shop,
    )
    return TestClient(app, base_url=BASE), shop


def _login(client: TestClient) -> None:
    res = client.post(
        "/v1/session/login",
        headers=HDRS,
        json={
            "provider": "sia",
            "customer": "kunde1",
            "password": "geheim",
            "device_id": "dev-1",
        },
    )
    assert res.status_code == 200, res.text


def _download(client: TestClient, product_id: str) -> None:
    res = client.post("/v1/documents/download", headers=HDRS, json={"product_id": product_id})
    assert res.status_code == 202, res.text
    job = cast("dict[str, object]", res.json()["job"])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for j in client.get("/v1/jobs", headers=HDRS).json():
            if j["id"] == job["id"] and j["status"] in {"done", "error"}:
                assert j["status"] == "done", f"Download fehlgeschlagen: {j}"
                return
        time.sleep(0.02)
    raise AssertionError("Download-Job nach 10 s nicht fertig")


def test_req808_worksets_empty_initially(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    assert client.get("/v1/worksets", headers=HDRS).json() == []


def test_req808_worksets_create_and_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, shop = _build(tmp_path, monkeypatch)
    res = client.post("/v1/worksets", headers=HDRS, json={"name": "  Meins  "})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "Meins"
    assert body["document_ids"] == []
    assert client.get("/v1/worksets", headers=HDRS).json() == [
        {"name": "Meins", "document_ids": []}
    ]
    state = load_workspace_json(shop.data_dir)
    assert state is not None
    assert state["worksets"] == {"Meins": []}


def test_req808_worksets_create_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    for _ in range(2):
        res = client.post("/v1/worksets", headers=HDRS, json={"name": "ws"})
        assert res.status_code == 200
    assert client.get("/v1/worksets", headers=HDRS).json() == [{"name": "ws", "document_ids": []}]


def test_req808_worksets_create_invalid_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    for bad in ("", "   ", "x" * 101):
        res = client.post("/v1/worksets", headers=HDRS, json={"name": bad})
        assert res.status_code == 400
        assert "Ungültiger Arbeitssetname" in res.json()["error"]


def test_req808_worksets_update_replaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    client.post("/v1/worksets", headers=HDRS, json={"name": "ws"})
    client.put("/v1/worksets/ws", headers=HDRS, json={"document_ids": ["doc-1", "doc-2"]})
    assert client.get("/v1/worksets", headers=HDRS).json() == [
        {"name": "ws", "document_ids": ["doc-1", "doc-2"]}
    ]
    res = client.put("/v1/worksets/ws", headers=HDRS, json={"document_ids": ["doc-9"]})
    assert res.status_code == 200
    assert res.json()["document_ids"] == ["doc-9"]  # ersetzen, nicht ergänzen


def test_req808_worksets_update_auto_creates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.put("/v1/worksets/neu", headers=HDRS, json={"document_ids": ["doc-1"]})
    assert res.status_code == 200
    assert client.get("/v1/worksets", headers=HDRS).json() == [
        {"name": "neu", "document_ids": ["doc-1"]}
    ]


def test_req808_worksets_update_invalid_id_rejected_and_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    client.put("/v1/worksets/ws", headers=HDRS, json={"document_ids": ["doc-1"]})
    res = client.put("/v1/worksets/ws", headers=HDRS, json={"document_ids": ["doc-2", "bad id"]})
    assert res.status_code == 400
    assert "Ungültige Dokument-ID" in res.json()["error"]
    # ungültige Id → 400, vorherige Liste bleibt unverändert (keine Teilveränderung)
    assert client.get("/v1/worksets", headers=HDRS).json() == [
        {"name": "ws", "document_ids": ["doc-1"]}
    ]


def test_req808_worksets_update_invalid_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    res = client.put("/v1/worksets/" + "x" * 101, headers=HDRS, json={"document_ids": []})
    assert res.status_code == 400


def test_req808_worksets_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)
    client.post("/v1/worksets", headers=HDRS, json={"name": "ws"})
    res = client.delete("/v1/worksets/ws", headers=HDRS)
    assert res.status_code == 200
    assert client.get("/v1/worksets", headers=HDRS).json() == []
    res = client.delete("/v1/worksets/ws", headers=HDRS)  # No-op wie Java
    assert res.status_code == 200


def test_req808_worksets_persist_across_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ein zweiter ShopState (App-Neustart) sieht die gespeicherten Arbeitssets.
    client, _ = _build(tmp_path, monkeypatch)
    client.post("/v1/worksets", headers=HDRS, json={"name": "ws"})
    client.put("/v1/worksets/ws", headers=HDRS, json={"document_ids": ["doc-1"]})
    reloaded = ShopState(data_dir=tmp_path / "data")
    assert reloaded.worksets.snapshot() == {"ws": ("doc-1",)}


def test_req808_document_delete_removes_from_worksets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Java-Referenz: WorksetStore.removeDocumentEverywhere beim Dokument-DELETE.
    client = FakeSoapClient(
        login_result_ok(),
        make_mro(LICENSE_XML),
        document_result_ok("101_2020_dSIA.srd"),
        make_srd("prod-101", PDF),
    )
    monkeypatch.setenv("SIA_FAKE_KEYCHAIN", str(tmp_path / "keychain"))
    monkeypatch.delenv("SIA_STATE_KEY_B64", raising=False)
    shop = ShopState(client_factory=lambda profile: client, data_dir=tmp_path / "data")
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token=TOKEN,
        mode="window",
        port=8141,
        shop=shop,
    )
    with TestClient(app, base_url=BASE) as c:
        _login(c)
        _download(c, "prod-101")
        c.post("/v1/worksets", headers=HDRS, json={"name": "ws"})
        c.put("/v1/worksets/ws", headers=HDRS, json={"document_ids": ["prod-101"]})
        res = c.delete("/v1/documents/prod-101", headers=HDRS)
        assert res.status_code == 200, res.text
        assert c.get("/v1/worksets", headers=HDRS).json() == [{"name": "ws", "document_ids": []}]
    state = load_workspace_json(shop.data_dir)
    assert state is not None
    assert state["worksets"] == {"ws": []}


def test_req808_workspace_json_shape_roundtrip(tmp_path: Path) -> None:
    """Die workspace.json bleibt gültiges JSON (Kein Seiteneffekt auf Einstellungen)."""
    store = WorksetStore()
    store.add("ws", "doc-1")
    save_store(store, tmp_path)
    raw = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert raw["worksets"] == {"ws": ["doc-1"]}
