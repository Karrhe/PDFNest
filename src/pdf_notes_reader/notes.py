from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_NAME = "PDFNotesReader"


@dataclass
class Note:
    id: str
    pdf_key: str
    page_index: int
    x_norm: float
    y_norm: float
    markdown: str
    created_at: str
    updated_at: str
    note_type: str = "point"
    rects_norm: list[list[float]] = field(default_factory=list)
    selected_text: str = ""
    color: str = ""
    note_number: int = 0

    @classmethod
    def create(
        cls,
        *,
        pdf_key: str,
        page_index: int,
        x_norm: float,
        y_norm: float,
        markdown: str = "",
        note_type: str = "point",
        rects_norm: list[list[float]] | None = None,
        selected_text: str = "",
        color: str = "",
        note_number: int = 0,
    ) -> "Note":
        now = utc_now()
        return cls(
            id=str(uuid.uuid4()),
            pdf_key=pdf_key,
            page_index=page_index,
            x_norm=clamp01(x_norm),
            y_norm=clamp01(y_norm),
            markdown=markdown,
            created_at=now,
            updated_at=now,
            note_type=note_type,
            rects_norm=rects_norm or [],
            selected_text=selected_text,
            color=str(color),
            note_number=max(0, int(note_number)),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Note":
        return cls(
            id=str(data["id"]),
            pdf_key=str(data["pdf_key"]),
            page_index=int(data["page_index"]),
            x_norm=clamp01(float(data["x_norm"])),
            y_norm=clamp01(float(data["y_norm"])),
            markdown=str(data.get("markdown", "")),
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            note_type=str(data.get("note_type") or "point"),
            rects_norm=normalize_rects(data.get("rects_norm", [])),
            selected_text=str(data.get("selected_text", "")),
            color=str(data.get("color", "")),
            note_number=normalize_nonnegative_int(data.get("note_number"), default=0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def update_markdown(self, markdown: str) -> None:
        self.markdown = markdown
        self.updated_at = utc_now()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalize_rects(value: Any) -> list[list[float]]:
    if not isinstance(value, list):
        return []

    rects: list[list[float]] = []
    for item in value:
        if not isinstance(item, list | tuple) or len(item) != 4:
            continue
        rects.append([clamp01(float(coord)) for coord in item])
    return rects


def default_data_dir() -> Path:
    override = os.environ.get("PDF_NOTES_READER_DATA_DIR")
    if override:
        return Path(override).expanduser()

    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
    else:
        app_dir = Path(__file__).resolve().parents[2]
    return app_dir / ".local-data"


def notes_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "notes"


def pdf_key_for_path(pdf_path: str | Path) -> str:
    path = Path(pdf_path).expanduser()
    try:
        canonical = path.resolve(strict=False)
    except OSError:
        canonical = path.absolute()

    normalized = os.path.normcase(str(canonical))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def notes_path_for_key(pdf_key: str, data_dir: Path | None = None) -> Path:
    return notes_dir(data_dir) / f"{pdf_key}.json"


def load_notes(pdf_key: str, data_dir: Path | None = None) -> list[Note]:
    notes, _counters = load_notes_with_counters(pdf_key, data_dir)
    return notes


def load_notes_with_counters(pdf_key: str, data_dir: Path | None = None) -> tuple[list[Note], dict[str, int]]:
    path = notes_path_for_key(pdf_key, data_dir)
    if not path.exists():
        return [], {}

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    raw_notes = payload.get("notes", [])
    if not isinstance(raw_notes, list):
        return [], {}

    notes: list[Note] = []
    for item in raw_notes:
        if isinstance(item, dict):
            notes.append(Note.from_dict(item))
    return notes, normalize_note_counters(payload.get("note_counters", {}))


def normalize_note_counters(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counters: dict[str, int] = {}
    for key, counter in value.items():
        try:
            counters[str(key)] = max(1, int(counter))
        except (TypeError, ValueError):
            continue
    return counters


def normalize_nonnegative_int(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def save_notes(
    *,
    pdf_key: str,
    pdf_path: str | Path,
    notes: list[Note],
    note_counters: dict[str, int] | None = None,
    data_dir: Path | None = None,
) -> Path:
    path = notes_path_for_key(pdf_key, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "pdf_key": pdf_key,
        "pdf_path": str(Path(pdf_path).expanduser()),
        "schema_version": 1,
        "note_counters": normalize_note_counters(note_counters or {}),
        "notes": [note.to_dict() for note in notes],
    }
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)
    return path


def find_note(notes: list[Note], note_id: str) -> Note | None:
    return next((note for note in notes if note.id == note_id), None)
