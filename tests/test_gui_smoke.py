import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fitz
from PySide6.QtWidgets import QApplication

from pdf_notes_reader.main import MainWindow
from pdf_notes_reader.notes import load_notes


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

    @staticmethod
    def _create_sample_pdf(path: Path) -> None:
        document = fitz.open()
        page = document.new_page(width=300, height=200)
        page.insert_text((40, 80), "PDF smoke test")
        document.save(path)
        document.close()


if __name__ == "__main__":
    unittest.main()
