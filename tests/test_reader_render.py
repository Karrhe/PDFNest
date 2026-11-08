from gui_helpers import GuiTestCase  # noqa: I001 - sets sys.path and offscreen Qt first

import os
import tempfile
import time
from pathlib import Path
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from pdf_notes_reader.main import MainWindow, PdfCanvas
from pdf_notes_reader.notes import load_notes


class ReaderRenderTest(GuiTestCase):
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
            # Pages are rasterized at the screen's device pixel ratio (1.0 offscreen).
            self.assertEqual(window.canvas.render_device_pixel_ratio(), window.render_scale)
            self.assertEqual(window.render_scale, max(1.0, window.scroll_area.viewport().devicePixelRatioF()))

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

    def test_offscreen_pages_render_after_load_and_canvases_are_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "progressive.pdf"
            self._create_sample_pdf(pdf_path, page_count=12)

            window = MainWindow()
            try:
                window.resize(900, 600)
                window.show()
                window.load_pdf(pdf_path)
                # Only the pages on screen are rasterized during load; the buffer pages are pending.
                self.assertFalse(window.page_canvases[window.page_index].is_pending())
                pending = {page for page, canvas in window.page_canvases.items() if canvas.is_pending()}
                self.assertTrue(pending)
                self.assertEqual(window.page_canvases[max(pending)].size(), window._page_display_size(max(pending)))

                deadline = time.monotonic() + 5
                while any(canvas.is_pending() for canvas in window.page_canvases.values()) and time.monotonic() < deadline:
                    QTest.qWait(20)
                self.assertFalse(any(canvas.is_pending() for canvas in window.page_canvases.values()))

                kept = window.page_canvases[2]
                rasterizations = window.render_cache.rasterizations
                window.render_page(center_current=False)
                self.assertIs(window.page_canvases[2], kept)
                self.assertEqual(window.render_cache.rasterizations, rasterizations)
            finally:
                window.close()

    def test_continuous_scrolling_renders_pages_before_scrolling_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp_path / "data")
            pdf_path = tmp_path / "throttle.pdf"
            self._create_sample_pdf(pdf_path, page_count=30)

            window = MainWindow()
            try:
                window.resize(900, 600)
                window.show()
                window.load_pdf(pdf_path)
                self.app.processEvents()
                scroll_bar = window.scroll_area.verticalScrollBar()
                step = max(1, window.page_heights[0] // 4)
                for _ in range(40):  # one event every 10 ms: never a 35 ms pause
                    scroll_bar.setValue(scroll_bar.value() + step)
                    QTest.qWait(10)
                    if window.page_index >= 8:
                        break
                self.assertGreaterEqual(window.page_index, 8)
                self.assertIn(window.page_index, window.page_canvases)
            finally:
                window.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
