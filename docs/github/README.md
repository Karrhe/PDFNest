# GitHub report material for PDFNest 0.3.0

Nothing here has been published. These files are ready to paste into GitHub.

| File | Use |
|---|---|
| [`RELEASE_NOTES_0.3.0.md`](RELEASE_NOTES_0.3.0.md) | Body of the GitHub release `v0.3.0`. |
| [`../../CHANGELOG.md`](../../CHANGELOG.md) | Repository changelog. |
| [`issues/001-toc-save-corrupts-pdf.md`](issues/001-toc-save-corrupts-pdf.md) | Bug: contents save corrupts PDFs (fixed). |
| [`issues/002-corrupt-data-files-lose-notes.md`](issues/002-corrupt-data-files-lose-notes.md) | Bug: corrupt data files crash or overwrite notes (fixed). |
| [`issues/003-pdf-types-fail-to-load.md`](issues/003-pdf-types-fail-to-load.md) | Bug: encrypted/rotated/damaged/huge PDFs (fixed). |
| [`issues/004-markdown-math-rendering.md`](issues/004-markdown-math-rendering.md) | Bug + enhancement: Markdown/LaTeX preview (fixed). |
| [`issues/005-search.md`](issues/005-search.md) | Enhancement: search (implemented). |
| [`issues/006-migration-export-backup.md`](issues/006-migration-export-backup.md) | Bug: migration, data folder, export; backup (fixed). |
| [`issues/101-open-issues.md`](issues/101-open-issues.md) | Tracking issue for what remains open. |

Each issue file starts with a small front-matter block (title, labels, status, issue-register IDs). Paste the
title into the GitHub title field and the rest as the body. For already-fixed issues, open and immediately
close them with a reference to the release, so the history stays searchable.

Example with the GitHub CLI (run it yourself after reviewing):

```powershell
gh release create v0.3.0 --title "PDFNest 0.3.0" --notes-file docs/github/RELEASE_NOTES_0.3.0.md
```
