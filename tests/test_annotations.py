from gui_helpers import GuiTestCase  # noqa: I001 - sets sys.path and offscreen Qt first

import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QContextMenuEvent, QImage, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from pdf_notes_reader.main import MainWindow, PdfCanvas
from pdf_notes_reader.notes import Note
from pdf_notes_reader.notes import load_notes


class AnnotationsTest(GuiTestCase):
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
        with patch("pdf_notes_reader.ui.canvas.QMenu", FakeMenu):
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
        with patch("pdf_notes_reader.ui.canvas.QMenu", FakeMenu):
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
        with patch("pdf_notes_reader.ui.canvas.QMenu", FakeMenu):
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
        with patch("pdf_notes_reader.ui.canvas.QMenu", FakeMenu):
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
        with patch("pdf_notes_reader.ui.canvas.QMenu", FakeMenu):
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
        with patch("pdf_notes_reader.ui.canvas.QMenu", FakeMenu):
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
        with patch("pdf_notes_reader.ui.canvas.QMenu", FakeMenu):
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


if __name__ == "__main__":
    import unittest

    unittest.main()
