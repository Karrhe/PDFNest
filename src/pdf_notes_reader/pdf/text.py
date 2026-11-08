"""Page text geometry in the reader's normalized coordinates (0..1 of the displayed page)."""

from __future__ import annotations

import fitz


def page_words(page: fitz.Page) -> list[dict[str, object]]:
    """Words with rects normalized to the *displayed* page.

    MuPDF reports text in unrotated page space. Pages with /Rotate are displayed rotated, so each
    rect is mapped through ``page.rotation_matrix`` first; otherwise selections and highlights on
    rotated pages land in the wrong place.
    """
    rect = page.rect
    if rect.width == 0 or rect.height == 0:
        return []
    rotation_matrix = page.rotation_matrix if page.rotation else None

    words: list[dict[str, object]] = []
    for raw in page.get_text("words"):
        if len(raw) < 8:
            continue
        x0, y0, x1, y1, text, block_no, line_no, word_no = raw[:8]
        word_rect = fitz.Rect(x0, y0, x1, y1)
        if rotation_matrix is not None:
            word_rect = word_rect * rotation_matrix
            word_rect.normalize()
        words.append(
            {
                "rect": [
                    max(0.0, min(1.0, float(word_rect.x0) / rect.width)),
                    max(0.0, min(1.0, float(word_rect.y0) / rect.height)),
                    max(0.0, min(1.0, float(word_rect.x1) / rect.width)),
                    max(0.0, min(1.0, float(word_rect.y1) / rect.height)),
                ],
                "text": str(text),
                "block": int(block_no),
                "line": int(line_no),
                "word_no": int(word_no),
            }
        )
    return words
