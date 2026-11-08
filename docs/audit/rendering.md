# Rendering, caching and PDF loading audit

Scope: items #3 (render and cache logic) and #7 (loading problems that depend on the kind of PDF).
Code: `pdf/render.py`, `pdf/document.py`, `pdf/text.py`, `ui/main_window.py` (render pipeline), `ui/canvas.py`.

## Pipeline

```
load_pdf ─ open_pdf (password, repair warning) ─ page_base_sizes (all pages, tolerant)
render_page
  ├─ _clear_page_widgets                    every refresh rebuilds the page widgets (cheap)
  ├─ _recalculate_page_metrics              geometry for the whole document → full-length scrollbar
  ├─ _populate_continuous_pages             current page ± render_page_buffer, plus visible pages;
  │                                          the gaps become merged spacer widgets
  └─ _add_rendered_page
        ├─ _render_page_pixmap → PageRenderCache.render → rasterize_page   (expensive)
        └─ _page_text_words → page_words (cached per page)
scroll → _sync_current_page_from_scroll → _schedule_page_window_render (35 ms) → render_page
```

The beige tint, note markers, highlights and selection are painted by `PdfCanvas.paintEvent` on top of
the pixmap. They never change the pixmap, so cached pixmaps can be shared safely.

## Findings

| # | Finding | Impact | Status |
|---|---------|--------|--------|
| R1 | Every page-window refresh re-rasterized **every** page in the window, including pages already rendered at the same zoom. | Measured 65 rasterizations while scrolling about 10 pages (6.6 per page) in a 2,000-page PDF. Wasted CPU and scroll stutter. Breaks the "never rasterize the same page and zoom twice" rule in `.agents/memory.md`. | **Fixed**: `PageRenderCache`, an LRU keyed by (page, zoom, render scale) with an 80 MP budget. Now 8 rasterizations (0.8 per page) and scrolling is 33% faster. |
| R2 | No pixel limit. A large page at 2× precision (posters, maps, A0 scans up to 14,400 pt) needs gigapixel buffers. | Out-of-memory or very long freezes. | **Fixed**: `page_render_scale` lowers the precision for pages over 16 MP. |
| R3 | One page that failed to render raised out of `render_page`, so the whole visible window broke. | Damaged PDFs became unreadable from that page on. | **Fixed**: `rasterize_page` returns an error placeholder ("Page N could not be displayed") and logs the error. Failures are not cached, so a later retry can still succeed. |
| R4 | Text boxes for selection and highlights came from MuPDF's *unrotated* page space but were drawn on the rotated page. | On `/Rotate` 90/180/270 pages, selection, copy and highlights landed in the wrong place. | **Fixed**: `pdf/text.page_words` maps through `page.rotation_matrix`. Highlights created on rotated pages *before* this fix keep their old (wrong) positions. |
| R5 | Encrypted PDFs: no password prompt. Worse, `_ensure_cover` re-opened the file without the password and its `load_page` error was uncaught, so opening any password-protected PDF crashed while saving history. | Password-protected PDFs could not be used. | **Fixed**: password prompt (3 attempts), the password is kept per tab for reopening after a contents save, and the cover is skipped for locked files. |
| R6 | Damaged files that MuPDF repairs on open gave no hint. | Users didn't know why pages or contents were missing. | **Fixed**: status-bar warning. |
| R7 | Empty files, non-PDF files and zero-page documents gave raw MuPDF errors (or opened as XPS/EPUB/images). | Confusing errors. | **Fixed**: clear messages; `fitz.open(..., filetype="pdf")`. |
| R8 | Reading page sizes at open called `load_page` for every page; one broken page aborted the open. | About 200 ms for 3,000 pages (acceptable), but fatal on a bad page. | **Fixed (robustness)**: `page_base_sizes` borrows a neighbor's size. Speed unchanged; `page_cropbox` was only 2× faster and ignores `/Rotate`. |
| R9 | `_chapter_for_document` called `document.get_toc()` on every call. It runs once per note when numbering or rebuilding counters. | O(notes × outline entries) work on PDFs with large outlines. | **Fixed**: `services.chapters.ChapterLookup`, a cached O(log n) index that matches the original scan exactly (randomized equivalence test). |
| R10 | `render_page` still rebuilds the page *widgets* on every window move. | Cheap now that pixmaps are cached; widget churn remains. | Open: keeping widgets would mean reworking the spacer layout, which the Fit/scroll regression rules make risky. |
| R11 | Rendering runs on the UI thread. | Very complex pages (vector maps) can still pause the UI for one page. | Open: needs a worker-thread renderer. |

## Measurements

`scripts/bench_render.py --pages 2000` (offscreen, 1200×900 window, A4 pages):

| | before | after |
|---|---:|---:|
| `load_pdf` time | 337 ms | 333 ms |
| rasterizations at open | 6 | 6 |
| rasterizations while scrolling ~10 pages | 65 | 8 |
| scroll wall time (30 steps) | 2,270 ms | 1,513 ms |

## PDF types covered by tests (`tests/test_pdf_loading.py`, `tests/pdf_factory.py`)

Password-protected (correct, wrong ×3, cancelled), owner-only encrypted, damaged xref (repaired), object
streams/xref streams, rotated pages and CropBox ≠ MediaBox, image-only (scanned) pages, CJK text, 6,000 pt
poster, a page that fails to render, empty file, non-PDF file, and zero pages.
