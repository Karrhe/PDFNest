from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pdf_notes_reader import sync_store
from pdf_notes_reader.notes import _absorb_conflicts, default_data_dir, read_json_checked, utc_now
from pdf_notes_reader.portable import ensure_local


ROOT_FOLDER_ID = "root"
UNFILED_FOLDER_ID = "unfiled"


@dataclass
class LibraryFolder:
    id: str
    name: str
    created_at: str
    parent_id: str = ""

    @classmethod
    def create(cls, name: str, parent_id: str = "") -> "LibraryFolder":
        return cls(id=str(uuid.uuid4()), name=name.strip() or "New folder", created_at=utc_now(), parent_id=parent_id)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LibraryFolder":
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            name=str(data.get("name") or "New folder"),
            created_at=str(data.get("created_at") or utc_now()),
            parent_id=str(data.get("parent_id") or ""),
        )

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "created_at": self.created_at, "parent_id": self.parent_id}


@dataclass
class LibraryState:
    folders: list[LibraryFolder]
    assignments: dict[str, str]
    aliases: dict[str, str]
    archived: dict[str, str]
    # The library.json content this state was loaded from (or last saved as). Saving merges against
    # it, so a change made on another computer since then is kept, not overwritten.
    base: dict[str, Any] | None = field(default=None, repr=False, compare=False)


def ensure_folder_path(state: "LibraryState", parent_id: str, names: tuple[str, ...] | list[str]) -> str:
    """The id of the library folder ``parent / names[0] / names[1] / ...``, creating missing ones.

    An existing folder with the same name (ignoring case) under the same parent is reused, so adding
    the same disk folder twice does not duplicate the tree. Returns ``parent_id`` for no names.
    """
    current = parent_id if parent_id and parent_id != UNFILED_FOLDER_ID else ""
    for raw_name in names:
        name = str(raw_name).strip() or "New folder"
        existing = next(
            (
                folder
                for folder in state.folders
                if folder.parent_id == current and folder.id != UNFILED_FOLDER_ID and folder.name.casefold() == name.casefold()
            ),
            None,
        )
        if existing is None:
            existing = LibraryFolder.create(name, parent_id=current)
            state.folders.append(existing)
        current = existing.id
    return current


def library_path(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "library.json"


def default_folders() -> list[LibraryFolder]:
    return [
        LibraryFolder(id=UNFILED_FOLDER_ID, name="Unfiled", created_at=utc_now()),
    ]


def load_library(data_dir: Path | None = None) -> LibraryState:
    """Every computer's folders, filing, renames and archive, merged (see ``sync_store``)."""
    path = library_path(data_dir)
    records = sync_store.load_records(path, _legacy_records(path))
    state = _state_from_records(records)
    state.base = _records(state)
    return state


def _legacy_records(path: Path) -> dict[str, Any]:
    """Records from the plain ``library.json``: data from before per-computer replicas, or written by
    an older PDFNest on the other computer."""
    if not ensure_local(path):
        return {}
    # Conflict copies the cloud client made (library 2.json...) may hold folders the plain file
    # lost when two computers wrote it; fold them in before anything else reads it.
    _absorb_conflicts(path, _union_library_payloads, path.parent / "conflicts")
    payload = read_json_checked(path)
    return _records(_state_from_payload(payload)) if isinstance(payload, dict) else {}


def _union_library_payloads(ours: dict[str, Any], theirs: dict[str, Any], _base: Any = None) -> dict[str, Any]:
    """Everything either copy has: used for conflict copies, where dropping something loses it."""
    folders = {str(item.get("id")): item for item in theirs.get("folders", []) if isinstance(item, dict)}
    folders.update({str(item.get("id")): item for item in ours.get("folders", []) if isinstance(item, dict)})
    merged: dict[str, Any] = {"schema_version": 1, "app": "PDFNest", "folders": list(folders.values())}
    for name in ("assignments", "aliases", "archived"):
        combined = dict(theirs.get(name) or {}) if isinstance(theirs.get(name), dict) else {}
        if isinstance(ours.get(name), dict):
            combined.update(ours[name])
        merged[name] = combined
    return merged


# One record per folder and per book setting, so two computers changing different things never
# collide: "folder:<id>", "assign:<pdf key>", "alias:<pdf key>", "archived:<pdf key>".
_RECORD_MAPS = (("assign:", "assignments"), ("alias:", "aliases"), ("archived:", "archived"))


def _records(state: LibraryState) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for folder in state.folders:
        if folder.id != UNFILED_FOLDER_ID:  # built in, the same everywhere
            records[f"folder:{folder.id}"] = folder.to_dict()
    for prefix, name in _RECORD_MAPS:
        for key, value in getattr(state, name).items():
            records[f"{prefix}{key}"] = value
    return records


def _state_from_records(records: dict[str, Any]) -> LibraryState:
    payload: dict[str, Any] = {"folders": [], "assignments": {}, "aliases": {}, "archived": {}}
    for key, value in records.items():
        if key.startswith("folder:") and isinstance(value, dict):
            payload["folders"].append(value)
            continue
        for prefix, name in _RECORD_MAPS:
            if key.startswith(prefix):
                payload[name][key[len(prefix):]] = value
                break
    payload["folders"].sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("id", ""))))
    return _state_from_payload(payload)


def _state_from_payload(payload: Any) -> LibraryState:
    if not isinstance(payload, dict):
        return LibraryState(folders=default_folders(), assignments={}, aliases={}, archived={})

    folders = []
    for item in payload.get("folders", []):
        if isinstance(item, dict):
            folders.append(LibraryFolder.from_dict(item))
    if not any(folder.id == UNFILED_FOLDER_ID for folder in folders):
        folders = default_folders() + folders
    folder_ids = {folder.id for folder in folders}
    for folder in folders:
        if folder.parent_id not in folder_ids:
            folder.parent_id = ""

    raw_assignments = payload.get("assignments", {})
    assignments = {str(key): str(value) for key, value in raw_assignments.items()} if isinstance(raw_assignments, dict) else {}
    assignments = {key: value for key, value in assignments.items() if value in folder_ids}
    raw_aliases = payload.get("aliases", {})
    aliases = {str(key): str(value) for key, value in raw_aliases.items() if str(value).strip()} if isinstance(raw_aliases, dict) else {}
    raw_archived = payload.get("archived", {})
    archived = {str(key): str(value) for key, value in raw_archived.items()} if isinstance(raw_archived, dict) else {}
    return LibraryState(folders=folders, assignments=assignments, aliases=aliases, archived=archived)


def _payload(state: LibraryState) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "app": "PDFNest",
        "folders": [folder.to_dict() for folder in state.folders],
        "assignments": dict(sorted(state.assignments.items())),
        "aliases": dict(sorted(state.aliases.items())),
        "archived": dict(sorted(state.archived.items())),
    }


def save_library(state: LibraryState, data_dir: Path | None = None) -> Path:
    """Records this computer's library changes and updates ``state`` to the merged library.

    Only what changed here since ``state`` was loaded is written, into this computer's own replica,
    so a state that is out of date never removes a folder, filing or archive change made on the other
    computer. ``library.json`` is rewritten as a readable copy of the merged library.
    """
    path = library_path(data_dir)
    merged_records = sync_store.save_records(
        path,
        _records(state),
        state.base,
        legacy=_legacy_records(path),
        materialize=lambda records: _payload(_state_from_records(records)),
    )
    merged = _state_from_records(merged_records)
    state.folders[:] = merged.folders
    for name in ("assignments", "aliases", "archived"):
        target = getattr(state, name)
        target.clear()
        target.update(getattr(merged, name))
    state.base = _records(state)
    return path
