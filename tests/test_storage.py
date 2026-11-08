import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui_helpers import StorageIsolationMixin  # noqa: E402

from pdf_notes_reader.notes import Bookmark, Note, load_notes, load_notes_data, load_notes_with_counters, pdf_key_for_path, save_notes
from pdf_notes_reader.storage_migration import migrate_storage
from pdf_notes_reader.history import load_history


class NotesStorageTest(StorageIsolationMixin, unittest.TestCase):
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
                color="#93c5fd",
                note_number=4,
                exported_markdown_path=str(data_dir / "markdown_notes" / "sample" / "note.md"),
            )

            bookmark = Bookmark.create(pdf_key=pdf_key, page_index=2, title="Important")
            saved_path = save_notes(
                pdf_key=pdf_key,
                pdf_path=pdf_path,
                notes=[note],
                note_counters={"2": 5},
                bookmarks=[bookmark],
                data_dir=data_dir,
            )
            loaded, counters, bookmarks = load_notes_data(pdf_key, data_dir=data_dir)

            self.assertTrue(saved_path.exists())
            self.assertEqual(saved_path, data_dir / "notebooks" / "sample" / "note" / "notes.json")
            self.assertTrue((data_dir / "notebooks" / "sample" / "note").is_dir())
            self.assertTrue((data_dir / "notebooks" / "sample" / "manifest.json").exists())
            self.assertTrue((data_dir / "notebooks" / "sample" / "markups.json").exists())
            self.assertTrue((data_dir / "notebooks" / "sample" / "recentfile.json").exists())
            self.assertTrue((data_dir / "bookmarks" / f"{pdf_key}_bookmark.json").exists())
            self.assertTrue((data_dir / "bookmarks" / "sync.lock").exists())
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].id, note.id)
            self.assertEqual(loaded[0].page_index, 2)
            self.assertEqual(loaded[0].x_norm, 0.25)
            self.assertEqual(loaded[0].y_norm, 0.75)
            self.assertEqual(loaded[0].markdown, "**hello**")
            self.assertEqual(loaded[0].color, "#93c5fd")
            self.assertEqual(loaded[0].note_number, 4)
            self.assertEqual(loaded[0].exported_markdown_path, str(data_dir / "markdown_notes" / "sample" / "note.md"))
            self.assertEqual(counters, {"2": 5})
            self.assertEqual(bookmarks[0].title, "Important")
            self.assertEqual(bookmarks[0].page_index, 2)
            self.assertEqual(load_notes_with_counters(pdf_key, data_dir=data_dir)[1], {"2": 5})
            self.assertEqual(load_notes(pdf_key, data_dir=data_dir)[0].note_number, 4)

    def test_normalized_coordinates_are_clamped(self) -> None:
        note = Note.create(pdf_key="abc", page_index=0, x_norm=-1, y_norm=2)

        self.assertEqual(note.x_norm, 0.0)
        self.assertEqual(note.y_norm, 1.0)

    def test_migrates_legacy_history_and_notes_to_notebook_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            pdf_path = data_dir / "legacy.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
            pdf_key = pdf_key_for_path(pdf_path)
            note = Note.create(pdf_key=pdf_key, page_index=1, x_norm=0.2, y_norm=0.3, markdown="legacy")
            bookmark = Bookmark.create(pdf_key=pdf_key, page_index=1, title="Legacy bookmark")

            legacy_notes_dir = data_dir / "notes"
            legacy_notes_dir.mkdir()
            with (legacy_notes_dir / f"{pdf_key}.json").open("w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "pdf_key": pdf_key,
                        "pdf_path": str(pdf_path),
                        "schema_version": 1,
                        "note_counters": {"1": 2},
                        "bookmarks": [bookmark.to_dict()],
                        "notes": [note.to_dict()],
                    },
                    handle,
                )
            with (data_dir / "pdf_history.json").open("w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema_version": 1,
                        "entries": [
                            {
                                "pdf_key": pdf_key,
                                "path": str(pdf_path),
                                "title": pdf_path.name,
                                "last_page_index": 1,
                                "page_count": 3,
                                "opened_at": "2026-01-01T00:00:00+00:00",
                                "updated_at": "2026-01-01T00:00:00+00:00",
                            }
                        ],
                    },
                    handle,
                )

            self.assertTrue(migrate_storage(data_dir, legacy_roots=[data_dir]))

            notebook_dir = data_dir / "notebooks" / "legacy"
            self.assertTrue((data_dir / "recentnotes.json").exists())
            self.assertTrue((data_dir / "notebooks" / "index.json").exists())
            self.assertTrue((notebook_dir / "note" / "notes.json").exists())
            loaded_notes, counters, bookmarks = load_notes_data(pdf_key, data_dir=data_dir)
            self.assertEqual(loaded_notes[0].markdown, "legacy")
            self.assertEqual(counters, {"1": 2})
            self.assertEqual(bookmarks[0].title, "Legacy bookmark")
            self.assertEqual(load_history(data_dir)[0].last_page_index, 1)


if __name__ == "__main__":
    unittest.main()
