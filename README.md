# PDF Notes Reader

A Python desktop PDF reader with external anchored Markdown notes.

## Features

- Open and render local PDF files.
- Read in continuous vertical scroll mode by default, or switch to single-page mode from the PDF context menu.
- Navigate pages with the bottom `- Page n / l +` control or keyboard arrow keys.
- Jump by editing the bottom page number directly.
- Zoom by editing the bottom zoom percentage, using context menu fit commands, or pressing `Ctrl` + mouse wheel.
- `Ctrl` + mouse wheel zooms around the current reading page center instead of the mouse pointer.
- Fit width and fit height keep adapting when the reader window changes size or when the reader/notes splitter is moved.
- Browse PDF outlines from the left Contents panel when the PDF provides a table of contents.
- Keep full-document page geometry in continuous mode so the scrollbar represents the whole PDF, while rasterizing only the current visible page window and nearby buffered pages.
- Render only the current reading page during zoom and fit changes first, so zoom controls respond faster.
- Render pages at 2x internal precision for sharper text while keeping anchors aligned to the visible page size.
- Apply a warm beige reading tint to the PDF page content, the reader blank area, and the UI.
- Right-click anywhere on a PDF page to add an anchored note.
- Store note anchors as `page_index + x_norm + y_norm`, so markers stay aligned across zoom changes.
- Show note markers as colored dots on the page.
- Click a marker to edit or preview its Markdown note in the right sidebar.
- Preview Markdown with tables, fenced code blocks, inline code, block quotes, and `$...$` / `$$...$$` math formula styling.
- Save note anchors/content in external JSON files without modifying the original PDF.
- Export individual notes as Markdown files to a selectable local folder.
- Reopen known PDFs from the Home history page.
- Restore the last-read page when opening a PDF again.
- Prompt for relocation when a PDF history item points to a missing absolute path.
- Use a beige reading theme inspired by notebook/library reading tools.

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
.\.venv\Scripts\pdf-notes-reader.exe
```

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
- Right-click a PDF page for `Add note`, `Fit width`, `Fit height`, `Continuous scroll`, and `Single page`.
- Click an item in the left Contents panel to jump to that PDF outline page.

Page rendering uses a 2x internal render scale, so the PDF is rasterized at higher resolution than the on-screen logical page size. Note anchors still use normalized coordinates on the visible page, so zoom and render precision changes do not shift note positions. In continuous mode, the reader keeps geometry for every page so the scrollbar range matches the whole PDF, but it only creates widgets for the current page window and a few merged spacer runs. It rasterizes only the current page plus nearby buffered pages, then refreshes that window as you scroll or jump. Zoom and fit commands prioritize the current reading page to reduce interaction lag.

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

Formula content is parsed and rendered into styled inline or block formula elements in the preview. It keeps the original LaTeX-style text in storage, so notes remain portable.

The local formula renderer supports common LaTeX-style commands used in notes, including Greek symbols such as `\beta`, superscripts/subscripts such as `$x_i^2$`, fractions such as `$\frac{1}{2}$`, roots such as `$\sqrt{x}$`, and common math operators such as `\times`, `\leq`, `\sum`, and arrows.

The right note sidebar has a `Notes folder` button and an `Export MD` button. `Notes folder` selects where standalone `.md` files are written. `Save` updates the JSON anchor store. `Export MD` first saves the current editor text to the JSON anchor store, then writes a Markdown copy using this default filename pattern:

```text
YYYYMMDD-HHMMSS-<pdf-name>-<chapter-name-or-page-number>-<number>.md
```

`<number>` is the note's order on that PDF page. Chapter names come from the PDF outline when available; otherwise the filename uses `page-<page_number>`. Characters that are invalid in Windows filenames are replaced with `_`.

## Data Storage

Notes and PDF-related metadata are saved outside the original PDF. The app never writes notes back into the PDF file.

Default storage locations:

- Windows: `%APPDATA%\PDFNotesReader\notes\`
- Linux: `$XDG_DATA_HOME/PDFNotesReader/notes/` or `~/.local/share/PDFNotesReader/notes/`
- Other systems: `~/.PDFNotesReader\notes\`

The default Markdown export folder is:

- Windows: `%APPDATA%\PDFNotesReader\markdown_notes\`
- Linux: `$XDG_DATA_HOME/PDFNotesReader/markdown_notes/` or `~/.local/share/PDFNotesReader/markdown_notes/`
- Other systems: `~/.PDFNotesReader\markdown_notes\`

To store note files inside this project while developing, set `PDF_NOTES_READER_DATA_DIR` before launching the app:

```powershell
$env:PDF_NOTES_READER_DATA_DIR = "$PWD\.local-data"
.\.venv\Scripts\python.exe -m pdf_notes_reader.main
```

With that setting, note files are written under:

```text
.\.local-data\notes\<pdf_key>.json
```

Markdown exports are written under this folder unless changed from the right sidebar:

```text
.\.local-data\markdown_notes\
```

The PDF history file is written under:

```text
.\.local-data\pdf_history.json
```

The project `.gitignore` ignores `.local-data/`, so private local notes are not picked up by Git by default.

### PDF Key And File Naming

Each PDF gets a stable key derived from its canonical file path:

```text
pdf_key = first 24 characters of sha256(normcase(resolved_pdf_path))
```

The note JSON file path is:

```text
<data_dir>\notes\<pdf_key>.json
```

For example, if `PDF_NOTES_READER_DATA_DIR=F:\...\PDFReading\.local-data`, a PDF with key `abc123...` stores notes at:

```text
F:\...\PDFReading\.local-data\notes\abc123....json
```

### JSON Contents

Each PDF has one JSON file. The file stores the PDF key, the PDF path recorded when notes were saved, the schema version, and all note anchors/content:

```json
{
  "pdf_key": "24-character-path-hash",
  "pdf_path": "F:\\path\\to\\example.pdf",
  "schema_version": 1,
  "notes": [
    {
      "id": "note-uuid",
      "pdf_key": "24-character-path-hash",
      "page_index": 0,
      "x_norm": 0.5,
      "y_norm": 0.5,
      "markdown": "# Note",
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

Field meanings:

- `pdf_key`: stable path-derived identifier for the PDF.
- `pdf_path`: PDF path stored for reference; the app uses `pdf_key` to load the matching note file.
- `schema_version`: note file format version.
- `notes[].page_index`: zero-based PDF page index.
- `notes[].x_norm` and `notes[].y_norm`: normalized anchor coordinates from `0.0` to `1.0`, relative to the rendered PDF page.
- `notes[].markdown`: raw Markdown note text.
- `created_at` and `updated_at`: UTC ISO timestamps.

Saves are written through a temporary sibling file named `<pdf_key>.tmp`, then atomically replaced as `<pdf_key>.json`.

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
      "updated_at": "..."
    }
  ]
}
```

When opening a PDF from history:

- If `path` exists, the app opens it and jumps to `last_page_index`.
- In continuous scroll mode, the current page is updated from the scroll position and saved when returning Home or closing the window.
- On app startup, the most recent existing PDF is reopened at its saved page; opening an existing PDF from Home history also restores its saved page.
- If `path` no longer exists, the app asks whether to relocate the PDF.
- If relocated, the history entry keeps the same `pdf_key`, updates the absolute path, and restores the last-read page.

## Tests

Run the full test suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```
