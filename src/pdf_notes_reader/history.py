from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pdf_notes_reader.notes import default_data_dir, notebook_dir_for_pdf, pdf_key_for_path, root_sync_lock_path, utc_now
from pdf_notes_reader.notes import _atomic_write_json, _ensure_cover, _manifest_payload, _markups_payload, _write_sync_lock, read_json_checked
from pdf_notes_reader.notes import _LOCATOR_CACHE, _absorb_conflicts, _dict_list, machine_id, read_manifest
from pdf_notes_reader import sync_store
from pdf_notes_reader.portable import ensure_local, icloud_stub_for, portable_relpath


@dataclass
class PdfHistoryEntry:
    pdf_key: str
    path: str
    title: str
    last_page_index: int
    page_count: int
    opened_at: str
    updated_at: str
    last_note_id: str = ""
    zoom: float = 1.25
    fit_mode: str = ""
    # ``path`` relative to the data folder (``/`` separators): finds the PDF on another computer that
    # shares the data folder through iCloud Drive, OneDrive or Dropbox. Empty on another drive.
    rel_path: str = ""
    # Where each computer sharing the data folder keeps this PDF: machine id -> absolute path. The
    # book (notes, cover, reading position) is the same everywhere; only its file location differs.
    machine_paths: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PdfHistoryEntry":
        path = str(data.get("path", ""))
        return cls(
            pdf_key=str(data.get("pdf_key") or pdf_key_for_path(path)),
            path=path,
            title=str(data.get("title") or Path(path).name),
            last_page_index=max(0, int(data.get("last_page_index", 0))),
            page_count=max(0, int(data.get("page_count", 0))),
            opened_at=str(data.get("opened_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            last_note_id=str(data.get("last_note_id") or ""),
            zoom=normalize_zoom(data.get("zoom")),
            fit_mode=normalize_fit_mode(data.get("fit_mode")),
            rel_path=str(data.get("rel_path") or ""),
            machine_paths=_clean_machine_paths(data.get("machine_paths")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def exists(self) -> bool:
        return Path(self.path).exists()

    @property
    def located_here(self) -> bool:
        """Whether this computer has been told where the PDF is (opened, added or relocated here)."""
        return machine_id() in self.machine_paths

    @property
    def in_cloud_only(self) -> bool:
        """The PDF is an iCloud ``.name.icloud`` stub: present, but not downloaded to this computer."""
        return not self.exists and icloud_stub_for(self.path).exists()


def _clean_machine_paths(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(path) for key, path in value.items() if str(key) and str(path)}


def _combine_machine_paths(winner: dict[str, Any], versions: list[tuple[str, Any]]) -> dict[str, Any]:
    """Each computer's path to the PDF survives, whichever computer's copy of the entry is newest."""
    paths: dict[str, str] = {}
    for _stamp, data in sorted(versions, key=lambda item: item[0]):
        if isinstance(data, dict):
            paths.update(_clean_machine_paths(data.get("machine_paths")))
    combined = dict(winner)
    combined["machine_paths"] = dict(sorted(paths.items()))
    return combined


def history_path(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "recentnotes.json"


def legacy_history_path(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "pdf_history.json"


def normalize_zoom(value: Any) -> float:
    try:
        zoom = float(value)
    except (TypeError, ValueError):
        zoom = 1.25
    return max(0.3, min(4.0, zoom))


def normalize_fit_mode(value: Any) -> str:
    mode = str(value or "")
    return mode if mode in {"width", "height"} else ""


def _legacy_records(data_dir: Path | None) -> dict[str, dict[str, Any]]:
    """Entries from the plain ``recentnotes.json`` (or the older ``pdf_history.json``)."""
    path = history_path(data_dir)
    if not path.exists() and not ensure_local(path):
        path = legacy_history_path(data_dir)
    if not path.exists():
        return {}
    # Conflict copies (recentnotes 2.json...) may hold books the plain file lost: fold them in.
    _absorb_conflicts(path, _union_history_payloads, path.parent / "conflicts")
    payload = read_json_checked(path)
    raw_entries = payload if isinstance(payload, list) else payload.get("entries", []) if isinstance(payload, dict) else []
    records: dict[str, dict[str, Any]] = {}
    for item in _dict_list(raw_entries):
        try:
            entry = PdfHistoryEntry.from_dict(item)
        except (TypeError, ValueError):
            continue
        records[entry.pdf_key] = entry.to_dict()
    return records


def _union_history_payloads(ours: Any, theirs: Any, _base: Any = None) -> dict[str, Any]:
    """Every book either copy has, the more recently read version of each."""
    books: dict[str, dict[str, Any]] = {}
    for payload in (theirs, ours):
        for item in _dict_list(payload.get("entries") if isinstance(payload, dict) else payload):
            key = str(item.get("pdf_key") or "")
            if key and (key not in books or str(item.get("updated_at", "")) >= str(books[key].get("updated_at", ""))):
                books[key] = item
    return {"schema_version": 1, "app": "PDFNest", "entries": list(books.values())}


def _entries_from_records(records: dict[str, Any], data_dir: Path | None) -> list[PdfHistoryEntry]:
    root = data_dir or default_data_dir()
    entries: list[PdfHistoryEntry] = []
    for data in records.values():
        if not isinstance(data, dict):
            continue
        try:
            entry = PdfHistoryEntry.from_dict(data)
        except (TypeError, ValueError):
            continue
        resolve_entry_path(entry, root)
        entries.append(entry)
    return sorted(entries, key=lambda entry: entry.updated_at, reverse=True)


def _materialize(records: dict[str, Any]) -> dict[str, Any]:
    entries = sorted((data for data in records.values() if isinstance(data, dict)), key=lambda item: str(item.get("updated_at", "")), reverse=True)
    return {"schema_version": 1, "app": "PDFNest", "entries": entries}


def load_history(data_dir: Path | None = None) -> list[PdfHistoryEntry]:
    """Every computer's books, merged (see ``sync_store``): newest change per book wins."""
    path = history_path(data_dir)
    records = sync_store.load_records(path, _legacy_records(data_dir), combine=_combine_machine_paths)
    entries = _entries_from_records(records, data_dir)
    _HISTORY_BASES[str(path)] = {entry.pdf_key: entry.to_dict() for entry in entries}
    return entries


# pdf_key -> entry as this process last loaded or saved it: a book that differs from it changed
# here, one missing from the saved list was removed here. Nothing else is touched by a save.
_HISTORY_BASES: dict[str, dict[str, dict[str, Any]]] = {}


def reload_history_into(entries: list[PdfHistoryEntry], data_dir: Path | None = None) -> bool:
    """Shows books the other computer added, removed or read further, without writing anything.

    Books changed here since the last save keep this computer's version. Returns whether
    ``entries`` changed.
    """
    path = history_path(data_dir)
    base = _HISTORY_BASES.get(str(path))
    merged = _entries_from_records(
        sync_store.load_records(path, _legacy_records(data_dir), combine=_combine_machine_paths), data_dir
    )
    by_key = {entry.pdf_key: entry for entry in merged}
    if base is not None:
        for entry in entries:  # unsaved changes made here win
            if base.get(entry.pdf_key) != entry.to_dict():
                by_key[entry.pdf_key] = entry
    _HISTORY_BASES[str(path)] = {key: entry.to_dict() for key, entry in by_key.items()}
    updated = sorted(by_key.values(), key=lambda item: item.updated_at, reverse=True)
    if [entry.to_dict() for entry in updated] == [entry.to_dict() for entry in entries]:
        return False
    entries[:] = updated
    return True


def resolve_entry_path(entry: PdfHistoryEntry, data_dir: Path) -> None:
    """Points ``entry.path`` at the PDF on this computer, which may not be the one that recorded it.

    In order: the path this computer recorded (``machine_paths``); the path relative to the shared
    data folder (``rel_path``), for a PDF that is in the cloud drive too; ``path`` as written by
    whichever computer saved last. When none exists, the user is asked to locate the file once.
    """
    own = entry.machine_paths.get(machine_id())
    if own:
        entry.path = own
        if Path(own).exists():
            return
    if not entry.rel_path:
        return
    try:
        candidate = Path(os.path.normpath(data_dir / entry.rel_path))
        # The copy next to the shared data folder wins: on the computer that wrote ``path`` it is the
        # same file, and elsewhere ``path`` may name an unrelated local file.
        if candidate.exists() or (not Path(entry.path).exists() and icloud_stub_for(candidate).exists()):
            entry.path = str(candidate)
    except (OSError, ValueError):
        return


def save_history(entries: list[PdfHistoryEntry], data_dir: Path | None = None, *, touched_pdf_keys: set[str] | None = None) -> Path:
    """Records this computer's changes to the book list and updates ``entries`` (in place) to the
    merged list of all computers sharing the data folder.

    Only books that changed here (or were removed here) are written as changes, into this computer's
    own replica, so saving a list that is out of date never removes or rolls back what the other
    computer did. ``recentnotes.json`` is rewritten as a readable copy of the merged list.
    """
    path = history_path(data_dir)
    root = data_dir or default_data_dir()
    for entry in entries:
        _refresh_rel_path(entry, root)
    current = {entry.pdf_key: entry.to_dict() for entry in entries}
    merged = sync_store.save_records(
        path,
        current,
        _HISTORY_BASES.get(str(path)),
        legacy=_legacy_records(data_dir),
        combine=_combine_machine_paths,
        materialize=_materialize,
    )
    updated = _entries_from_records(merged, data_dir)
    _HISTORY_BASES[str(path)] = {entry.pdf_key: entry.to_dict() for entry in updated}
    if [entry.to_dict() for entry in updated] != [entry.to_dict() for entry in entries]:
        entries[:] = updated
    _write_sync_lock(root_sync_lock_path(data_dir))
    touched = touched_pdf_keys
    for entry in entries:
        if touched is not None and entry.pdf_key not in touched:
            continue
        _save_notebook_recent_file(entry, data_dir)
    return path


def _refresh_rel_path(entry: PdfHistoryEntry, data_dir: Path) -> None:
    try:
        if Path(entry.path).exists():
            entry.rel_path = portable_relpath(entry.path, data_dir)
    except (OSError, ValueError):
        return


def _save_notebook_recent_file(entry: PdfHistoryEntry, data_dir: Path | None = None) -> None:
    notebook_dir = notebook_dir_for_pdf(entry.path, entry.pdf_key, data_dir)
    notebook_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = notebook_dir / "manifest.json"
    _atomic_write_json(
        manifest_path,
        _manifest_payload(
            pdf_key=entry.pdf_key,
            pdf_path=entry.path,
            page_count=entry.page_count,
            data_dir=data_dir,
            previous=read_manifest(manifest_path),
        ),
    )
    _LOCATOR_CACHE.clear()
    if not (notebook_dir / "markups.json").exists():
        _atomic_write_json(notebook_dir / "markups.json", _markups_payload([]))
    recent_payload = [
        {
            "~docid": 0,
            "~entry": "",
            "~mod": entry.updated_at,
            "~view": [entry.last_page_index, -1, round(entry.zoom * 100, 4), 0, 0, False, 0, False, 0, False, False, False, ""],
        }
    ]
    _atomic_write_json(notebook_dir / "recentfile.json", recent_payload)
    _write_sync_lock(notebook_dir / "sync.lock")
    _ensure_cover(entry.path, notebook_dir)


def find_history_entry(entries: list[PdfHistoryEntry], pdf_key: str) -> PdfHistoryEntry | None:
    return next((entry for entry in entries if entry.pdf_key == pdf_key), None)


def upsert_history_entry(
    entries: list[PdfHistoryEntry],
    *,
    pdf_key: str,
    path: str | Path,
    page_count: int,
    last_page_index: int,
    last_note_id: str = "",
    zoom: float = 1.25,
    fit_mode: str | None = "",
) -> PdfHistoryEntry:
    now = utc_now()
    absolute_path = str(Path(path).expanduser().resolve(strict=False))
    entry = find_history_entry(entries, pdf_key)

    if entry is None:
        entry = PdfHistoryEntry(
            pdf_key=pdf_key,
            path=absolute_path,
            title=Path(absolute_path).name,
            last_page_index=max(0, last_page_index),
            page_count=max(0, page_count),
            opened_at=now,
            updated_at=now,
            last_note_id=str(last_note_id or ""),
            zoom=normalize_zoom(zoom),
            fit_mode=normalize_fit_mode(fit_mode),
            machine_paths={machine_id(): absolute_path},
        )
        entries.append(entry)
    else:
        entry.path = absolute_path
        entry.machine_paths[machine_id()] = absolute_path
        entry.title = Path(absolute_path).name
        entry.page_count = max(0, page_count)
        entry.last_page_index = max(0, min(last_page_index, max(page_count - 1, 0)))
        entry.last_note_id = str(last_note_id or "")
        entry.zoom = normalize_zoom(zoom)
        entry.fit_mode = normalize_fit_mode(fit_mode)
        entry.updated_at = now

    entries.sort(key=lambda item: item.updated_at, reverse=True)
    return entry


def remove_history_entry(entries: list[PdfHistoryEntry], pdf_key: str) -> list[PdfHistoryEntry]:
    return [entry for entry in entries if entry.pdf_key != pdf_key]
