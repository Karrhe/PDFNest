# Search system evaluation

Scope: item #5. Code: `pdf/search.py`, `services/note_search.py`, `ui/find_bar.py`, `ui/main_window.py`
(find-bar wiring), `ui/note_panel.py` (note filter), `ui/history_panel.py` (Home search).

## Before (0.2.5)

| Search need | Available? | Notes |
|---|---|---|
| Find text inside the open PDF | **No** | No Ctrl+F at all. Users had to scroll or rely on the outline. |
| Find a note in the open PDF | **No** | The note selector only lists first lines, in page order. |
| Find a notebook on Home | Partly | `HistoryPanel.search_edit` matched the notebook **title and file path** only. |
| Find which notebook contains a note about X | **No** | Note content was never searched. |

## After

| Search need | How | Behavior |
|---|---|---|
| Find in PDF | **Ctrl+F** opens the find bar above the reader. Enter / **F3** goes to the next match, Shift+Enter / **Shift+F3** to the previous, Esc closes. | Starts at the current page and wraps around. Jumps to the first match as soon as it's found. Shows "Searching… n/N pages", then "k of N" or "No matches". Selected PDF text pre-fills the query. |
| Options | *Match case*, *Whole words* | Checked against the exact characters under each hit (MuPDF `rawdict` character boxes) and the characters just outside it, so neighboring words never cause false matches. |
| Highlighting | Orange overlay; the current match is darker with an outline | Drawn by `PdfCanvas` as an overlay, like annotations. It **never re-rasterizes** the page (memory.md rule, covered by a test). |
| Responsiveness | `DocumentSearch.step()` runs in timed slices from a 0 ms `QTimer` (≤ 12 pages or 30 ms per slice) | The UI stays responsive on large PDFs. Typing is debounced (250 ms). A new query, tab switch or new PDF cancels the running search. |
| Rotated pages | Hit rects are mapped through `page.rotation_matrix` | Same coordinate fix as text selection (see rendering audit R4). |
| Filter notes in the open PDF | "Filter notes by text..." box above the note selector | Every term must appear in the note's Markdown or captured PDF text (case-insensitive). |
| Home search by note content | The Home search box now also matches note content | Matching notebooks show "· n matching notes". `NotebookSearchIndex` caches each `notes.json` and re-reads it only when its mtime changes. |

## Limits and possible next steps

- **Scanned (image-only) PDFs have no text layer**, so they can't be searched. That would need OCR (e.g. Tesseract via PyMuPDF `get_textpage_ocr`), which isn't bundled.
- MuPDF search doesn't match across a **hyphenated line break** ("vola-↵tility"). Adding `TEXT_DEHYPHENATE` to the flags would help, but character boxes then need care.
- Search runs on the UI thread in slices. Very heavy pages (huge vector maps) can still take tens of ms per page. A worker thread with its own `fitz.Document` would remove that.
- There's no persistent full-text index across PDFs: "which of my PDFs mentions X" is not supported. A SQLite FTS5 index built in the background would make it possible.
- Regular-expression search isn't offered.

## Tests

`tests/test_search.py`:
- Options (case and whole word, including the neighboring-word trap).
- CJK, scanned pages, and rotated pages at 0/90/180/270°.
- Wrap-around order, cancellation, time budget.
- Find bar: navigation and wrapping, status text, overlay without re-render, reset on document switch.
- Note filter.
- Index refresh on file change.
- Home search by note content.
