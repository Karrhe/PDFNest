import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf_notes_reader.notes import Note, load_notes, pdf_key_for_path, save_notes


class NotesStorageTest(unittest.TestCase):
    def test_save_and_load_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            pdf_path = data_dir / "sample.pdf"
            pdf_key = pdf_key_for_path(pdf_path)
            note = Note.create(
                pdf_key=pdf_key,
                page_index=2,
                x_norm=0.25,
                y_norm=0.75,
                markdown="**hello**",
            )

            saved_path = save_notes(pdf_key=pdf_key, pdf_path=pdf_path, notes=[note], data_dir=data_dir)
            loaded = load_notes(pdf_key, data_dir=data_dir)

            self.assertTrue(saved_path.exists())
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].id, note.id)
            self.assertEqual(loaded[0].page_index, 2)
            self.assertEqual(loaded[0].x_norm, 0.25)
            self.assertEqual(loaded[0].y_norm, 0.75)
            self.assertEqual(loaded[0].markdown, "**hello**")

    def test_normalized_coordinates_are_clamped(self) -> None:
        note = Note.create(pdf_key="abc", page_index=0, x_norm=-1, y_norm=2)

        self.assertEqual(note.x_norm, 0.0)
        self.assertEqual(note.y_norm, 1.0)


if __name__ == "__main__":
    unittest.main()
