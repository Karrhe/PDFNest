"""Maps pages to the PDF outline chapter that contains them; drives note titles and numbering."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

import fitz


def single_line_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


@dataclass
class ChapterIndex:
    """O(log n) page -> chapter lookup with the semantics of a linear outline scan.

    The chapter for a page is the last titled outline entry before the first entry that starts
    after that page. Outlines are not always in page order, so ``prefix_max`` (non-decreasing)
    finds that first entry by bisection, and ``last_titled`` gives the answer for each cut-off.
    """

    starts: list[int] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    prefix_max: list[int] = field(default_factory=list)
    last_titled: list[int] = field(default_factory=lambda: [-1])

    @classmethod
    def from_toc(cls, toc: list[list]) -> "ChapterIndex":
        index = cls()
        highest = -1
        for raw in toc:
            if len(raw) < 3:
                continue
            start = max(0, int(raw[2]) - 1)
            title = single_line_title(str(raw[1]))
            index.starts.append(start)
            index.titles.append(title)
            highest = max(highest, start)
            index.prefix_max.append(highest)
            index.last_titled.append(len(index.starts) - 1 if title else index.last_titled[-1])
        return index

    def chapter_for_page(self, page_index: int) -> tuple[str, int] | None:
        cutoff = bisect.bisect_right(self.prefix_max, page_index)
        position = self.last_titled[cutoff]
        if position < 0:
            return None
        return self.titles[position], self.starts[position]


class ChapterLookup:
    """Caches the ChapterIndex per open document; a replaced or re-opened document rebuilds it."""

    def __init__(self) -> None:
        self._document: fitz.Document | None = None
        self._index = ChapterIndex()

    def index_for(self, document: fitz.Document | None) -> ChapterIndex:
        if document is None:
            return ChapterIndex()
        if document is not self._document:
            self._document = document
            self._index = ChapterIndex.from_toc(document.get_toc())
        return self._index

    def invalidate(self) -> None:
        self._document = None

    def chapter_for_page(self, document: fitz.Document | None, page_index: int) -> tuple[str, int] | None:
        return self.index_for(document).chapter_for_page(page_index)


def location_label(chapter: tuple[str, int] | None, page_index: int) -> str:
    return chapter[0] if chapter is not None else f"page-{page_index + 1}"


def counter_key(chapter: tuple[str, int] | None, page_index: int) -> str:
    if chapter is None:
        return f"page:{max(0, int(page_index))}"
    title, start_page_index = chapter
    return f"toc:{start_page_index}:{title}"
