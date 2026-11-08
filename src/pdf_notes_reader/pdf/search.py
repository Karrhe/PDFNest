"""Full-text search inside a PDF, run in small steps so the UI never freezes.

Hits use the reader's normalized coordinates (0..1 of the *displayed* page), like note anchors.
MuPDF's ``search_for`` is case-insensitive and reports unrotated page coordinates; case-sensitive
and whole-word matching are applied afterwards by reading the text under and around each hit.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import fitz

MAX_HITS_PER_PAGE = 500


@dataclass(frozen=True)
class SearchOptions:
    case_sensitive: bool = False
    whole_word: bool = False


@dataclass(frozen=True)
class SearchHit:
    page_index: int
    rect: tuple[float, float, float, float]  # x0, y0, x1, y1 normalized to the displayed page


def _normalized(rect: fitz.Rect, page: fitz.Page) -> tuple[float, float, float, float]:
    if page.rotation:
        rect = rect * page.rotation_matrix
        rect.normalize()
    width, height = page.rect.width or 1, page.rect.height or 1
    clamp = lambda value: max(0.0, min(1.0, value))  # noqa: E731
    return (clamp(rect.x0 / width), clamp(rect.y0 / height), clamp(rect.x1 / width), clamp(rect.y1 / height))


def _page_lines(page: fitz.Page) -> list[list[tuple[str, fitz.Rect]]]:
    """Characters with their boxes, per text line (unrotated coordinates, like search_for)."""
    lines: list[list[tuple[str, fitz.Rect]]] = []
    for block in page.get_text("rawdict").get("blocks", []):
        for line in block.get("lines", []):
            chars = [(char["c"], fitz.Rect(char["bbox"])) for span in line.get("spans", []) for char in span.get("chars", [])]
            if chars:
                lines.append(chars)
    return lines


def _accept(lines: list[list[tuple[str, fitz.Rect]]], rect: fitz.Rect, query: str, options: SearchOptions) -> bool:
    """Checks the exact characters under a hit (case) and the characters just outside it (word bounds)."""
    if not options.case_sensitive and not options.whole_word:
        return True
    for chars in lines:
        inside = [index for index, (_char, box) in enumerate(chars) if rect.contains(fitz.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2))]
        if not inside:
            continue
        first, last = inside[0], inside[-1]
        matched = re.sub(r"\s+", " ", "".join(chars[index][0] for index in range(first, last + 1))).strip()
        if options.case_sensitive and matched != query:
            return False
        if options.whole_word:
            before = chars[first - 1][0] if first > 0 else " "
            after = chars[last + 1][0] if last + 1 < len(chars) else " "
            if re.match(r"\w", before) or re.match(r"\w", after):
                return False
        return True
    return False


def search_page(page: fitz.Page, query: str, options: SearchOptions = SearchOptions()) -> list[SearchHit]:
    query = re.sub(r"\s+", " ", query).strip()
    if not query:
        return []
    try:
        rects = page.search_for(query)[:MAX_HITS_PER_PAGE]
    except (RuntimeError, ValueError):  # A damaged page has no searchable text.
        return []
    lines = _page_lines(page) if rects and (options.case_sensitive or options.whole_word) else []
    hits = [SearchHit(page.number, _normalized(rect, page)) for rect in rects if _accept(lines, rect, query, options)]
    hits.sort(key=lambda hit: (round(hit.rect[1], 3), hit.rect[0]))
    return hits


@dataclass
class DocumentSearch:
    """Searches all pages starting at ``start_page`` (wrapping around) via repeated ``step`` calls."""

    document: fitz.Document
    query: str
    options: SearchOptions = SearchOptions()
    start_page: int = 0
    hits_by_page: dict[int, list[SearchHit]] = field(default_factory=dict)
    pages_searched: int = 0
    cancelled: bool = False

    def __post_init__(self) -> None:
        count = self.document.page_count
        start = max(0, min(self.start_page, count - 1)) if count else 0
        self._order = [(start + offset) % count for offset in range(count)] if count else []

    @property
    def done(self) -> bool:
        return self.cancelled or self.pages_searched >= len(self._order)

    @property
    def page_count(self) -> int:
        return len(self._order)

    def cancel(self) -> None:
        self.cancelled = True

    def step(self, *, max_pages: int = 12, max_seconds: float = 0.03) -> list[SearchHit]:
        """Searches up to ``max_pages`` pages (or until the time budget runs out); returns new hits."""
        new_hits: list[SearchHit] = []
        deadline = time.perf_counter() + max_seconds
        searched_now = 0
        while not self.done and searched_now < max_pages:
            page_index = self._order[self.pages_searched]
            self.pages_searched += 1
            searched_now += 1
            try:
                page = self.document.load_page(page_index)
            except Exception:
                continue
            hits = search_page(page, self.query, self.options)
            if hits:
                self.hits_by_page[page_index] = hits
                new_hits.extend(hits)
            if time.perf_counter() >= deadline:
                break
        return new_hits

    def run_to_end(self) -> list[SearchHit]:
        while not self.done:
            self.step(max_pages=50, max_seconds=10.0)
        return self.hits

    @property
    def hits(self) -> list[SearchHit]:
        """All hits found so far, in document order."""
        return [hit for page_index in sorted(self.hits_by_page) for hit in self.hits_by_page[page_index]]
