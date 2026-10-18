from gui_helpers import GuiTestCase  # noqa: I001 - sets sys.path and offscreen Qt first

import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from pdf_notes_reader.main import MainWindow
from pdf_notes_reader.notes import load_notes


class NotesPanelExportTest(GuiTestCase):
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
                    "pdf_notes_reader.ui.main_window.QFileDialog.getExistingDirectory",
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


if __name__ == "__main__":
    import unittest

    unittest.main()
