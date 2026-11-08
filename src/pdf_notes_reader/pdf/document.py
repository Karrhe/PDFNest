"""Opening PDFs robustly: passwords, damaged files, unsupported files and broken pages."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)

MAX_PASSWORD_ATTEMPTS = 3
DEFAULT_PAGE_SIZE = (595.0, 842.0)  # A4 in points, used when a page's size cannot be read

# Called with (path, attempt, previous_attempt_failed); returns a password or None to cancel.
PasswordProvider = Callable[[Path, int, bool], "str | None"]


class PdfOpenError(Exception):
    """A PDF could not be opened. ``str(exc)`` is a message meant for the user."""


@dataclass
class OpenedPdf:
    document: fitz.Document
    password: str | None = None
    warnings: list[str] = field(default_factory=list)


def open_pdf(path: Path, *, password_provider: PasswordProvider | None = None) -> OpenedPdf:
    path = Path(path)
    if not path.exists():
        raise PdfOpenError(f"The file does not exist:\n{path}")
    if path.stat().st_size == 0:
        raise PdfOpenError("The file is empty (0 bytes).")

    fitz.TOOLS.mupdf_warnings()  # discard warnings from earlier operations
    try:
        document = fitz.open(path, filetype="pdf")
    except Exception as exc:  # MuPDF raises several exception types.
        raise PdfOpenError(f"This file could not be read as a PDF.\n\n{exc}") from exc

    try:
        password = _unlock(document, path, password_provider)
        if document.page_count <= 0:
            raise PdfOpenError("The PDF has no pages.")
        warnings: list[str] = []
        if document.is_repaired:
            warnings.append("The PDF was damaged and has been repaired for reading. Some content may be missing.")
        mupdf_warnings = fitz.TOOLS.mupdf_warnings().strip()
        if mupdf_warnings:
            logger.info("MuPDF warnings for %s: %s", path, mupdf_warnings)
        return OpenedPdf(document=document, password=password, warnings=warnings)
    except Exception:
        document.close()
        raise


def reopen_pdf(path: Path, password: str | None) -> fitz.Document:
    """Re-opens a file the reader already unlocked once (e.g. after it was rewritten)."""
    document = fitz.open(path, filetype="pdf")
    if document.needs_pass and not document.authenticate(password or ""):
        document.close()
        raise PdfOpenError("The PDF could not be unlocked again.")
    return document


def _unlock(document: fitz.Document, path: Path, password_provider: PasswordProvider | None) -> str | None:
    if not document.needs_pass:
        return None
    if password_provider is None:
        raise PdfOpenError("The PDF is password protected.")
    failed = False
    for attempt in range(1, MAX_PASSWORD_ATTEMPTS + 1):
        password = password_provider(path, attempt, failed)
        if password is None:
            raise PdfOpenError("Opening was cancelled: the PDF is password protected.")
        if document.authenticate(password):
            return password
        failed = True
    raise PdfOpenError("The password is not correct.")


def page_base_sizes(document: fitz.Document) -> list[tuple[float, float]]:
    """Displayed page sizes in points; unreadable pages borrow a neighbor's size."""
    sizes: list[tuple[float, float]] = []
    for page_index in range(document.page_count):
        try:
            rect = document.load_page(page_index).rect
            size = (float(rect.width), float(rect.height))
            if size[0] <= 0 or size[1] <= 0:
                raise ValueError("empty page box")
        except Exception as exc:
            logger.warning("Page %s has no readable size: %s", page_index + 1, exc)
            size = sizes[-1] if sizes else DEFAULT_PAGE_SIZE
        sizes.append(size)
    return sizes
