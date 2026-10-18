"""Data-integrity guarantees for the external note store: corrupt files never cause silent data loss."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pdf_notes_reader import notes as notes_module
from pdf_notes_reader.history import PdfHistoryEntry, load_history, save_history, upsert_history_entry
from pdf_notes_reader.library import LibraryFolder, load_library, save_library
from pdf_notes_reader.notes import (
    Bookmark,
    Note,
    drain_storage_issues,
    load_notes_data,
    notebook_index_path,
    notes_path_for_key,
    pdf_key_for_path,
    save_notes,
)
from pdf_notes_reader.settings import load_settings, save_settings


def _note(pdf_key: str, page: int = 0, text: str = "# keep me") -> Note:
    return Note.create(pdf_key=pdf_key, page_index=page, x_norm=0.5, y_norm=0.5, markdown=text, note_number=1)


def _save(pdf_path: Path, notes: list[Note], **kwargs) -> Path:
    return save_notes(pdf_key=pdf_key_for_path(pdf_path), pdf_path=pdf_path, notes=notes, **kwargs)


@pytest.fixture(autouse=True)
def _clear_issues():
    drain_storage_issues()
    yield
    drain_storage_issues()


def test_round_trip_preserves_notes_counters_bookmarks_and_unicode(tmp_path):
    pdf_path = tmp_path / "论文 — 长名字.pdf"
    key = pdf_key_for_path(pdf_path)
    note = _note(key, page=3, text="## 公式 $\\alpha$ ✓\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    bookmark = Bookmark.create(pdf_key=key, page_index=2, title="第二章")
    _save(pdf_path, [note], note_counters={"3": 5}, bookmarks=[bookmark])

    loaded, counters, bookmarks = load_notes_data(key)

    assert [n.to_dict() for n in loaded] == [note.to_dict()]
    assert counters == {"3": 5}
    assert [b.to_dict() for b in bookmarks] == [bookmark.to_dict()]


def test_same_named_pdfs_in_different_folders_get_separate_notebooks(tmp_path):
    first = tmp_path / "a" / "paper.pdf"
    second = tmp_path / "b" / "paper.pdf"
    path_one = _save(first, [_note(pdf_key_for_path(first), text="first")])
    path_two = _save(second, [_note(pdf_key_for_path(second), text="second")])

    assert path_one != path_two
    assert load_notes_data(pdf_key_for_path(first))[0][0].markdown == "first"
    assert load_notes_data(pdf_key_for_path(second))[0][0].markdown == "second"


def test_corrupt_notes_file_is_quarantined_not_overwritten(tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    key = pdf_key_for_path(pdf_path)
    notes_file = _save(pdf_path, [_note(key)])
    original = notes_file.read_text(encoding="utf-8")
    notes_file.write_text(original[: len(original) // 2], encoding="utf-8")  # truncated write

    loaded, _counters, _bookmarks = load_notes_data(key)
    assert loaded == []
    issues = drain_storage_issues()
    assert len(issues) == 1 and "notes.json" in issues[0].message

    quarantined = issues[0].quarantined_path
    assert quarantined is not None and quarantined.exists()
    assert quarantined.read_text(encoding="utf-8") == original[: len(original) // 2]

    # Saving afterwards must not destroy the quarantined copy.
    _save(pdf_path, [_note(key, text="new")])
    assert quarantined.exists()


def test_corrupt_notebook_index_still_finds_existing_notes(tmp_path):
    pdf_path = tmp_path / "indexed.pdf"
    key = pdf_key_for_path(pdf_path)
    _save(pdf_path, [_note(key, text="still here")])
    notebook_index_path().write_text("{ not json", encoding="utf-8")

    loaded, _counters, _bookmarks = load_notes_data(key)
    assert [n.markdown for n in loaded] == ["still here"]

    # And a save goes back to the same notebook rather than a fresh empty one.
    path_after = _save(pdf_path, loaded + [_note(key, text="added")])
    assert [n.markdown for n in load_notes_data(key)[0]] == ["still here", "added"]
    assert path_after == notes_path_for_key(key)


def test_stale_index_without_entry_still_finds_notes(tmp_path):
    pdf_path = tmp_path / "stale.pdf"
    key = pdf_key_for_path(pdf_path)
    _save(pdf_path, [_note(key, text="kept")])
    notebook_index_path().write_text(json.dumps({"schema_version": 1, "notebooks": {}}), encoding="utf-8")

    assert [n.markdown for n in load_notes_data(key)[0]] == ["kept"]


def test_failed_replace_keeps_previous_file_and_no_temp_leftovers(tmp_path, monkeypatch):
    pdf_path = tmp_path / "atomic.pdf"
    key = pdf_key_for_path(pdf_path)
    notes_file = _save(pdf_path, [_note(key, text="v1")])

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(notes_module.os, "replace", boom)
    with pytest.raises(OSError):
        _save(pdf_path, [_note(key, text="v2")])
    monkeypatch.undo()

    assert json.loads(notes_file.read_text(encoding="utf-8"))["notes"][0]["markdown"] == "v1"
    assert not [p for p in notes_file.parent.iterdir() if p.name.endswith(".tmp")]


def test_note_save_keeps_manifest_page_count_and_recent_page(tmp_path):
    pdf_path = tmp_path / "meta.pdf"
    key = pdf_key_for_path(pdf_path)
    entries: list[PdfHistoryEntry] = []
    upsert_history_entry(entries, pdf_key=key, path=pdf_path, page_count=40, last_page_index=17)
    save_history(entries, touched_pdf_keys={key})
    notebook = notes_path_for_key(key).parent.parent

    _save(pdf_path, [_note(key, page=2)])

    manifest = json.loads((notebook / "manifest.json").read_text(encoding="utf-8"))
    recent = json.loads((notebook / "recentfile.json").read_text(encoding="utf-8"))
    assert manifest["res"][0]["page_count"] == 40
    assert recent[0]["~view"][0] == 17


def test_corrupt_history_does_not_crash_and_is_quarantined(isolated_storage):
    path = isolated_storage / "recentnotes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"entries": [', encoding="utf-8")

    assert load_history() == []
    issues = drain_storage_issues()
    assert issues and issues[0].quarantined_path.exists()


def test_corrupt_settings_fall_back_to_defaults(isolated_storage):
    path = isolated_storage / "user_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{oops", encoding="utf-8")

    settings = load_settings()
    assert settings["theme"]
    assert drain_storage_issues()


def test_corrupt_library_is_quarantined_before_reset(isolated_storage):
    state = load_library()
    state.folders.append(LibraryFolder.create("Physics"))
    save_library(state)
    path = isolated_storage / "library.json"
    good = path.read_text(encoding="utf-8")
    path.write_text(good[:20], encoding="utf-8")

    reset = load_library()
    assert all(folder.name != "Physics" for folder in reset.folders)
    issues = drain_storage_issues()
    assert issues and issues[0].quarantined_path.read_text(encoding="utf-8") == good[:20]


def test_writers_use_unique_temp_files(isolated_storage, monkeypatch):
    seen: list[str] = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(notes_module.os, "replace", spy)
    save_settings(load_settings())
    save_library(load_library())
    save_history([])
    assert len(seen) >= 3
    assert len(set(seen)) == len(seen)


@pytest.mark.gui
def test_window_reports_corrupt_notes_without_blocking(tmp_path, window):
    import pdf_factory

    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "gui.pdf", page_count=2)
    key = pdf_key_for_path(pdf_path)
    notes_file = _save(pdf_path, [_note(key)])
    notes_file.write_text("{", encoding="utf-8")

    window.load_pdf(pdf_path)

    assert window.notes == []
    box = window.last_storage_issue_box
    assert box.isVisible() and not box.isModal()
    assert "notes.json" in box.detailedText()
    assert list(notes_file.parent.glob("notes.corrupt-*.json"))
