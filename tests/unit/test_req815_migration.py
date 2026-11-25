"""REQ-815: Migration des Java-Stands (ADR-0011 Punkt 7, 09 §9.4).

``workspace.state`` (SIASST1, gleicher Codec + Key wie Java) →
``workspace.json``; ``index/*.siaidx`` → ``index/*.sniidx`` (reines
Umbenennen). Port von ``M2EncryptedPersistenceSelfTest`` (kein
Klartext auf Disk, Roundtrip, Tamper → Abweisung) plus
Konflikt-/Keyless-Fälle und der Launcher-Aufruf vor dem Server.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sni.app import launcher
from sni.search.page_source import PageSource
from sni.search.vectors import VectorEntry
from sni.shop.catalog_xml import StandardDocument
from sni.state.index_cache import EncryptedIndexCache, IndexCacheEntry, stem
from sni.state.migrate import MigrationReport, migrate
from sni.state.vault import EncryptedStateVault
from sni.state.workspace import (
    PersistedWorkspace,
    WorkspacePersistenceService,
    load_workspace_json,
    save_workspace_json,
)

KEY = bytes([7]) * 32  # Java-Testschlüssel (M2EncryptedPersistenceSelfTest)


class _StaticKeys:
    def __init__(self, key: bytes | None) -> None:
        self._key = key

    def load(self) -> bytes:
        if self._key is None:
            raise RuntimeError("kein Schlüssel")
        return self._key

    def available(self) -> bool:
        return self._key is not None


def _data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


def _legacy_workspace(data_dir: Path, key: bytes) -> PersistedWorkspace:
    """Java-Selbsttest-Szenario (``M2EncryptedPersistenceSelfTest`` 1:1)."""
    workspace = PersistedWorkspace(
        generation_model="qwen3:8b",
        embedding_model="embed-test",
        worksets={"Nassräume": ("sia271", "sia118-271")},
        provider="gibb",
        gibb_base_url="https://chat.gibb.ch/api",
        gibb_model="gibb-chat-1",
    )
    vault = EncryptedStateVault(data_dir / "workspace.state", _StaticKeys(key))
    WorkspacePersistenceService(vault).save(workspace)
    return workspace


def _legacy_index(data_dir: Path, key: bytes) -> str:
    """Gültigen Cache-Eintrag speichern und auf die Java-Erweiterung umbenennen."""
    product_id = "101_2020_dSIA"
    page = PageSource(product_id, "SIA 101", "2020", 1, "1", "Seite 1")
    entry = IndexCacheEntry(
        StandardDocument(
            product_id,
            "SIA 101",
            "Testnorm",
            "",
            "",
            "D",
            "2020",
            "1",
            date(2020, 1, 1),
            None,
            "101.srd",
            True,
            True,
            True,
        ),
        (page,),
        "embeddinggemma",
        (VectorEntry(page, (0.5, 1.5)),),
    )
    cache = EncryptedIndexCache(data_dir / "index", _StaticKeys(key))
    cache.save(entry)
    target = cache.file(product_id)
    target.rename(target.with_suffix(".siaidx"))
    return product_id


# ------------------------------------------------------------------ workspace


def test_req815_migration_workspace_roundtrip(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    _legacy_workspace(data_dir, KEY)
    report = migrate(data_dir, _StaticKeys(KEY))
    assert report.workspace_migrated is True
    assert report.workspace_problem is None
    state = load_workspace_json(data_dir)
    assert state is not None
    assert state["generation_model"] == "qwen3:8b"
    assert state["embedding_model"] == "embed-test"
    assert state["provider"] == "gibb"
    assert state["gibb_base_url"] == "https://chat.gibb.ch/api"
    assert state["gibb_model"] == "gibb-chat-1"
    assert state["worksets"] == {"Nassräume": ["sia271", "sia118-271"]}
    assert (data_dir / "workspace.state").is_file()  # nicht-destruktiv


def test_req815_migration_no_plaintext_on_disk(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    _legacy_workspace(data_dir, KEY)
    raw = (data_dir / "workspace.state").read_bytes()
    assert "Nassräume".encode() not in raw
    assert b"qwen3:8b" not in raw


def test_req815_migration_tamper_rejected(tmp_path: Path) -> None:
    # Port M2EncryptedPersistenceSelfTest: letztes Byte umgedreht → Abweisung.
    data_dir = _data_dir(tmp_path)
    _legacy_workspace(data_dir, KEY)
    path = data_dir / "workspace.state"
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(bytes(raw))
    report = migrate(data_dir, _StaticKeys(KEY))
    assert report.workspace_migrated is False
    assert report.workspace_problem is not None
    assert load_workspace_json(data_dir) is None


def test_req815_migration_wrong_key_rejected(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    _legacy_workspace(data_dir, KEY)
    report = migrate(data_dir, _StaticKeys(bytes([9]) * 32))
    assert report.workspace_migrated is False
    assert report.workspace_problem is not None
    assert load_workspace_json(data_dir) is None


def test_req815_migration_idempotent(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    _legacy_workspace(data_dir, KEY)
    first = migrate(data_dir, _StaticKeys(KEY))
    second = migrate(data_dir, _StaticKeys(KEY))
    assert first.workspace_migrated is True
    assert second == MigrationReport(False, None, 0, 0)


def test_req815_migration_existing_json_not_overwritten(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    save_workspace_json({"provider": "gibb", "generation_model": "neu"}, data_dir)
    _legacy_workspace(data_dir, KEY)
    report = migrate(data_dir, _StaticKeys(KEY))
    assert report.workspace_migrated is False
    state = load_workspace_json(data_dir)
    assert state is not None
    assert state["generation_model"] == "neu"  # unangetastet


# ------------------------------------------------------------------ Index


def test_req815_migration_renames_index(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    product_id = _legacy_index(data_dir, KEY)
    report = migrate(data_dir, _StaticKeys(KEY))
    assert report.index_renamed == 1
    assert report.index_kept == 0
    index_dir = data_dir / "index"
    assert list(index_dir.glob("*.siaidx")) == []
    entry = EncryptedIndexCache(index_dir, _StaticKeys(KEY)).load(product_id)
    assert entry is not None  # gleicher Codec + Key: lesbar nach dem Umbenennen
    assert entry.document.product_id == product_id


def test_req815_migration_index_conflict_kept(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    product_id = _legacy_index(data_dir, KEY)
    index_dir = data_dir / "index"
    old_file = index_dir / (stem(product_id) + ".siaidx")
    new_file = index_dir / (stem(product_id) + ".sniidx")
    new_file.write_bytes(old_file.read_bytes())  # beide Formate vorhanden
    before = new_file.read_bytes()
    report = migrate(data_dir, _StaticKeys(KEY))
    assert report.index_renamed == 0
    assert report.index_kept == 1
    assert new_file.read_bytes() == before  # bestehende Zielschreibweise gewinnt
    assert old_file.is_file()  # Altdatei bleibt erhalten


# ------------------------------------------------------------------ Keyless


def test_req815_migration_keyless_skips_workspace(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    _legacy_workspace(data_dir, KEY)
    _legacy_index(data_dir, KEY)
    report = migrate(data_dir, _StaticKeys(None))
    assert report.workspace_migrated is False
    assert report.workspace_problem is not None
    assert "Statusschlüssel" in report.workspace_problem
    assert load_workspace_json(data_dir) is None
    assert report.index_renamed == 1  # Umbenennen braucht keinen Schlüssel


# ------------------------------------------------------------------ No-op


def test_req815_migration_noop_without_legacy(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    report = migrate(data_dir, _StaticKeys(KEY))
    assert report == MigrationReport(False, None, 0, 0)
    assert not (data_dir / "workspace.json").exists()


# ------------------------------------------------------------------ Launcher


def test_req815_launcher_runs_migration_before_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_migrate(data_dir: Path | None = None, keys: object = None) -> MigrationReport:
        calls.append("migrate")
        return MigrationReport(False, None, 0, 0)

    def fake_headless(args: object) -> int:
        calls.append("server")
        return 0

    monkeypatch.setattr(launcher, "migrate", fake_migrate)
    monkeypatch.setattr(launcher, "run_headless", fake_headless)
    assert launcher.main(["--headless"]) == 0
    assert calls == ["migrate", "server"]
