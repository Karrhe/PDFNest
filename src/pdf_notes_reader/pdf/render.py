"""Page rasterization with a bounded pixmap cache, a per-page pixel limit and error isolation.

Rasterizing is the expensive step of reading. The reader rebuilds its page widgets whenever the
visible page window moves; this cache makes sure a page is rasterized once per zoom level instead
of on every rebuild.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass

import fitz
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from pdf_notes_reader.pdf.render_worker import MAX_PAGE_PIXELS, RenderResult, page_render_scale

__all__ = ["MAX_PAGE_PIXELS", "PageRenderCache", "RenderedPage", "page_render_scale", "rasterize_page", "rendered_page_from_result"]

logger = logging.getLogger(__name__)

# Total device pixels kept in the cache (about 25 A4 pages at 125% zoom, 2x precision).
DEFAULT_CACHE_PIXELS = 80_000_000


@dataclass
class RenderedPage:
    pixmap: QPixmap
    display_size: QSize
    error: str = ""

    @property
    def device_pixels(self) -> int:
        return self.pixmap.width() * self.pixmap.height()


def rendered_page_from_result(result: RenderResult, page_width_pt: float, page_height_pt: float, zoom: float) -> RenderedPage:
    """Turns a worker's raw RGB samples into a pixmap (main thread only: QPixmap is GUI-bound)."""
    image = QImage(result.samples, result.width, result.height, result.stride, QImage.Format_RGB888)
    pixmap = QPixmap.fromImage(image)
    del image
    pixmap.setDevicePixelRatio(result.scale)
    display_size = QSize(max(1, round(page_width_pt * zoom)), max(1, round(page_height_pt * zoom)))
    return RenderedPage(pixmap=pixmap, display_size=display_size)


def _zoom_key(value: float) -> int:
    return round(value * 10000)


class PageRenderCache:
    def __init__(self, *, max_pixels: int = DEFAULT_CACHE_PIXELS) -> None:
        self.max_pixels = max_pixels
        self._entries: OrderedDict[tuple[int, int, int], RenderedPage] = OrderedDict()
        self._pixels = 0
        self._document: fitz.Document | None = None
        self.rasterizations = 0

    def clear(self) -> None:
        self._entries.clear()
        self._pixels = 0

    def bind(self, document: fitz.Document | None) -> None:
        """Drops cached pages when the reader switches to (or re-opens) a different document."""
        if document is not self._document:
            self._document = document
            self.clear()

    def has(self, document: fitz.Document | None, page_index: int, zoom: float, render_scale: float) -> bool:
        """True when ``render`` would return a cached page without rasterizing."""
        return document is self._document and (page_index, _zoom_key(zoom), _zoom_key(render_scale)) in self._entries

    def preview(self, document: fitz.Document | None, page_index: int) -> RenderedPage | None:
        """The most recent render of a page at any zoom, shown scaled while the exact one renders."""
        if document is not self._document:
            return None
        for (cached_page, _zoom, _scale), rendered in reversed(self._entries.items()):
            if cached_page == page_index:
                return rendered
        return None

    def store(self, document: fitz.Document, page_index: int, zoom: float, render_scale: float, rendered: RenderedPage) -> None:
        """Adds a page rasterized elsewhere (a render worker). Ignored for another document."""
        if document is not self._document or rendered.error:
            return
        key = (page_index, _zoom_key(zoom), _zoom_key(render_scale))
        old = self._entries.pop(key, None)
        if old is not None:
            self._pixels -= old.device_pixels
        self._entries[key] = rendered
        self._pixels += rendered.device_pixels
        self._evict()

    def render(self, document: fitz.Document, page_index: int, zoom: float, render_scale: float) -> RenderedPage:
        self.bind(document)
        key = (page_index, _zoom_key(zoom), _zoom_key(render_scale))
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            return cached
        rendered = rasterize_page(document, page_index, zoom, render_scale)
        self.rasterizations += 1
        if not rendered.error:
            self._entries[key] = rendered
            self._pixels += rendered.device_pixels
            self._evict()
        return rendered

    def _evict(self) -> None:
        while self._pixels > self.max_pixels and len(self._entries) > 1:
            _key, old = self._entries.popitem(last=False)
            self._pixels -= old.device_pixels

    def __len__(self) -> int:
        return len(self._entries)


def rasterize_page(document: fitz.Document, page_index: int, zoom: float, render_scale: float) -> RenderedPage:
    """Renders one page. A broken page yields an error placeholder instead of raising."""
    try:
        page = document.load_page(page_index)
        rect = page.rect
        scale = page_render_scale(rect.width, rect.height, zoom, render_scale)
        render_zoom = zoom * scale
        pix = page.get_pixmap(matrix=fitz.Matrix(render_zoom, render_zoom), alpha=False, colorspace=fitz.csRGB)
        # The QImage wraps MuPDF's buffer without copying; fromImage makes the one copy we keep,
        # while ``pix`` is still alive.
        image = QImage(pix.samples_mv, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(image)
        del image, pix
        pixmap.setDevicePixelRatio(scale)
        display_size = QSize(max(1, round(rect.width * zoom)), max(1, round(rect.height * zoom)))
        return RenderedPage(pixmap=pixmap, display_size=display_size)
    except Exception as exc:  # MuPDF raises many error types for damaged content.
        logger.warning("Could not render page %s: %s", page_index + 1, exc)
        return error_page(document, page_index, zoom, str(exc) or type(exc).__name__)


def error_page(document: fitz.Document, page_index: int, zoom: float, message: str) -> RenderedPage:
    try:
        rect = document.load_page(page_index).rect
        width, height = rect.width, rect.height
    except Exception:
        width, height = 595.0, 842.0
    size = QSize(max(1, round(width * zoom)), max(1, round(height * zoom)))
    pixmap = QPixmap(size)
    pixmap.fill(QColor("#f3f0e8"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#8a5a00"))
    painter.drawText(pixmap.rect().adjusted(16, 16, -16, -16), Qt.AlignCenter | Qt.TextWordWrap, f"Page {page_index + 1} could not be displayed.\n\n{message}")
    painter.end()
    return RenderedPage(pixmap=pixmap, display_size=size, error=message)
