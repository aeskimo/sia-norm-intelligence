"""M8.6 (REQ-813): Frozen-Bootstrap — schreibbarer Kerndaten-Mount.

Im PyInstaller-Bündel wäre ``<repo>/data`` read-only (und die Review-
Freigabe schreibt dorthin). Die frozen App nutzt ``<user_data_dir>/data``
(Env ``SIA_CORE_DATA_DIR``), beim Start aus den gebündelten Pilot-
Snapshots gesättigt (idempotent). Dev-Modus (Repo-Checkout) bleibt
unverändert.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from sni.app import bootstrap, launcher
from sni.app.server import build_app
from sni.catalog.snapshot import SnapshotValidationError
from sni.catalog.store import ConceptStore
from sni.ingest import pipeline
from sni.state import paths as state_paths

REPO = Path(__file__).resolve().parents[2]
REPO_DATA = REPO / "data"


def _root() -> Path:
    return Path(state_paths.__file__).resolve().parents[3]


# -------------------------------------------------
# core_data_dir (paths)
# -------------------------------------------------


def test_req813_core_data_dir_repo_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ohne Override: der Kerndaten-Mount ist das Repo-``data/``."""
    monkeypatch.delenv("SIA_CORE_DATA_DIR", raising=False)
    assert state_paths.core_data_dir() == _root() / "data"


def test_req813_core_data_dir_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIA_CORE_DATA_DIR", str(tmp_path))
    assert state_paths.core_data_dir() == tmp_path


# -------------------------------------------------
# Call-time-Defaults folgen SIA_CORE_DATA_DIR
# -------------------------------------------------


def test_req813_pipeline_defaults_follow_core_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIA_CORE_DATA_DIR", str(tmp_path))
    assert pipeline.default_norms_dir() == tmp_path / "norms"
    assert pipeline.default_queue_dir() == tmp_path / "review_queue"


def test_req813_pipeline_defaults_repo_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SIA_CORE_DATA_DIR", raising=False)
    assert pipeline.default_norms_dir() == _root() / "data" / "norms"


# -------------------------------------------------
# Bootstrap: frozen / core_data_dir / bundle_data_dir
# -------------------------------------------------


def test_req813_bootstrap_not_frozen_in_dev() -> None:
    assert bootstrap.frozen() is False


def test_req813_bootstrap_frozen_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert bootstrap.frozen() is True


def test_req813_bootstrap_core_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIA_DATA_DIR", str(tmp_path))
    assert bootstrap.core_data_dir() == tmp_path / "data"


def test_req813_bundle_data_dir_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert bootstrap.bundle_data_dir() is None
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bootstrap.bundle_data_dir() is None  # ohne sni_data/


def test_req813_bundle_data_dir_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "sni_data" / "catalog" / "snapshots").mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bootstrap.bundle_data_dir() == tmp_path / "sni_data"


# -------------------------------------------------
# seed_core_data
# -------------------------------------------------


def test_req813_seed_creates_layout_and_imports_snapshots(tmp_path: Path) -> None:
    target = tmp_path / "core"
    imported = bootstrap.seed_core_data(target, REPO_DATA)
    assert imported == 9  # 6 (pilot-sia416) + 3 (pilot-synthetic)
    for sub in bootstrap.CORE_SUBDIRS:
        assert (target / sub).is_dir(), f"Sub-Verzeichnis fehlt: {sub}"
    store = ConceptStore(target / "catalog" / "catalog.db")
    try:
        assert len(store.concept_ids()) == 9
    finally:
        store.close()


def test_req813_seed_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "core"
    assert bootstrap.seed_core_data(target, REPO_DATA) == 9
    # Re-Run (jeder App-Start): keine neuen Concepts, kein Konflikt
    assert bootstrap.seed_core_data(target, REPO_DATA) == 0
    store = ConceptStore(target / "catalog" / "catalog.db")
    try:
        assert len(store.concept_ids()) == 9
    finally:
        store.close()


def test_req813_seed_without_source_is_empty(tmp_path: Path) -> None:
    target = tmp_path / "core"
    assert bootstrap.seed_core_data(target, None) == 0
    for sub in bootstrap.CORE_SUBDIRS:
        assert (target / sub).is_dir()
    store = ConceptStore(target / "catalog" / "catalog.db")
    try:
        assert store.concept_ids() == []
    finally:
        store.close()


def test_req813_seed_rejects_invalid_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "bundle"
    (source / "catalog" / "snapshots").mkdir(parents=True)
    (source / "catalog" / "snapshots" / "kaputt.json").write_text(
        json.dumps({"foo": "bar"}), encoding="utf-8"
    )
    with pytest.raises(SnapshotValidationError):
        bootstrap.seed_core_data(tmp_path / "core", source)


# -------------------------------------------------
# build_app(core_data_dir=…) + Launcher-Wiring
# -------------------------------------------------


def test_req813_build_app_wires_core_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIA_DATA_DIR", str(tmp_path / "user"))
    core = tmp_path / "core"
    app = build_app(core_data_dir=core)
    assert app.state.knowledge_dir == core / "extracted"
    assert app.state.rules_dir == core / "rules"
    assert (core / "catalog" / "catalog.db").is_file()


def test_req813_launcher_frozen_wires_core_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Frozen-Start: Env gesetzt, Kerndaten-Mount unter user_data/data gesättigt."""
    bundle = tmp_path / "bundle" / "sni_data" / "catalog" / "snapshots"
    bundle.mkdir(parents=True)
    snapshot = sorted((REPO_DATA / "catalog" / "snapshots").glob("*.json"))[0]
    shutil.copy(snapshot, bundle / snapshot.name)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setenv("SIA_DATA_DIR", str(tmp_path / "user"))
    monkeypatch.delenv("SIA_CORE_DATA_DIR", raising=False)
    core = launcher._frozen_core_data_dir()
    assert core == tmp_path / "user" / "data"
    assert os.environ["SIA_CORE_DATA_DIR"] == str(core)
    assert (core / "catalog" / "catalog.db").is_file()
    assert (core / "review_queue").is_dir()
    store = ConceptStore(core / "catalog" / "catalog.db")
    try:
        assert len(store.concept_ids()) == 6  # nur der 1 kopierte Snapshot
    finally:
        store.close()


def test_req813_launcher_dev_mode_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("SIA_CORE_DATA_DIR", raising=False)
    assert launcher._frozen_core_data_dir() is None
    assert "SIA_CORE_DATA_DIR" not in os.environ
