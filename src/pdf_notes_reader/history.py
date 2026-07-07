from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pdf_notes_reader.notes import default_data_dir, pdf_key_for_path, utc_now


@dataclass
class PdfHistoryEntry:
    pdf_key: str
    path: str
    title: str
    last_page_index: int
    page_count: int
    opened_at: str
    updated_at: str

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
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def exists(self) -> bool:
        return Path(self.path).exists()


def history_path(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "pdf_history.json"


def load_history(data_dir: Path | None = None) -> list[PdfHistoryEntry]:
    path = history_path(data_dir)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    raw_entries = payload.get("entries", [])
    if not isinstance(raw_entries, list):
        return []

    entries: list[PdfHistoryEntry] = []
    for item in raw_entries:
        if isinstance(item, dict):
            entries.append(PdfHistoryEntry.from_dict(item))
    return sorted(entries, key=lambda entry: entry.updated_at, reverse=True)


def save_history(entries: list[PdfHistoryEntry], data_dir: Path | None = None) -> Path:
    path = history_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "entries": [entry.to_dict() for entry in entries],
    }
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)
    return path


def find_history_entry(entries: list[PdfHistoryEntry], pdf_key: str) -> PdfHistoryEntry | None:
    return next((entry for entry in entries if entry.pdf_key == pdf_key), None)


def upsert_history_entry(
    entries: list[PdfHistoryEntry],
    *,
    pdf_key: str,
    path: str | Path,
    page_count: int,
    last_page_index: int,
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
        )
        entries.append(entry)
    else:
        entry.path = absolute_path
        entry.title = Path(absolute_path).name
        entry.page_count = max(0, page_count)
        entry.last_page_index = max(0, min(last_page_index, max(page_count - 1, 0)))
        entry.updated_at = now

    entries.sort(key=lambda item: item.updated_at, reverse=True)
    return entry


def remove_history_entry(entries: list[PdfHistoryEntry], pdf_key: str) -> list[PdfHistoryEntry]:
    return [entry for entry in entries if entry.pdf_key != pdf_key]
