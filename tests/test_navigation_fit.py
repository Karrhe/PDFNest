from gui_helpers import GuiTestCase  # noqa: I001 - sets sys.path and offscreen Qt first

import os
import tempfile
from pathlib import Path
import fitz
from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabBar, QToolButton
from pdf_notes_reader.main import MainWindow
from pdf_notes_reader.notes import load_notes
from pdf_notes_reader.notes import pdf_key_for_path


class NavigationFitTest(GuiTestCase):
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


if __name__ == "__main__":
    import unittest

    unittest.main()
