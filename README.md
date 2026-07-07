# PDF Notes Reader

A Python desktop PDF reader with external anchored Markdown notes.

## Features

- Open and render local PDF files.
- Navigate pages and zoom in or out.
- Right-click anywhere on a PDF page to add an anchored note.
- Store note anchors as `page_index + x_norm + y_norm`, so markers stay aligned across zoom changes.
- Show note markers as colored dots on the page.
- Click a marker to edit or preview its Markdown note in the right sidebar.
- Save notes in external JSON files without modifying the original PDF.

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

## Data Storage

Notes and PDF-related metadata are saved outside the original PDF. The app never writes notes back into the PDF file.

Default storage locations:

- Windows: `%APPDATA%\PDFNotesReader\notes\`
- Linux: `$XDG_DATA_HOME/PDFNotesReader/notes/` or `~/.local/share/PDFNotesReader/notes/`
- Other systems: `~/.PDFNotesReader\notes\`

To store note files inside this project while developing, set `PDF_NOTES_READER_DATA_DIR` before launching the app:

```powershell
$env:PDF_NOTES_READER_DATA_DIR = "$PWD\.local-data"
.\.venv\Scripts\python.exe -m pdf_notes_reader.main
```

With that setting, note files are written under:

```text
.\.local-data\notes\<pdf_key>.json
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

## Tests

Run the full test suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```
