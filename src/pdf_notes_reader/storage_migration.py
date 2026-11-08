from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pdf_notes_reader.history import PdfHistoryEntry, history_path, legacy_history_path, load_history, save_history
from pdf_notes_reader.notes import (
    Bookmark,
    Note,
    _atomic_write_json,
    app_local_data_dir,
    default_data_dir,
    notebooks_dir,
    notes_path_for_key,
    portable_locators,
    read_manifest,
    rebuild_notebook_index,
    record_storage_issue,
    save_notes,
    utc_now,
)
from pdf_notes_reader.settings import DEFAULT_SETTINGS, save_settings, settings_path


# 1: old notes/ and pdf_history.json moved into notebooks/. 2: portable locators (cross-machine sync).
MIGRATION_VERSION = 2


def migration_state_path(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "migration_state.json"


def migrate_storage(data_dir: Path | None = None, *, legacy_roots: list[Path] | None = None) -> bool:
    target_dir = data_dir or default_data_dir()
    state_path = migration_state_path(target_dir)
    state = _read_migration_state(state_path)
    version = _state_version(state)
    # Locators are relative to the data folder, so a copied or moved data folder recomputes them.
    locators_current = version >= 2 and str(state.get("locators_dir") or "") == str(target_dir)
    if version >= MIGRATION_VERSION and locators_current:
        return False

    migrated = False
    if version < 1:
        roots = legacy_roots or _legacy_roots(target_dir)
        migrated = _migrate_settings(target_dir, roots) or migrated
        migrated = _migrate_history(target_dir, roots) or migrated
        rebuild_notebook_index(target_dir)
        migrated = _migrate_notes(target_dir, roots) or migrated
        rebuild_notebook_index(target_dir)
    if not locators_current:
        migrated = backfill_portable_locators(target_dir) or migrated
    _write_migration_state(state_path, target_dir)
    return migrated


def _read_migration_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _state_version(state: dict[str, Any]) -> int:
    try:
        return int(state.get("schema_version", 0))
    except (TypeError, ValueError):
        return 0


def _migration_complete(path: Path) -> bool:
    return _state_version(_read_migration_state(path)) >= MIGRATION_VERSION


def _write_migration_state(path: Path, target_dir: Path) -> None:
    payload = {
        "schema_version": MIGRATION_VERSION,
        "migrated_at": utc_now(),
        "locators_dir": str(target_dir),
    }
    _atomic_write_json(path, payload)


def backfill_portable_locators(target_dir: Path) -> bool:
    """Adds ``relpath`` and ``fingerprint`` to notebooks saved before cross-machine lookup existed.

    Notebooks keep their key and folder: nothing is renamed or re-keyed, so no note can be lost. The
    locators only let another computer sharing this data folder find the notebook for its own path to
    the same PDF (see ``notes.resolve_pdf_key``). PDFs that are missing here, or only in the cloud,
    are left for the computer that has them. History entries get their ``rel_path`` the same way.
    """
    changed = False
    root = notebooks_dir(target_dir)
    for manifest_path in sorted(root.glob("*/manifest.json")) if root.exists() else []:
        manifest = read_manifest(manifest_path)
        resources = manifest.get("res")
        if not manifest.get("pdf_key") or not isinstance(resources, list) or not resources or not isinstance(resources[0], dict):
            continue
        refpath = str(resources[0].get("refpath") or "")
        if not refpath:
            continue
        locators = portable_locators(refpath, target_dir, manifest)
        if all(manifest.get(name) == value for name, value in locators.items()):
            continue
        manifest.update(locators)
        try:
            _atomic_write_json(manifest_path, manifest)
        except OSError as exc:
            record_storage_issue(f"Could not update {manifest_path} for cloud sync ({exc}).", manifest_path)
            continue
        changed = True
    if history_path(target_dir).exists():
        entries = load_history(target_dir)
        before = [entry.rel_path for entry in entries]
        if entries:
            save_history(entries, target_dir, touched_pdf_keys=set())
            changed = changed or before != [entry.rel_path for entry in entries]
    rebuild_notebook_index(target_dir)
    return changed


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
        try:
            _read_json(legacy)  # validate first: load_history would quarantine (rename) a corrupt file
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            record_storage_issue(f"Old history file {legacy.name} could not be read and was not migrated ({exc}).", legacy)
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
    # Legacy files are never modified or deleted; problems are reported instead of skipped silently.
    try:
        payload = _read_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        record_storage_issue(f"Old notes file {path.name} could not be read and was not migrated ({exc}).", path)
        return False
    if not isinstance(payload, dict):
        record_storage_issue(f"Old notes file {path.name} has an unknown format and was not migrated.", path)
        return False
    pdf_key = str(payload.get("pdf_key") or path.stem)
    if notes_path_for_key(pdf_key, target_dir).exists():
        return False
    pdf_path = str(payload.get("pdf_path") or "") or _history_path_for_key(pdf_key, target_dir)
    if not pdf_path:
        # Still migrate: notes are found by pdf_key, so they reappear when that PDF is opened again.
        pdf_path = str(path.with_suffix(".pdf"))
        record_storage_issue(
            f"Old notes file {path.name} did not record its PDF; its notes were migrated and appear when the PDF is opened from its original location.",
            path,
        )
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


def _history_path_for_key(pdf_key: str, target_dir: Path) -> str:
    for entry in load_history(target_dir):
        if entry.pdf_key == pdf_key:
            return entry.path
    return ""


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
