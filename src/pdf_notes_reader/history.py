from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pdf_notes_reader.notes import default_data_dir, notebook_dir_for_pdf, pdf_key_for_path, root_sync_lock_path, utc_now
from pdf_notes_reader.notes import _atomic_write_json, _ensure_cover, _manifest_payload, _markups_payload, _write_sync_lock


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
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def exists(self) -> bool:
        return Path(self.path).exists()


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


def load_history(data_dir: Path | None = None) -> list[PdfHistoryEntry]:
    path = history_path(data_dir)
    if not path.exists():
        path = legacy_history_path(data_dir)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    raw_entries = payload if isinstance(payload, list) else payload.get("entries", [])
    if not isinstance(raw_entries, list):
        return []

    entries: list[PdfHistoryEntry] = []
    for item in raw_entries:
        if isinstance(item, dict):
            entries.append(PdfHistoryEntry.from_dict(item))
    return sorted(entries, key=lambda entry: entry.updated_at, reverse=True)


def save_history(entries: list[PdfHistoryEntry], data_dir: Path | None = None, *, touched_pdf_keys: set[str] | None = None) -> Path:
    path = history_path(data_dir)
    payload = {
        "schema_version": 1,
        "app": "PDFNest",
        "entries": [entry.to_dict() for entry in entries],
    }
    _atomic_write_json(path, payload)
    _write_sync_lock(root_sync_lock_path(data_dir))
    touched = touched_pdf_keys
    for entry in entries:
        if touched is not None and entry.pdf_key not in touched:
            continue
        _save_notebook_recent_file(entry, data_dir)
    return path


def _save_notebook_recent_file(entry: PdfHistoryEntry, data_dir: Path | None = None) -> None:
    notebook_dir = notebook_dir_for_pdf(entry.path, entry.pdf_key, data_dir)
    notebook_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(notebook_dir / "manifest.json", _manifest_payload(pdf_key=entry.pdf_key, pdf_path=entry.path, page_count=entry.page_count))
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
        )
        entries.append(entry)
    else:
        entry.path = absolute_path
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
