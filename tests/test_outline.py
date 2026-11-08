from gui_helpers import GuiTestCase  # noqa: I001 - sets sys.path and offscreen Qt first

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import fitz
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QToolButton, QWidget
from pdf_notes_reader.main import MainWindow
from pdf_notes_reader.notes import load_notes_data


class OutlineTest(GuiTestCase):
    def test_new_note_number_stays_on_first_line_when_outline_title_wraps(self) -> None:
        window = MainWindow()
        try:
            window.document = SimpleNamespace(get_toc=lambda: [[1, "1 Introduction\n", 15]], close=lambda: None, page_count=20)
            self.assertEqual(window._default_note_title(14, 10), "1 Introduction-10")
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

                with patch("pdf_notes_reader.ui.main_window.QInputDialog.getText", return_value=("Bookmark title", True)):
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

                with patch("pdf_notes_reader.ui.main_window.QMessageBox.question", return_value=QMessageBox.Yes):
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
                with patch("pdf_notes_reader.ui.main_window.QInputDialog.getText", return_value=("Parent", True)):
                    window.add_outline_item()
                parent = window.outline_panel.tree.topLevelItem(0)
                self.assertEqual(window.outline_panel.outline_toc(), [[1, "Parent", 2]])

                window.outline_panel.tree.setCurrentItem(parent)
                with patch("pdf_notes_reader.ui.main_window.QInputDialog.getText", return_value=("Child", True)):
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

    def test_outline_save_on_bom_prefixed_pdf_keeps_file_valid_notes_and_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "prefixed.pdf"
            self._create_sample_pdf(pdf_path, page_count=4, toc=[[1, "Intro", 1]])
            original = bytes([0xEF, 0xBB, 0xBF]) + pdf_path.read_bytes()  # UTF-8 BOM before %PDF-
            pdf_path.write_bytes(original)

            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                key = window.pdf_key
                window.go_to_page(2)
                window.add_note(window.page_index, 0.4, 0.4)
                note_count = len(window.notes)
                window.outline_panel.set_outline([[1, "Intro", 1], [1, "Methods", 3]])
                with patch("pdf_notes_reader.ui.main_window.QMessageBox.question", return_value=QMessageBox.Yes):
                    window.save_outline_to_pdf()

                self.assertFalse(window.document.is_closed)
                self.assertEqual(window.document.get_toc(), [[1, "Intro", 1], [1, "Methods", 3]])
                self.assertEqual(window.pdf_key, key)
                self.assertEqual(len(window.notes), note_count)
                self.assertIs(window.pdf_tabs[key].document, window.document)
            finally:
                window.close()

            self.assertEqual((tmp_path / "prefixed.pdf.pdfnest.bak").read_bytes(), original)
            self.assertTrue(pdf_path.read_bytes().startswith(b"%PDF-"))
            reopened = fitz.open(pdf_path)
            try:
                self.assertFalse(reopened.is_repaired)
                self.assertEqual(reopened.get_toc(), [[1, "Intro", 1], [1, "Methods", 3]])
            finally:
                reopened.close()
            self.assertEqual(len(load_notes_data(key)[0]), note_count)

    def test_outline_save_refuses_signed_pdf_without_touching_it(self) -> None:
        import pdf_factory

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = pdf_factory.create_signed_like_pdf(tmp_path / "signed.pdf")
            before = pdf_path.read_bytes()
            window = MainWindow()
            try:
                window.load_pdf(pdf_path)
                window.outline_panel.set_outline([[1, "Intro", 1]])
                with patch("pdf_notes_reader.ui.main_window.QMessageBox.warning") as warning, patch(
                    "pdf_notes_reader.ui.main_window.QMessageBox.question"
                ) as question:
                    window.save_outline_to_pdf()
                self.assertIn("signed", warning.call_args.args[2])
                question.assert_not_called()
            finally:
                window.close()
            self.assertEqual(pdf_path.read_bytes(), before)


if __name__ == "__main__":
    import unittest

    unittest.main()
