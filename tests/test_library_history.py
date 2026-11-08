from gui_helpers import GuiTestCase  # noqa: I001 - sets sys.path and offscreen Qt first

import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QComboBox, QPushButton, QSplitter, QWidget
from PySide6.QtWidgets import QMessageBox
from pdf_notes_reader.history import PdfHistoryEntry, load_history, save_history
from pdf_notes_reader.library import UNFILED_FOLDER_ID, load_library
from pdf_notes_reader.main import MainWindow
from pdf_notes_reader.notes import default_data_dir
from pdf_notes_reader.notes import load_notes
from pdf_notes_reader.notes import pdf_key_for_path
from pdf_notes_reader.settings import load_settings


class LibraryHistoryTest(GuiTestCase):
    def test_home_notebooks_uses_virtual_folders_without_moving_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(data_dir)
            pdf_path = tmp_path / "source" / "a.pdf"
            pdf_path.parent.mkdir()
            self._create_sample_pdf(pdf_path, page_count=2)

            window = MainWindow()
            try:
                window.show()
                window.load_pdf(pdf_path)
                window.show_home()
                self.assertTrue(window.history_panel.recent_button.isChecked())
                self.assertFalse(window.history_panel.recent_button.icon().isNull())
                self.assertFalse(window.history_panel.notebooks_button.icon().isNull())

                window.history_panel.notebooks_button.click()
                self.assertEqual(window.history_panel.home_mode, "notebooks")
                with patch("pdf_notes_reader.ui.main_window.QInputDialog.getText", return_value=("alpha", True)):
                    window.history_panel._create_virtual_folder()
                self.app.processEvents()
                leaked_rows = [
                    widget
                    for widget in QApplication.topLevelWidgets()
                    if widget.isVisible() and widget.objectName() in {"LibraryRow", "LibraryRowMissing", "LibraryListHeader"}
                ]
                self.assertEqual(leaked_rows, [])

                library = load_library(data_dir)
                folder = next(item for item in library.folders if item.name == "alpha")
                window.history_panel._assign_entry_folder(pdf_key_for_path(pdf_path), folder.id)
                library = load_library(data_dir)

                self.assertEqual(library.assignments[pdf_key_for_path(pdf_path)], folder.id)
                self.assertTrue(pdf_path.exists())
                self.assertEqual(window.history_entries[0].path, str(pdf_path.resolve(strict=False)))
            finally:
                window.close()

    def test_home_notebooks_nested_folders_actions_and_icon_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(data_dir)
            long_name = "An Introduction to Econophysics Correlations and Complexity in Finance Very Long Planned Name.pdf"
            pdf_path = tmp_path / long_name
            self._create_sample_pdf(pdf_path, page_count=2)

            window = MainWindow()
            try:
                window.show()
                window.show_home()
                window.history_panel.notebooks_button.click()
                self.assertFalse(window.history_panel.new_folder_button.icon().isNull())
                self.assertFalse(window.history_panel.new_notebook_button.icon().isNull())

                with patch("pdf_notes_reader.ui.main_window.QInputDialog.getText", return_value=("Physics", True)):
                    window.history_panel._create_virtual_folder()
                library = load_library(data_dir)
                parent = next(folder for folder in library.folders if folder.name == "Physics")
                with patch("pdf_notes_reader.ui.main_window.QInputDialog.getText", return_value=("String_Theory", True)):
                    window.history_panel._create_virtual_folder(parent_id=parent.id)
                library = load_library(data_dir)
                child = next(folder for folder in library.folders if folder.name == "String_Theory")
                self.assertEqual(child.parent_id, parent.id)

                with patch.object(window, "_choose_pdf_file", return_value=str(pdf_path)):
                    window.add_planned_notebook(child.id)
                pdf_key = pdf_key_for_path(pdf_path)
                library = load_library(data_dir)
                self.assertEqual(library.assignments[pdf_key], child.id)
                self.assertTrue(pdf_path.exists())

                window.history_panel.notebooks_button.click()
                window.history_panel._select_folder(parent.id)
                self.assertIn(pdf_key, [entry.pdf_key for entry in window.history_panel._filtered_entries()])
                window.history_panel._select_folder(child.id)
                self.assertIn(pdf_key, [entry.pdf_key for entry in window.history_panel._filtered_entries()])
                self.assertTrue(window.history_panel.list_container.findChildren(QSplitter, "LibraryRowSplitter"))
                header_splitter = window.history_panel.list_container.findChild(QSplitter, "LibraryHeaderSplitter")
                row_splitters = window.history_panel.list_container.findChildren(QSplitter, "LibraryRowSplitter")
                self.assertIsNotNone(header_splitter)
                assert header_splitter is not None
                self.assertEqual(header_splitter.handleWidth(), 1)
                self.assertEqual(header_splitter.count(), 5)
                header_splitter.setSizes([120, 80, 80, 52, 120])
                window.history_panel._sync_list_column_sizes(header_splitter)
                self.app.processEvents()
                self.assertTrue(row_splitters)
                self.assertTrue(all(splitter.handleWidth() == 1 for splitter in row_splitters))
                header_sizes = header_splitter.sizes()
                self.assertTrue(
                    all(
                        len(splitter.sizes()) == len(header_sizes)
                        and all(abs(row_size - header_size) <= 1 for row_size, header_size in zip(splitter.sizes(), header_sizes))
                        for splitter in row_splitters
                    )
                )
                row_title = window.history_panel.list_container.findChild(QLabel, "HistoryRowTitle")
                self.assertIsNotNone(row_title)
                assert row_title is not None
                self.assertEqual(row_title.font().styleStrategy(), QFont.PreferAntialias)
                self.assertLessEqual(row_title.font().weight(), QFont.Medium)
                self.assertEqual(row_title.toolTip(), long_name)
                self.assertIn("…", row_title.text())
                row_buttons = [
                    button.text()
                    for row in window.history_panel.list_container.findChildren(QWidget, "LibraryRow")
                    for button in row.findChildren(QPushButton)
                ]
                self.assertNotIn("Open", row_buttons)
                self.assertNotIn("Archive", row_buttons)
                opened_keys: list[str] = []
                window.history_panel.open_requested.connect(opened_keys.append)
                row_widget = window.history_panel.list_container.findChild(QWidget, "LibraryRow")
                self.assertIsNotNone(row_widget)
                assert row_widget is not None
                QTest.mouseDClick(row_widget, Qt.LeftButton)
                self.assertEqual(opened_keys[-1], pdf_key)
                window.show_home()
                window.history_panel.notebooks_button.click()
                window.history_panel._select_folder(child.id)
                self.app.processEvents()
                window.history_panel.folder_tree.folder_drop_requested.emit(pdf_key, parent.id)
                self.assertEqual(load_library(data_dir).assignments[pdf_key], parent.id)
                window.history_panel._assign_entry_folder(pdf_key, child.id)
                root_item = window.history_panel.folder_tree.topLevelItem(0)
                self.assertIsNotNone(root_item)
                assert root_item is not None
                parent_item = next(
                    root_item.child(index)
                    for index in range(root_item.childCount())
                    if root_item.child(index).data(0, Qt.UserRole) == parent.id
                )
                target_pos = window.history_panel.folder_tree.viewport().mapToGlobal(
                    window.history_panel.folder_tree.visualItemRect(parent_item).center()
                )
                window.history_panel._start_entry_drag(row_widget, pdf_key)
                window.history_panel._finish_entry_drag(target_pos)
                self.assertEqual(load_library(data_dir).assignments[pdf_key], parent.id)
                window.history_panel._assign_entry_folder(pdf_key, child.id)
                self.assertEqual(
                    [combo for combo in window.history_panel.findChildren(QComboBox) if combo.objectName() == "LibraryFolderCombo"],
                    [],
                )

                before_icon = window.history_panel.view_toggle_button.icon().cacheKey()
                window.history_panel.view_toggle_button.click()
                after_icon = window.history_panel.view_toggle_button.icon().cacheKey()
                self.assertNotEqual(before_icon, after_icon)
                self.assertEqual(window.history_panel.content_stack.currentIndex(), 1)

                self.app.processEvents()
                title = window.history_panel.grid_container.findChild(QLabel, "LibraryGridTitle")
                cover = window.history_panel.grid_container.findChild(QLabel, "LibraryGridCover")
                self.assertIsNotNone(title)
                self.assertIsNotNone(cover)
                assert title is not None
                assert cover is not None
                self.assertIn("...", title.text())
                self.assertGreaterEqual(len(title.text()), 80)
                self.assertEqual(title.toolTip(), long_name)
                self.assertLess(cover.geometry().bottom(), title.geometry().top())

                window.rename_history_entry(pdf_key, "Custom display name")
                self.assertEqual(load_library(data_dir).aliases[pdf_key], "Custom display name")
                self.assertEqual(window.history_panel._entry_title(window.history_panel._entry_by_key[pdf_key]), "Custom display name")
                window.history_panel.sort_combo.setCurrentIndex(window.history_panel.sort_combo.findData("name"))
                self.assertEqual(window.history_panel.sort_mode, "name")

                window.archive_history_entry(pdf_key)
                library = load_library(data_dir)
                self.assertIn(pdf_key, library.archived)
                window.history_panel.notebooks_button.click()
                self.assertNotIn(pdf_key, [entry.pdf_key for entry in window.history_panel._filtered_entries()])
                window.history_panel.trash_button.click()
                self.assertIn(pdf_key, [entry.pdf_key for entry in window.history_panel._filtered_entries()])
                window.restore_history_entry(pdf_key)
                self.assertNotIn(pdf_key, load_library(data_dir).archived)

                window.history_panel._delete_folder(parent.id)
                library = load_library(data_dir)
                self.assertNotIn(parent.id, {folder.id for folder in library.folders})
                self.assertNotIn(child.id, {folder.id for folder in library.folders})
                self.assertNotIn(pdf_key, library.assignments)
                window.history_panel.notebooks_button.click()
                window.history_panel._select_folder(UNFILED_FOLDER_ID)
                self.assertIn(pdf_key, [entry.pdf_key for entry in window.history_panel._filtered_entries()])
                root = window.history_panel.folder_tree.topLevelItem(0)
                self.assertEqual(root.child(0).data(0, Qt.UserRole), UNFILED_FOLDER_ID)

                window.history_panel.selected_pdf_key = pdf_key
                window.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
                self.assertIn(pdf_key, load_library(data_dir).archived)
                window.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.ShiftModifier))
                self.assertIsNone(next((entry for entry in load_history(data_dir) if entry.pdf_key == pdf_key), None))
            finally:
                window.close()

    def test_reopens_pdf_at_last_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path, page_count=4)

            first_window = MainWindow()
            first_window.load_pdf(pdf_path)
            first_window.go_to_page(2)
            first_window.close()

            second_window = MainWindow()
            second_window.load_pdf(pdf_path)
            self.assertEqual(second_window.page_index, 2)
            second_window.close()

    def test_reopens_pdf_with_current_note_and_autosaved_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "notes-restore.pdf"
            self._create_sample_pdf(pdf_path, page_count=3)

            first_window = MainWindow()
            try:
                first_window.load_pdf(pdf_path)
                first_window.add_note(1, 0.25, 0.30)
                first_note_id = first_window.note_panel.current_note_id
                first_window.note_panel.editor.setPlainText("# First edited without manual save\nBody")

                first_window.add_note(1, 0.50, 0.30)
                second_note_id = first_window.note_panel.current_note_id
                first_window.note_panel.editor.setPlainText("# Second left open\nDraft")
            finally:
                first_window.close()

            notes = load_notes(pdf_key_for_path(pdf_path))
            note_text_by_id = {note.id: note.markdown for note in notes}
            self.assertEqual(note_text_by_id[first_note_id], "# First edited without manual save\nBody")
            self.assertEqual(note_text_by_id[second_note_id], "# Second left open\nDraft")
            self.assertEqual(load_history()[0].last_note_id, second_note_id)

            second_window = MainWindow()
            try:
                self.assertEqual(second_window.pdf_path, pdf_path)
                self.assertEqual(second_window.page_index, 1)
                self.assertEqual(second_window.note_panel.current_note_id, second_note_id)
                self.assertIn("# Second left open", second_window.note_panel.editor.toPlainText())
            finally:
                second_window.close()

    def test_reopens_window_size_and_pdf_view_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "view-state.pdf"
            self._create_sample_pdf(pdf_path, page_count=4)

            first_window = MainWindow()
            try:
                first_window.resize(1010, 710)
                first_window.show()
                self.app.processEvents()
                first_window.load_pdf(pdf_path)
                first_window.go_to_page(2)
                first_window.set_zoom_percent(175)
            finally:
                first_window.close()

            saved_settings = load_settings()
            self.assertAlmostEqual(load_history()[0].zoom, 1.75)
            second_window = MainWindow()
            try:
                self.assertEqual(second_window.width(), saved_settings["window_width"])
                self.assertEqual(second_window.height(), saved_settings["window_height"])
                self.assertEqual(second_window.page_index, 2)
                self.assertIsNone(second_window.fit_mode)
                self.assertAlmostEqual(second_window.zoom, 1.75)
                second_window.fit_page("height")
            finally:
                second_window.close()

            third_window = MainWindow()
            try:
                self.assertEqual(third_window.page_index, 2)
                self.assertEqual(third_window.fit_mode, "height")
            finally:
                third_window.close()

    def test_reopens_maximized_window_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            window = MainWindow()
            try:
                window.resize(960, 680)
                window.showMaximized()
                self.app.processEvents()
            finally:
                window.close()

            settings = load_settings()
            self.assertTrue(settings["window_maximized"])
            self.assertGreaterEqual(settings["window_width"], 640)
            self.assertGreaterEqual(settings["window_height"], 640)

            restored = MainWindow()
            try:
                self.assertTrue(restored.restore_window_maximized)
                self.assertTrue(bool(restored.windowState() & Qt.WindowMaximized))
            finally:
                restored.close()

    def test_scroll_position_is_saved_as_last_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path, page_count=5)

            first_window = MainWindow()
            try:
                first_window.resize(900, 600)
                first_window.show()
                self.app.processEvents()
                first_window.load_pdf(pdf_path)
                self.app.processEvents()
                first_window.go_to_page(2)
                self.app.processEvents()

                target_canvas = first_window.page_canvases[3]
                first_window.scroll_area.verticalScrollBar().setValue(target_canvas.y())
                self.app.processEvents()
                first_window._sync_current_page_from_scroll()
                self.assertEqual(first_window.page_index, 3)
            finally:
                first_window.close()

            second_window = MainWindow()
            second_window.load_pdf(pdf_path)
            self.assertEqual(second_window.page_index, 3)
            second_window.close()

    def test_history_open_restores_last_page_for_existing_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path, page_count=5)
            pdf_key = pdf_key_for_path(pdf_path)
            save_history(
                [
                    PdfHistoryEntry(
                        pdf_key=pdf_key,
                        path=str(pdf_path),
                        title="sample.pdf",
                        last_page_index=3,
                        page_count=5,
                        opened_at="2026-01-01T00:00:00+00:00",
                        updated_at="2026-01-01T00:00:00+00:00",
                    )
                ]
            )

            window = MainWindow()
            self.assertEqual(window.page_index, 3)
            window.close_document()
            window.page_index = 0
            window.show_home()
            window.open_history_entry(pdf_key)
            self.assertEqual(window.page_index, 3)
            window.close()

    def test_default_data_dir_is_project_local(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("pdf_notes_reader.notes._read_storage_pointer", return_value=None):
            expected = Path(__file__).resolve().parents[1] / "Note_PDFNest"
            self.assertEqual(default_data_dir(), expected)

    def test_missing_history_entry_can_be_relocated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            missing_path = tmp_path / "missing.pdf"
            relocated_path = tmp_path / "relocated.pdf"
            self._create_sample_pdf(relocated_path, page_count=2)

            old_key = pdf_key_for_path(missing_path)
            save_history(
                [
                    PdfHistoryEntry(
                        pdf_key=old_key,
                        path=str(missing_path),
                        title="missing.pdf",
                        last_page_index=1,
                        page_count=2,
                        opened_at="2026-01-01T00:00:00+00:00",
                        updated_at="2026-01-01T00:00:00+00:00",
                    )
                ]
            )

            window = MainWindow()
            with patch("pdf_notes_reader.ui.main_window.QMessageBox.question", return_value=QMessageBox.Yes):
                with patch.object(window, "_choose_pdf_file", return_value=str(relocated_path)):
                    window.open_history_entry(old_key)

            self.assertEqual(window.pdf_key, old_key)
            self.assertEqual(window.pdf_path, relocated_path)
            self.assertEqual(window.page_index, 1)
            self.assertEqual(window.history_entries[0].path, str(relocated_path.resolve(strict=False)))
            window.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
