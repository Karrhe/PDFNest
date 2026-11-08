from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pdf_notes_reader.notes import _absorb_conflicts, _atomic_write_json, default_data_dir, read_json_checked, utc_now
from pdf_notes_reader.portable import ensure_local, merge_records


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
    path = library_path(data_dir)
    if ensure_local(path):
        _absorb_conflicts(path, _merge_library_payloads, path.parent / "conflicts")
    payload = read_json_checked(path) if path.exists() else None
    state = _state_from_payload(payload)
    state.base = _payload(state)
    return state


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


def _merge_mapping(ours: dict, theirs: dict, base: dict | None) -> dict:
    """Three-way merge of a key -> value map: a change made here wins, otherwise the other computer's
    value (or removal) is taken. Without a base, the two are combined and this computer's values win."""
    if base is None:
        merged = dict(theirs)
        merged.update(ours)
        return merged
    merged: dict = {}
    for key in set(ours) | set(theirs):
        changed_here = ours.get(key) != base.get(key)
        source = ours if changed_here else theirs
        if key in source:
            merged[key] = source[key]
    return dict(sorted(merged.items()))


def _merge_library_payloads(ours: dict[str, Any], theirs: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    def mapping(payload: dict[str, Any] | None, name: str) -> dict | None:
        if payload is None:
            return None
        value = payload.get(name)
        return dict(value) if isinstance(value, dict) else {}

    base_folders = None
    if base is not None:
        base_folders = {str(item.get("id")): str(item.get("created_at", "")) for item in base.get("folders", []) if isinstance(item, dict)}
    merged = {
        "schema_version": 1,
        "app": "PDFNest",
        "folders": merge_records(
            [item for item in ours.get("folders", []) if isinstance(item, dict)],
            [item for item in theirs.get("folders", []) if isinstance(item, dict)],
            base=base_folders,
            stamp="created_at",
        ),
    }
    for name in ("assignments", "aliases", "archived"):
        merged[name] = _merge_mapping(mapping(ours, name) or {}, mapping(theirs, name) or {}, mapping(base, name))
    return merged


def save_library(state: LibraryState, data_dir: Path | None = None) -> Path:
    """Writes the library, merged with the copy on disk.

    With the data folder in iCloud Drive (or OneDrive / Dropbox), the other computer may have added
    folders, filed books or archived some since this state was loaded; those changes are kept, and the
    merged result is applied to ``state`` too.
    """
    path = library_path(data_dir)
    payload = _payload(state)
    if ensure_local(path):
        _absorb_conflicts(path, _merge_library_payloads, path.parent / "conflicts")
    on_disk = read_json_checked(path) if path.exists() else None
    if isinstance(on_disk, dict):
        payload = _merge_library_payloads(payload, on_disk, state.base)
        merged = _state_from_payload(payload)
        state.folders[:] = merged.folders
        for name in ("assignments", "aliases", "archived"):
            target = getattr(state, name)
            target.clear()
            target.update(getattr(merged, name))
        payload = _payload(state)
    _atomic_write_json(path, payload)
    state.base = payload
    return path
