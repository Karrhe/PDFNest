"""Selecting several books on Home (Ctrl/Shift+click, Ctrl+A) and acting on all of them, and adding a
folder of PDFs with its folder structure (picked, dropped on Home, dropped on a library folder)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

import pdf_factory
from pdf_notes_reader.history import load_history
from pdf_notes_reader.library import LibraryFolder, ensure_folder_path, load_library, save_library
from pdf_notes_reader.notes import resolve_pdf_key


def _folder_paths(state) -> dict[str, str]:
    """folder id -> "A / B" path, for readable assertions."""
    by_id = {folder.id: folder for folder in state.folders}

    def path_of(folder) -> str:
        parts = [folder.name]
        while folder.parent_id in by_id:
            folder = by_id[folder.parent_id]
            parts.append(folder.name)
        return " / ".join(reversed(parts))

    return {folder.id: path_of(folder) for folder in state.folders if folder.id != "unfiled"}


def _home_with_books(tmp_path: Path, window, count: int = 4) -> list[str]:
    pdfs = [pdf_factory.create_sample_pdf(tmp_path / f"book{index}.pdf") for index in range(count)]
    window.add_pdfs_to_library(pdfs)
    window.resize(1100, 750)
    window.show()
    window.show_home()
    panel = window.history_panel
    panel.sort_combo.setCurrentIndex(panel.sort_combo.findData("name"))  # book0, book1, ... in order
    return [resolve_pdf_key(pdf) for pdf in pdfs]


def _row(panel, key: str):
    return panel._entry_widgets[key][0]  # the list row (the grid card is second)


def _click(panel, key: str, modifiers=Qt.NoModifier) -> None:
    row = _row(panel, key)
    QTest.mouseClick(row, Qt.LeftButton, modifiers, QPoint(row.width() - 5, row.height() // 2))


def _tree_item(panel, folder_id: str):
    tree = panel.folder_tree
    pending = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
    while pending:
        item = pending.pop()
        if str(item.data(0, Qt.UserRole) or "") == folder_id:
            return item
        pending.extend(item.child(index) for index in range(item.childCount()))
    raise AssertionError(f"folder {folder_id} is not in the tree")


def _choose_menu_action(path: list[str]):
    """A replacement for HistoryPanel._exec_menu that picks the action at ``path`` (submenu titles, then the action)."""

    def exec_(menu, *_args, **_kwargs):
        current = menu
        for text in path:
            action = next(action for action in current.actions() if action.text() == text)
            if action.menu() is not None and text != path[-1]:
                current = action.menu()
            else:
                return action
        return None

    return staticmethod(exec_)


# --- Selecting ---------------------------------------------------------------------------------------


def test_ctrl_shift_click_and_ctrl_a_select_several_books(tmp_path, window) -> None:
    keys = _home_with_books(tmp_path, window)
    panel = window.history_panel

    _click(panel, keys[0])
    assert panel.selected_pdf_keys == [keys[0]]
    _click(panel, keys[2], Qt.ControlModifier)
    assert panel.selected_pdf_keys == [keys[0], keys[2]]
    _click(panel, keys[0], Qt.ControlModifier)  # Ctrl+click again unselects
    assert panel.selected_pdf_keys == [keys[2]]

    _click(panel, keys[1])
    _click(panel, keys[3], Qt.ShiftModifier)
    assert panel.selected_pdf_keys == keys[1:4]
    assert all(_row(panel, key).property("selected") for key in keys[1:4])
    assert not _row(panel, keys[0]).property("selected")

    _click(panel, keys[2])  # a plain click selects just that book again
    assert panel.selected_pdf_keys == [keys[2]]
    assert panel.selected_pdf_key == keys[2]

    QTest.keyClick(panel, Qt.Key_A, Qt.ControlModifier)
    assert sorted(panel.selected_pdf_keys) == sorted(keys)

    panel.search_edit.setFocus()
    panel.search_edit.setText("abc")
    QTest.keyClick(panel.search_edit, Qt.Key_A, Qt.ControlModifier)
    assert panel.search_edit.selectedText() == "abc"  # Ctrl+A in the search field selects its text
    panel.search_edit.clear()


def test_selection_only_keeps_books_still_shown(tmp_path, window) -> None:
    keys = _home_with_books(tmp_path, window)
    panel = window.history_panel
    panel.select_all_entries()
    panel.search_edit.setText("book1")
    assert panel.selected_pdf_keys == [keys[1]]


# --- Removing, archiving -------------------------------------------------------------------------------


def test_removing_several_books_asks_once_with_the_count(tmp_path, window) -> None:
    keys = _home_with_books(tmp_path, window)
    panel = window.history_panel
    panel.set_selected_pdf_keys(keys[:3])

    with patch("pdf_notes_reader.ui.main_window.QMessageBox.question", return_value=QMessageBox.No) as question:
        panel.setFocus()
        QTest.keyClick(panel, Qt.Key_Delete, Qt.ShiftModifier)
    question.assert_called_once()
    assert "Remove 3 PDFs" in question.call_args.args[2]
    assert {entry.pdf_key for entry in load_history()} == set(keys)  # declined: nothing removed

    with patch("pdf_notes_reader.ui.main_window.QMessageBox.question", return_value=QMessageBox.Yes) as question:
        with patch.object(type(window.history_panel), "_exec_menu", _choose_menu_action(["Permanent delete 3 PDFs…"])):
            panel._show_entry_context_menu(keys[1], QPoint(0, 0))
    question.assert_called_once()
    assert {entry.pdf_key for entry in load_history()} == {keys[3]}
    assert panel.selected_pdf_keys == []
    assert "Removed 3 PDFs" in window.statusBar().currentMessage()


def test_removing_one_book_still_needs_no_confirmation(tmp_path, window) -> None:
    keys = _home_with_books(tmp_path, window, count=2)
    panel = window.history_panel
    _click(panel, keys[0])
    with patch("pdf_notes_reader.ui.main_window.QMessageBox.question") as question:
        QTest.keyClick(panel, Qt.Key_Delete, Qt.ShiftModifier)
    question.assert_not_called()
    assert {entry.pdf_key for entry in load_history()} == {keys[1]}


def test_delete_archives_every_selected_book_and_restore_brings_them_back(tmp_path, window) -> None:
    keys = _home_with_books(tmp_path, window)
    panel = window.history_panel
    panel.set_selected_pdf_keys(keys[1:3])
    panel.setFocus()
    QTest.keyClick(panel, Qt.Key_D)
    assert set(load_library().archived) == set(keys[1:3])
    assert "Moved 2 PDFs to archive" in window.statusBar().currentMessage()

    panel.trash_button.click()
    panel.select_all_entries()
    with patch.object(type(window.history_panel), "_exec_menu", _choose_menu_action(["Restore"])):
        panel._show_entry_context_menu(keys[1], QPoint(0, 0))
    assert load_library().archived == {}


# --- Moving into a folder ------------------------------------------------------------------------------


def test_move_to_folder_menu_files_every_selected_book(tmp_path, window) -> None:
    keys = _home_with_books(tmp_path, window)
    library = load_library()
    physics = LibraryFolder.create("Physics")
    library.folders.append(physics)
    save_library(library)
    window.show_home()
    panel = window.history_panel
    panel.set_selected_pdf_keys([keys[0], keys[3]])

    with patch.object(type(window.history_panel), "_exec_menu", _choose_menu_action(["Move to folder", "Physics"])):
        panel._show_entry_context_menu(keys[3], QPoint(0, 0))
    assignments = load_library().assignments
    assert assignments[keys[0]] == physics.id and assignments[keys[3]] == physics.id
    assert keys[1] not in assignments and keys[2] not in assignments

    with patch.object(type(window.history_panel), "_exec_menu", _choose_menu_action(["Move to folder", "Unfiled"])):
        panel._show_entry_context_menu(keys[0], QPoint(0, 0))
    assert load_library().assignments == {}


def test_right_click_outside_the_selection_acts_on_that_book_only(tmp_path, window) -> None:
    keys = _home_with_books(tmp_path, window)
    panel = window.history_panel
    panel.set_selected_pdf_keys(keys[:2])
    row = _row(panel, keys[3])
    QTest.mousePress(row, Qt.RightButton, Qt.NoModifier, QPoint(row.width() - 5, row.height() // 2))
    QTest.mouseRelease(row, Qt.RightButton, Qt.NoModifier, QPoint(row.width() - 5, row.height() // 2))
    assert panel.selected_pdf_keys == [keys[3]]


def test_dragging_several_selected_books_onto_a_folder_moves_them_all(tmp_path, window) -> None:
    keys = _home_with_books(tmp_path, window)
    library = load_library()
    physics = LibraryFolder.create("Physics")
    library.folders.append(physics)
    save_library(library)
    window.show_home()
    panel = window.history_panel
    panel.notebooks_button.click()
    _click(panel, keys[0])
    _click(panel, keys[2], Qt.ControlModifier)

    # Pressing on a selected book keeps the selection (to drag them all) ...
    row = _row(panel, keys[2])
    QTest.mousePress(row, Qt.LeftButton, Qt.NoModifier, QPoint(row.width() - 5, row.height() // 2))
    assert panel.selected_pdf_keys == [keys[0], keys[2]]
    started: list[list[str]] = []
    with patch.object(type(panel), "_start_entry_drag", lambda self, _source, key: started.append(
        self.selected_pdf_keys if key in self.selected_pdf_keys else [key]
    )):
        QTest.mouseMove(row, QPoint(row.width() - 5 - 40, row.height() // 2))
    assert started == [[keys[0], keys[2]]]
    QTest.mouseRelease(row, Qt.LeftButton, Qt.NoModifier, QPoint(row.width() - 45, row.height() // 2))
    assert panel.selected_pdf_keys == [keys[0], keys[2]]  # a drag does not collapse the selection

    # ... and dropping them on a folder files all of them.
    tree = panel.folder_tree
    mime = panel.entry_drag_mime(panel.selected_pdf_keys)
    point = QPointF(tree.visualItemRect(_tree_item(panel, physics.id)).center())
    tree.dropEvent(QDropEvent(point, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier))
    assignments = load_library().assignments
    assert assignments == {keys[0]: physics.id, keys[2]: physics.id}


def test_click_on_a_selected_book_without_dragging_selects_just_it(tmp_path, window) -> None:
    keys = _home_with_books(tmp_path, window)
    panel = window.history_panel
    panel.set_selected_pdf_keys(keys[:3])
    _click(panel, keys[1])
    assert panel.selected_pdf_keys == [keys[1]]


# --- Adding a folder keeps its structure -----------------------------------------------------------------


def _pdftext(root: Path) -> dict[str, Path]:
    books = {"A1": root / "PDFTEXT" / "A" / "A1.pdf", "B1": root / "PDFTEXT" / "B" / "B1.pdf"}
    for path in books.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf_factory.create_sample_pdf(path)
    return books


def _filed_paths(books: dict[str, Path]) -> dict[str, str]:
    library = load_library()
    paths = _folder_paths(library)
    return {name: paths.get(library.assignments.get(resolve_pdf_key(path), ""), "") for name, path in books.items()}


def test_adding_a_picked_folder_keeps_its_subfolders(tmp_path, window) -> None:
    books = _pdftext(tmp_path)
    with patch("pdf_notes_reader.ui.main_window.QFileDialog.getExistingDirectory", return_value=str(tmp_path / "PDFTEXT")):
        window.add_pdf_folder()
    assert _filed_paths(books) == {"A1": "PDFTEXT / A", "B1": "PDFTEXT / B"}
    assert sorted(_folder_paths(load_library()).values()) == ["PDFTEXT", "PDFTEXT / A", "PDFTEXT / B"]


def test_dropping_a_folder_on_home_keeps_its_subfolders_and_reuses_existing_ones(tmp_path, window) -> None:
    books = _pdftext(tmp_path)
    library = load_library()
    existing_a = LibraryFolder.create("a")  # same name, other case: reused, not duplicated
    existing_top = LibraryFolder.create("pdftext")
    existing_a.parent_id = existing_top.id
    library.folders.extend([existing_top, existing_a])
    save_library(library)
    window.resize(1000, 700)
    window.show()
    window.show_home()
    panel = window.history_panel

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "PDFTEXT"))])
    panel.dropEvent(QDropEvent(QPointF(panel.width() - 20, panel.height() - 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))

    assert _filed_paths(books) == {"A1": "pdftext / a", "B1": "pdftext / B"}
    assert load_library().assignments[resolve_pdf_key(books["A1"])] == existing_a.id
    assert sorted(_folder_paths(load_library()).values()) == ["pdftext", "pdftext / B", "pdftext / a"]


def test_dropping_a_folder_on_a_library_folder_builds_the_tree_inside_it(tmp_path, window) -> None:
    books = _pdftext(tmp_path)
    library = load_library()
    shelf = LibraryFolder.create("Shelf")
    library.folders.append(shelf)
    save_library(library)
    window.resize(1000, 700)
    window.show()
    window.show_home()
    panel = window.history_panel
    panel.notebooks_button.click()

    tree = panel.folder_tree
    target = tree.viewport().mapTo(panel, tree.visualItemRect(_tree_item(panel, shelf.id)).center())
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "PDFTEXT"))])
    panel.dropEvent(QDropEvent(QPointF(target), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert _filed_paths(books) == {"A1": "Shelf / PDFTEXT / A", "B1": "Shelf / PDFTEXT / B"}

    panel.dropEvent(QDropEvent(QPointF(target), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))  # again
    assert len(_folder_paths(load_library())) == 4  # Shelf, PDFTEXT, A, B: nothing duplicated


def test_both_computers_adding_the_same_folder_get_one_library_folder() -> None:
    mine = load_library()  # loaded before the other computer saved
    other = load_library()
    other_id = ensure_folder_path(other, "", ["PDFTEXT", "A"])
    save_library(other)
    my_id = ensure_folder_path(mine, "", ["PDFTEXT", "A"])
    save_library(mine)
    assert my_id == other_id
    assert sorted(_folder_paths(load_library()).values()) == ["PDFTEXT", "PDFTEXT / A"]


def test_a_renamed_imported_folder_does_not_clash_with_a_new_import() -> None:
    state = load_library()
    first = ensure_folder_path(state, "", ["PDFTEXT"])
    next(folder for folder in state.folders if folder.id == first).name = "Renamed"
    second = ensure_folder_path(state, "", ["PDFTEXT"])
    assert second != first
    assert len({folder.id for folder in state.folders}) == len(state.folders)
