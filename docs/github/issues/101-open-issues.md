---
title: "Open issues after 0.3.0 (tracking)"
labels: [tracking]
status: open
register: O-01 … O-08
---

Each item can become its own GitHub issue. Details in `docs/KNOWN_ISSUES.md`.

- [ ] **O-01 Highlights from before 0.3.0 on rotated pages are misplaced.** They were stored in unrotated
  coordinates. The rotation at creation time wasn't recorded, so an automatic fix needs a heuristic (e.g. the
  note's `selected_text` re-located on the page). Workaround: re-create them.
- [ ] **O-02 Moved/renamed PDFs opened via Open… start an empty notebook.** `pdf_key` is path-based. Proposal:
  store a content fingerprint (page count + hash of the first pages' content streams) in `manifest.json`, and
  offer to re-link when a fingerprint matches an orphaned notebook. Workaround: Home → *Relocate*.
- [ ] **O-03 Rendering and search run on the UI thread** (sliced). Proposal: a worker thread with its own
  `fitz.Document`, posting `QImage`s back to the UI thread.
- [ ] **O-04 Page widgets are rebuilt when the visible window moves.** Pixmaps are cached, so this is cheap,
  but widget reuse would remove the churn. Must respect the Fit/scroll rules in `.agents/memory.md`.
- [ ] **O-05 Scanned PDFs can't be searched or selected.** OCR via PyMuPDF `get_textpage_ocr` needs Tesseract,
  which isn't bundled.
- [ ] **O-06 Search across hyphenated line breaks.**
- [ ] **O-07 Bare URL auto-linking; relative image paths in notes.**
- [ ] **O-08 Inline fractions are `a⁄b`.** Qt rich text has no inline-block. Rendering math to images (e.g.
  matplotlib mathtext) would allow stacked inline fractions at the cost of a dependency.
