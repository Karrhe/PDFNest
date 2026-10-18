"""One-file backups of everything PDFNest stores (notes, anchors, bookmarks, library, settings)."""

from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

from pdf_notes_reader.notes import APP_NAME

SKIPPED_SUFFIXES = (".tmp", ".lock")
SKIPPED_NAMES = {"cover.png"}  # regenerated from the PDF on demand


def default_backup_name() -> str:
    return f"PDFNest-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"


def create_backup(data_dir: Path, target: Path) -> tuple[Path, int]:
    """Writes a zip of ``data_dir``; returns (path, number of files). Written to a temp name first."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"PDFNest data folder not found: {data_dir}")
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".partial")
    count = 0
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(data_dir.rglob("*")):
                if not path.is_file() or path.name in SKIPPED_NAMES or path.name.endswith(SKIPPED_SUFFIXES):
                    continue
                if path.resolve() == target.resolve() or path == tmp:
                    continue
                archive.write(path, Path("Note_PDFNest") / path.relative_to(data_dir))
                count += 1
            archive.writestr(
                "Note_PDFNest/backup_info.json",
                json.dumps({"app": APP_NAME, "created_at": datetime.now().isoformat(timespec="seconds"),
                            "source": str(data_dir), "files": count}, ensure_ascii=False, indent=2),
            )
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target, count


def verify_backup(path: Path) -> list[str]:
    """Names of JSON files in the backup that do not parse (empty list = backup is readable)."""
    broken: list[str] = []
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            return ["<zip checksum error>"]
        for name in archive.namelist():
            if name.endswith(".json"):
                try:
                    json.loads(archive.read(name).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    broken.append(name)
    return broken
