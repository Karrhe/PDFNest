---
title: "Some kinds of PDFs fail to open or display incorrectly (encrypted, rotated, damaged, huge pages)"
labels: [bug, rendering, compatibility]
status: fixed in 0.3.0
register: I-11, I-12, I-13, I-14, I-15, I-16
---

## Summary
Loading and display depended on the kind of PDF:

| PDF kind | 0.2.5 behavior |
|---|---|
| Password protected | No prompt; **opening crashed** while saving history (the cover thumbnail re-opened the file without the password). |
| Rotated pages (`/Rotate` 90/180/270) | Text selection, highlights and underlines drawn **in the wrong place**. |
| A page MuPDF cannot render | The whole visible page window failed. |
| A page with no readable size | Opening the document failed. |
| Poster/map pages (large page boxes) | 2× render could need gigapixel buffers (memory exhaustion). |
| Empty / non-PDF file | Raw MuPDF error text; non-PDF formats (XPS/EPUB/images) were opened as documents. |
| Damaged (repaired on open) | Opened silently; users didn't know content might be missing. |

Also, scrolling re-rendered every page in the window on each step: 65 page renders while scrolling past
about 10 pages of a 2,000-page PDF.

## Fix
- `pdf/document.open_pdf`: password prompt (3 attempts, kept per tab), clear messages, repaired-file warning,
  tolerant page sizes.
- `pdf/text.page_words`: word boxes mapped through `page.rotation_matrix`.
- `pdf/render.PageRenderCache`: LRU pixmap cache (80 MP), 16 MP per-page limit, error placeholder per page.
- `_ensure_cover` skips locked PDFs and can never fail a save.

Result: 8 renders instead of 65 for the same scroll; scrolling 33% faster. See `docs/audit/rendering.md`.

## Tests
`tests/test_pdf_loading.py` (22 tests) with generated encrypted, repaired, object-stream, rotated/cropped,
scanned, CJK, poster, empty and non-PDF files; `tests/test_pdf_factory.py` checks that each fixture really has its defect.

## Known remaining issue
Highlights created on rotated pages **before** 0.3.0 keep their old positions (see #O-01).
