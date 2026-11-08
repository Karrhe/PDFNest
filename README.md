# PDFNest

A Python desktop PDF reader with external anchored Markdown notes.

## Features

- Open and render multiple local PDF files in browser-style tabs (*Open PDF* accepts several files at once), including password-protected and damaged (repairable) PDFs.
- Find text in the PDF with `Ctrl+F` (match case, whole words, `F3` / `Shift+F3`), filter notes by text, and search note content from Home.
- Save edited contents (outline) into the PDF safely: full rewrite, verification, and a `.pdfnest.bak` backup of the original that can be restored.
- Back up all PDFNest data into one verified `.zip` from Settings → Storage.
- Use `Ctrl+W` to close the current PDF tab, and `Ctrl+1` through `Ctrl+9` to switch tabs.
- Read in continuous vertical scroll mode by default, or switch to single-page mode from the PDF context menu.
- Navigate pages with the bottom `- Page n / l +` control or keyboard arrow keys.
- Jump by editing the bottom page number directly.
- Zoom by editing the bottom zoom percentage, using context menu fit commands, or pressing `Ctrl` + mouse wheel.
- `Ctrl` + mouse wheel zooms around the current reading page center instead of the mouse pointer.
- Fit width and fit height keep adapting when the reader window changes size or when the reader/notes splitter is moved.
- Fit width uses the widest page in the PDF as the reference width, matching browser-style PDF readers and avoiding horizontal scrolling on mixed-width PDFs.
- Browse PDF outlines from the left Contents panel when the PDF provides a table of contents.
- Keep full-document page geometry in continuous mode so the scrollbar represents the whole PDF, while rasterizing only the current visible page window and nearby buffered pages.
- Render only the current reading page during zoom and fit changes first, so zoom controls respond faster.
- Render pages at the screen's device pixel ratio for sharp text while keeping anchors aligned to the visible page size.
- Apply a warm beige reading tint to the PDF page content, the reader blank area, and the UI.
- Right-click anywhere on a PDF page to add an anchored note.
- Drag across digital PDF text to select continuous line-by-line text, then press `Ctrl+C` to copy it.
- Right-click selected text to create a colored highlight or underline annotation with an editable Markdown note.
- New point notes start with a Markdown title based on the current PDF outline entry, or `page-<number>` when no outline entry is available, plus the note number on that page.
- Store note anchors as `page_index + x_norm + y_norm`, so markers stay aligned across zoom changes.
- Show note markers as colored dots on the page, with configurable marker size in Settings.
- Click a marker, highlight, or underline to edit or preview its Markdown note in the right sidebar.
- Right-click a marker, highlight, or underline to change its color or delete it.
- Use the note selector at the top of the right sidebar to switch between notes. Entries use each note's first non-empty line.
- Preview Markdown with tables, fenced code blocks, inline code, block quotes, and `$...$` / `$$...$$` math formula styling.
- Save note anchors/content in external JSON files without modifying the original PDF.
- Export individual notes as Markdown files to a selectable local folder.
- Reopen known PDFs from the Home history page.
- Add books to the library without opening them: the Home **+** button offers *Add PDF files…* (pick several at once with `Ctrl`/`Shift`+click) and *Add all PDFs in a folder…* (subfolders included; hidden folders such as `.trash` are skipped). You can also drag PDFs or folders from Explorer onto Home, or onto a library folder in Notebooks. New books go into the open Notebooks folder; books already in the library keep their reading position and folder.
- Open, Add and Relocate use the standard Windows file dialog and start in the folder you used last.
- Restore the last-read page when opening a PDF again.
- Prompt for relocation when a PDF history item points to a missing absolute path.
- Use a beige reading theme inspired by notebook/library reading tools.
- Switch themes in Settings. Theme names are loaded from standalone JSON files in `.local-data/themes/`.
- Use `Icon.png` as the application icon.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Or install the direct requirements:

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python.exe -m pdf_notes_reader.main
```

If installed with `pip install -e .`, you can also run:

```powershell
.\.venv\Scripts\pdfnest.exe
```

The older command name is kept as an alias:

```powershell
.\.venv\Scripts\pdf-notes-reader.exe
```

## Windows EXE Release

For end-user distribution on Windows, build the executable package with PyInstaller:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\scripts\build_windows_exe.ps1
```

Pushing a tag such as `v0.3.2` also builds the Windows files on GitHub Actions (`.github/workflows/release.yml`) and attaches the `.zip` and single-file `.exe` to the GitHub Release, next to the macOS builds. Without `release_assets\` (it is not in Git), the script uses `PDFNest-Icon.png` and generates the `.ico` with `scripts\make_windows_icon.py`.

The release outputs are written under `release\`:

- `PDFNest\PDFNest.exe`: portable folder build. Distribute the whole `PDFNest` folder, or the generated zip.
- `PDFNest-0.3.2-windows-x64.zip`: zipped portable folder build.
- `PDFNest-0.3.2-windows-x64.exe`: single-file executable. It is easier to share, but starts more slowly because it extracts bundled files at launch.
- `*.VisualElementsManifest.xml` and `*.VisualElements\`: Windows Start menu tile assets. Keep them beside the matching executable when pinning PDFNest to Start.

The app data folder remains beside the executable as `.local-data\` unless `PDF_NOTES_READER_DATA_DIR` is set.

## macOS App Release

PyInstaller cannot cross-compile, so the Mac app is built on a Mac or by GitHub Actions.

**GitHub Actions** (`.github/workflows/release.yml`, which also builds the Windows files): pushing a tag such as `v0.3.2` builds `PDFNest.app` on an Apple Silicon (`arm64`) and an Intel (`x86_64`) runner and attaches `PDFNest-<version>-macos-arm64.dmg` and `PDFNest-<version>-macos-x86_64.dmg` to the GitHub Release for that tag. *Actions → Build release → Run workflow* builds the same files as downloadable workflow artifacts without a release.

**On a Mac** (Python 3.10+, with the Xcode command line tools for `codesign`):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt pyinstaller
bash scripts/build_macos_app.sh            # version from pyproject.toml, or pass one: 0.3.2
```

The outputs are written under `release/`:

- `PDFNest.app`: the app bundle (for the Mac's own architecture). It declares the `pdfnest://` link scheme and offers itself in Finder's *Open With* menu for PDFs.
- `PDFNest-<version>-macos-<arch>.dmg`: disk image with the app and an `Applications` shortcut (a `.zip` instead when `hdiutil` is unavailable).

**Installing**: open the `.dmg` and drag PDFNest into Applications. Choose `arm64` for Apple Silicon Macs (M1 and later) and `x86_64` for Intel Macs (Apple menu → About This Mac shows which). Both need macOS 14 Sonoma or later (required by Qt 6.12). The app is ad-hoc signed but not signed with an Apple Developer ID or notarized, so Gatekeeper says it is from an unidentified developer (or that it "is damaged and can't be opened" for downloaded copies). To open it the first time, either:

- Control-click PDFNest in Applications → **Open** → **Open** (on macOS 15 and later: try to open it once, then *System Settings → Privacy & Security → Open Anyway*), or
- remove the download quarantine flag in Terminal:

  ```bash
  xattr -dr com.apple.quarantine /Applications/PDFNest.app
  ```

On macOS the app keeps its data in `~/Library/Application Support/PDFNest/` (`Note_PDFNest/` and `.local-data/`), not inside the app bundle, so replacing the app with a newer version keeps your notes. A data folder chosen in Settings and `PDF_NOTES_READER_DATA_DIR` still take precedence. Running from source on a Mac keeps data in the project folder, as on Windows.

## Reading Controls

- `Home`: returns to the recent PDFs page.
- `Open`: opens a local PDF and records its absolute path in history.
- `Reader`: returns to the active PDF reader.
- `Contents`: toggles the PDF outline panel.
- Bottom page control: `- Page n / l +`, where `-` goes to the previous page, `+` goes to the next page, and the page number field can be edited directly.
- Bottom zoom control: edit the percentage field to set the PDF zoom directly.
- Arrow keys: `Up` or `Left` goes to the previous page; `Down` or `Right` goes to the next page.
- `PageUp` / `PageDown`: previous or next page.
- `Ctrl` + mouse wheel over the PDF area: zooms in or out around the current reading page center.
- Right-click a PDF page for `Add note`, `Fit width`, `Fit height`, `Continuous scroll`, `Single page`, and `Settings`.
- Open Settings from the Home page or from the PDF right-click menu.
- Drag-select digital PDF text, then press `Ctrl+C` to copy the selected text. Selection follows PDF reading order: the start line, full middle lines, and end line are selected as continuous line spans. `Ctrl+V` also copies the current PDF selection for compatibility with the original shortcut request.
- Right-click a text selection for `Copy selected text`, colored `Highlight selection`, and colored `Underline selection`.
- Click an item in the left Contents panel to jump to that PDF outline page.
- `Ctrl+F`: find text in the PDF. `Enter` / `F3` = next match, `Shift+Enter` / `Shift+F3` = previous, `Esc` closes. Selected PDF text pre-fills the search. Matches are highlighted in orange; the search starts at the current page, wraps around, and runs in small steps so large PDFs stay responsive.
- Contents ⋯ menu → **Restore original PDF** puts back the original file from before PDFNest first saved contents into it.

Pages are rasterized at the screen's device pixel ratio (for example 1.25 at 125% Windows scaling), so every screen pixel gets exactly one rendered pixel. Note anchors use normalized coordinates on the visible page, so zoom and render precision changes do not shift note positions. In continuous mode, the reader keeps geometry for every page so the scrollbar range matches the whole PDF, but it only creates widgets for the current page window and a few merged spacer runs, and reuses them while the zoom stays the same. Only the pages on screen are rendered right away; nearby buffered pages are filled in afterwards, nearest first, and pages keep appearing while you scroll.

Pages are rendered in two background worker processes, so slow pages (scanned books, heavy drawings) never freeze the window. For such documents even visible pages are drawn by the workers, and a page waiting at a new zoom shows its previous image scaled until the sharp one arrives. Set the environment variable `PDFNEST_RENDER_WORKERS=0` to render everything in the main process.

## Markdown Notes

The preview tab supports common Markdown authoring features:

- Inline code: `` `x = 1` ``
- Fenced code blocks:

````markdown
```python
print("hello")
```
````

- Block quotes: `> quoted text`
- Tables
- Inline formulas: `$a^2 + b^2 = c^2$`
- Formula blocks: `$$E = mc^2$$`

- Strikethrough `~~text~~`, task lists `- [ ]` / `- [x]`, footnotes, definition lists, abbreviations
- Nested lists indented with 2 or 4 spaces

Formula content is parsed and rendered into styled inline or block formula elements in the preview. It keeps the original LaTeX-style text in storage, so notes remain portable.

The local formula renderer (`latex.py`) is a brace-aware LaTeX parser that renders to Qt rich text. It supports 228 symbols (Greek with variants, relations, operators, arrows, big operators, dots and delimiters), `\sin`-style functions, nested `\frac`, `\sqrt[n]{}`, `\binom`, accents (`\hat`, `\vec`, `\bar`, …), `\mathbb`/`\mathcal`/`\mathfrak`/`\mathbf`/`\text`, `\left…\right`, and the `matrix`/`pmatrix`/`bmatrix`/`vmatrix`/`cases`/`aligned`/`array` environments. Display math (`$$…$$`) stacks fractions, matrices and limits under `\sum`/`\lim`; inline math stays on one line (`a⁄b`). Dollar amounts such as "$5 and $10" stay text, and `\$` is a literal dollar. Unknown commands stay visible in red instead of disappearing.

The full feature list with before/after status is in [`docs/markdown-compat.md`](docs/markdown-compat.md).

Without an Obsidian vault (see below), the right note sidebar has an `Export MD` button; the base folder for standalone `.md` files is set in Settings → Storage → *Markdown export base*. `Export MD` creates a subfolder named after the current PDF inside that base folder, first saves the current editor text to the JSON anchor store, then writes a Markdown copy using this default filename pattern:

```text
YYYYMMDD-HHMMSS-<chapter-name-or-page-number>-<number>.md
```

`<number>` is a monotonic note number for that PDF page and is not reused after deleting earlier notes. Chapter names come from the PDF outline when available; otherwise the filename uses `page-<page_number>`. Characters that are invalid in Windows filenames are replaced with `_`. Long PDF names and location names are truncated with a stable hash suffix before folder or file creation to avoid Windows path component limits.

After a note has been exported once, its Markdown file path is stored in the note JSON. Exporting that same note again asks whether to replace the previous `.md` file or create a new timestamped `.md` file.

## Obsidian Integration

PDFNest can keep your notes in an [Obsidian](https://obsidian.md) vault, so you write and format them in Obsidian (with its plugins, links, graph and search) while PDFNest keeps the anchors, highlights and excerpt markers. The integration is off until you choose a vault in **Settings → Obsidian**:

- **Vault folder**: your vault. If it is not an Obsidian vault yet, open it once in Obsidian (*Open folder as vault*).
- **Folder in vault**: where PDFNest's notes go (default `PDFNest`; empty = the vault's top folder).
- **Links back**: registers PDFNest as the handler of `pdfnest://` links for your Windows user (`HKCU\Software\Classes\pdfnest`; unticking removes it). On macOS this setting is unavailable: `PDFNest.app` declares the scheme in its `Info.plist`, so links work once the app is in Applications (and has been opened once).

Layout, one file per note plus a generated index per book:

```text
<vault>/PDFNest/<pdf name>/
  _Index.md              generated: links to every note in page order (rewritten by PDFNest)
  p25 Scaling-1.md       one file per note, highlight and underline
```

Each note file starts with front matter that PDFNest manages (`pdfnest_id`, `pdf`, `page`, `type`, `created`, `link`); properties you add in Obsidian, such as `tags`, are kept. Everything below the front matter is the note itself. Text appended from the PDF ends with a link to its exact place, for example `> — [p.25](pdfnest://open?path=…&page=25&note=…)`. With *Links back* on, clicking such a link in Obsidian opens the PDF at that excerpt: in the running PDFNest if there is one (PDFNest runs as a single instance), otherwise in a new one.

Sync rules:

- The note sidebar's button becomes **Open in Obsidian** (`Ctrl+Shift+S`): it saves the note to the vault and opens it in Obsidian.
- PDFNest writes a note's file whenever it saves the note. It reads Obsidian's edits back when a PDF opens, when you pick another note, and whenever the PDFNest window becomes active again.
- If a note was edited in both apps, Obsidian's text is kept as the note and PDFNest's text is saved beside it as `<name>.pdfnest-conflict.md`. Nothing is overwritten silently.
- Renaming or moving a note file inside the vault is fine: PDFNest finds it again by its `pdfnest_id`. File names are chosen once, when the note is created.
- Deleting a note in PDFNest moves its file to the vault's `.trash` folder (Obsidian's trash). A file deleted only in Obsidian is written again from PDFNest's copy.
- Existing notes are written to the vault the first time their PDF is opened after a vault is set; sidebar ⋯ → *Export all notes* (or the library's export) syncs a whole book at once.

The built-in editor and preview remain for quick notes while reading; Obsidian is the place for longer writing.

## Data Storage

Notes and PDF-related metadata are saved outside the original PDF. The app never writes notes back into the PDF file.

The only operation that changes a PDF is **Save contents to PDF** in the Contents panel, and only after you confirm. PDFNest rewrites the file completely into a temporary copy, re-opens and checks that copy, keeps the original as `<name>.pdf.pdfnest.bak` (created once and never overwritten), and only then replaces the PDF. Signed, permission-restricted and XFA-form PDFs are refused untouched.

If a data file cannot be read (for example after a crash or a sync conflict), PDFNest moves it aside as `<name>.corrupt-<time>.json`, continues with what it can read, and shows a warning listing the files. It never overwrites an unreadable notes file with an empty one.

Default storage location:

```text
<project-or-program-folder>\Note_PDFNest\
```

(For the macOS app: `~/Library/Application Support/PDFNest/Note_PDFNest/`, with `.local-data/` beside it.)

PDFNest stores PDF history, bookmarks, notebook data, and app settings in this structure:

```text
Note_PDFNest\
|-- bookmarks\
|   |-- <pdf_key>_bookmark.json
|   `-- sync.lock
|-- notebooks\
|   |-- index.json
|   `-- <PDF_name>\
|       |-- note\
|       |   `-- notes.json
|       |-- cover.png
|       |-- manifest.json
|       |-- markups.json
|       |-- recentfile.json
|       `-- sync.lock
|-- library.json
|-- migration_state.json
|-- recentnotes.json
`-- user_config.json
```

`library.json` stores PDFNest-only virtual folders, optional `parent_id` links for nested folders, and each PDF's folder assignment. It does not move or rename the original PDF files. Deleting a virtual folder only removes that folder metadata and returns its PDFs to `Unfiled`.

On startup, PDFNest runs a one-time migration from the older `.local-data\pdf_history.json`, `.local-data\notes\*.json`, and `.local-data\settings.json` layout when those files are present. The migration writes `notebooks\index.json`, so normal note and bookmark lookups do not scan every notebook folder.

The default Markdown export folder is:

- Base folder: `<project-or-program-folder>\.local-data\markdown_notes\`
- Per-PDF folder: `<project-or-program-folder>\.local-data\markdown_notes\<pdf-name>\`

The app settings file is:

```text
<project-or-program-folder>\Note_PDFNest\user_config.json
```

It stores the selected theme name, note marker size, shortcut settings, and the configurable PDFNest data folder.

Settings that describe one computer (window size and state, the data folder, the Markdown export folder, the last folder used to open PDFs, the Obsidian vault folder and the `pdfnest://` link registration) are also kept in `.local-data/machine_settings.json`, beside the data-folder pointer. That file is never inside the data folder, so a Windows PC and a Mac that share one data folder each keep their own. See [Sync between Windows and Mac](#sync-between-windows-and-mac).

Theme files are stored as independent JSON files under:

```text
<project-or-program-folder>\Note_PDFNest\themes\
```

Each `*.json` filename becomes a theme name in Settings. For example, `Note_PDFNest\themes\white.json` appears as `white`. Default `beige.json` and `white.json` files are created automatically if they are missing.

To store note files inside this project while developing, set `PDF_NOTES_READER_DATA_DIR` before launching the app:

```powershell
$env:PDF_NOTES_READER_DATA_DIR = "$PWD\Note_PDFNest"
.\.venv\Scripts\python.exe -m pdf_notes_reader.main
```

With that setting, note files are written under:

```text
.\Note_PDFNest\notebooks\<PDF_name>\note\notes.json
```

Markdown exports are written under this folder unless the base folder is changed from the right sidebar:

```text
.\.local-data\markdown_notes\<pdf-name>\
```

The PDF history file is written under:

```text
.\Note_PDFNest\recentnotes.json
```

The settings file and theme folder are written under:

```text
.\Note_PDFNest\user_config.json
.\Note_PDFNest\themes\*.json
```

The project `.gitignore` ignores `.local-data/` and `Note_PDFNest/`, so private local notes, Markdown exports, history, settings, and local themes are not picked up by Git by default.

### PDF Key And File Naming

Each PDF gets a `pdf_key` the first time PDFNest sees it, and keeps it for good. Notes, bookmarks, history and library folders all refer to it, and notebooks are never re-keyed.

- A new PDF's key is a hash of its path relative to the data folder (`sha256("pdfnest-relpath\0" + relpath)[:24]`, with the path in a case- and Unicode-normalized form). It is the same on every computer that shares the data folder.
- A PDF on a different drive than the data folder has no relative path. It gets the older path key, `sha256(normcase(resolved_pdf_path))[:24]`, which notebooks made by PDFNest 0.3.1 and earlier also keep.

When a PDF is opened, PDFNest looks for its notebook in this order:

1. This computer's path key (older notebooks, or the same file reopened from the same place).
2. The PDF's path relative to the data folder (`relpath` in `manifest.json`, for example `../Books/a.pdf`). With the data folder and the PDFs both in iCloud Drive, this is identical on Windows and macOS.
3. The content fingerprint (`fingerprint` in `manifest.json`): a SHA-256 of the file size plus the first and last MiB. This finds a PDF that moved, or one outside the data folder's drive. Step 2 still finds a PDF whose contents changed in place, for example after *Save contents to PDF*.
4. For an old notebook made on the other computer that has no fingerprint yet: a unique match on the file name.

Steps 3 and 4 skip a notebook whose PDF still exists on this computer at another path. That is a second copy, and each copy keeps its own notes.

The primary note data file path is:

```text
<data_dir>\notebooks\<PDF_name>\note\notes.json
```

For example, if `PDF_NOTES_READER_DATA_DIR=F:\...\PDFReading\Note_PDFNest`, `example.pdf` stores notes at:

```text
F:\...\PDFReading\Note_PDFNest\notebooks\example\note\notes.json
```

### JSON Contents

Each PDF notebook has a `note` folder with a primary `notes.json` file. The file stores the PDF key, the PDF path recorded when notes were saved, the schema version, and all note anchors/content. Point notes use `note_type: "point"`. Text highlights and underlines use `note_type: "highlight"` or `note_type: "underline"`, plus normalized text rectangles:

```json
{
  "pdf_key": "24-character-path-hash",
  "pdf_path": "F:\\path\\to\\example.pdf",
  "schema_version": 1,
  "note_counters": {
    "0": 2
  },
  "notes": [
    {
      "id": "note-uuid",
      "pdf_key": "24-character-path-hash",
      "page_index": 0,
      "x_norm": 0.5,
      "y_norm": 0.5,
      "markdown": "# Note",
      "created_at": "...",
      "updated_at": "...",
      "note_type": "point",
      "rects_norm": [],
      "selected_text": "",
      "color": "#e11d48",
      "note_number": 1,
      "exported_markdown_path": "F:\\path\\to\\markdown_notes\\example\\20260708-120000-page-1-1.md"
    }
  ]
}
```

Field meanings:

- `pdf_key`: stable path-derived identifier for the PDF.
- `pdf_path`: PDF path stored for reference; the app uses `pdf_key` to load the matching note file.
- `schema_version`: note file format version.
- `note_counters`: next note number per zero-based page index. Counters are monotonic and do not decrease when notes are deleted.
- `notes[].page_index`: zero-based PDF page index.
- `notes[].x_norm` and `notes[].y_norm`: normalized anchor coordinates from `0.0` to `1.0`, relative to the rendered PDF page.
- `notes[].markdown`: raw Markdown note text.
- `notes[].note_type`: `point`, `highlight`, or `underline`.
- `notes[].rects_norm`: normalized text rectangles for text annotations.
- `notes[].selected_text`: copied text captured when the text annotation was created.
- `notes[].color`: optional per-note marker, highlight, or underline color.
- `notes[].note_number`: note number assigned when the note was created.
- `notes[].exported_markdown_path`: last exported Markdown file path for the note. It is used to offer replacement on later exports.
- `created_at` and `updated_at`: UTC ISO timestamps.

Every JSON file is written to a uniquely named temporary file in the same folder, flushed to disk, then atomically renamed over the target, so a crash leaves either the old or the new file, never a partial one.

### PDF History Contents

The history file stores one entry per opened PDF:

```json
{
  "schema_version": 1,
  "entries": [
    {
      "pdf_key": "24-character-path-hash",
      "path": "F:\\path\\to\\example.pdf",
      "title": "example.pdf",
      "last_page_index": 3,
      "page_count": 20,
      "opened_at": "...",
      "updated_at": "...",
      "rel_path": "../path/to/example.pdf"
    }
  ]
}
```

`path` is absolute and only valid on the computer that wrote it. `rel_path` is the same file relative to the data folder (empty when the PDF is on another drive). On a computer that shares the data folder, an entry whose `rel_path` points at an existing file opens that file.

When opening a PDF from history:

- If `path` exists, the app opens it and jumps to `last_page_index`.
- In continuous scroll mode, the current page is updated from the scroll position and saved when returning Home or closing the window.
- On app startup, the most recent existing PDF is reopened at its saved page; opening an existing PDF from Home history also restores its saved page.
- If `path` no longer exists, the app asks whether to relocate the PDF.
- If relocated, the history entry keeps the same `pdf_key`, updates the absolute path, and restores the last-read page.

### Sync between Windows and Mac

PDFNest can share notes, highlights, bookmarks, library folders and reading positions between a Windows PC and a Mac through iCloud Drive. OneDrive and Dropbox work the same way. PDFNest does not talk to the cloud itself: both computers use one data folder inside the cloud drive, and the cloud client copies the files.

1. Put the PDFs in the cloud drive, for example `iCloud Drive/Books/`.
2. Create a data folder in the cloud drive too, for example `iCloud Drive/PDFNest/`. To keep the notes you already have, copy your current `Note_PDFNest` folder's contents into it first.
3. On each computer, choose that folder in **Settings → Storage → PDFNest data folder**:
   - Windows (iCloud for Windows): `C:\Users\<you>\iCloudDrive\PDFNest`
   - macOS: `~/Library/Mobile Documents/com~apple~CloudDocs/PDFNest` (in Finder: *iCloud Drive → PDFNest*)
4. On both computers, open the PDFs from the cloud drive, not from a local copy.

The data folder and the PDFs must sit the same way relative to each other on both computers (`../Books/a.pdf` from the data folder). A PDF opened from somewhere else, for example a copy in Downloads, is still found by its fingerprint, but its library entry only opens on the computer that has that copy.

The first time PDFNest starts with a data folder, it records the relative path and fingerprint of every notebook whose PDF it can read (`migration_state.json` records which folder that was done for). Old notebooks keep their key and their notes. They show up on the other computer once the computer that made them has done this, or earlier through the file-name match above.

When both computers are in use:

- Saving notes or history merges with the copy on disk instead of replacing it. A note or book added on the other computer is kept. A note deleted here stays deleted. When the same note was edited on both, the later edit wins.
- Sync clients sometimes make conflict copies: `notes 2.json` (iCloud), `notes (… conflicted copy …).json` (Dropbox), `notes-PCNAME.json` (OneDrive). For `notes.json`, a bookmarks file or `recentnotes.json`, PDFNest merges the copy in, moves it to a `conflicts/` folder and shows a warning. `notebooks/index.json` is only a cache: if the other computer's copy is missing a notebook, PDFNest finds it again from the `manifest.json` files.
- When macOS has evicted a file to a `.<name>.icloud` placeholder, PDFNest asks iCloud to download it (`brctl download`) and waits up to 10 seconds. If the file is still missing, PDFNest shows a warning and treats the notebook as empty without overwriting the real file. The next save merges with the file once it arrives. Files that are only in the cloud on Windows or on newer macOS download when PDFNest reads them. Library covers are not made for books that are only in the cloud.
- Settings for one computer stay in `.local-data/machine_settings.json` (see above). A folder setting that the other operating system wrote into the shared `user_config.json` (`C:\...` on a Mac, `/Users/...` on Windows) is ignored.

Good practice:

- Keep the data folder downloaded. On the Mac: right-click it in Finder → *Keep Downloaded*. On Windows: right-click it → *Always keep on this device*.
- Let the cloud finish syncing before you switch computers, and don't edit the same note on both at once. PDFNest does not reload an open PDF's notes when they change on disk, so close and reopen the PDF to see notes just synced from the other computer.
- Markdown export paths and the Obsidian vault folder are per computer. On each computer, set the vault folder to that computer's path to the same vault.

### Backups and moving the data folder

Settings → Storage → **Back up all data...** writes one `.zip` with notes, anchors, highlights, bookmarks, library folders and settings, and verifies it. If the data folder configured in Settings no longer exists (drive unplugged, folder moved), PDFNest uses the local `Note_PDFNest` folder instead of silently starting an empty library, and says so.

## Project structure

```text
src/pdf_notes_reader/
  app.py, main.py          entry point (main.py re-exports the public names for compatibility)
  ui/                      Qt widgets: main_window, canvas, find_bar, note/outline/history panels, settings, styles
  pdf/                     document opening, render cache, text geometry, search, safe outline writer
  services/                Qt-free logic: chapters/numbering, Markdown export, note search, backup
  markdown_render.py       Markdown preview pipeline
  latex.py                 LaTeX math → Qt rich-text HTML
  notes.py, history.py, library.py, settings.py, storage_migration.py   storage
docs/                      audits, issue register, Markdown compatibility matrix, GitHub release notes
scripts/                   Windows and macOS builds, icon tool, render benchmark, compatibility-matrix generator
```

## Tests

Install the development dependencies, then run the full test suite (Qt tests run offscreen):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

The suite also runs with `python -m unittest discover -s tests` for the unittest-style modules. `tests/pdf_factory.py` builds the problem PDFs used by the loading, rendering and contents-saving tests. Each test gets its own temporary data folder, so tests never touch your notes.

Useful tools:

```powershell
.\.venv\Scripts\python.exe scripts\bench_render.py --pages 2000      # open/scroll rasterization benchmark
.\.venv\Scripts\python.exe scripts\gen_markdown_compat.py            # regenerate docs/markdown-compat.md
```
