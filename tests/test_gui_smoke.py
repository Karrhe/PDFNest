import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fitz
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QMessageBox

from pdf_notes_reader.history import PdfHistoryEntry, save_history
from pdf_notes_reader.main import MainWindow, PdfCanvas
from pdf_notes_reader.main import render_markdown_preview
from pdf_notes_reader.notes import load_notes
from pdf_notes_reader.notes import pdf_key_for_path


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
            window.load_pdf(pdf_path)

            self.assertTrue(window.continuous_scroll)
            self.assertEqual(len(window.page_canvases), 3)
            self.assertEqual(window.page_index, 0)

            self._press_key(window, Qt.Key_Down)
            self.assertEqual(window.page_index, 1)

            self._press_key(window, Qt.Key_Right)
            self.assertEqual(window.page_index, 2)

            self._press_key(window, Qt.Key_Up)
            self.assertEqual(window.page_index, 1)

            window.add_note(1, 0.25, 0.75)
            notes = load_notes(window.pdf_key)
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0].page_index, 1)
            self.assertEqual(notes[0].x_norm, 0.25)
            self.assertEqual(notes[0].y_norm, 0.75)
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
        self.assertIn("<sup>2</sup>", html)
        self.assertIn("latex-frac", html)
        self.assertIn("latex-sqrt", html)
        self.assertIn("<table>", html)
        self.assertNotIn("<p><div class=\"math-block\"", html)
        self.assertIn("margin: 4px 0 6px 0", html)
        self.assertIn("padding: 4px 8px", html)

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

                target_canvas = first_window.page_canvases[3]
                first_window.scroll_area.verticalScrollBar().setValue(target_canvas.y())
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
                with patch(
                    "pdf_notes_reader.main.QFileDialog.getOpenFileName",
                    return_value=(str(relocated_path), "PDF files (*.pdf)"),
                ):
                    window.open_history_entry(old_key)

            self.assertEqual(window.pdf_key, old_key)
            self.assertEqual(window.pdf_path, relocated_path)
            self.assertEqual(window.page_index, 1)
            self.assertEqual(window.history_entries[0].path, str(relocated_path.resolve(strict=False)))
            window.close()

    @staticmethod
    def _create_sample_pdf(path: Path, page_count: int = 1) -> None:
        document = fitz.open()
        for page_number in range(page_count):
            page = document.new_page(width=300, height=200)
            page.insert_text((40, 80), f"PDF smoke test {page_number + 1}")
        document.save(path)
        document.close()

    @staticmethod
    def _press_key(window: MainWindow, key: Qt.Key) -> None:
        event = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
        window.keyPressEvent(event)


if __name__ == "__main__":
    unittest.main()
