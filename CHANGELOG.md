# Changelog

All notable changes to PDFNest. Issue IDs refer to [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md).

## Unreleased

## 0.3.1 — 2026-11-08

### Added
- Obsidian integration (Settings → Obsidian): one Markdown file per note in your vault plus a generated
  `_Index.md` per book; two-way sync with conflict copies (`*.pdfnest-conflict.md`); deleted notes go to the
  vault's `.trash`; *Open in Obsidian* button.
- `pdfnest://open?path=…&page=…&note=…` links that jump back to the PDF page or excerpt; optional per-user
  link handler registration; PDFNest now runs as a single instance and accepts links or `.pdf` paths on the
  command line.
- Library: add several PDFs at once, add every PDF in a folder (with subfolders), or drag PDFs and folders
  from Explorer onto Home or onto a library folder; the add button is now a menu, and folders' right-click
  menus offer the same.
- Background render worker processes (`PDFNEST_RENDER_WORKERS`, default 2) for slow pages such as scanned books.
- Notes panel **Summary** tab: every highlight and underline, grouped by PDF outline section (by page where
  a page has no section), with its note if it has one; click to jump, double-click to add a note;
  *Export summary* writes `Highlights.md` (into the Obsidian book folder when a vault is set).
- **Notes** button in the document bar shows or hides the notes panel, like **Contents**.
- macOS app: `scripts/build_macos_app.sh` builds `PDFNest.app` (`.icns` icon, `pdfnest://` URL scheme and
  `.pdf` document type in `Info.plist`, ad-hoc signed) and packs it as `PDFNest-<version>-macos-<arch>.dmg`;
  `.github/workflows/build-macos.yml` builds arm64 and x86_64 on tag pushes or manual runs and attaches the
  `.dmg` files to the GitHub Release.
- macOS: PDFs opened from Finder and clicked `pdfnest://` links (delivered as `QFileOpenEvent`, not on the
  command line) open in PDFNest.

### Changed (macOS)
- The frozen macOS app stores its data in `~/Library/Application Support/PDFNest/` instead of beside the
  executable inside the read-only, signed app bundle. Windows builds and source checkouts are unchanged.
- Settings → Obsidian → *Links back* is disabled outside Windows (the app bundle declares the scheme).

### Changed (notes)
- Highlights and underlines no longer create a note automatically. A note is optional and each highlight or
  underline has at most one: right-click it (or its Summary row) → *Add note* / *Open note* / *Delete note*.
  Deleting the note keeps the marked text; *Delete highlight* removes both. Existing highlights whose note
  holds only the generated title and quote count as having no note (the text is kept and reused if a note is
  added later); these no longer get files in an Obsidian vault.

### Changed
- Pages render at the screen's device pixel ratio instead of a fixed 2x.
- Only on-screen pages render immediately; buffered pages fill in afterwards and keep appearing during
  continuous scrolling (throttled instead of debounced); page widgets are reused while the zoom is unchanged.
- The empty "Other" settings page is replaced by "Obsidian".
- Open / Add / Relocate PDF use the system file dialog instead of Qt's own, and start in the last-used folder.

### Fixed
- Adding a PDF that was already in the library reset its last-read page to 1.
- `scripts/build_windows_exe.ps1` silently built nothing when the venv's `pyinstaller.exe` launcher was stale
  (after moving the project); it now runs `python -m PyInstaller` and stops on failure.

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
