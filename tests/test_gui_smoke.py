import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fitz
from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QColor, QContextMenuEvent, QFocusEvent, QFont, QImage, QKeyEvent, QKeySequence, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QComboBox, QDialog, QPushButton, QSplitter, QTabBar, QToolBar, QToolButton, QWidget
from PySide6.QtWidgets import QMessageBox

from pdf_notes_reader.history import PdfHistoryEntry, load_history, save_history
from pdf_notes_reader.library import LibraryFolder, UNFILED_FOLDER_ID, load_library, save_library
from pdf_notes_reader.main import MainWindow, PdfCanvas, SettingsDialog
from pdf_notes_reader.main import render_markdown_preview
from pdf_notes_reader.notes import Note, default_data_dir
from pdf_notes_reader.notes import load_notes, load_notes_data
from pdf_notes_reader.notes import pdf_key_for_path
from pdf_notes_reader.settings import load_settings, load_theme_files, save_settings, themes_dir


class GuiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_load_pdf_render_and_persist_note_without_modifying_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path)
            original_mtime = pdf_path.stat().st_mtime_ns

            window = MainWindow()
            window.load_pdf(pdf_path)
            self.assertIsNotNone(window.document)
            self.assertGreater(window.canvas.width(), 0)
            self.assertGreater(window.canvas.height(), 0)
            self.assertEqual(window.canvas.render_device_pixel_ratio(), 2.0)

            window.add_note(0.5, 0.4)
            self.assertEqual(len(window.notes), 1)

            window.note_panel.editor.setPlainText("**updated**")
            window.save_current_note(window.note_panel.editor.toPlainText())

            notes = load_notes(window.pdf_key)
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0].page_index, 0)
            self.assertEqual(notes[0].x_norm, 0.5)
            self.assertEqual(notes[0].y_norm, 0.4)
            self.assertEqual(notes[0].markdown, "**updated**")
            self.assertEqual(pdf_path.stat().st_mtime_ns, original_mtime)
            window.close()

    def test_continuous_scroll_and_arrow_key_page_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path, page_count=3)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)

                self.assertTrue(window.continuous_scroll)
                self.assertEqual(sorted(window.page_canvases), [0, 1, 2])
                self.assertEqual(window.page_index, 0)

                before_scroll = window.scroll_area.verticalScrollBar().value()
                self._press_key(window, Qt.Key_Down)
                self.assertEqual(window.page_index, 0)
                self.assertGreaterEqual(window.scroll_area.verticalScrollBar().value(), before_scroll)

                self._press_key(window, Qt.Key_Right)
                self.assertEqual(window.page_index, 1)
                self.assertEqual(sorted(window.page_canvases), [0, 1, 2])

                self._press_key(window, Qt.Key_Right)
                self.assertEqual(window.page_index, 2)
                self.assertEqual(sorted(window.page_canvases), [0, 1, 2])

                self._press_key(window, Qt.Key_Up)
                self.assertEqual(window.page_index, 2)

                self._press_key(window, Qt.Key_Left)
                self.assertEqual(window.page_index, 1)

                window.add_note(1, 0.25, 0.75)
                notes = load_notes(window.pdf_key)
                self.assertEqual(len(notes), 1)
                self.assertEqual(notes[0].page_index, 1)
                self.assertEqual(notes[0].x_norm, 0.25)
                self.assertEqual(notes[0].y_norm, 0.75)
            finally:
                window.close()

    def test_arrow_keys_scroll_lines_and_horizontal_keys_turn_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "keyboard.pdf"
            self._create_sample_pdf(pdf_path, page_count=4)

            window = MainWindow()
            try:
                window.resize(900, 600)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()

                self._press_key(window, Qt.Key_Right)
                self.assertEqual(window.page_index, 1)
                expected_top = window._scroll_target_for_page(1, center=False)
                self.assertLessEqual(abs(window.scroll_area.verticalScrollBar().value() - expected_top), 2)

                before_page = window.page_index
                before_scroll = window.scroll_area.verticalScrollBar().value()
                self._press_key(window, Qt.Key_Down)
                self.assertEqual(window.page_index, before_page)
                self.assertGreaterEqual(window.scroll_area.verticalScrollBar().value(), before_scroll)

                window.set_reading_mode("single")
                self.assertFalse(window.continuous_scroll)
                before_page = window.page_index
                self._press_key(window, Qt.Key_Down)
                self.assertEqual(window.page_index, before_page)
                self._press_key(window, Qt.Key_Right)
                self.assertEqual(window.page_index, before_page + 1)
            finally:
                window.close()

    def test_browser_style_pdf_tabs_and_shortcuts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            first_pdf = tmp_path / "first.pdf"
            second_pdf = tmp_path / "second.pdf"
            self._create_sample_pdf(first_pdf, page_count=3)
            self._create_sample_pdf(second_pdf, page_count=2)

            window = MainWindow()
            try:
                window.load_pdf(first_pdf)
                window.go_to_page(1)
                window.add_note(1, 0.25, 0.75)
                first_note_id = window.note_panel.current_note_id
                window.note_panel.editor.setPlainText("# First tab note\nBody")
                window.save_current_note(window.note_panel.editor.toPlainText())
                window.load_pdf(second_pdf)
                window.add_note(0, 0.50, 0.50)
                second_note_id = window.note_panel.current_note_id

                self.assertEqual(window.document_tab_bar.count(), 3)
                self.assertEqual(set(window.pdf_tabs), {pdf_key_for_path(first_pdf), pdf_key_for_path(second_pdf)})
                self.assertEqual(window.pdf_path, second_pdf)
                self.assertEqual(window.document_title_combo.count(), 2)
                self.assertEqual(window.document_title_combo.currentText(), second_pdf.name)
                self.assertEqual(
                    [window.document_title_combo.itemData(index) for index in range(window.document_title_combo.count())],
                    [pdf_key_for_path(first_pdf), pdf_key_for_path(second_pdf)],
                )
                close_button = window.document_tab_bar.tabButton(1, QTabBar.RightSide)
                self.assertIsInstance(close_button, QToolButton)
                assert isinstance(close_button, QToolButton)
                self.assertFalse(close_button.icon().isNull())
                self.assertEqual(close_button.iconSize(), QSize(9, 9))
                self.assertEqual(close_button.size(), QSize(18, 18))

                window.switch_to_document_title_index(0)
                self.assertEqual(window.pdf_path, first_pdf)
                self.assertEqual(window.document_title_combo.currentText(), first_pdf.name)

                window.tab_switch_shortcuts[0].activated.emit()
                self.assertEqual(window.pdf_path, first_pdf)
                self.assertEqual(window.page_index, 1)
                self.assertEqual(window.note_panel.current_note_id, first_note_id)
                self.assertIn("# First tab note", window.note_panel.editor.toPlainText())

                window.tab_switch_shortcuts[1].activated.emit()
                self.assertEqual(window.pdf_path, second_pdf)
                self.assertEqual(window.note_panel.current_note_id, second_note_id)

                window.show_home()
                self.assertFalse(window.history_panel.settings_button.icon().isNull())
                self.assertEqual(window.history_panel.settings_button.text(), "")
                self.assertFalse(window.history_panel.list_mode_button.icon().isNull())
                self.assertFalse(window.history_panel.icon_mode_button.icon().isNull())
                window.history_panel.icon_mode_button.click()
                self.assertEqual(window.history_panel.content_stack.currentIndex(), 1)
                self.assertGreater(window.history_panel.grid_layout.count(), 0)
                window.show_reader()

                window.close_tab_shortcut.activated.emit()
                self.assertNotIn(pdf_key_for_path(second_pdf), window.pdf_tabs)
                self.assertEqual(window.document_tab_bar.count(), 2)
                self.assertEqual(window.pdf_path, first_pdf)
            finally:
                window.close()

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
                with patch("pdf_notes_reader.main.QInputDialog.getText", return_value=("alpha", True)):
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

                with patch("pdf_notes_reader.main.QInputDialog.getText", return_value=("Physics", True)):
                    window.history_panel._create_virtual_folder()
                library = load_library(data_dir)
                parent = next(folder for folder in library.folders if folder.name == "Physics")
                with patch("pdf_notes_reader.main.QInputDialog.getText", return_value=("String_Theory", True)):
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

    def test_markdown_preview_supports_math_code_and_quotes(self) -> None:
        html = render_markdown_preview(
            "> quoted\n\n"
            "Inline code `\\beta` and bare latex \\beta plus math $a^2+b^2=c^2$.\n\n"
            "```python\nprint('hello')\n```\n\n"
            "$$E = mc^2 + \\frac{1}{2}\\sqrt{x}$$\n\n"
            "| A | B |\n| - | - |\n| 1 | 2 |"
        )

        self.assertIn("<blockquote>", html)
        self.assertIn("<code>", html)
        code_html = render_markdown_preview("`\\beta`")
        self.assertIn("\\beta", code_html)
        self.assertNotIn("β", code_html)
        self.assertIn("β", html)
        self.assertNotIn("\\beta plus", html)
        self.assertIn("math-inline", html)
        self.assertIn("math-block", html)
        int_html = render_markdown_preview("$\\int_K f(x) dx$")
        self.assertIn("∫<sub>K</sub>", int_html)
        self.assertIn("<sup>2</sup>", html)
        self.assertIn("latex-frac", html)
        self.assertIn("latex-sqrt", html)
        self.assertIn("<table>", html)
        self.assertNotIn("<p><table class=\"math-block\"", html)
        self.assertIn("margin: 0 0 4px 0", html)
        self.assertIn("padding: 1px 6px", html)

    def test_pdf_canvas_tints_white_pages_beige(self) -> None:
        pixmap = QPixmap(40, 40)
        pixmap.fill(QColor("#ffffff"))
        canvas = PdfCanvas()
        canvas.set_page(pixmap, [])

        image = QImage(canvas.size(), QImage.Format_ARGB32)
        image.fill(QColor("#000000"))
        painter = QPainter(image)
        canvas.render(painter, QPoint(0, 0))
        painter.end()

        center = image.pixelColor(20, 20)
        self.assertNotEqual(center.name().lower(), "#ffffff")
        self.assertGreater(center.red(), center.blue())

    def test_pdf_canvas_context_menu_can_request_note_number_reset(self) -> None:
        pixmap = QPixmap(80, 80)
        pixmap.fill(QColor("#ffffff"))
        canvas = PdfCanvas()
        canvas.set_page(pixmap, [])
        emitted: list[bool] = []
        canvas.reset_note_counters_requested.connect(lambda: emitted.append(True))
        saw_reset_action: list[bool] = []

        class FakeMenu:
            def __init__(self, *_args):
                self._actions = []

            def addAction(self, action):
                self._actions.append(action)

            def addMenu(self, _label: str):
                return FakeMenu()

            def addSeparator(self) -> None:
                pass

            def exec(self, _pos: QPoint):
                for action in self._actions:
                    if action.text() == "Reset note numbering":
                        saw_reset_action.append(True)
                        return action
                return None

        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10), QPoint(10, 10))
        with patch("pdf_notes_reader.main.QMenu", FakeMenu):
            canvas.contextMenuEvent(event)

        self.assertEqual(saw_reset_action, [True])
        self.assertEqual(emitted, [True])

    def test_pdf_canvas_context_menu_can_append_selected_text_to_current_note(self) -> None:
        pixmap = QPixmap(80, 80)
        pixmap.fill(QColor("#ffffff"))
        canvas = PdfCanvas()
        canvas.set_page(pixmap, [])
        canvas._selected_text = "selected excerpt"
        canvas._selected_rects_norm = [[0.1, 0.1, 0.2, 0.2]]
        emitted: list[tuple[int, list, str]] = []
        canvas.append_selection_requested.connect(lambda page, rects, text: emitted.append((page, rects, text)))
        saw_append_action: list[bool] = []

        class FakeMenu:
            def __init__(self, *_args):
                self._actions = []

            def addAction(self, action):
                self._actions.append(action)

            def addMenu(self, _label: str):
                return FakeMenu()

            def addSeparator(self) -> None:
                pass

            def exec(self, _pos: QPoint):
                for action in self._actions:
                    if action.text() == "Add selected text to current note":
                        saw_append_action.append(True)
                        return action
                return None

        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10), QPoint(10, 10))
        with patch("pdf_notes_reader.main.QMenu", FakeMenu):
            canvas.contextMenuEvent(event)

        self.assertEqual(saw_append_action, [True])
        self.assertEqual(emitted, [(0, [[0.1, 0.1, 0.2, 0.2]], "selected excerpt")])
        self.assertEqual(canvas._selected_text, "")
        self.assertEqual(canvas._selected_rects_norm, [])

    def test_pdf_canvas_context_menu_can_change_excerpt_marker_style(self) -> None:
        pixmap = QPixmap(100, 100)
        pixmap.fill(QColor("#ffffff"))
        marker = Note.create(
            pdf_key="pdf",
            page_index=0,
            x_norm=0.25,
            y_norm=0.15,
            note_type="excerpt",
            rects_norm=[[0.1, 0.1, 0.4, 0.2]],
            linked_note_id="note-id",
        )
        canvas = PdfCanvas()
        canvas.set_page(pixmap, [marker])
        emitted: list[tuple[str, str]] = []
        canvas.note_style_requested.connect(lambda note_id, style: emitted.append((note_id, style)))

        class FakeMenu:
            def __init__(self, *_args):
                self._actions = []

            def addAction(self, action):
                self._actions.append(action)

            def addMenu(self, _label: str):
                return self

            def addSeparator(self) -> None:
                pass

            def exec(self, _pos: QPoint):
                return next((action for action in self._actions if action.text() == "Highlight"), None)

        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(20, 19), QPoint(20, 19))
        with patch("pdf_notes_reader.main.QMenu", FakeMenu):
            canvas.contextMenuEvent(event)

        self.assertEqual(emitted, [(marker.id, "highlight")])

    def test_pdf_canvas_context_menu_can_convert_highlight_to_underline(self) -> None:
        pixmap = QPixmap(100, 100)
        pixmap.fill(QColor("#ffffff"))
        annotation = Note.create(
            pdf_key="pdf",
            page_index=0,
            x_norm=0.25,
            y_norm=0.15,
            note_type="highlight",
            rects_norm=[[0.1, 0.1, 0.4, 0.2]],
        )
        canvas = PdfCanvas()
        canvas.set_page(pixmap, [annotation])
        emitted: list[tuple[str, str]] = []
        canvas.note_style_requested.connect(lambda note_id, style: emitted.append((note_id, style)))

        class FakeMenu:
            def __init__(self, *_args):
                self._actions = []

            def addAction(self, action):
                self._actions.append(action)

            def addMenu(self, _label: str):
                return self

            def addSeparator(self) -> None:
                pass

            def exec(self, _pos: QPoint):
                return next((action for action in self._actions if action.text() == "Underline"), None)

        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(20, 19), QPoint(20, 19))
        with patch("pdf_notes_reader.main.QMenu", FakeMenu):
            canvas.contextMenuEvent(event)

        self.assertEqual(emitted, [(annotation.id, "underline")])

    def test_highlight_multiply_blend_preserves_black_text(self) -> None:
        pixmap = QPixmap(100, 60)
        pixmap.fill(QColor("#ffffff"))
        source_painter = QPainter(pixmap)
        source_painter.fillRect(30, 20, 10, 20, QColor("#000000"))
        source_painter.end()
        annotation = Note.create(
            pdf_key="pdf",
            page_index=0,
            x_norm=0.5,
            y_norm=0.5,
            note_type="highlight",
            rects_norm=[[0.2, 0.2, 0.8, 0.8]],
            color="#fca5a5",
        )
        canvas = PdfCanvas()
        canvas.set_theme_colors({"pdf_tint": "#ffffff"})
        canvas.set_page(pixmap, [annotation])
        rendered = QImage(canvas.size(), QImage.Format_ARGB32)
        canvas.render(rendered)

        self.assertEqual(rendered.pixelColor(35, 30).name(), "#000000")
        self.assertNotEqual(rendered.pixelColor(25, 30).name(), "#ffffff")

    def test_pdf_canvas_context_menu_can_request_bookmark(self) -> None:
        pixmap = QPixmap(80, 80)
        pixmap.fill(QColor("#ffffff"))
        canvas = PdfCanvas(page_index=2)
        canvas.set_page(pixmap, [])
        emitted: list[int] = []
        canvas.bookmark_requested.connect(emitted.append)
        saw_bookmark_action: list[bool] = []

        class FakeMenu:
            def __init__(self, *_args):
                self._actions = []

            def addAction(self, action):
                self._actions.append(action)

            def addMenu(self, _label: str):
                return FakeMenu()

            def addSeparator(self) -> None:
                pass

            def exec(self, _pos: QPoint):
                for action in self._actions:
                    if action.text() == "Add bookmark":
                        saw_bookmark_action.append(True)
                        return action
                return None

        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10), QPoint(10, 10))
        with patch("pdf_notes_reader.main.QMenu", FakeMenu):
            canvas.contextMenuEvent(event)

        self.assertEqual(saw_bookmark_action, [True])
        self.assertEqual(emitted, [2])

    def test_pdf_canvas_context_menu_selection_annotation_clears_selection(self) -> None:
        pixmap = QPixmap(80, 80)
        pixmap.fill(QColor("#ffffff"))
        canvas = PdfCanvas(page_index=1)
        canvas.set_page(pixmap, [])
        canvas._selected_text = "selected excerpt"
        canvas._selected_rects_norm = [[0.1, 0.1, 0.2, 0.2]]
        emitted: list[tuple[int, str, list, str, str]] = []
        canvas.annotation_requested.connect(lambda page, kind, rects, text, color: emitted.append((page, kind, rects, text, color)))

        class FakeMenu:
            def __init__(self, *_args):
                self._actions = []

            def addAction(self, action):
                self._actions.append(action)

            def addMenu(self, _label: str):
                return self

            def addSeparator(self) -> None:
                pass

            def exec(self, _pos: QPoint):
                for action in self._actions:
                    if action.text() == "Yellow":
                        return action
                return None

        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10), QPoint(10, 10))
        with patch("pdf_notes_reader.main.QMenu", FakeMenu):
            canvas.contextMenuEvent(event)

        self.assertEqual(emitted, [(1, "highlight", [[0.1, 0.1, 0.2, 0.2]], "selected excerpt", "#fde047")])
        self.assertEqual(canvas._selected_text, "")
        self.assertEqual(canvas._selected_rects_norm, [])

    def test_pdf_canvas_context_menu_puts_highlight_and_underline_first(self) -> None:
        pixmap = QPixmap(80, 80)
        pixmap.fill(QColor("#ffffff"))
        canvas = PdfCanvas()
        canvas.set_page(pixmap, [])
        canvas._selected_text = "selected excerpt"
        canvas._selected_rects_norm = [[0.1, 0.1, 0.2, 0.2]]
        root_entries: list[str] = []

        class FakeMenu:
            def __init__(self, *_args, is_root: bool = True):
                self.is_root = is_root

            def addAction(self, action):
                if self.is_root:
                    root_entries.append(action.text())

            def addMenu(self, label: str):
                if self.is_root:
                    root_entries.append(label)
                return FakeMenu(is_root=False)

            def addSeparator(self) -> None:
                if self.is_root:
                    root_entries.append("---")

            def exec(self, _pos: QPoint):
                return None

        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10), QPoint(10, 10))
        with patch("pdf_notes_reader.main.QMenu", FakeMenu):
            canvas.contextMenuEvent(event)

        self.assertEqual(root_entries[:2], ["Highlight selection", "Underline selection"])

    def test_pdf_canvas_selects_and_copies_text(self) -> None:
        pixmap = QPixmap(200, 100)
        pixmap.fill(QColor("#ffffff"))
        canvas = PdfCanvas()
        canvas.set_page(
            pixmap,
            [],
            text_words=[
                {"rect": [0.1, 0.1, 0.3, 0.3], "text": "Hello", "block": 0, "line": 0, "word_no": 0},
                {"rect": [0.32, 0.1, 0.5, 0.3], "text": "PDF", "block": 0, "line": 0, "word_no": 1},
            ],
        )
        canvas._selection_start = QPoint(0, 0)
        canvas._selection_end = QPoint(140, 50)
        canvas._update_text_selection()
        canvas.copy_selected_text()

        self.assertEqual(QApplication.clipboard().text(), "Hello PDF")
        self.assertEqual(canvas._selected_text, "")
        self.assertEqual(canvas._selected_rects_norm, [])

    def test_pdf_canvas_selects_contiguous_lines_and_merges_rects(self) -> None:
        pixmap = QPixmap(300, 180)
        pixmap.fill(QColor("#ffffff"))
        canvas = PdfCanvas()
        canvas.set_page(
            pixmap,
            [],
            text_words=[
                {"rect": [0.1, 0.10, 0.2, 0.18], "text": "A1", "block": 0, "line": 0, "word_no": 0},
                {"rect": [0.22, 0.10, 0.4, 0.18], "text": "A2", "block": 0, "line": 0, "word_no": 1},
                {"rect": [0.1, 0.25, 0.2, 0.33], "text": "B1", "block": 0, "line": 1, "word_no": 0},
                {"rect": [0.22, 0.25, 0.4, 0.33], "text": "B2", "block": 0, "line": 1, "word_no": 1},
                {"rect": [0.1, 0.40, 0.2, 0.48], "text": "C1", "block": 0, "line": 2, "word_no": 0},
                {"rect": [0.22, 0.40, 0.4, 0.48], "text": "C2", "block": 0, "line": 2, "word_no": 1},
            ],
        )
        canvas._selection_start = QPoint(25, 20)
        canvas._selection_end = QPoint(65, 78)
        canvas._update_text_selection()

        self.assertEqual(canvas._selected_text, "A1 A2\nB1 B2\nC1")
        self.assertEqual(
            canvas._selected_rects_norm,
            [[0.1, 0.1, 0.4, 0.18], [0.1, 0.25, 0.4, 0.33], [0.1, 0.4, 0.2, 0.48]],
        )

    def test_pdf_canvas_selection_uses_linewise_boundaries(self) -> None:
        pixmap = QPixmap(400, 200)
        pixmap.fill(QColor("#ffffff"))
        canvas = PdfCanvas()
        canvas.set_page(
            pixmap,
            [],
            text_words=[
                {"rect": [0.10, 0.10, 0.175, 0.20], "text": "one", "block": 0, "line": 0, "word_no": 0},
                {"rect": [0.20, 0.10, 0.275, 0.20], "text": "two", "block": 0, "line": 0, "word_no": 1},
                {"rect": [0.30, 0.10, 0.400, 0.20], "text": "three", "block": 0, "line": 0, "word_no": 2},
                {"rect": [0.425, 0.10, 0.525, 0.20], "text": "four", "block": 0, "line": 0, "word_no": 3},
                {"rect": [0.10, 0.30, 0.1875, 0.40], "text": "five", "block": 0, "line": 1, "word_no": 0},
                {"rect": [0.2125, 0.30, 0.2875, 0.40], "text": "six", "block": 0, "line": 1, "word_no": 1},
                {"rect": [0.30, 0.30, 0.400, 0.40], "text": "seven", "block": 0, "line": 1, "word_no": 2},
                {"rect": [0.425, 0.30, 0.525, 0.40], "text": "eight", "block": 0, "line": 1, "word_no": 3},
            ],
        )

        canvas._selection_start = QPoint(130, 30)
        canvas._selection_end = QPoint(35, 70)
        canvas._update_text_selection()
        self.assertEqual(canvas._selected_text, "three four")
        self.assertEqual(canvas._selected_rects_norm, [[0.3, 0.1, 0.525, 0.2]])

        canvas._selection_end = QPoint(95, 70)
        canvas._update_text_selection()
        self.assertEqual(canvas._selected_text, "three four\nfive six")
        self.assertEqual(canvas._selected_rects_norm, [[0.3, 0.1, 0.525, 0.2], [0.1, 0.3, 0.2875, 0.4]])

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

    def test_reader_blank_area_uses_beige_palette(self) -> None:
        window = MainWindow()
        beige = "#f0ead8"
        self.assertEqual(window.scroll_area.viewport().palette().color(window.scroll_area.viewport().backgroundRole()).name(), beige)
        self.assertEqual(window.pages_container.palette().color(window.pages_container.backgroundRole()).name(), beige)
        window.close()

    def test_app_branding_and_theme_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(Path(tmp) / "data")
            window = MainWindow()
            try:
                self.assertEqual(window.windowTitle(), "PDFNest")
                self.assertFalse(window.windowIcon().isNull())

                window.theme_name = "white"
                window.settings["theme"] = "white"
                window.apply_theme()
                self.assertEqual(
                    window.scroll_area.viewport().palette().color(window.scroll_area.viewport().backgroundRole()).name(),
                    "#e5e7eb",
                )
                self.assertIn("white", window.themes)
                self.assertTrue((themes_dir(Path(tmp) / "data") / "white.json").exists())
            finally:
                window.close()

    def test_bottom_page_controls_and_reading_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path, page_count=3)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.show()
                QTest.qWait(80)
                self.app.processEvents()
                self.assertEqual(window.page_spin.text(), "1")
                self.assertEqual(window.page_count_label.text(), "/ 3")
                self.assertFalse(window.prev_page_button.isEnabled())
                self.assertTrue(window.next_page_button.isEnabled())

                window.next_page_button.click()
                self.assertEqual(window.page_index, 1)
                self.assertEqual(window.page_spin.text(), "2")

                window.page_spin.setText("3")
                QTest.keyClick(window.page_spin, Qt.Key_Return)
                self.assertEqual(window.page_index, 2)

                window.page_spin.setText("4")
                QTest.keyClick(window.page_spin, Qt.Key_Return)
                self.assertEqual(window.page_index, 2)
                self.assertEqual(window.page_spin.text(), "3")

                window.page_spin.setFocus()
                window.page_spin.setText("1")
                QApplication.sendEvent(window.page_spin, QFocusEvent(QEvent.FocusOut))
                self.app.processEvents()
                self.assertEqual(window.page_index, 2)
                self.assertEqual(window.page_spin.text(), "3")

                window.set_reading_mode("single")
                self.assertFalse(window.continuous_scroll)
                self.assertEqual(len(window.page_canvases), 1)

                window.set_reading_mode("continuous")
                self.assertTrue(window.continuous_scroll)
                self.assertEqual(sorted(window.page_canvases), [0, 1, 2])
            finally:
                window.close()

    def test_fit_width_height_and_ctrl_wheel_zoom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path, page_count=4)

            window = MainWindow()
            try:
                window.resize(1000, 700)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()
                window.go_to_page(2)
                self.app.processEvents()

                window.fit_page("width")
                width_zoom = window.zoom
                self.assertEqual(window.fit_mode, "width")
                self.assertEqual(window.page_index, 2)
                self.assertGreater(width_zoom, 0.3)
                self.assertEqual(
                    window._page_display_size(window.page_index).width() + self._horizontal_page_margins(window),
                    window.scroll_area.viewport().width(),
                )
                window.fit_page("width")
                self.assertAlmostEqual(window.zoom, width_zoom)
                window._sync_current_page_from_scroll()
                self.assertEqual(window.page_index, 2)

                window.reader_splitter.setSizes([0, 800, 200])
                window._handle_reader_splitter_moved(0, 1)
                self.app.processEvents()
                QTest.qWait(180)
                self.assertNotEqual(window.zoom, width_zoom)
                self.assertEqual(window.page_index, 2)
                self.assertEqual(
                    window._page_display_size(window.page_index).width() + self._horizontal_page_margins(window),
                    window.scroll_area.viewport().width(),
                )

                window.fit_page("height")
                height_zoom = window.zoom
                self.assertEqual(window.fit_mode, "height")
                self.assertGreater(height_zoom, 0.3)
                window._sync_current_page_from_scroll()
                self.assertEqual(window.page_index, 2)

                window.zoom_spin.setValue(175)
                self.assertAlmostEqual(window.zoom, 1.75)
                self.assertIsNone(window.fit_mode)
                self.assertEqual(window.page_index, 2)
                window._sync_current_page_from_scroll()
                self.assertEqual(window.page_index, 2)

                before = window.zoom

                class FakeWheel:
                    def type(self):
                        return QEvent.Wheel

                    def modifiers(self):
                        return Qt.ControlModifier

                    def angleDelta(self):
                        return QPoint(0, 120)

                    def accept(self):
                        self.accepted = True

                event = FakeWheel()
                handled = window.eventFilter(window.scroll_area.viewport(), event)
                self.assertTrue(handled)
                self.assertGreater(window.zoom, before)
                self.assertEqual(window.page_index, 2)
                self.assertIn(2, window.page_canvases)
                expected_scroll = window.page_tops[2] + window.page_heights[2] // 2 - window.scroll_area.viewport().height() // 2
                scroll_bar = window.scroll_area.verticalScrollBar()
                expected_scroll = max(0, min(scroll_bar.maximum(), expected_scroll))
                self.assertLessEqual(abs(scroll_bar.value() - expected_scroll), 2)
            finally:
                window.close()

    def test_fit_width_converges_when_scrollbars_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "short.pdf"
            self._create_sample_pdf(pdf_path, page_count=1, page_size=(300, 180))

            window = MainWindow()
            try:
                window.resize(1000, 700)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()

                window.fit_page("width")
                QTest.qWait(180)
                width_zoom = window.zoom
                self.assertEqual(
                    window._page_display_size(window.page_index).width() + self._horizontal_page_margins(window),
                    window.scroll_area.viewport().width(),
                )

                window.fit_page("width")
                QTest.qWait(180)
                self.assertAlmostEqual(window.zoom, width_zoom)
                self.assertEqual(
                    window._page_display_size(window.page_index).width() + self._horizontal_page_margins(window),
                    window.scroll_area.viewport().width(),
                )
            finally:
                window.close()

    def test_fit_width_uses_widest_pdf_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "mixed-width.pdf"
            document = fitz.open()
            document.new_page(width=420, height=240)
            document.new_page(width=300, height=240)
            document.new_page(width=360, height=240)
            document.save(pdf_path)
            document.close()

            window = MainWindow()
            try:
                window.resize(1000, 700)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()
                window.go_to_page(1)
                self.app.processEvents()

                window.fit_page("width")
                QTest.qWait(180)
                widest_display_width = max(window.page_widths)
                current_canvas = window.page_canvases[1]
                self.assertEqual(widest_display_width, window.scroll_area.viewport().width())
                self.assertLess(current_canvas.width(), window.scroll_area.viewport().width())
                self.assertFalse(window.scroll_area.horizontalScrollBar().isVisible())
                self.assertEqual(window.page_index, 1)
            finally:
                window.close()

    def test_fit_preserves_content_anchor_selection_and_render_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "fit-stability.pdf"
            self._create_sample_pdf(pdf_path, page_count=6)

            window = MainWindow()
            try:
                window.resize(900, 600)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()
                window.go_to_page(3)
                self.app.processEvents()
                reference_offset = min(80, max(1, window.scroll_area.viewport().height() // 4))
                target_scroll = window.page_tops[3] + round(window.page_heights[3] * 0.35) - reference_offset
                window.scroll_area.verticalScrollBar().setValue(target_scroll)
                window.page_index = 3
                canvas = window.page_canvases[3]
                canvas._selected_text = "selection survives fit"
                canvas._selected_rects_norm = [[0.1, 0.2, 0.4, 0.25]]
                anchor_before = window._fit_view_anchor(3)

                render_calls: list[tuple[int, float]] = []
                original_render = window._render_page_pixmap

                def tracked_render(page_index: int):
                    render_calls.append((page_index, round(window.zoom, 6)))
                    return original_render(page_index)

                window._render_page_pixmap = tracked_render
                window.fit_page("width")
                QTest.qWait(220)
                self.app.processEvents()

                anchor_after = window._fit_view_anchor(3)
                self.assertEqual(anchor_after[0], anchor_before[0])
                self.assertAlmostEqual(anchor_after[1], anchor_before[1], delta=0.015)
                self.assertTrue(set(window._visible_page_indexes()).issubset(window.page_canvases))
                restored_canvas = window.page_canvases[3]
                self.assertEqual(restored_canvas._selected_text, "selection survives fit")
                self.assertEqual(restored_canvas._selected_rects_norm, [[0.1, 0.2, 0.4, 0.25]])
                self.assertEqual(len(render_calls), len(set(render_calls)))
            finally:
                window.close()

    def test_continuous_scroll_uses_full_document_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path, page_count=8)

            window = MainWindow()
            try:
                window.resize(900, 600)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()

                self.assertEqual(len(window.page_tops), 8)
                self.assertEqual(len(window.page_heights), 8)
                self.assertEqual(sorted(window.page_canvases), [0, 1, 2, 3, 4])
                self.assertLessEqual(window.pages_layout.count(), 6)
                self.assertIn(0, window.page_widgets)
                self.assertNotIn(5, window.page_canvases)

                window.scroll_area.verticalScrollBar().setValue(window.page_tops[5])
                self.app.processEvents()
                window._sync_current_page_from_scroll()
                QTest.qWait(80)
                self.app.processEvents()
                self.assertEqual(window.page_index, 5)
                self.assertIn(5, window.page_canvases)
                self.assertLessEqual(window.pages_layout.count(), 8)
            finally:
                window.close()

    def test_continuous_scroll_renders_visible_placeholder_before_page_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "visible-placeholder.pdf"
            self._create_sample_pdf(pdf_path, page_count=8)

            window = MainWindow()
            try:
                window.resize(900, 600)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()
                window.go_to_page(4)
                self.app.processEvents()
                window.render_page(center_current=False, render_neighbors=False)
                self.app.processEvents()
                self.assertEqual(sorted(window.page_canvases), [4])

                scroll_bar = window.scroll_area.verticalScrollBar()
                target_scroll = window.page_tops[4] + window.page_heights[4] - 90
                scroll_bar.setValue(target_scroll)
                self.assertGreater(scroll_bar.value() + window.scroll_area.viewport().height(), window.page_tops[5])
                window._sync_current_page_from_scroll()
                self.assertEqual(window.page_index, 4)
                self.assertNotIn(5, window.page_canvases)

                QTest.qWait(80)
                self.app.processEvents()
                self.assertIn(5, window.page_canvases)
            finally:
                window.close()

    def test_note_export_button_writes_markdown_file_inside_pdf_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path, page_count=2, toc=[[1, "Chapter One", 1]])

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                with patch(
                    "pdf_notes_reader.main.QFileDialog.getExistingDirectory",
                    return_value=str(tmp_path / "markdown"),
                ):
                    window.choose_note_export_dir()
                self.assertEqual(window.note_export_dir, tmp_path / "markdown")
                self.assertFalse(hasattr(window.note_panel, "folder_label"))
                self.assertFalse(hasattr(window.note_panel, "title"))

                window.add_note(0, 0.25, 0.75)
                self.assertEqual(window.notes[0].markdown, "# Chapter One-1\n")
                window.note_panel.editor.setPlainText("# Exported\n\nBody")
                window.save_current_note(window.note_panel.editor.toPlainText())
                self.assertEqual(list(window.note_export_dir.glob("*.md")), [])

                window.export_current_note(window.note_panel.editor.toPlainText())

                markdown_files = list(window.note_export_dir.glob("*.md"))
                self.assertEqual(markdown_files, [])
                markdown_files = list((window.note_export_dir / "sample").glob("*.md"))
                self.assertEqual(len(markdown_files), 1)
                self.assertNotIn("sample", markdown_files[0].name)
                self.assertIn("Chapter One", markdown_files[0].name)
                self.assertTrue(markdown_files[0].name.endswith("-1.md"))
                self.assertEqual(markdown_files[0].read_text(encoding="utf-8"), "# Exported\n\nBody")
            finally:
                window.close()

    def test_markdown_export_limits_long_pdf_name_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            long_stem = "very-long-pdf-name-" * 7
            pdf_path = tmp_path / f"{long_stem}.pdf"
            self._create_sample_pdf(pdf_path, page_count=1)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.note_export_dir = tmp_path / "markdown"
                window.add_note(0, 0.25, 0.75)
                path = window.export_markdown_note(window.notes[0])

                self.assertIsNotNone(path)
                assert path is not None
                self.assertLessEqual(len(path.parent.name), 48)
                self.assertLessEqual(len(path.name), 153)
                self.assertNotIn(path.parent.name, path.name)
                self.assertTrue(path.exists())
            finally:
                window.close()

    def test_go_to_note_button_jumps_reader_and_return_button_restores_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path, page_count=4)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.show()
                QTest.qWait(80)
                self.app.processEvents()
                self.assertEqual(window.note_panel.folder_button.text(), "Go to note")
                self.assertFalse(window.return_position_button.isEnabled())

                window.add_note(1, 0.25, 0.75)
                note = window.notes[0]
                window._go_to_page_offset(3, 160)
                QTest.qWait(80)
                self.app.processEvents()
                previous_position = window._current_view_snapshot()

                window.note_panel.folder_button.click()
                QTest.qWait(160)
                self.app.processEvents()

                self.assertEqual(window.page_index, note.page_index)
                self.assertTrue(window.return_position_button.isEnabled())
                self.assertEqual(window.reader_return_stack[-1], previous_position)

                window.return_position_button.click()
                QTest.qWait(160)
                self.app.processEvents()

                self.assertEqual(window._current_view_snapshot(), previous_position)
                self.assertFalse(window.return_position_button.isEnabled())
            finally:
                window.close()

    def test_return_position_records_jumps_but_not_normal_paging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path, page_count=4)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.show()
                QTest.qWait(80)
                self.app.processEvents()

                window.next_page()
                QTest.qWait(80)
                self.app.processEvents()
                self.assertEqual(window.page_index, 1)
                self.assertEqual(window.reader_return_stack, [])

                before_page_number_jump = window._current_view_snapshot()
                window.page_spin.setText("4")
                QTest.keyClick(window.page_spin, Qt.Key_Return)
                QTest.qWait(120)
                self.app.processEvents()
                self.assertEqual(window.page_index, 3)
                self.assertEqual(window.reader_return_stack[-1], before_page_number_jump)

                window.return_to_previous_reading_position()
                QTest.qWait(120)
                self.app.processEvents()
                self.assertEqual(window._current_view_snapshot(), before_page_number_jump)
                self.assertEqual(window.reader_return_stack, [])

                same_page_snapshot = window._current_view_snapshot()
                window.jump_to_page_from_navigation(window.page_index)
                QTest.qWait(120)
                self.app.processEvents()
                self.assertEqual(window.reader_return_stack[-1], same_page_snapshot)
            finally:
                window.close()

    def test_markdown_export_can_replace_or_create_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "sample.pdf"
            self._create_sample_pdf(pdf_path, page_count=1)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.note_export_dir = tmp_path / "markdown"
                window.add_note(0, 0.25, 0.75)
                note = window.notes[0]

                note.update_markdown("# page-1-1\nfirst")
                first_path = window.export_markdown_note(note)
                self.assertIsNotNone(first_path)
                assert first_path is not None
                self.assertEqual(Path(note.exported_markdown_path), first_path)
                self.assertEqual(first_path.read_text(encoding="utf-8"), "# page-1-1\nfirst")
                self.assertEqual(load_notes(window.pdf_key)[0].exported_markdown_path, str(first_path))

                note.update_markdown("# page-1-1\nreplacement")
                replaced_path = window.export_markdown_note(note, replace_existing=True)
                self.assertEqual(replaced_path, first_path)
                self.assertEqual(first_path.read_text(encoding="utf-8"), "# page-1-1\nreplacement")
                self.assertEqual(load_notes(window.pdf_key)[0].exported_markdown_path, str(first_path))

                note.update_markdown("# page-1-1\nnew file")
                new_path = window.export_markdown_note(note, replace_existing=False)
                self.assertIsNotNone(new_path)
                assert new_path is not None
                self.assertNotEqual(new_path, first_path)
                self.assertEqual(first_path.read_text(encoding="utf-8"), "# page-1-1\nreplacement")
                self.assertEqual(new_path.read_text(encoding="utf-8"), "# page-1-1\nnew file")
                self.assertEqual(Path(load_notes(window.pdf_key)[0].exported_markdown_path), new_path)
            finally:
                window.close()

    def test_note_save_export_shortcuts_and_append_selection_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "shortcuts.pdf"
            self._create_sample_pdf(pdf_path, page_count=1)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.note_export_dir = tmp_path / "markdown"
                window.add_note(0, 0.25, 0.75)
                note = window.notes[0]

                self.assertEqual(window.save_note_shortcut.key().toString(QKeySequence.PortableText), "Ctrl+S")
                self.assertEqual(window.export_note_shortcut.key().toString(QKeySequence.PortableText), "Ctrl+Shift+S")
                self.assertEqual(window.append_selection_shortcut.key().toString(QKeySequence.PortableText), "Ctrl+Shift+C")

                window.note_panel.editor.setPlainText("# Saved by shortcut\nBody")
                window.save_note_shortcut.activated.emit()
                self.assertEqual(load_notes(window.pdf_key)[0].markdown, "# Saved by shortcut\nBody")

                window.append_selected_text_to_current_note("chosen text\nsecond line")
                self.assertIn("> chosen text\n> second line", note.markdown)
                self.assertIn("> chosen text\n> second line", load_notes(window.pdf_key)[0].markdown)

                canvas = window.page_canvases[0]
                canvas._selected_text = "shortcut selected text"
                canvas._selected_rects_norm = [[0.1, 0.1, 0.2, 0.2]]
                window.canvas = canvas
                window.append_selection_shortcut.activated.emit()
                self.assertIn("> shortcut selected text", note.markdown)
                excerpt_markers = [item for item in window.notes if item.note_type == "excerpt"]
                self.assertEqual(len(excerpt_markers), 1)
                self.assertEqual(excerpt_markers[0].color, "#93c5fd")
                self.assertEqual(excerpt_markers[0].linked_note_id, note.id)
                self.assertEqual(excerpt_markers[0].rects_norm, [[0.1, 0.1, 0.2, 0.2]])
                live_canvas = window.page_canvases[0]
                live_pixmap = live_canvas._pixmap
                window.set_note_color(excerpt_markers[0].id, "#86efac")
                self.assertEqual(excerpt_markers[0].color, "#86efac")
                self.assertEqual(window.note_panel.current_note_id, note.id)
                self.assertIs(window.page_canvases[0], live_canvas)
                self.assertIs(window.page_canvases[0]._pixmap, live_pixmap)
                window.set_note_style(excerpt_markers[0].id, "highlight")
                self.assertEqual(excerpt_markers[0].marker_style, "highlight")
                self.assertIs(window.page_canvases[0], live_canvas)
                self.assertIs(window.page_canvases[0]._pixmap, live_pixmap)
                window.set_note_style(excerpt_markers[0].id, "underline")
                self.assertEqual(excerpt_markers[0].marker_style, "underline")
                self.assertEqual(
                    next(item for item in load_notes(window.pdf_key) if item.note_type == "excerpt").marker_style,
                    "underline",
                )
                window.delete_note_by_id(excerpt_markers[0].id)
                self.assertFalse(any(item.note_type == "excerpt" for item in window.notes))
                self.assertEqual(window.note_panel.current_note_id, note.id)
                self.assertIs(window.page_canvases[0], live_canvas)
                self.assertIs(window.page_canvases[0]._pixmap, live_pixmap)
                self.assertEqual(canvas._selected_text, "")
                self.assertEqual(canvas._selected_rects_norm, [])

                window.export_note_shortcut.activated.emit()
                exported_path = Path(note.exported_markdown_path)
                self.assertTrue(exported_path.exists())
                self.assertIn("> chosen text", exported_path.read_text(encoding="utf-8"))
            finally:
                window.close()

    def test_annotation_shortcuts_use_configured_default_styles_and_colors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "annotation-shortcuts.pdf"
            self._create_sample_pdf(pdf_path)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.add_note(0, 0.8, 0.8)
                target_note = window.notes[0]
                canvas = window.page_canvases[0]
                window.canvas = canvas

                expected_keys = {
                    "highlight_selection_shortcut": "Ctrl+H",
                    "underline_selection_shortcut": "Ctrl+U",
                    "append_highlight_selection_shortcut": "Ctrl+Shift+H",
                    "append_underline_selection_shortcut": "Ctrl+Shift+U",
                }
                for setting_key, expected in expected_keys.items():
                    self.assertEqual(
                        window.selection_action_shortcuts[setting_key].key().toString(QKeySequence.PortableText),
                        expected,
                    )

                canvas._selected_text = "red highlight"
                canvas._selected_rects_norm = [[0.1, 0.1, 0.3, 0.2]]
                window.selection_action_shortcuts["highlight_selection_shortcut"].activated.emit()
                regular_highlight = next(item for item in window.notes if item.note_type == "highlight")
                self.assertEqual(regular_highlight.color, "#fca5a5")

                window.select_note(target_note.id)
                canvas._selected_text = "red underline"
                canvas._selected_rects_norm = [[0.1, 0.3, 0.3, 0.4]]
                window.selection_action_shortcuts["underline_selection_shortcut"].activated.emit()
                regular_underline = next(item for item in window.notes if item.note_type == "underline")
                self.assertEqual(regular_underline.color, "#fca5a5")

                window.select_note(target_note.id)
                canvas._selected_text = "blue copied highlight"
                canvas._selected_rects_norm = [[0.4, 0.1, 0.7, 0.2]]
                window.selection_action_shortcuts["append_highlight_selection_shortcut"].activated.emit()
                copied_highlight = next(item for item in window.notes if item.note_type == "excerpt")
                self.assertEqual(copied_highlight.marker_style, "highlight")
                self.assertEqual(copied_highlight.color, "#93c5fd")

                canvas._selected_text = "blue copied underline"
                canvas._selected_rects_norm = [[0.4, 0.3, 0.7, 0.4]]
                window.selection_action_shortcuts["append_underline_selection_shortcut"].activated.emit()
                copied_underline = [item for item in window.notes if item.note_type == "excerpt"][-1]
                self.assertEqual(copied_underline.marker_style, "underline")
                self.assertEqual(copied_underline.color, "#93c5fd")
                self.assertIn("> blue copied highlight", target_note.markdown)
                self.assertIn("> blue copied underline", target_note.markdown)
            finally:
                window.close()

    def test_new_note_number_stays_on_first_line_when_outline_title_wraps(self) -> None:
        window = MainWindow()
        try:
            window.document = SimpleNamespace(get_toc=lambda: [[1, "1 Introduction\n", 15]], close=lambda: None, page_count=20)
            self.assertEqual(window._default_note_title(14, 10), "1 Introduction-10")
        finally:
            window.close()

    def test_reset_note_counters_to_current_note_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "reset-counters.pdf"
            self._create_sample_pdf(pdf_path, page_count=2)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.add_note(0, 0.20, 0.20)
                window.add_note(0, 0.40, 0.20)
                window.note_counters["0"] = 25

                window.reset_note_counters_to_current_notes()
                key = window._counter_key(0)
                self.assertEqual(window.note_counters, {key: 3})
                persisted = load_notes(window.pdf_key)
                self.assertEqual(len(persisted), 2)

                window.add_note(0, 0.60, 0.20)
                self.assertEqual(window.notes[-1].markdown, "# page-1-3\n")

                for note in list(window.notes):
                    window.delete_note_by_id(note.id)
                self.assertEqual(window.note_counters.get(key), 4)

                window.reset_note_counters_to_current_notes()
                self.assertEqual(window.note_counters, {})
                window.add_note(0, 0.80, 0.20)
                self.assertEqual(window.notes[-1].markdown, "# page-1-1\n")
            finally:
                window.close()

    def test_reset_note_counters_uses_saved_outline_across_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "chapter-counters.pdf"
            self._create_sample_pdf(pdf_path, page_count=3, toc=[[1, "Introduction", 1], [1, "Next", 3]])

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.add_note(0, 0.20, 0.20)
                window.add_note(1, 0.40, 0.20)
                self.assertEqual(window.notes[0].markdown, "# Introduction-1\n")
                self.assertEqual(window.notes[1].markdown, "# Introduction-2\n")
                key = window._counter_key(1)

                deleted_note_id = window.notes[1].id
                window.delete_note_by_id(deleted_note_id)
                window.reset_note_counters_to_current_notes()
                self.assertEqual(window.note_counters, {key: 2})

                window.add_note(1, 0.60, 0.20)
                self.assertEqual(window.notes[-1].markdown, "# Introduction-2\n")
                self.assertEqual(window.notes[-1].note_number, 2)
                self.assertEqual(window.note_counters.get(key), 3)
            finally:
                window.close()

    def test_reset_note_counters_counts_remaining_notes_not_highest_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "reset-high-number.pdf"
            self._create_sample_pdf(pdf_path, page_count=1)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.add_note(0, 0.20, 0.20)
                remaining = window.notes[0]
                remaining.note_number = 5
                remaining.update_markdown("# page-1-5\n")
                window.note_counters[window._counter_key(0)] = 6

                window.reset_note_counters_to_current_notes()
                self.assertEqual(window.note_counters, {window._counter_key(0): 2})

                window.add_note(0, 0.40, 0.20)
                self.assertEqual(window.notes[-1].markdown, "# page-1-2\n")
                self.assertEqual(window.notes[-1].note_number, 2)
            finally:
                window.close()

    def test_add_note_preserves_scroll_position_and_note_selector_switches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "scroll-note.pdf"
            self._create_sample_pdf(pdf_path, page_count=6)

            window = MainWindow()
            try:
                window.resize(900, 600)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()
                window.scroll_area.verticalScrollBar().setValue(window.page_tops[3])
                self.app.processEvents()
                window._sync_current_page_from_scroll()
                before_scroll = window.scroll_area.verticalScrollBar().value()

                window.add_note(3, 0.25, 0.30)
                self.app.processEvents()
                self.assertLessEqual(abs(window.scroll_area.verticalScrollBar().value() - before_scroll), 2)
                self.assertEqual(window.page_index, 3)
                first_id = window.notes[0].id
                self.assertEqual(window.notes[0].markdown, "# page-4-1\n")
                self.assertNotIn(
                    "Select note...",
                    [window.note_panel.note_selector.itemText(i) for i in range(window.note_panel.note_selector.count())],
                )

                window.note_panel.editor.setPlainText("# First note title\nBody")
                window.save_current_note(window.note_panel.editor.toPlainText())
                self.assertIn("# First note title", [window.note_panel.note_selector.itemText(i) for i in range(window.note_panel.note_selector.count())])

                window.add_note(3, 0.50, 0.30)
                self.assertEqual(window.notes[1].markdown, "# page-4-2\n")
                second_id = window.notes[1].id
                self.assertEqual(window.note_panel.current_note_id, second_id)

                window.delete_note_by_id(first_id)
                key = window._counter_key(3)
                self.assertEqual(window.note_counters.get(key), 3)
                self.assertEqual(window.note_panel.current_note_id, second_id)

                index = window.note_panel.note_selector.findData(first_id)
                self.assertEqual(index, -1)
                index = window.note_panel.note_selector.findData(second_id)
                self.assertGreaterEqual(index, 0)
                window.note_panel.note_selector.setCurrentIndex(index)
                window.note_panel._emit_selected_note(index)
                self.assertEqual(window.note_panel.current_note_id, second_id)

                window.go_to_page(4)
                self.assertEqual(window.note_panel.current_note_id, second_id)
                self.assertIn("# page-4-2", window.note_panel.editor.toPlainText())
                self.assertEqual(window.note_panel.note_selector.currentData(), second_id)
            finally:
                window.close()

            reloaded_window = MainWindow()
            try:
                reloaded_window.load_pdf(pdf_path)
                reloaded_window.go_to_page(3)
                reloaded_window.add_note(3, 0.75, 0.30)
                self.assertEqual(reloaded_window.notes[-1].markdown, "# page-4-3\n")
                self.assertEqual(reloaded_window.notes[-1].note_number, 3)
                key = reloaded_window._counter_key(3)
                self.assertEqual(reloaded_window.note_counters.get(key), 4)
            finally:
                reloaded_window.close()

    def test_note_operations_preserve_pdf_geometry_text_and_scroll(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "stable-display.pdf"
            self._create_sample_pdf(pdf_path, page_count=6)

            window = MainWindow()
            try:
                window.resize(900, 600)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()
                window.scroll_area.verticalScrollBar().setValue(window.page_tops[3] + 12)
                self.app.processEvents()
                window._sync_current_page_from_scroll()
                self.assertEqual(window.page_index, 3)

                def page_signature() -> tuple:
                    canvas = window.page_canvases[3]
                    return (
                        tuple(window.page_tops),
                        tuple(window.page_heights),
                        tuple(window.page_widths),
                        canvas._page_size.width(),
                        canvas._page_size.height(),
                        tuple(
                            (
                                tuple(round(value, 6) for value in word["rect"]),
                                word["text"],
                                word["block"],
                                word["line"],
                                word["word_no"],
                            )
                            for word in window._page_text_words(3)
                        ),
                    )

                before = page_signature()
                before_scroll = window.scroll_area.verticalScrollBar().value()
                before_words_object = window.page_text_words_cache[3]
                before_canvas = window.page_canvases[3]
                before_pixmap = before_canvas._pixmap

                window.add_note(3, 0.25, 0.30)
                self.app.processEvents()
                after_add = page_signature()
                self.assertEqual(after_add, before)
                self.assertLessEqual(abs(window.scroll_area.verticalScrollBar().value() - before_scroll), 2)
                self.assertIs(window.page_text_words_cache[3], before_words_object)
                self.assertIs(window.page_canvases[3], before_canvas)
                self.assertIs(window.page_canvases[3]._pixmap, before_pixmap)

                window.reset_note_counters_to_current_notes()
                self.app.processEvents()
                after_reset = page_signature()
                self.assertEqual(after_reset, before)
                self.assertLessEqual(abs(window.scroll_area.verticalScrollBar().value() - before_scroll), 2)
                self.assertIs(window.page_text_words_cache[3], before_words_object)
            finally:
                window.close()

    def test_text_annotation_uses_note_panel_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "annotation.pdf"
            self._create_sample_pdf(pdf_path)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.add_text_annotation(0, "highlight", [[0.1, 0.2, 0.4, 0.25]], "selected text", "#86efac")

                self.assertEqual(len(window.notes), 1)
                self.assertEqual(window.notes[0].note_type, "highlight")
                self.assertEqual(window.notes[0].selected_text, "selected text")
                self.assertTrue(window.notes[0].markdown.startswith("# page-1-1\n\n> selected text"))
                self.assertEqual(window.notes[0].color, "#86efac")
                self.assertEqual(window.note_panel.current_note_id, window.notes[0].id)
                note_id = window.notes[0].id

                window.select_note(note_id)
                self.assertEqual(window.note_panel.current_note_id, note_id)
                window.set_note_color(note_id, "#93c5fd")
                self.assertEqual(window.notes[0].color, "#93c5fd")
                live_canvas = window.page_canvases[0]
                live_pixmap = live_canvas._pixmap
                window.set_note_style(note_id, "underline")
                self.assertEqual(window.notes[0].note_type, "underline")
                self.assertIs(window.page_canvases[0], live_canvas)
                self.assertIs(window.page_canvases[0]._pixmap, live_pixmap)
                window.set_note_style(note_id, "highlight")
                self.assertEqual(window.notes[0].note_type, "highlight")

                loaded = load_notes(window.pdf_key)
                self.assertEqual(loaded[0].note_type, "highlight")
                self.assertEqual(loaded[0].rects_norm, [[0.1, 0.2, 0.4, 0.25]])
                self.assertEqual(loaded[0].color, "#93c5fd")

                window.delete_note_by_id(note_id)
                self.assertEqual(window.notes, [])
                self.assertEqual(load_notes(window.pdf_key), [])
            finally:
                window.close()

    def test_settings_store_marker_size_without_embedded_themes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(data_dir)
            window = MainWindow()
            try:
                window.note_marker_radius = 13
                window.settings["note_marker_radius"] = 13
                window.settings["theme"] = "white"
                window.settings["wheel_scroll_lines"] = 9
                window.settings["auto_save_current_note"] = False
                window.settings["window_width"] = 900
                window.settings["window_height"] = 700
                window.settings["window_maximized"] = True
                window.settings["markdown_export_dir"] = str(data_dir / "md")
                save_settings(window.settings)

                settings = load_settings()
                self.assertEqual(settings["note_marker_radius"], 13)
                self.assertEqual(settings["theme"], "white")
                self.assertEqual(settings["wheel_scroll_lines"], 9)
                self.assertFalse(settings["auto_save_current_note"])
                self.assertEqual(settings["window_width"], 900)
                self.assertEqual(settings["window_height"], 700)
                self.assertTrue(settings["window_maximized"])
                self.assertEqual(settings["markdown_export_dir"], str(data_dir / "md"))
                self.assertNotIn("themes", settings)
                self.assertIn("beige", load_theme_files())
                self.assertTrue((data_dir / "themes" / "beige.json").exists())
                custom_theme = data_dir / "themes" / "ocean.json"
                custom_theme.write_text('{"reader": "#ffffff", "window": "#ffffff"}\n', encoding="utf-8")
                self.assertIn("ocean", load_theme_files())
            finally:
                window.close()

    def test_settings_dialog_uses_theme_and_hides_theme_file_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(data_dir)
            window = MainWindow()
            dialog = SettingsDialog(
                settings=window.settings,
                themes=window.themes,
                data_dir=data_dir,
                note_json_path=None,
                markdown_dir=data_dir / "markdown_notes",
                theme_dir=themes_dir(data_dir),
                parent=window,
            )
            try:
                dialog.setStyleSheet(window.styleSheet())
                dialog.append_selection_shortcut_edit.setKeySequence(QKeySequence("Alt+C"))
                dialog.selection_shortcut_edits["highlight_selection_shortcut"].setKeySequence(QKeySequence("Alt+H"))
                color_combo = dialog.selection_color_combos["highlight_selection_color"]
                custom_index = color_combo.count() - 1
                color_combo.setCurrentIndex(custom_index)
                with patch("pdf_notes_reader.main.QColorDialog.getColor", return_value=QColor("#123456")):
                    dialog._choose_selection_color("highlight_selection_color", custom_index)
                dialog.wheel_scroll_lines_spin.setValue(11)
                dialog.auto_save_note_checkbox.setChecked(False)
                dialog.markdown_dir_edit.setText(str(data_dir / "custom-md"))
                labels = [label.text() for label in dialog.findChildren(QLabel)]
                categories = [
                    dialog.category_list.topLevelItem(index).text(0)
                    for index in range(dialog.category_list.topLevelItemCount())
                ]
                self.assertIn("QDialog", window.styleSheet())
                self.assertNotIn("Theme files", labels)
                self.assertIn("Theme folder", labels)
                self.assertIn("Page display", categories)
                self.assertIn("Storage", categories)
                self.assertIn("Annotation colors", categories)
                self.assertEqual(dialog.append_selection_shortcut, "Alt+C")
                self.assertEqual(dialog.selection_shortcuts["highlight_selection_shortcut"], "Alt+H")
                self.assertEqual(dialog.selection_colors["highlight_selection_color"], "#123456")
                self.assertEqual(
                    [color_combo.itemText(index).split(" (")[0] for index in range(color_combo.count())],
                    ["Yellow", "Green", "Blue", "Pink", "Red", "Purple", "Custom color..."],
                )
                self.assertEqual(dialog.wheel_scroll_lines, 11)
                self.assertEqual(dialog.markdown_dir, data_dir / "custom-md")
                self.assertLessEqual(dialog.storage_dir_edit.maximumWidth(), 420)
                self.assertEqual(dialog.storage_dir_edit.alignment() & Qt.AlignHorizontal_Mask, Qt.AlignLeft)
                self.assertEqual(dialog.markdown_dir_edit.alignment() & Qt.AlignHorizontal_Mask, Qt.AlignLeft)
                self.assertEqual(dialog.storage_dir_edit.cursorPosition(), 0)
                self.assertTrue(any(button.objectName() == "CopyPathButton" for button in dialog.findChildren(QToolButton)))
                path_labels = dialog.findChildren(QLabel, "SettingsPathLabel")
                self.assertTrue(path_labels)
                self.assertTrue(all(label.minimumWidth() == label.maximumWidth() == 160 for label in path_labels))
                self.assertFalse(dialog.auto_save_current_note)
            finally:
                dialog.close()
                window.close()

    def test_white_theme_keeps_selected_text_readable_and_uses_branch_arrows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(data_dir)
            window = MainWindow()
            try:
                window.theme_name = "white"
                window.apply_theme()
                stylesheet = window.styleSheet()
                self.assertIn("selection-color:", stylesheet)
                self.assertIn("#LibraryFolderTree::branch", stylesheet)
                self.assertIn("width: 16px", stylesheet)
                self.assertIn("image: none", stylesheet)
                self.assertNotIn("tree-open.png", stylesheet)
                self.assertNotIn("tree-closed.png", stylesheet)
                self.assertIn("outline: none", stylesheet)
                self.assertIn("down-arrow.png", stylesheet)
                self.assertIn("up-arrow.png", stylesheet)
                self.assertIn("QComboBox::down-arrow", stylesheet)
                self.assertIn("QSpinBox::up-arrow", stylesheet)
            finally:
                window.close()

    def test_default_data_dir_is_project_local(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("pdf_notes_reader.notes._read_storage_pointer", return_value=None):
            expected = Path(__file__).resolve().parents[1] / "Note_PDFNest"
            self.assertEqual(default_data_dir(), expected)

    def test_toolbar_no_longer_exposes_mode_zoom_or_settings_controls(self) -> None:
        window = MainWindow()
        try:
            action_texts = [action.text() for toolbar in window.findChildren(QToolBar) for action in toolbar.actions()]
            self.assertEqual(window.document_tab_bar.tabText(0), "Home")
            self.assertEqual(window.open_tab_button.text(), "+ Open")
            self.assertFalse(window.document_title_bar.isVisible())
            self.assertEqual(window.outline_toggle_button.text(), "Contents")
            self.assertEqual(window.history_panel.settings_button.text(), "")
            self.assertFalse(window.history_panel.settings_button.icon().isNull())
            self.assertNotIn("Continuous Scroll", action_texts)
            self.assertNotIn("Zoom In", action_texts)
            self.assertNotIn("Zoom Out", action_texts)
            self.assertNotIn("Settings", action_texts)
        finally:
            window.close()

    def test_pdf_file_picker_uses_non_native_dialog(self) -> None:
        calls: dict[str, object] = {}

        class FakeFileDialog:
            ExistingFile = 1
            DontUseNativeDialog = 2

            def __init__(self, parent, title, directory, name_filter) -> None:
                calls["parent"] = parent
                calls["title"] = title
                calls["directory"] = directory
                calls["name_filter"] = name_filter
                self.options: list[tuple[int, bool]] = []

            def setFileMode(self, mode: int) -> None:
                calls["file_mode"] = mode

            def setNameFilter(self, name_filter: str) -> None:
                calls["set_name_filter"] = name_filter

            def setOption(self, option: int, enabled: bool) -> None:
                self.options.append((option, enabled))
                calls["options"] = self.options

            def setWindowModality(self, modality) -> None:
                calls["modality"] = modality

            def exec(self) -> int:
                return QDialog.Accepted

            def selectedFiles(self) -> list[str]:
                return ["chosen.pdf"]

        window = MainWindow()
        try:
            with patch("pdf_notes_reader.main.QFileDialog", FakeFileDialog):
                self.assertEqual(window._choose_pdf_file("Open PDF"), "chosen.pdf")
            self.assertEqual(calls["title"], "Open PDF")
            self.assertEqual(calls["file_mode"], FakeFileDialog.ExistingFile)
            self.assertIn((FakeFileDialog.DontUseNativeDialog, True), calls["options"])
            self.assertEqual(calls["modality"], Qt.ApplicationModal)
        finally:
            window.close()

    def test_outline_actions_use_pic_icons(self) -> None:
        window = MainWindow()
        try:
            expected_contents_buttons = {
                "OutlineMoreButton",
                "OutlineNewButton",
                "OutlineChildButton",
                "OutlineDeleteButton",
                "OutlineSaveButton",
            }
            expected_bookmark_buttons = {
                "BookmarkAddButton",
                "BookmarkDeleteButton",
            }
            expected_buttons = expected_contents_buttons | expected_bookmark_buttons
            buttons = {
                button.objectName(): button
                for button in window.outline_panel.findChildren(QToolButton)
                if button.objectName() in expected_buttons
            }

            self.assertEqual(set(buttons), expected_buttons)
            for button in buttons.values():
                self.assertEqual(button.text(), "")
                self.assertFalse(button.icon().isNull())
                self.assertEqual(button.iconSize().width(), 22)
                self.assertEqual(button.width(), 36)
                self.assertTrue(button.toolTip())
            self.assertEqual(buttons["OutlineChildButton"].toolTip(), "New subcontents item")
            self.assertIn("#OutlineMoreButton::menu-indicator", window.styleSheet())
            self.assertIn("image: none", window.styleSheet())

            more_menu = buttons["OutlineMoreButton"].menu()
            self.assertIsNotNone(more_menu)
            assert more_menu is not None
            actions_by_text = {action.text(): action for action in more_menu.actions()}
            self.assertIn("Expand all", actions_by_text)
            self.assertIn("Collapse all", actions_by_text)
            self.assertTrue(actions_by_text["Expand all"].icon().isNull())
            self.assertTrue(actions_by_text["Collapse all"].icon().isNull())

            contents_tab = window.outline_panel.findChild(QWidget, "ContentsTab")
            bookmarks_tab = window.outline_panel.findChild(QWidget, "BookmarksTab")
            self.assertIsNotNone(contents_tab)
            self.assertIsNotNone(bookmarks_tab)
            assert contents_tab is not None
            assert bookmarks_tab is not None
            self.assertEqual(
                {button.objectName() for button in contents_tab.findChildren(QToolButton) if button.objectName()},
                expected_contents_buttons,
            )
            self.assertEqual(
                {button.objectName() for button in bookmarks_tab.findChildren(QToolButton) if button.objectName()},
                expected_bookmark_buttons,
            )

            for icon_name in (
                "more.png",
                "expand.png",
                "foldall.png",
                "up-arrow.png",
                "down-arrow.png",
            ):
                icon_image = QImage(str(Path(__file__).resolve().parents[1] / "Pic" / icon_name))
                dark_pixels = [
                    icon_image.pixelColor(x, y)
                    for y in range(icon_image.height())
                    for x in range(icon_image.width())
                    if icon_image.pixelColor(x, y).alpha() > 0
                ]
                self.assertTrue(dark_pixels, icon_name)
                self.assertLessEqual(
                    max(max(pixel.red(), pixel.green(), pixel.blue()) for pixel in dark_pixels),
                    80,
                    icon_name,
                )
        finally:
            window.close()

    def test_pdf_outline_jumps_to_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "outline.pdf"
            document = fitz.open()
            for page_number in range(3):
                page = document.new_page(width=300, height=200)
                page.insert_text((40, 80), f"Outline PDF {page_number + 1}")
            document.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 3]])
            document.save(pdf_path)
            document.close()

            window = MainWindow()
            window.load_pdf(pdf_path)
            self.assertEqual(window.outline_panel.tree.topLevelItemCount(), 2)
            item = window.outline_panel.tree.topLevelItem(1)
            window.outline_panel.tree.itemPressed.emit(item, 0)
            self.assertEqual(window.page_index, 2)
            window.close()

    def test_bookmarks_are_shown_navigable_and_persisted_with_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "bookmarks.pdf"
            self._create_sample_pdf(pdf_path, page_count=6)

            window = MainWindow()
            try:
                window.resize(900, 600)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()
                window.scroll_area.verticalScrollBar().setValue(window.page_tops[2] + 40)
                self.app.processEvents()
                window._sync_current_page_from_scroll()
                before_scroll = window.scroll_area.verticalScrollBar().value()
                before_offset = before_scroll - window.page_tops[2]

                with patch("pdf_notes_reader.main.QInputDialog.getText", return_value=("Bookmark title", True)):
                    window.add_bookmark_for_page(1)

                self.assertEqual(len(window.bookmarks), 1)
                self.assertLessEqual(abs(window.scroll_area.verticalScrollBar().value() - before_scroll), 2)
                self.assertLessEqual(abs(window.scroll_area.verticalScrollBar().value() - window.page_tops[2] - before_offset), 2)
                _notes, _counters, bookmarks = load_notes_data(window.pdf_key)
                self.assertEqual(bookmarks[0].title, "Bookmark title")
                self.assertEqual(bookmarks[0].page_index, 1)

                window.reset_note_counters_to_current_notes()
                self.app.processEvents()
                self.assertLessEqual(abs(window.scroll_area.verticalScrollBar().value() - before_scroll), 2)
                self.assertLessEqual(abs(window.scroll_area.verticalScrollBar().value() - window.page_tops[2] - before_offset), 2)

                item = window.outline_panel.bookmark_tree.topLevelItem(0)
                window.go_to_page(0)
                window.outline_panel.bookmark_tree.itemPressed.emit(item, 0)
                self.assertEqual(window.page_index, 1)

                window.delete_bookmark(bookmarks[0].id)
                self.assertEqual(window.bookmarks, [])
                self.assertEqual(load_notes_data(window.pdf_key)[2], [])
            finally:
                window.close()

    def test_outline_edit_save_writes_pdf_and_refreshes_counter_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "outline-edit.pdf"
            self._create_sample_pdf(pdf_path, page_count=3, toc=[[1, "Intro", 1]])

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                original_key = window._counter_key(1)
                self.assertEqual(original_key, "toc:0:Intro")

                window.outline_panel.set_outline([[1, "Intro", 1], [1, "Methods", 2]])
                self.assertEqual(window._counter_key(1), original_key)

                window.save_outline_to_pdf()
                self.assertEqual(window.document.get_toc(), [[1, "Intro", 1], [1, "Methods", 2]])
                self.assertEqual(window._counter_key(1), "toc:1:Methods")
            finally:
                window.close()

            reopened = fitz.open(pdf_path)
            try:
                self.assertEqual(reopened.get_toc(), [[1, "Intro", 1], [1, "Methods", 2]])
            finally:
                reopened.close()

    def test_outline_items_can_be_created_nested_and_deleted_before_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "outline-actions.pdf"
            self._create_sample_pdf(pdf_path, page_count=2, toc=[])

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.go_to_page(1)
                with patch("pdf_notes_reader.main.QInputDialog.getText", return_value=("Parent", True)):
                    window.add_outline_item()
                parent = window.outline_panel.tree.topLevelItem(0)
                self.assertEqual(window.outline_panel.outline_toc(), [[1, "Parent", 2]])

                window.outline_panel.tree.setCurrentItem(parent)
                with patch("pdf_notes_reader.main.QInputDialog.getText", return_value=("Child", True)):
                    window.add_outline_child_item()
                self.assertEqual(window.outline_panel.outline_toc(), [[1, "Parent", 2], [2, "Child", 2]])

                child = parent.child(0)
                window.outline_panel.tree.setCurrentItem(child)
                window.delete_outline_item()
                self.assertEqual(window.outline_panel.outline_toc(), [[1, "Parent", 2]])
                self.assertEqual(window.document.get_toc(), [])
            finally:
                window.close()

    def test_fit_updates_when_outline_panel_is_toggled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "outline-fit.pdf"
            self._create_sample_pdf(pdf_path, page_count=4, toc=[[1, "Chapter 1", 1]])

            window = MainWindow()
            try:
                window.resize(1000, 700)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()
                window.go_to_page(2)
                self.app.processEvents()

                window.fit_page("width")
                zoom_with_outline = window.zoom
                self.assertEqual(window.page_index, 2)
                self.assertEqual(
                    window._page_display_size(window.page_index).width() + self._horizontal_page_margins(window),
                    window.scroll_area.viewport().width(),
                )

                window.set_outline_visible(False)
                self.app.processEvents()
                QTest.qWait(180)
                zoom_without_outline = window.zoom
                self.assertGreater(zoom_without_outline, zoom_with_outline)
                self.assertEqual(window.page_index, 2)
                self.assertEqual(
                    window._page_display_size(window.page_index).width() + self._horizontal_page_margins(window),
                    window.scroll_area.viewport().width(),
                )

                window.set_outline_visible(True)
                self.app.processEvents()
                QTest.qWait(180)
                self.assertLess(window.zoom, zoom_without_outline)
                self.assertEqual(window.page_index, 2)
                self.assertEqual(
                    window._page_display_size(window.page_index).width() + self._horizontal_page_margins(window),
                    window.scroll_area.viewport().width(),
                )

                window.fit_page("height")
                self.assertEqual(window.fit_mode, "height")
                self.assertEqual(window.page_index, 2)
                self.assertEqual(
                    window._page_display_size(window.page_index).height() + self._vertical_page_margins(window),
                    window.scroll_area.viewport().height(),
                )

                window.set_outline_visible(False)
                self.app.processEvents()
                QTest.qWait(320)
                self.assertEqual(window.page_index, 2)
                self.assertEqual(
                    window._page_display_size(window.page_index).height() + self._vertical_page_margins(window),
                    window.scroll_area.viewport().height(),
                )

                window.set_outline_visible(True)
                self.app.processEvents()
                QTest.qWait(320)
                self.assertEqual(window.page_index, 2)
                self.assertEqual(
                    window._page_display_size(window.page_index).height() + self._vertical_page_margins(window),
                    window.scroll_area.viewport().height(),
                )
            finally:
                window.close()

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
            with patch("pdf_notes_reader.main.QMessageBox.question", return_value=QMessageBox.Yes):
                with patch.object(window, "_choose_pdf_file", return_value=str(relocated_path)):
                    window.open_history_entry(old_key)

            self.assertEqual(window.pdf_key, old_key)
            self.assertEqual(window.pdf_path, relocated_path)
            self.assertEqual(window.page_index, 1)
            self.assertEqual(window.history_entries[0].path, str(relocated_path.resolve(strict=False)))
            window.close()

    @staticmethod
    def _create_sample_pdf(
        path: Path,
        page_count: int = 1,
        toc: list[list] | None = None,
        page_size: tuple[int, int] = (300, 200),
    ) -> None:
        document = fitz.open()
        for page_number in range(page_count):
            page = document.new_page(width=page_size[0], height=page_size[1])
            page.insert_text((40, 80), f"PDF smoke test {page_number + 1}")
        if toc:
            document.set_toc(toc)
        document.save(path)
        document.close()

    @staticmethod
    def _press_key(window: MainWindow, key: Qt.Key) -> None:
        event = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
        window.keyPressEvent(event)

    @staticmethod
    def _horizontal_page_margins(window: MainWindow) -> int:
        margins = window.pages_layout.contentsMargins()
        return margins.left() + margins.right()

    @staticmethod
    def _vertical_page_margins(window: MainWindow) -> int:
        margins = window.pages_layout.contentsMargins()
        return margins.top() + margins.bottom()


if __name__ == "__main__":
    unittest.main()
