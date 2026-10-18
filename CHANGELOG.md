# Changelog

All notable changes to PDFNest. Issue IDs refer to [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md).

## 0.3.0 — 2026-10

### Added
- Find in PDF: `Ctrl+F` find bar, `F3`/`Shift+F3`, match case, whole words, highlighted matches, incremental search.
- Note search: sidebar note filter; Home search matches note content with match counts.
- Password prompt for encrypted PDFs.
- Contents ⋯ → *Restore original PDF*; `.pdfnest.bak` backup before the first contents save.
- Settings → Storage → *Back up all data...* (verified `.zip`).
- LaTeX renderer (`latex.py`): nested fractions, roots with index, binomials, accents, `\mathbb`/`\mathcal`/`\mathfrak`,
  fonts, `\left…\right`, matrix/cases/aligned/array environments, display-math limits, 228 symbols, 36 functions.
- Markdown: strikethrough, task lists, footnotes, definition lists, abbreviations, 2-space nested lists, `~~~` fences.
- `docs/markdown-compat.md`, `docs/KNOWN_ISSUES.md`, `docs/audit/*`, `scripts/bench_render.py`, `scripts/gen_markdown_compat.py`.

### Fixed
- Saving contents corrupted PDFs with bytes before `%PDF-`; follow-up saves failed (I-01, I-02).
- Signed / restricted / XFA PDFs could be rewritten (I-04); invalid contents reached MuPDF (I-05).
- Corrupt notes, index, history, settings or library files: crashes, silent resets, overwritten notes (I-06 – I-08).
- Note saves reset the manifest page count and last-read page (I-09); non-atomic writes (I-10).
- Encrypted PDFs crashed on open (I-11); selection and highlights misplaced on rotated pages (I-12).
- Repeated rasterization while scrolling (I-13); huge pages (I-14); broken pages (I-15); unclear open errors (I-16).
- O(notes × outline) chapter lookups (I-17).
- Stacked fractions, `$` amounts, missing LaTeX and Markdown features in the preview (I-18 – I-22).
- Migration dropped or crashed on bad legacy files (I-25); a missing data folder showed an empty library (I-26);
  unhandled export errors (I-27).

### Changed
- `main.py` split into `ui/`, `pdf/`, `services/` modules (compatibility re-exports kept).
- Test suite moved to pytest and split by area; 276 tests (was 64).
- `__version__` now matches the package version.

## 0.2.5 and earlier

See the git history (`Release PDFNest 0.2.x` commits).
