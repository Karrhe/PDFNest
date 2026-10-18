# PDFNest issue register

Status as of **0.3.0** (2026-10). Each fixed issue lists the test that guards against regressions.
Audit details: [`docs/audit/`](audit/). Markdown support: [`docs/markdown-compat.md`](markdown-compat.md).

## Fixed in 0.3.0

### PDF modification (contents / TOC saving)

| ID | Issue | Cause | Fix | Regression test |
|---|---|---|---|---|
| I-01 | **"Save contents to PDF" damaged some PDFs so that other readers could not open them.** | `set_toc()` + `saveIncr()` appended an incremental update to the open original. PDFs with bytes before `%PDF-` (UTF-8 BOM, blank lines, HTTP headers left by download tools) got xref offsets that don't match, and qpdf reports "file is damaged … invalid xref entry". | `pdf/outline_writer.save_toc_safely`: full rewrite to a temp file, independent re-open check, pristine `.pdfnest.bak` backup, atomic replace. | `test_outline_writer.py::test_legacy_incremental_save_damages_prefixed_pdf`, `test_safe_save_produces_file_strict_readers_accept` |
| I-02 | After the first damaging save, the next save failed: "Can't do incremental writes on a repaired file". | MuPDF had to repair the damaged file on open. | Full saves only. | `test_repeated_saves_keep_pristine_backup_and_stay_valid` |
| I-03 | No backup and no way back after modifying a PDF. | — | `.pdfnest.bak` of the original from before the first save, plus Contents ⋯ → **Restore original PDF**. | `test_repeated_saves_keep_pristine_backup_and_stay_valid` |
| I-04 | Signed, permission-restricted or XFA PDFs could be rewritten. | No pre-flight checks. | Refused with a clear message; the file is untouched. | `test_unsafe_documents_are_refused_and_left_untouched`, `test_outline.py::test_outline_save_refuses_signed_pdf_without_touching_it` |
| I-05 | Invalid contents (level jumps, pages out of range, empty titles) reached MuPDF. | No checks. | `normalize_toc` checks them first. | `test_invalid_toc_is_rejected` |

### Data integrity

| ID | Issue | Cause | Fix | Regression test |
|---|---|---|---|---|
| I-06 | A corrupt `notes.json` crashed opening the PDF. | Uncaught `JSONDecodeError`. | Unreadable files are moved to `*.corrupt-<time>.json`, and a non-blocking warning lists them. | `test_data_integrity.py::test_corrupt_notes_file_is_quarantined_not_overwritten` |
| I-07 | **A corrupt `notebooks/index.json` made notes appear empty, and the next save overwrote them.** | An index that failed to parse was read as `{}`, with no rebuild. | Rebuild from `manifest.json`; a stale index falls back to a manifest scan. | `test_corrupt_notebook_index_still_finds_existing_notes`, `test_stale_index_without_entry_still_finds_notes` |
| I-08 | A corrupt `recentnotes.json` / `user_config.json` crashed startup. A corrupt `library.json` silently reset all folders. | Uncaught errors / silent reset. | Quarantine and warn, then continue with defaults. | `test_corrupt_history_…`, `test_corrupt_settings_…`, `test_corrupt_library_…` |
| I-09 | Every note save reset `manifest.json` page count to 0 and overwrote the last-read page in `recentfile.json`. | `save_notes` rewrote metadata owned by history. | Preserved. | `test_note_save_keeps_manifest_page_count_and_recent_page` |
| I-10 | Writes used a fixed `.tmp` name and no `fsync`. Library and settings were written directly. | — | `_atomic_write_json`: unique temp file, `fsync`, `os.replace`, cleanup on failure. Used everywhere. | `test_failed_replace_keeps_previous_file_and_no_temp_leftovers`, `test_writers_use_unique_temp_files` |

### Loading and rendering

| ID | Issue | Cause | Fix | Regression test |
|---|---|---|---|---|
| I-11 | **Password-protected PDFs could not be used; opening one crashed while saving history.** | No password prompt. `_ensure_cover` re-opened the file without the password and its error was uncaught. | Password prompt (3 attempts), the password is kept per tab, and no cover for locked files. | `test_pdf_loading.py::test_password_prompt_unlocks_encrypted_pdf` and two related tests |
| I-12 | **Text selection, highlights and underlines were misplaced on rotated pages.** | MuPDF word boxes are in unrotated space. | Mapped through `page.rotation_matrix`. | `test_word_rects_line_up_with_rendered_text_on_rotated_pages[0/90/180/270]` |
| I-13 | Scrolling re-rasterized every page in the window: 6.6 rasterizations per page passed. | No pixmap cache; widgets are rebuilt on every window move. | `PageRenderCache` (LRU, 80 MP budget): 0.8 per page, scrolling 33% faster. | `test_scrolling_the_reader_does_not_rerasterize_rendered_pages`, `test_cache_*` |
| I-14 | Very large pages (posters, maps) could exhaust memory. | No pixel limit at 2× precision. | Per-page limit of 16 MP. | `test_huge_page_is_rendered_under_pixel_limit` |
| I-15 | One page that failed to render broke the visible window. A page with no readable size aborted the open. | No per-page error handling. | Error placeholder for that page; neighboring size used. | `test_broken_page_shows_placeholder_and_others_render`, `test_page_sizes_survive_a_broken_page` |
| I-16 | Raw MuPDF errors for empty or non-PDF files; damaged files repaired silently. | — | Clear messages, and a status-bar note for repaired files. | `test_unreadable_files_show_clear_error`, `test_repaired_pdf_opens_with_warning` |
| I-17 | Chapter lookup re-read the whole outline for every note (O(notes × outline)). | `get_toc()` on each call. | Cached `ChapterIndex`, O(log n), identical results. | `test_services.py::test_chapter_index_matches_original_linear_scan` |

### Markdown and LaTeX preview

| ID | Issue | Cause | Fix | Regression test |
|---|---|---|---|---|
| I-18 | `\frac` never displayed as a stacked fraction. | CSS `inline-flex`, which Qt rich text doesn't support. | Nested tables in display math, `a⁄b` inline. | `test_markdown_compat.py` (`frac-*`) |
| I-19 | Dollar amounts ("$5 and $10") became math. | Greedy `$…$` regex. | Pandoc-style delimiter rules; `\$` escapes. | `prices`, `escaped-dollar` |
| I-20 | Only ~55 symbols. Nested braces, `\sqrt[n]`, `\mathbb`, accents, matrices, cases, aligned and limits were unsupported. | Single-level regexes. | Brace-aware parser (`latex.py`) with 228 symbols, 36 function names and environments. Unknown commands stay visible. | 66-case compatibility matrix |
| I-21 | No strikethrough, task lists, footnotes, definition lists or abbreviations; 2-space nested lists flattened; `~~~` code was converted. | Limited extensions; Python-Markdown's 4-space nesting rule. | `extra` extension, strikethrough, task lists, indentation normalization, `~~~` protection. | `strike`, `tasks`, `nested-2`, `fence-tilde`, … |
| I-22 | `LATEX_SYMBOLS` was defined twice; the first copy was dead code. | — | Removed. | — |

### Search

| ID | Issue | Fix | Regression test |
|---|---|---|---|
| I-23 | No way to search the text of the open PDF. | Ctrl+F find bar, F3/Shift+F3, match case, whole words, incremental, overlay highlights. | `test_search.py` |
| I-24 | Notes could not be searched; Home search matched titles only. | Note filter in the sidebar; Home search matches note content with match counts. | `test_note_panel_filter`, `test_home_search_finds_notebooks_by_note_content` |

### Migration, export and backup

| ID | Issue | Fix | Regression test |
|---|---|---|---|
| I-25 | Migration silently dropped corrupt legacy notes and notes without `pdf_path`; corrupt legacy history crashed startup. | Reported; path-less notes migrated by key; legacy files never modified. | `test_migration_export.py` |
| I-26 | When the configured data folder disappeared, PDFNest silently started an empty library. | Falls back to the local store and tells the user once. | `test_missing_configured_folder_falls_back_to_local_store_once` |
| I-27 | Export errors (read-only folder, missing drive) escaped from the Qt slot. | One warning per export action; notes unchanged. | `test_export_failure_shows_one_warning_and_keeps_notes` |
| I-28 | No full backup (Markdown export misses anchors, highlights, bookmarks, library, settings). | Settings → Storage → **Back up all data...** (verified zip). | `test_backup_*`, `test_settings_backup_button` |

### Development and test infrastructure

| ID | Issue | Fix |
|---|---|---|
| I-29 | `main.py` was 5,400 lines holding everything. | Split into `ui/`, `pdf/`, `services/`, `markdown_render.py` and `latex.py`; `main.py` is a compatibility shim. |
| I-30 | Tests leaked `PDF_NOTES_READER_DATA_DIR` between tests, one theme test depended on test order (and could read the developer's real theme), and `save_settings` wrote the real `.local-data/storage_location.json`. | Per-test data folder and pointer isolation (`conftest.py`, `gui_helpers.py`). |
| I-31 | One 2,400-line test class; no problem-PDF fixtures. | Tests split by area; `tests/pdf_factory.py` builds encrypted, repaired, object-stream, rotated/cropped, scanned, CJK, poster, signed-like, empty and non-PDF files. |
| I-32 | `.venv` pointed at a removed Python 3.10. | Recreated on Python 3.14 (environment only). |
| I-33 | The README said PDFNest never writes to the PDF, but "Save contents to PDF" does. | README corrected. |

## Open issues

| ID | Issue | Workaround / plan |
|---|---|---|
| O-01 | Highlights and underlines **created on rotated pages before 0.3.0** keep their old (wrong) positions. | Delete and re-create them. A one-off converter would need each page's rotation at creation time, which wasn't stored. |
| O-02 | Opening a **moved/renamed PDF via Open…** starts an empty notebook (the key is path-based). | Open it from Home and choose *Relocate*. Plan: content fingerprint in `manifest.json` to offer re-linking. |
| O-03 | Rendering and search run on the UI thread (sliced). Very heavy pages can still pause briefly. | Plan: worker thread with its own `fitz.Document`. |
| O-04 | Page widgets are rebuilt when the visible window moves (pixmaps are cached, so it's cheap). | Reusing widgets needs care with the Fit/scroll regression rules. |
| O-05 | Scanned PDFs without a text layer can't be searched or selected. | OCR (`get_textpage_ocr` + Tesseract) isn't bundled. |
| O-06 | Search doesn't match across hyphenated line breaks. | Search the unhyphenated form. |
| O-07 | Bare URLs aren't auto-linked; relative image paths in notes aren't resolved. | Use `<https://…>` / `[text](url)` and absolute image paths. |
| O-08 | Inline-math fractions show as `a⁄b` (Qt rich text has no inline-block). | Use `$$…$$` for stacked fractions. |
| By design | Signed, permission-restricted and XFA PDFs can't receive saved contents. | Keep contents as PDFNest bookmarks instead. |
