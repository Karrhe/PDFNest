from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pdf_notes_reader.history import PdfHistoryEntry, history_path, legacy_history_path, load_history, save_history
from pdf_notes_reader.notes import (
    Bookmark,
    Note,
    app_local_data_dir,
    default_data_dir,
    notes_path_for_key,
    rebuild_notebook_index,
    save_notes,
    utc_now,
)
from pdf_notes_reader.settings import DEFAULT_SETTINGS, save_settings, settings_path


MIGRATION_VERSION = 1


def migration_state_path(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "migration_state.json"


def migrate_storage(data_dir: Path | None = None, *, legacy_roots: list[Path] | None = None) -> bool:
    target_dir = data_dir or default_data_dir()
    state_path = migration_state_path(target_dir)
    if _migration_complete(state_path):
        return False

    roots = legacy_roots or _legacy_roots(target_dir)
    migrated = False
    migrated = _migrate_settings(target_dir, roots) or migrated
    migrated = _migrate_history(target_dir, roots) or migrated
    rebuild_notebook_index(target_dir)
    migrated = _migrate_notes(target_dir, roots) or migrated
    rebuild_notebook_index(target_dir)
    _write_migration_state(state_path)
    return migrated


def _migration_complete(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    try:
        return int(payload.get("schema_version", 0)) >= MIGRATION_VERSION
    except (TypeError, ValueError):
        return False


def _write_migration_state(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": MIGRATION_VERSION,
        "migrated_at": utc_now(),
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _legacy_roots(target_dir: Path) -> list[Path]:
    if os.environ.get("PDF_NOTES_READER_DATA_DIR"):
        return [target_dir]
    roots = [target_dir, app_local_data_dir()]
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        marker = str(root.resolve(strict=False)).lower()
        if marker not in seen:
            seen.add(marker)
            unique.append(root)
    return unique


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _migrate_settings(target_dir: Path, legacy_roots: list[Path]) -> bool:
    target = settings_path(target_dir)
    if target.exists():
        return False
    for root in legacy_roots:
        legacy = root / "settings.json"
        if not legacy.exists():
            continue
        try:
            payload = _read_json(legacy)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        settings = dict(DEFAULT_SETTINGS)
        settings.update({key: value for key, value in payload.items() if key in DEFAULT_SETTINGS})
        settings["storage_dir"] = str(target_dir)
        save_settings(settings, data_dir=target_dir)
        return True
    return False


def _migrate_history(target_dir: Path, legacy_roots: list[Path]) -> bool:
    if history_path(target_dir).exists():
        return False
    entries: list[PdfHistoryEntry] = []
    for root in legacy_roots:
        legacy = legacy_history_path(root)
        if not legacy.exists():
            continue
        entries.extend(load_history(root))
    entries = _dedupe_history(entries)
    if not entries:
        return False
    save_history(entries, target_dir)
    return True


def _dedupe_history(entries: list[PdfHistoryEntry]) -> list[PdfHistoryEntry]:
    by_key: dict[str, PdfHistoryEntry] = {}
    for entry in entries:
        existing = by_key.get(entry.pdf_key)
        if existing is None or entry.updated_at > existing.updated_at:
            by_key[entry.pdf_key] = entry
    return sorted(by_key.values(), key=lambda item: item.updated_at, reverse=True)


def _migrate_notes(target_dir: Path, legacy_roots: list[Path]) -> bool:
    migrated = False
    for root in legacy_roots:
        legacy_dir = root / "notes"
        if not legacy_dir.exists():
            continue
        for path in legacy_dir.glob("*.json"):
            migrated = _migrate_note_file(path, target_dir) or migrated
    return migrated


def _migrate_note_file(path: Path, target_dir: Path) -> bool:
    try:
        payload = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    pdf_key = str(payload.get("pdf_key") or path.stem)
    pdf_path = str(payload.get("pdf_path") or "")
    if not pdf_path:
        return False
    if notes_path_for_key(pdf_key, target_dir).exists():
        return False
    notes = _notes_from_payload(payload)
    bookmarks = _bookmarks_from_payload(payload)
    counters = payload.get("note_counters", {})
    save_notes(
        pdf_key=pdf_key,
        pdf_path=pdf_path,
        notes=notes,
        note_counters=counters if isinstance(counters, dict) else {},
        bookmarks=bookmarks,
        data_dir=target_dir,
    )
    return True


def _notes_from_payload(payload: dict[str, Any]) -> list[Note]:
    notes: list[Note] = []
    raw_notes = payload.get("notes", [])
    if not isinstance(raw_notes, list):
        return notes
    for item in raw_notes:
        if isinstance(item, dict):
            try:
                notes.append(Note.from_dict(item))
            except (KeyError, TypeError, ValueError):
                continue
    return notes


def _bookmarks_from_payload(payload: dict[str, Any]) -> list[Bookmark]:
    bookmarks: list[Bookmark] = []
    raw_bookmarks = payload.get("bookmarks", [])
    if not isinstance(raw_bookmarks, list):
        return bookmarks
    for item in raw_bookmarks:
        if isinstance(item, dict):
            try:
                bookmarks.append(Bookmark.from_dict(item))
            except (KeyError, TypeError, ValueError):
                continue
    return bookmarks
