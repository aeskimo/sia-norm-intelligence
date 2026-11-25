"""Migration des Java-Stands (REQ-815, ADR-0011 Punkt 7, 09 §9.4).

Beim ersten Start der Python-App importiert der Launcher die Artefakte
der Java-App in den Python-Zielzustand — bevor der Server startet:

- ``workspace.state`` (SIASST1; gleicher Codec und Key wie Java) wird
  dechiffriert und als ``workspace.json`` (Klartext-JSON, atomar)
  geschrieben. Nur, wenn ``workspace.json`` noch fehlt. Die
  Ursprungsdatei bleibt erhalten (nicht-destruktiver Import).
- ``index/*.siaidx`` → ``index/*.sniidx``: gleicher Codec und Key,
  die Migration ist ein reines Umbenennen. Existiert schon ein
  ``.sniidx`` mit gleichem Namen, bleibt das neue Format erhalten und
  die Altdatei wird gemeldet.
- Best-Effort: ohne Statusschlüssel oder bei defekten/manipulierten
  Dateien wird der betroffene Schritt mit Meldung übersprungen —
  der App-Start wird nie abgebrochen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sni.state.keys import StateKeyProvider, default_state_keys
from sni.state.paths import user_data_dir
from sni.state.vault import EncryptedStateVault
from sni.state.workspace import PersistedWorkspace, WorkspaceCodec, save_workspace_json

#: Java-Erweiterung des verschlüsselten Index-Caches.
_LEGACY_INDEX_SUFFIX = ".siaidx"
#: Python-Zielerweiterung (gleicher Codec + Key, nur der Name ist neu).
_INDEX_SUFFIX = ".sniidx"


@dataclass(frozen=True, slots=True)
class MigrationReport:
    """Ergebnis der Java-Migration (REQ-815)."""

    #: ``workspace.json`` wurde aus ``workspace.state`` erzeugt.
    workspace_migrated: bool
    #: ``None`` = ok bzw. nichts zu tun; sonst Meldung (z. B. manipuliert).
    workspace_problem: str | None
    #: Anzahl umbenannter Index-Dateien (``.siaidx`` → ``.sniidx``).
    index_renamed: int
    #: Altdateien, die wegen bestehender ``.sniidx``-Datei behalten wurden.
    index_kept: int


def workspace_state_to_json(workspace: PersistedWorkspace) -> dict[str, object]:
    """Bildet den Java-Workspace auf die ``workspace.json``-Keys ab (09 §9.1)."""
    return {
        "generation_model": workspace.generation_model,
        "embedding_model": workspace.embedding_model,
        "provider": workspace.provider,
        "gibb_base_url": workspace.gibb_base_url,
        "gibb_model": workspace.gibb_model,
        "worksets": {name: list(doc_ids) for name, doc_ids in workspace.worksets.items()},
    }


def migrate(
    data_dir: Path | None = None,
    keys: StateKeyProvider | None = None,
) -> MigrationReport:
    """Migriert den Java-Stand in den Python-Zielzustand (best-effort).

    ``data_dir=None`` → :func:`user_data_dir`; ``keys=None`` →
    :func:`default_state_keys` (Umgebungsvariable, dann Keyring).
    Wirft keine Exception; Probleme landen im :class:`MigrationReport`.
    """
    base = data_dir if data_dir is not None else user_data_dir()
    provider = keys if keys is not None else default_state_keys()

    workspace_migrated = False
    workspace_problem: str | None = None
    state_file = base / "workspace.state"
    if state_file.is_file() and not (base / "workspace.json").is_file():
        if not provider.available():
            workspace_problem = "workspace.state: kein Statusschlüssel verfügbar"
        else:
            try:
                vault = EncryptedStateVault(state_file, provider)
                workspace = WorkspaceCodec().decode(vault.load())
                save_workspace_json(workspace_state_to_json(workspace), base)
                workspace_migrated = True
            except Exception as exc:  # noqa: BLE001 — Best-Effort-Import
                workspace_problem = f"workspace.state nicht lesbar: {exc}"

    renamed = 0
    kept = 0
    index_dir = base / "index"
    if index_dir.is_dir():
        for legacy in sorted(index_dir.glob("*" + _LEGACY_INDEX_SUFFIX)):
            target = legacy.with_suffix(_INDEX_SUFFIX)
            if target.exists():
                kept += 1  # bestehende Zielschreibweise gewinnt; Altdatei bleibt
                continue
            legacy.rename(target)
            renamed += 1

    return MigrationReport(workspace_migrated, workspace_problem, renamed, kept)
