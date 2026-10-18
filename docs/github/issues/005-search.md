---
title: "Add search: find text in the PDF and search notes"
labels: [enhancement, search]
status: implemented in 0.3.0
register: I-23, I-24
---

## Problem
There was no way to search the text of the open PDF. Notes couldn't be searched either: Home only matched
notebook titles and paths, and the note selector only lists first lines.

## Implemented
- **Find in PDF** (`Ctrl+F`):
  - Next/previous with Enter / `F3` and Shift+Enter / `Shift+F3`; *Match case*; *Whole words*.
  - Starts at the current page and wraps around; status "k of N".
  - Orange overlay highlights that never re-render the page.
  - Incremental (≤ 12 pages / 30 ms per UI slice), cancelled on a new query or document switch.
  - Correct on rotated pages; works for CJK.
- **Note filter** above the note selector (all terms, Markdown and captured PDF text).
- **Home search by note content**, with "· n matching notes". `NotebookSearchIndex` caches each notebook
  and re-reads it only when `notes.json` changes.

Design and limits: `docs/audit/search.md`.

## Tests
`tests/test_search.py` (15 tests).

## Follow-ups (not in 0.3.0)
- OCR for scanned PDFs.
- Matching across hyphenated line breaks.
- Cross-PDF full-text index (SQLite FTS5).
- Regex search.
- Background-thread search.
