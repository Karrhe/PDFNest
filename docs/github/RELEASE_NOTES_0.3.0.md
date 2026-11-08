# PDFNest 0.3.0

A reliability release: saving contents no longer damages PDFs, notes can't be silently lost to a corrupt
file, more kinds of PDFs open and display correctly, and you can now search inside PDFs and your notes.

## Highlights

- **Find in PDF.** `Ctrl+F` opens a find bar with *Match case* and *Whole words*. `F3` / `Shift+F3` move
  between matches, which are highlighted on the page. Large PDFs stay responsive while searching.
- **Search your notes.** Filter the current PDF's notes by text in the sidebar. The Home search box now also
  finds notebooks by note content and shows how many notes match.
- **Safe "Save contents to PDF".** PDFNest rewrites the file into a temporary copy, checks it, keeps the
  original as `<name>.pdf.pdfnest.bak` and only then replaces the PDF. *Restore original PDF* is in the
  Contents ⋯ menu.
- **Password-protected PDFs** now open, with a password prompt.
- **Much better math in notes.** A new LaTeX renderer: stacked fractions, matrices, `cases`, `aligned`,
  limits under `\sum`/`\lim`, `\sqrt[n]{}`, `\mathbb{R}`, accents, and 228 symbols. Dollar amounts like
  "$5 and $10" are no longer turned into math. Plus strikethrough, task lists, footnotes and 2-space nested
  lists. See [`docs/markdown-compat.md`](../markdown-compat.md).
- **Full backup.** Settings → Storage → *Back up all data...* saves everything in one verified `.zip`.

## Fixes

### PDF files
- Saving contents damaged PDFs that have extra bytes before their `%PDF-` header (common for downloaded
  files), so other readers refused to open them, and the next save failed outright. (I-01, I-02)
- Signed, permission-restricted and XFA-form PDFs are no longer modified. (I-04)
- Invalid contents entries (pages out of range, level jumps, empty titles) are rejected with a clear message. (I-05)

### Notes and data
- A corrupt `notebooks/index.json` could make a PDF's notes look empty, and the next save then overwrote
  them. Notes are now found via the notebook manifests. (I-07)
- Corrupt data files no longer crash PDFNest or get overwritten. They are set aside as
  `*.corrupt-<time>.json` and listed in a warning. (I-06, I-08)
- Saving a note no longer resets the stored page count and last-read page. (I-09)
- All data files are written atomically with a flush to disk. (I-10)
- When the configured data folder is missing, PDFNest uses the local store instead of silently starting an
  empty library. (I-26)
- Migrating from the old `.local-data` layout no longer drops corrupt or path-less legacy note files
  silently, and a corrupt legacy history no longer crashes startup. (I-25)
- Markdown export failures (read-only folder, missing drive) show one clear warning instead of failing
  silently. (I-27)

### Reading
- Text selection, highlights and underlines are placed correctly on rotated pages. (I-12)
- Scrolling no longer re-renders pages that are already rendered: 8 instead of 65 page renders while scrolling
  about 10 pages, and scrolling is 33% faster. (I-13)
- Very large pages are rendered within a memory limit. (I-14)
- A page that fails to render shows a placeholder instead of breaking the reader. (I-15)
- Clear messages for empty, non-PDF and damaged files. (I-16)

## Upgrade notes

- **Highlights made on rotated pages with earlier versions** keep their old (wrong) position. Re-create
  them if needed. (O-01)
- After **Save contents to PDF**, a `<name>.pdf.pdfnest.bak` file appears next to the PDF. It holds the
  original from before the first save; delete it once you are happy with the result.
- The data folder layout is unchanged; no migration is needed from 0.2.x.

## For developers

- `main.py` (5,400 lines) is split into `ui/`, `pdf/`, `services/`, `markdown_render.py` and `latex.py`.
  `pdf_notes_reader.main` still exports `MainWindow`, `main`, `render_markdown_preview`, etc.
- Tests use pytest (`pip install -e ".[dev]"`, then `pytest`): 276 tests, up from 64.
  - Split by area, with per-test data isolation.
  - `tests/pdf_factory.py` builds problem PDFs.
  - Strict-reader checks (qpdf via pikepdf, pypdf) for files PDFNest writes.
  - A 66-case Markdown/LaTeX compatibility suite.
- New tools: `scripts/bench_render.py` (render benchmark) and `scripts/gen_markdown_compat.py`.
- Audits: [`docs/audit/rendering.md`](../audit/rendering.md), [`search.md`](../audit/search.md),
  [`migration-export.md`](../audit/migration-export.md). Issue register: [`docs/KNOWN_ISSUES.md`](../KNOWN_ISSUES.md).
- `pdf_notes_reader.__version__` was stuck at 0.2.4; it now matches the package version.
- Development environment: Python 3.14, PySide6 6.12, PyMuPDF 1.28.

**Full issue list:** [`docs/KNOWN_ISSUES.md`](../KNOWN_ISSUES.md). Issue IDs (I-xx, O-xx) refer to it.
