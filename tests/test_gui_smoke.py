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
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QToolBar
from PySide6.QtWidgets import QMessageBox

from pdf_notes_reader.history import PdfHistoryEntry, save_history
from pdf_notes_reader.main import MainWindow, PdfCanvas, SettingsDialog
from pdf_notes_reader.main import render_markdown_preview
from pdf_notes_reader.notes import default_data_dir
from pdf_notes_reader.notes import load_notes
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
                self.assertEqual(sorted(window.page_canvases), [0, 1])
                self.assertEqual(window.page_index, 0)

                self._press_key(window, Qt.Key_Down)
                self.assertEqual(window.page_index, 1)
                self.assertEqual(sorted(window.page_canvases), [0, 1, 2])

                self._press_key(window, Qt.Key_Right)
                self.assertEqual(window.page_index, 2)
                self.assertEqual(sorted(window.page_canvases), [1, 2])

                self._press_key(window, Qt.Key_Up)
                self.assertEqual(window.page_index, 1)

                window.add_note(1, 0.25, 0.75)
                notes = load_notes(window.pdf_key)
                self.assertEqual(len(notes), 1)
                self.assertEqual(notes[0].page_index, 1)
                self.assertEqual(notes[0].x_norm, 0.25)
                self.assertEqual(notes[0].y_norm, 0.75)
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
        self.assertEqual(canvas._selected_rects_norm, [[0.1, 0.1, 0.5, 0.3]])

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
                self.assertEqual(window.page_spin.value(), 1)
                self.assertEqual(window.page_count_label.text(), "/ 3")
                self.assertFalse(window.prev_page_button.isEnabled())
                self.assertTrue(window.next_page_button.isEnabled())

                window.next_page_button.click()
                self.assertEqual(window.page_index, 1)
                self.assertEqual(window.page_spin.value(), 2)

                window.page_spin.setValue(3)
                self.assertEqual(window.page_index, 2)

                window.set_reading_mode("single")
                self.assertFalse(window.continuous_scroll)
                self.assertEqual(len(window.page_canvases), 1)

                window.set_reading_mode("continuous")
                self.assertTrue(window.continuous_scroll)
                self.assertEqual(sorted(window.page_canvases), [1, 2])
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

                window.reader_splitter.setSizes([0, 630, 774])
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
                self.assertGreater(current_canvas.x(), 0)
                self.assertFalse(window.scroll_area.horizontalScrollBar().isVisible())
                self.assertEqual(window.page_index, 1)
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
                self.assertEqual(sorted(window.page_canvases), [0, 1])
                self.assertLessEqual(window.pages_layout.count(), 4)
                self.assertIn(0, window.page_widgets)
                self.assertNotIn(5, window.page_canvases)

                window.scroll_area.verticalScrollBar().setValue(window.page_tops[5])
                self.app.processEvents()
                window._sync_current_page_from_scroll()
                self.assertEqual(window.page_index, 5)
                self.assertIn(5, window.page_canvases)
                self.assertLessEqual(window.pages_layout.count(), 5)
            finally:
                window.close()

    def test_note_export_button_writes_markdown_file_with_pdf_and_location_name(self) -> None:
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
                self.assertIn(str(tmp_path / "markdown"), window.note_panel.folder_label.text())

                window.add_note(0, 0.25, 0.75)
                window.note_panel.editor.setPlainText("# Exported\n\nBody")
                window.save_current_note(window.note_panel.editor.toPlainText())
                self.assertEqual(list(window.note_export_dir.glob("*.md")), [])

                window.export_current_note(window.note_panel.editor.toPlainText())

                markdown_files = list(window.note_export_dir.glob("*.md"))
                self.assertEqual(markdown_files, [])
                markdown_files = list((window.note_export_dir / "sample").glob("*.md"))
                self.assertEqual(len(markdown_files), 1)
                self.assertIn("sample", markdown_files[0].name)
                self.assertIn("Chapter One", markdown_files[0].name)
                self.assertTrue(markdown_files[0].name.endswith("-1.md"))
                self.assertEqual(markdown_files[0].read_text(encoding="utf-8"), "# Exported\n\nBody")
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
                self.assertEqual(window.notes[0].color, "#86efac")
                self.assertEqual(window.note_panel.current_note_id, window.notes[0].id)
                note_id = window.notes[0].id

                window.select_note(note_id)
                self.assertEqual(window.note_panel.current_note_id, note_id)
                window.set_note_color(note_id, "#93c5fd")
                self.assertEqual(window.notes[0].color, "#93c5fd")

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
                save_settings(window.settings)

                settings = load_settings()
                self.assertEqual(settings["note_marker_radius"], 13)
                self.assertEqual(settings["theme"], "white")
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
                labels = [label.text() for label in dialog.findChildren(QLabel)]
                self.assertIn("QDialog", window.styleSheet())
                self.assertNotIn("Theme files", labels)
                self.assertIn("Theme folder", labels)
            finally:
                dialog.close()
                window.close()

    def test_default_data_dir_is_project_local(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            expected = Path(__file__).resolve().parents[1] / ".local-data"
            self.assertEqual(default_data_dir(), expected)

    def test_toolbar_no_longer_exposes_mode_zoom_or_settings_controls(self) -> None:
        window = MainWindow()
        try:
            action_texts = [action.text() for toolbar in window.findChildren(QToolBar) for action in toolbar.actions()]
            self.assertIn("Home", action_texts)
            self.assertIn("Open", action_texts)
            self.assertIn("Reader", action_texts)
            self.assertNotIn("Continuous Scroll", action_texts)
            self.assertNotIn("Zoom In", action_texts)
            self.assertNotIn("Zoom Out", action_texts)
            self.assertNotIn("Settings", action_texts)
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
