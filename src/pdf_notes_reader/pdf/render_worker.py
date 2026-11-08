"""Page rasterization in worker processes, so slow pages never block the reader's UI thread.

PyMuPDF keeps Python's global interpreter lock while it rasterizes, so a background *thread* still
freezes the UI for the whole render (0.4-0.6 s per page on scanned books). Worker *processes* do
not. This module is imported by the workers: it must stay free of Qt and of the UI modules.

The main process submits jobs and polls the returned futures from a Qt timer; it never waits.
"""

from __future__ import annotations

import logging
import math
import os
import time
from collections import OrderedDict
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass

import fitz

from pdf_notes_reader.pdf.text import page_words

logger = logging.getLogger(__name__)

# One page never exceeds this many device pixels (about 64 MB as a 32-bit pixmap).
MAX_PAGE_PIXELS = 16_000_000
# Set PDFNEST_RENDER_WORKERS=0 to rasterize on the UI thread only.
WORKERS_ENV = "PDFNEST_RENDER_WORKERS"
DEFAULT_WORKERS = 2


def page_render_scale(width_pt: float, height_pt: float, zoom: float, render_scale: float, *, max_pixels: int = MAX_PAGE_PIXELS) -> float:
    """The render scale to use, lowered for huge pages so they stay under ``max_pixels``."""
    pixels = width_pt * zoom * render_scale * height_pt * zoom * render_scale
    if pixels <= max_pixels or pixels <= 0:
        return render_scale
    return max(0.05, render_scale * math.sqrt(max_pixels / pixels))


@dataclass(frozen=True)
class RenderJob:
    path: str
    password: str | None
    page_index: int
    zoom: float
    render_scale: float


@dataclass(frozen=True)
class RenderResult:
    page_index: int
    width: int
    height: int
    stride: int
    samples: bytes
    scale: float
    words: list[dict[str, object]] | None
    error: str = ""
    seconds: float = 0.0  # time the worker spent rasterizing


# --- worker side ---------------------------------------------------------------------------------

_open_documents: OrderedDict[tuple[str, int, int], fitz.Document] = OrderedDict()


def _worker_document(path: str, password: str | None) -> fitz.Document:
    """Documents stay open between jobs. The key includes size and mtime, so a rewritten file
    (contents saved, backup restored) is opened afresh instead of served from a stale handle."""
    stat = os.stat(path)
    key = (path, stat.st_size, stat.st_mtime_ns)
    document = _open_documents.get(key)
    if document is not None:
        _open_documents.move_to_end(key)
        return document
    # Opened from memory: a file handle held by a worker would stop the reader from replacing the
    # PDF on Windows (saving contents, restoring the backup).
    with open(path, "rb") as handle:
        data = handle.read()
    document = fitz.open(stream=data, filetype="pdf")
    if document.needs_pass and not document.authenticate(password or ""):
        document.close()
        raise RuntimeError("The PDF could not be unlocked in the render worker.")
    _open_documents[key] = document
    while len(_open_documents) > 4:
        _key, old = _open_documents.popitem(last=False)
        old.close()
    return document


def render_in_worker(job: RenderJob) -> RenderResult:
    started = time.perf_counter()
    try:
        page = _worker_document(job.path, job.password).load_page(job.page_index)
        rect = page.rect
        scale = page_render_scale(rect.width, rect.height, job.zoom, job.render_scale)
        render_zoom = job.zoom * scale
        pix = page.get_pixmap(matrix=fitz.Matrix(render_zoom, render_zoom), alpha=False, colorspace=fitz.csRGB)
        try:
            words = page_words(page)
        except Exception:
            words = None  # the reader extracts them itself if needed
        return RenderResult(job.page_index, pix.width, pix.height, pix.stride, bytes(pix.samples_mv), scale, words, seconds=time.perf_counter() - started)
    except Exception as exc:  # The reader falls back to rendering this page itself.
        return RenderResult(job.page_index, 0, 0, 0, b"", 0.0, None, str(exc) or type(exc).__name__)


# --- main-process side ---------------------------------------------------------------------------


def configured_worker_count() -> int:
    raw = os.environ.get(WORKERS_ENV, "").strip()
    if not raw:
        return DEFAULT_WORKERS
    try:
        return max(0, min(8, int(raw)))
    except ValueError:
        return DEFAULT_WORKERS


class RenderWorkerPool:
    """A lazily started process pool. Any failure disables it, and the reader renders in-process."""

    def __init__(self, workers: int | None = None) -> None:
        self.workers = configured_worker_count() if workers is None else workers
        self._executor: ProcessPoolExecutor | None = None
        self.failed = False

    @property
    def available(self) -> bool:
        return self.workers > 0 and not self.failed

    def submit(self, job: RenderJob) -> Future | None:
        if not self.available:
            return None
        try:
            if self._executor is None:
                self._executor = ProcessPoolExecutor(max_workers=self.workers)
            return self._executor.submit(render_in_worker, job)
        except Exception as exc:
            self._disable(exc)
            return None

    def mark_failed(self, exc: BaseException) -> None:
        self._disable(exc)

    def _disable(self, exc: BaseException) -> None:
        logger.warning("Render workers disabled, rendering in-process: %s", exc)
        self.failed = True
        self.shutdown()

    def shutdown(self) -> None:
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
