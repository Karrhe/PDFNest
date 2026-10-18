---
title: "Migration, data folder and export problems can hide or lose notes; no full backup"
labels: [bug, data-loss, storage]
status: fixed in 0.3.0
register: I-25, I-26, I-27, I-28
---

## Summary
- **Migration** from the old `.local-data` layout silently skipped corrupt legacy note files and files without
  a `pdf_path`, then marked the migration complete, so they were never retried and no one was told. A corrupt
  legacy history file crashed startup.
- **Configured data folder missing** (external drive unplugged, folder moved): PDFNest silently started a new,
  empty library there. That looks exactly like all notes were lost.
- **Markdown export** to a read-only or missing folder raised an unhandled `OSError` from the Qt slot. The
  export stopped halfway without a message.
- **No full backup:** Markdown export covers note text only, not anchors, highlights, bookmarks, library or settings.

## Fix
- Migration reports problems in the data-problem dialog and never modifies or deletes legacy files.
  Path-less notes are migrated by `pdf_key`.
- `default_data_dir` falls back to the local `Note_PDFNest` when the configured folder is gone and the local
  store exists (or the drive is missing), and tells the user once.
- Export failures are collected into one warning per action; notes inside PDFNest are unchanged.
- Settings → Storage → **Back up all data...**: one zip (temp file + atomic rename), skips temp/lock files and
  regenerable covers, includes `backup_info.json`, verified after writing.

Details: `docs/audit/migration-export.md`.

## Tests
`tests/test_migration_export.py` (12 tests).
