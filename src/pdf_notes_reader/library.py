from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdf_notes_reader.notes import default_data_dir, utc_now


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


def library_path(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "library.json"


def default_folders() -> list[LibraryFolder]:
    return [
        LibraryFolder(id=UNFILED_FOLDER_ID, name="Unfiled", created_at=utc_now()),
    ]


def load_library(data_dir: Path | None = None) -> LibraryState:
    path = library_path(data_dir)
    if not path.exists():
        return LibraryState(folders=default_folders(), assignments={}, aliases={}, archived={})

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return LibraryState(folders=default_folders(), assignments={}, aliases={}, archived={})

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


def save_library(state: LibraryState, data_dir: Path | None = None) -> Path:
    path = library_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "app": "PDFNest",
        "folders": [folder.to_dict() for folder in state.folders],
        "assignments": dict(sorted(state.assignments.items())),
        "aliases": dict(sorted(state.aliases.items())),
        "archived": dict(sorted(state.archived.items())),
    }
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)
    return path
