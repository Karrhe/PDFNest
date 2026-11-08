"""Adding books to the library: several files at once, whole folders, drag and drop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

import pdf_factory
from pdf_notes_reader.history import find_history_entry, load_history
from pdf_notes_reader.library import LibraryFolder, load_library, save_library
from pdf_notes_reader.notes import pdf_key_for_path
from pdf_notes_reader.services.library_import import expand_pdf_paths, pdfs_in_folder


def _books(root: Path) -> dict[str, Path]:
    paths = {
        "a": root / "a.pdf",
        "b": root / "B.PDF",
        "c": root / "sub" / "c.pdf",
        "hidden": root / ".trash" / "old.pdf",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf_factory.create_sample_pdf(path, page_count=2)
    (root / "notes.txt").write_text("not a pdf", encoding="utf-8")
    return paths


def test_pdfs_in_folder_finds_subfolders_and_skips_hidden(tmp_path) -> None:
    books = _books(tmp_path)
    assert pdfs_in_folder(tmp_path) == [books["a"], books["b"], books["c"]]


def test_expand_pdf_paths_mixes_files_and_folders_without_duplicates(tmp_path) -> None:
    books = _books(tmp_path)
    found = expand_pdf_paths([books["a"], tmp_path, tmp_path / "notes.txt", tmp_path / "missing.pdf"])
    assert found == [books["a"], books["b"], books["c"]]


def test_add_several_files_into_a_folder(tmp_path, window) -> None:
    books = _books(tmp_path / "books")
    library = load_library()
    folder = LibraryFolder.create("Physics")
    library.folders.append(folder)
    save_library(library)

    with patch.object(window, "_choose_pdf_files", return_value=[str(books["a"]), str(books["c"])]):
        window.add_planned_notebook(folder.id)

    history = load_history()
    library = load_library()
    for name in ("a", "c"):
        key = pdf_key_for_path(books[name])
        entry = find_history_entry(history, key)
        assert entry is not None and entry.page_count == 2
        assert library.assignments[key] == folder.id
    assert find_history_entry(history, pdf_key_for_path(books["b"])) is None
    assert "Added 2 PDFs" in window.statusBar().currentMessage()


def test_add_folder_adds_every_pdf_and_keeps_existing_books(tmp_path, window) -> None:
    books = _books(tmp_path / "books")
    window.load_pdf(books["a"])
    window.go_to_page(1)
    window.show_home()  # saves the reading position of a.pdf
    key_a = pdf_key_for_path(books["a"])
    assert find_history_entry(window.history_entries, key_a).last_page_index == 1

    with patch("pdf_notes_reader.ui.main_window.QFileDialog.getExistingDirectory", return_value=str(tmp_path / "books")):
        window.add_pdf_folder()

    history = load_history()
    assert {pdf_key_for_path(books[name]) for name in ("a", "b", "c")} <= {entry.pdf_key for entry in history}
    assert find_history_entry(history, pdf_key_for_path(books["hidden"])) is None
    assert find_history_entry(history, key_a).last_page_index == 1  # not reset by adding it again
    assert window.settings["last_pdf_dir"] == str(tmp_path / "books")
    assert "Added 2 PDFs" in window.statusBar().currentMessage()
    assert "1 was already there" in window.statusBar().currentMessage()


def test_add_button_menu_offers_files_and_folder(window) -> None:
    panel = window.history_panel
    actions = [action.text() for action in panel.new_notebook_button.menu().actions()]
    assert actions == ["Add PDF files…", "Add all PDFs in a folder…"]
    requested: list[str] = []
    panel.add_folder_requested.connect(requested.append)
    with patch("pdf_notes_reader.ui.main_window.QFileDialog.getExistingDirectory", return_value="") as picker:
        panel.add_folder_action.trigger()
    assert requested == [""]
    picker.assert_called_once()  # the main window opens the system folder picker


def test_dropping_pdfs_and_folders_on_the_library(tmp_path, window) -> None:
    books = _books(tmp_path / "books")
    window.resize(1000, 700)
    window.show()
    window.show_home()
    panel = window.history_panel

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(books["a"])), QUrl.fromLocalFile(str(tmp_path / "books" / "sub"))])
    event = QDropEvent(QPointF(panel.width() - 20, panel.height() - 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    panel.dropEvent(event)

    keys = {entry.pdf_key for entry in load_history()}
    assert pdf_key_for_path(books["a"]) in keys
    assert pdf_key_for_path(books["c"]) in keys
    assert pdf_key_for_path(books["b"]) not in keys


def test_drop_ignores_non_pdf_files(tmp_path, window) -> None:
    text = tmp_path / "notes.txt"
    text.write_text("x", encoding="utf-8")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(text))])
    received: list[list[str]] = []
    window.history_panel.pdfs_dropped.connect(lambda paths, _folder: received.append(paths))
    event = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.history_panel.dropEvent(event)
    assert received == []
