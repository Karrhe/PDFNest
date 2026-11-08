"""Compatibility entry point.

``pdf_notes_reader.main`` used to hold the whole application. It now re-exports the public names
from their modules so ``python -m pdf_notes_reader.main``, the console scripts and the PyInstaller
build keep working.
"""

from __future__ import annotations

from pdf_notes_reader.app import main
from pdf_notes_reader.markdown_render import latex_to_html, render_markdown_preview
from pdf_notes_reader.ui.canvas import PdfCanvas
from pdf_notes_reader.ui.history_panel import HistoryPanel
from pdf_notes_reader.ui.main_window import MainWindow, PdfTabState
from pdf_notes_reader.ui.note_panel import NotePanel
from pdf_notes_reader.ui.outline_panel import OutlinePanel
from pdf_notes_reader.ui.settings_dialog import SettingsDialog

__all__ = [
    "HistoryPanel",
    "MainWindow",
    "NotePanel",
    "OutlinePanel",
    "PdfCanvas",
    "PdfTabState",
    "SettingsDialog",
    "latex_to_html",
    "main",
    "render_markdown_preview",
]


if __name__ == "__main__":
    raise SystemExit(main())
