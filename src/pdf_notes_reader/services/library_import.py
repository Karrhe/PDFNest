"""Finding the PDFs to add to the library from picked files, dropped files and whole folders."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import fitz

SKIPPED_DIR_NAMES = {".trash", ".git", ".obsidian", "__pycache__", "node_modules", "$RECYCLE.BIN", "System Volume Information"}


def is_pdf_file(path: Path) -> bool:
    return path.suffix.lower() == ".pdf" and path.is_file()


def pdfs_in_folder(folder: Path) -> list[Path]:
    """Every PDF under ``folder``, including subfolders, sorted by path. Hidden and system folders and
    folders that cannot be read are skipped."""
    found: list[Path] = []
    for root, dirs, files in os.walk(folder, onerror=lambda _error: None):
        dirs[:] = sorted(name for name in dirs if not name.startswith(".") and name not in SKIPPED_DIR_NAMES)
        found.extend(Path(root) / name for name in files if name.lower().endswith(".pdf"))
    return sorted(found, key=lambda path: str(path).casefold())


def expand_pdf_paths(paths: Iterable[str | Path]) -> list[Path]:
    """The PDFs among ``paths``: PDF files as they are, folders expanded to the PDFs inside them.
    Duplicates are dropped and the order is kept."""
    result: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        candidates = pdfs_in_folder(path) if path.is_dir() else [path] if is_pdf_file(path) else []
        for candidate in candidates:
            key = os.path.normcase(str(candidate.resolve(strict=False)))
            if key not in seen:
                seen.add(key)
                result.append(candidate)
    return result


def plan_pdf_import(paths: Iterable[str | Path]) -> list[tuple[Path, tuple[str, ...]]]:
    """Like ``expand_pdf_paths``, with the library folder path each PDF belongs in.

    A picked or dropped folder becomes a library folder of the same name, and its subfolders become
    library subfolders, so ``Books/Physics/a.pdf`` added as ``Books`` lands in *Books / Physics*. A PDF
    picked on its own has an empty folder path (it goes where it was dropped).
    """
    result: list[tuple[Path, tuple[str, ...]]] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            base = path.resolve(strict=False)
            planned = []
            for candidate in pdfs_in_folder(path):
                try:
                    relative_parent = candidate.resolve(strict=False).parent.relative_to(base)
                except ValueError:
                    relative_parent = Path()
                planned.append((candidate, (base.name or str(base), *relative_parent.parts)))
        elif is_pdf_file(path):
            planned = [(path, ())]
        else:
            planned = []
        for candidate, folder_parts in planned:
            key = os.path.normcase(str(candidate.resolve(strict=False)))
            if key not in seen:
                seen.add(key)
                result.append((candidate, folder_parts))
    return result


def pdf_page_count(path: Path) -> int:
    """The page count, or 0 when the file cannot be opened (it can still be added and opened later)."""
    try:
        document = fitz.open(path)
    except Exception:
        return 0
    try:
        return document.page_count
    except Exception:
        return 0
    finally:
        document.close()
