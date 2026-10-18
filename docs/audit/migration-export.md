# Data migration and export evaluation

Scope: item #9. Code: `storage_migration.py`, `notes.py` (data folder resolution, writes), `services/export.py`,
`services/backup.py`, `ui/main_window.py` (export actions), `ui/settings_dialog.py` (backup button).

## Storage layout recap

```
<data dir>  = PDF_NOTES_READER_DATA_DIR
            | the folder in .local-data/storage_location.json (Settings → Storage)
            | <program folder>/Note_PDFNest
notebooks/<PDF name>/note/notes.json   notes, anchors, counters (+ bookmark mirror)
notebooks/<PDF name>/manifest.json     pdf_key → notebook folder; page count
notebooks/index.json                   pdf_key → folder cache (rebuildable from manifests)
bookmarks/<pdf_key>_bookmark.json      bookmarks (primary copy)
recentnotes.json / library.json / user_config.json / themes/*.json
```

## Migration (`.local-data` 0.1.x layout → `Note_PDFNest`)

| # | Check | Result before | Now |
|---|---|---|---|
| M1 | Idempotent: running twice changes nothing | OK. Each step skips targets that exist, and `migration_state.json` short-circuits. | OK, tested. |
| M2 | Crash halfway | OK. The state file is written last, so the next start resumes. Every step skips completed work. | OK, tested. |
| M3 | Corrupt legacy **notes** file | **Silently skipped**, then the migration was marked complete, so it was never retried. The notes were invisible and no one was told. | Reported in the "data problem" dialog. The legacy file is left untouched for manual recovery. |
| M4 | Legacy notes **without `pdf_path`** | **Silently skipped**, so those notes were never migrated. | Migrated anyway (notes are keyed by `pdf_key`, so they reappear when that PDF is opened). The path is taken from history when known. Reported. |
| M5 | Corrupt legacy **history** | `load_history` raised, so **startup crashed**. | Reported and skipped. The legacy file is not renamed: migration never modifies legacy data. |
| M6 | Legacy data cleanup | Legacy files are kept (non-destructive). | Unchanged, on purpose. Removing them is left to the user. |

## Data folder resolution

| # | Check | Result before | Now |
|---|---|---|---|
| D1 | Configured folder (`storage_location.json`) no longer exists: drive unplugged, folder moved or deleted | Used anyway. The app silently started a **new empty library** there (or failed to create it), which looks like all notes were lost. | Falls back to the local `Note_PDFNest` when it exists or when the configured drive is missing, and tells the user once. A missing folder on an existing drive with no local store is still created (fresh setup). |
| D2 | Tests and tools writing the real pointer file | `save_settings` wrote `.local-data/storage_location.json` of the real project during tests. | Tests isolate the pointer (`tests/conftest.py`, `tests/gui_helpers.py`). |

## Notes ↔ PDF identity

`pdf_key = sha256(normcase(resolved path))[:24]`. Moving or renaming a PDF therefore changes its key.

- Opening a moved PDF **from Home** offers "relocate" and keeps the old key and notes. This works and is tested.
- Opening a moved PDF **with Open…** creates a new, empty notebook. The old one stays on disk but isn't linked. **Open issue.** A content fingerprint (e.g. hash of the first pages + page count) stored in `manifest.json` would let PDFNest offer "notes found for this PDF at its old location". Until then: open moved PDFs from Home and choose *Relocate*.

## Markdown export

| # | Check | Result before | Now |
|---|---|---|---|
| E1 | Export folder is read-only, missing drive, or blocked by a file | `OSError` escaped from the Qt slot, so the export stopped halfway with no message (or a crash, depending on the PySide6 version). | `ExportError`. All failures of one export action are collected into **one** warning. Notes inside PDFNest are unchanged, and `exported_markdown_path` is only set on success. |
| E2 | File names: Windows-invalid characters, long names | OK. `safe_filename` replaces `<>:"/\|?*` and control characters, and shortens with a stable hash. | Moved to `services/export.py`, tested. |
| E3 | Name collisions | OK. `-2`, `-3`, … suffixes. | Tested. |
| E4 | Re-export | OK. Asks *Replace previous* or *Create new*. "Export all" replaces silently. | Unchanged. Note: after renaming a PDF, replace mode still writes to the folder named after the old PDF name. |
| E5 | Excerpt notes (text copied into another note) | Excluded from export by design. | Unchanged. |
| E6 | **Full backup** | **Missing.** Markdown export covers only note text, not anchors, highlights, bookmarks, library folders or settings. | Settings → Storage → **Back up all data...** writes one `.zip` (temp file + atomic rename), skips temp/lock files and regenerable covers, adds `backup_info.json`, and verifies that every JSON in the archive parses. |

## Tests

`tests/test_migration_export.py`:
- Migration: idempotency, crash/resume, corrupt legacy files, missing `pdf_path`, history.
- Data folder: fallback cases.
- Export: failure reporting.
- Backup: contents, verification, Settings button.

`tests/test_data_integrity.py` covers the corrupt-current-file cases.
