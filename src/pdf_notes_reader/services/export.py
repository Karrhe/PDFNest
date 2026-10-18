"""Markdown export: Windows-safe file names and writing note files."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from pdf_notes_reader.notes import Note


class ExportError(OSError):
    """A note could not be written; the message is meant for the user."""


def safe_filename(value: str, *, max_length: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    cleaned = cleaned or "untitled"
    if len(cleaned) <= max_length:
        return cleaned
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]
    prefix_length = max(1, max_length - len(digest) - 1)
    prefix = cleaned[:prefix_length].rstrip(" ._-") or "untitled"
    return f"{prefix}-{digest}"


def unique_markdown_path(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}-{datetime.now().strftime('%f')}{path.suffix}")


def export_note_markdown(
    note: Note,
    *,
    pdf_path: Path,
    export_root: Path,
    location: str,
    note_number: int,
    replace_existing: bool = False,
) -> Path:
    """Writes ``note`` as a .md file and records the path on the note."""
    try:
        if replace_existing and note.exported_markdown_path:
            path = Path(note.exported_markdown_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(note.markdown, encoding="utf-8")
            note.exported_markdown_path = str(path)
            return path

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        export_dir = export_root / safe_filename(pdf_path.stem, max_length=48)
        export_dir.mkdir(parents=True, exist_ok=True)
        location_part = safe_filename(location, max_length=48)
        filename_stem = safe_filename(f"{timestamp}-{location_part}-{note_number}", max_length=150)
        path = unique_markdown_path(export_dir / f"{filename_stem}.md")
        path.write_text(note.markdown, encoding="utf-8")
    except OSError as exc:
        raise ExportError(f"Could not write the Markdown file: {exc}") from exc
    note.exported_markdown_path = str(path)
    return path
