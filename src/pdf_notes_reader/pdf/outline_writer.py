"""Writes an edited table of contents back into a PDF without risking the original file.

The old path called ``set_toc`` + ``saveIncr`` on the open original. That appends an incremental
update in place, and corrupts files that readers otherwise tolerate, e.g. PDFs with bytes before
the ``%PDF-`` header: the appended xref offsets no longer match, strict readers reject the file,
and MuPDF itself must repair it on the next open (after which incremental saves fail).

This module instead does a full rewrite to a temp file next to the original, re-opens and checks
that copy with a fresh MuPDF instance, keeps a pristine backup of the original, and only then
atomically swaps the new file in.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import fitz

BACKUP_SUFFIX = ".pdfnest.bak"
MAX_TITLE_LENGTH = 512
_RENDER_CHECK_PAGES = 4


class TocValidationError(ValueError):
    pass


class TocSaveRefused(RuntimeError):
    """The PDF must not be rewritten (signed, locked, modification not permitted, ...)."""


@dataclass
class TocSaveResult:
    path: Path
    backup_path: Path | None
    backup_created: bool
    warnings: list[str]


def backup_path_for(pdf_path: Path) -> Path:
    return pdf_path.with_name(pdf_path.name + BACKUP_SUFFIX)


def normalize_toc(toc: list[list], page_count: int) -> list[list]:
    """Returns a clean ``[level, title, page]`` list or raises TocValidationError."""
    cleaned: list[list] = []
    previous_level = 0
    for index, raw in enumerate(toc):
        if len(raw) < 3:
            raise TocValidationError(f"Contents item {index + 1} is incomplete.")
        try:
            level = int(raw[0])
            page = int(raw[2])
        except (TypeError, ValueError) as exc:
            raise TocValidationError(f"Contents item {index + 1} has an invalid level or page.") from exc
        title = re.sub(r"\s+", " ", str(raw[1])).strip()[:MAX_TITLE_LENGTH]
        if not title:
            raise TocValidationError(f"Contents item {index + 1} has no title.")
        if level < 1 or (index == 0 and level != 1):
            raise TocValidationError("Contents must start at level 1.")
        if level > previous_level + 1:
            raise TocValidationError(f'"{title}" is nested more than one level below the item before it.')
        if not 1 <= page <= page_count:
            raise TocValidationError(f'"{title}" points to page {page}, but the PDF has {page_count} pages.')
        cleaned.append([level, title, page])
        previous_level = level
    return cleaned


def refusal_reason(document: fitz.Document) -> str | None:
    """Why this document must not be rewritten, or None when it is safe to try."""
    if not document.is_pdf:
        return "Only PDF files can store contents."
    if document.is_encrypted:
        return "The PDF is locked. Unlock it with its password first."
    encrypted = bool((document.metadata or {}).get("encryption"))
    if encrypted and not (document.permissions & fitz.PDF_PERM_MODIFY):
        return "The PDF's security settings do not allow modifying it."
    if document.get_sigflags() > 0:
        return "The PDF is digitally signed. Rewriting it would invalidate the signature."
    catalog = document.pdf_catalog()
    if catalog > 0 and document.xref_get_key(catalog, "AcroForm/XFA")[0] != "null":
        return "The PDF contains an XFA form, which PDFNest cannot rewrite safely."
    return None


def save_toc_safely(document: fitz.Document, toc: list[list], *, password: str | None = None) -> TocSaveResult:
    """Rewrites ``document``'s file with ``toc``.

    The document is always closed when this returns or raises after the refusal checks, because
    Windows cannot replace a file that MuPDF still holds open. Callers must re-open the path.
    """
    if not document.name:
        raise TocSaveRefused("The PDF was not opened from a file.")
    path = Path(document.name)
    clean_toc = normalize_toc(toc, document.page_count)
    reason = refusal_reason(document)
    if reason:
        raise TocSaveRefused(reason)

    warnings: list[str] = []
    if document.is_repaired:
        warnings.append("The original file was damaged; PDFNest saved a repaired copy.")
    if not path.read_bytes()[:5] == b"%PDF-":
        warnings.append("The original file had extra bytes before its PDF header; they were removed.")

    page_count = document.page_count
    tmp_path = path.with_name(f".{path.stem}.pdfnest-{uuid.uuid4().hex[:8]}.tmp.pdf")
    try:
        document.set_toc(clean_toc)
        document.save(tmp_path, garbage=1, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    except Exception:
        document.close()
        tmp_path.unlink(missing_ok=True)
        raise
    document.close()

    try:
        verify_saved_pdf(tmp_path, page_count=page_count, toc=clean_toc, password=password)
        backup = backup_path_for(path)
        backup_created = not backup.exists()
        if backup_created:  # Keep the pristine original; later saves never overwrite it.
            shutil.copy2(path, backup)
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return TocSaveResult(path=path, backup_path=backup, backup_created=backup_created, warnings=warnings)


def verify_saved_pdf(path: Path, *, page_count: int, toc: list[list], password: str | None = None) -> None:
    """Raises RuntimeError unless a fresh MuPDF instance reads ``path`` cleanly with ``toc``."""
    data_head = path.read_bytes()[:5]
    if data_head != b"%PDF-":
        raise RuntimeError("The saved file does not start with a PDF header.")
    fitz.TOOLS.mupdf_warnings()  # discard earlier warnings
    check = fitz.open(path)
    try:
        if check.needs_pass and not check.authenticate(password or ""):
            raise RuntimeError("The saved file could not be unlocked with the original password.")
        if check.is_repaired:
            raise RuntimeError("The saved file needed repair when re-opened.")
        if check.page_count != page_count:
            raise RuntimeError(f"The saved file has {check.page_count} pages instead of {page_count}.")
        saved_toc = [[level, title, page] for level, title, page, *_rest in check.get_toc()]
        if saved_toc != toc:
            raise RuntimeError("The saved contents do not match what was written.")
        for index in range(page_count):
            check.load_page(index)
        for index in sorted({0, page_count - 1, *range(0, page_count, max(1, page_count // _RENDER_CHECK_PAGES))}):
            check.load_page(index).get_pixmap(matrix=fitz.Matrix(0.1, 0.1), alpha=False)
    finally:
        check.close()


def restore_backup(pdf_path: Path) -> Path:
    """Puts the pristine original back. The backup is kept so it can be restored again."""
    backup = backup_path_for(pdf_path)
    if not backup.exists():
        raise FileNotFoundError(backup)
    tmp_path = pdf_path.with_name(f".{pdf_path.stem}.pdfnest-restore-{uuid.uuid4().hex[:8]}.tmp.pdf")
    shutil.copy2(backup, tmp_path)
    os.replace(tmp_path, pdf_path)
    return backup
