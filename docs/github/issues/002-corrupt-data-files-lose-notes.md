---
title: "Corrupt data files crash PDFNest or cause notes to be overwritten"
labels: [bug, data-loss, storage]
status: fixed in 0.3.0
register: I-06, I-07, I-08, I-09, I-10
---

## Summary
If a PDFNest JSON file is damaged (crash during a write, disk full, sync conflict), PDFNest 0.2.5 either
crashes or, worse, shows the PDF with **no notes and overwrites the real notes on the next save**.

## Steps to reproduce (worst case)
1. Create notes on a PDF.
2. Truncate `Note_PDFNest/notebooks/index.json` (e.g. replace its content with `{`).
3. Open the PDF: the notes are gone. Add any note: the old `notes.json` is replaced by one containing just the new note.

Other variants:
- A truncated `notes.json` crashes opening the PDF.
- A truncated `recentnotes.json` or `user_config.json` crashes startup.
- A truncated `library.json` silently resets all virtual folders.

## Root cause
- `_load_notebook_index` returned `{}` for an unreadable index without rebuilding it. Lookups then fell back
  to a new empty notebook path.
- `load_notes_payload`, `load_history` and `load_settings` didn't catch `JSONDecodeError`.
- Writes used a fixed `.tmp` name without `fsync`. `library.json`/`user_config.json` had their own non-durable writers.
- Separately, every note save rewrote `manifest.json` with `page_count: 0` and `recentfile.json` with the
  highest note page, clobbering the values maintained by history.

## Fix
- `read_json_checked` moves unreadable files to `<name>.corrupt-<time>.json` and records a `StorageIssue`.
  The window shows a non-blocking warning listing them.
- The index is rebuilt from `manifest.json` files when unreadable; a stale entry falls back to a manifest scan.
- `_atomic_write_json`: unique temp file, `flush`+`fsync`, `os.replace`, cleanup on failure. Used by all writers.
- `save_notes` preserves the manifest page count and only seeds `recentfile.json`.

## Tests
`tests/test_data_integrity.py`: 12 tests covering every case above, plus round-trips with CJK/long names,
same-named PDFs in different folders, and a simulated failed rename.
