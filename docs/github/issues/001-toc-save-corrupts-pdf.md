---
title: "Save contents to PDF corrupts some PDFs so other readers can't open them"
labels: [bug, data-loss, pdf-write]
status: fixed in 0.3.0
register: I-01, I-02, I-03, I-04, I-05
---

## Summary
Adding or editing contents (outline) entries and clicking **Save contents to PDF** can leave a PDF that other
PDF readers refuse to open. Saving again afterwards fails with *"Can't do incremental writes on a repaired file"*.

## Steps to reproduce
1. Take a PDF with a few bytes before its `%PDF-` header, which is common for downloaded files. For example, a UTF-8 BOM:
   `printf '\xef\xbb\xbf' | cat - original.pdf > prefixed.pdf`
2. Open it in PDFNest 0.2.5, add a contents item, and click **Save contents to PDF**.
3. Run `qpdf --check prefixed.pdf`, or open it in a strict viewer.

**Expected:** a valid PDF with the new contents.
**Actual:** qpdf reports *"file is damaged … invalid xref entry (obj=13)"*. MuPDF has to repair the file on the
next open, and every later save fails.

## Root cause
`save_outline_to_pdf` called `document.set_toc(toc)` and then `document.saveIncr()` on the open original.
An incremental update writes its xref offsets from the start of the file, while the original's offsets count
from the `%PDF-` header. Lenient readers tolerate the original; after the update the file is inconsistent.
There was also:
- no backup,
- no check after writing,
- no refusal for signed or permission-restricted files,
- no validation of contents entries.

## Fix
`pdf/outline_writer.save_toc_safely`:
1. Validates the entries.
2. Refuses signed, restricted and XFA PDFs.
3. Does a **full** save to a temp file next to the original.
4. Re-opens it with a fresh MuPDF instance and checks the header, repair flag, page count, contents and page loading.
5. Keeps the pristine original as `<name>.pdf.pdfnest.bak` (once).
6. Atomically replaces the file and re-opens it in the same tab.

On any failure the original is untouched. Contents ⋯ → *Restore original PDF* brings back the backup.

## Tests
`tests/test_outline_writer.py`:
- The legacy path is shown to damage BOM / CRLF / HTTP-prefixed files.
- The new path produces files that qpdf and pypdf (strict) accept, across 6 PDF layouts.
- Repeated saves stay valid; signed and restricted files are refused.
- A failed check leaves no trace.
- Invalid contents are rejected.

GUI: `tests/test_outline.py::test_outline_save_on_bom_prefixed_pdf_keeps_file_valid_notes_and_view`.
