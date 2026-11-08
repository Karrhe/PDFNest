from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "src"))
sys.path.insert(0, str(TESTS_DIR))

GUI_MODULES = {
    "test_annotation_summary",
    "test_annotations",
    "test_library_history",
    "test_library_import",
    "test_markdown",
    "test_navigation_fit",
    "test_notes_panel_export",
    "test_obsidian",
    "test_url_links",
    "test_outline",
    "test_pdf_loading",
    "test_platform_macos",
    "test_reader_render",
    "test_render_workers",
    "test_search",
    "test_settings_theme",
}


def pytest_collection_modifyitems(config, items) -> None:
    for item in items:
        if item.module.__name__ in GUI_MODULES:
            item.add_marker(pytest.mark.gui)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Every test gets its own data dir and storage pointer; nothing touches the real project data."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("PDF_NOTES_READER_DATA_DIR", str(data_dir))
    # Render in-process by default; tests/test_render_workers.py exercises the worker processes.
    monkeypatch.setenv("PDFNEST_RENDER_WORKERS", "0")
    monkeypatch.setattr(
        "pdf_notes_reader.notes.storage_pointer_path",
        lambda: tmp_path / "pointer" / "storage_location.json",
    )
    # Never touch the real Windows registry (pdfnest:// link handler) from tests.
    monkeypatch.setattr("pdf_notes_reader.ui.main_window.set_pdfnest_links_registered", lambda enabled: None)
    return data_dir


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    from pdf_notes_reader.main import MainWindow

    created = MainWindow()
    yield created
    created.close()
