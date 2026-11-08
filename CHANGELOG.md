# Changelog

All notable changes to PDFNest. Issue IDs refer to [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md).

## 0.3.3 — 2026-11-08

### Added
- Books keep one path per computer: a book added on the PC shows on the Mac with its cover, notes and reading
  position, and is located there once (double-click, *Locate PDF on this computer…*, or adding the file),
  without changing where the PC finds it.
- Adding a folder builds the same folder tree in the library and files each PDF into its subfolder.
- Drag a book onto a folder in the Folders sidebar (a real drag with a picture of the row; the sidebar appears
  while dragging, also from Recent).
- `D` on Home moves the selected book to the Archive, like `Delete`.
- Touchpad pinch zoom on macOS; smooth pinch zoom on Windows precision touchpads.

### Fixed
- Left / Right arrows did not turn pages after clicking in the PDF (the scroll area took them).
- Library folders, filing, renames and the archive (`library.json`) are merged with the other computer's
  changes instead of overwritten; the open window picks up the other computer's books when it is activated.
- Settings → Storage showed the data folder twice and repeated it in every path below; files inside the
  data folder are now shown relative to it.

## 0.3.2 — 2026-11-08

### Added
- Sync between a Windows PC and a Mac through a data folder in iCloud Drive (or OneDrive / Dropbox): choose
  the same cloud folder in Settings → Storage on both. A PDF's notebook is found by its path relative to the
  data folder, then by a content fingerprint, so the same PDF shows the same notes, highlights, bookmarks and
  reading position on both computers (README → *Sync between Windows and Mac*).
- Saving notes, bookmarks and history merges with the copy on disk, so a computer with a stale copy no
  longer overwrites notes or books added on the other one. Sync-client conflict copies (`notes 2.json` etc.)
  are merged and moved to `conflicts/`.
- Evicted iCloud files (`.name.icloud`) are downloaded before they are read, and never overwritten meanwhile.

### Changed
- New PDFs get a key from their path relative to the data folder instead of the absolute path. Existing
  notebooks keep their keys; a one-time migration adds `relpath` and `fingerprint` to their `manifest.json`
  and `rel_path` to history entries.
- Window size, the data folder, export and last-opened folders, the Obsidian vault folder and the
  `pdfnest://` registration are kept per computer in `.local-data/machine_settings.json`.

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
  `.github/workflows/release.yml` builds Windows x64 and macOS arm64 and x86_64 on tag pushes or manual runs
  and attaches the Windows `.zip`/`.exe` and macOS `.dmg` files to the GitHub Release.
- `scripts/build_windows_exe.ps1` takes `-Python`, and falls back to `PDFNest-Icon.png` (generating the `.ico`)
  when the untracked `release_assets/` folder is missing, so it runs on a fresh checkout.
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
