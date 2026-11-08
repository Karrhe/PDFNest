"""Library folders from disk, dragging books into folders, library sync between computers, Home
shortcuts, reader paging keys, touchpad zoom and the Storage settings page."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

import pdf_factory
from pdf_notes_reader.history import load_history, save_history, upsert_history_entry
from pdf_notes_reader.library import LibraryFolder, ensure_folder_path, load_library, save_library
from pdf_notes_reader.notes import default_data_dir, resolve_pdf_key
from pdf_notes_reader.services.library_import import plan_pdf_import
from pdf_notes_reader.settings import settings_path
from pdf_notes_reader.ui.canvas import wheel_zoom_delta
from pdf_notes_reader.ui.settings_dialog import SettingsDialog


def _tree(root: Path) -> dict[str, Path]:
    books = {
        "top": root / "Books" / "top.pdf",
        "physics": root / "Books" / "Physics" / "p.pdf",
        "quantum": root / "Books" / "Physics" / "Quantum" / "q.pdf",
    }
    for path in books.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf_factory.create_sample_pdf(path, page_count=2)
    (root / "Books" / "Empty").mkdir()
    return books


def _folder_paths(state) -> dict[str, str]:
    """folder id -> "A / B" path, for readable assertions."""
    by_id = {folder.id: folder for folder in state.folders}

    def path_of(folder) -> str:
        parts = [folder.name]
        while folder.parent_id in by_id:
            folder = by_id[folder.parent_id]
            parts.append(folder.name)
        return " / ".join(reversed(parts))

    return {folder.id: path_of(folder) for folder in state.folders if folder.id != "unfiled"}


# --- Adding a folder keeps its structure ---------------------------------------------------------


def test_plan_pdf_import_keeps_the_folder_structure(tmp_path) -> None:
    books = _tree(tmp_path)
    single = tmp_path / "single.pdf"
    pdf_factory.create_sample_pdf(single)
    planned = dict(plan_pdf_import([tmp_path / "Books", single]))
    assert planned[books["top"]] == ("Books",)
    assert planned[books["physics"]] == ("Books", "Physics")
    assert planned[books["quantum"]] == ("Books", "Physics", "Quantum")
    assert planned[single] == ()


def test_ensure_folder_path_reuses_existing_folders() -> None:
    state = load_library()
    first = ensure_folder_path(state, "", ["Books", "Physics"])
    again = ensure_folder_path(state, "", ["books", "PHYSICS"])
    assert first == again
    assert sorted(_folder_paths(state).values()) == ["Books", "Books / Physics"]


def test_adding_a_folder_builds_the_same_folders_in_the_library(tmp_path, window) -> None:
    books = _tree(tmp_path)
    library = load_library()
    shelf = LibraryFolder.create("Shelf")
    library.folders.append(shelf)
    save_library(library)

    window.add_pdfs_to_library([tmp_path / "Books"], shelf.id)

    library = load_library()
    paths = _folder_paths(library)
    assert sorted(paths.values()) == ["Shelf", "Shelf / Books", "Shelf / Books / Physics", "Shelf / Books / Physics / Quantum"]
    assert paths[library.assignments[resolve_pdf_key(books["top"])]] == "Shelf / Books"
    assert paths[library.assignments[resolve_pdf_key(books["physics"])]] == "Shelf / Books / Physics"
    assert paths[library.assignments[resolve_pdf_key(books["quantum"])]] == "Shelf / Books / Physics / Quantum"
    assert "Empty" not in " ".join(paths.values())  # folders without PDFs are not created

    # Adding it again creates no duplicates and keeps a book the user re-filed.
    elsewhere = LibraryFolder.create("Elsewhere")
    library.folders.append(elsewhere)
    library.assignments[resolve_pdf_key(books["top"])] = elsewhere.id
    save_library(library)
    window.add_pdfs_to_library([tmp_path / "Books"], shelf.id)
    library = load_library()
    assert len(_folder_paths(library)) == 5
    assert library.assignments[resolve_pdf_key(books["top"])] == elsewhere.id


def test_unfiled_book_moves_into_its_folder_when_the_folder_is_added(tmp_path, window) -> None:
    books = _tree(tmp_path)
    window.add_pdfs_to_library([books["physics"]])
    assert resolve_pdf_key(books["physics"]) not in load_library().assignments
    window.add_pdfs_to_library([tmp_path / "Books"])
    library = load_library()
    assert _folder_paths(library)[library.assignments[resolve_pdf_key(books["physics"])]] == "Books / Physics"


# --- Dragging a book onto a folder -----------------------------------------------------------------


def test_dropping_a_dragged_book_on_a_folder_files_it(tmp_path, window) -> None:
    pdf = pdf_factory.create_sample_pdf(tmp_path / "a.pdf")
    window.add_pdfs_to_library([pdf])
    key = resolve_pdf_key(pdf)
    library = load_library()
    folder = LibraryFolder.create("Physics")
    library.folders.append(folder)
    library.assignments[key] = folder.id
    save_library(library)
    window.resize(1000, 700)
    window.show()
    window.show_home()
    panel = window.history_panel
    panel.notebooks_button.click()
    tree = panel.folder_tree

    root = tree.topLevelItem(0)
    target = next(root.child(i) for i in range(root.childCount()) if root.child(i).data(0, Qt.UserRole) == folder.id)
    from PySide6.QtGui import QDragMoveEvent, QDropEvent

    mime = panel.entry_drag_mime(key)
    point = QPointF(tree.visualItemRect(target).center())
    move = QDragMoveEvent(point.toPoint(), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    tree.dragMoveEvent(move)
    assert move.isAccepted()
    # Dropping on the top level takes the book out of its folder.
    top_point = QPointF(tree.visualItemRect(root).center())
    tree.dropEvent(QDropEvent(top_point, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert key not in load_library().assignments
    tree.dropEvent(QDropEvent(point, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert load_library().assignments[key] == folder.id


def test_folder_tree_leaves_file_drops_to_the_library_panel(window) -> None:
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDragEnterEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("C:/x.pdf")])
    event = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.history_panel.folder_tree.dragEnterEvent(event)
    assert not event.isAccepted()


# --- Library changes from the other computer -----------------------------------------------------


def test_library_save_keeps_the_other_computers_changes() -> None:
    mine = load_library()  # this computer, loaded before the other one saved
    other = load_library()
    physics = LibraryFolder.create("Physics")
    other.folders.append(physics)
    other.assignments["book-b"] = physics.id
    other.archived["book-c"] = "2026-11-08T10:00:00+00:00"
    save_library(other)

    mine.aliases["book-a"] = "My title"
    save_library(mine)

    saved = load_library()
    assert physics.id in {folder.id for folder in saved.folders}
    assert saved.assignments["book-b"] == physics.id
    assert "book-c" in saved.archived
    assert saved.aliases["book-a"] == "My title"
    assert mine.assignments["book-b"] == physics.id  # the in-memory state is updated too


def test_library_removals_on_either_computer_stick() -> None:
    setup = load_library()
    setup.archived["book-a"] = "t"
    setup.assignments["book-b"] = "unfiled-x"
    save_library(setup)
    mine, other = load_library(), load_library()
    other.archived.pop("book-a")  # restored on the other computer
    save_library(other)
    mine.aliases["book-z"] = "x"  # unrelated change here, from a stale copy
    save_library(mine)
    assert "book-a" not in load_library().archived


def test_window_shows_books_added_on_the_other_computer(tmp_path, window) -> None:
    pdf = pdf_factory.create_sample_pdf(tmp_path / "from-mac.pdf")
    key = resolve_pdf_key(pdf)
    # The other computer (another process) saved the shared recentnotes.json.
    other = []
    upsert_history_entry(other, pdf_key=key, path=pdf, page_count=1, last_page_index=0)
    (default_data_dir() / "recentnotes.json").parent.mkdir(parents=True, exist_ok=True)
    (default_data_dir() / "recentnotes.json").write_text(
        json.dumps({"schema_version": 1, "entries": [entry.to_dict() for entry in other]}), encoding="utf-8"
    )

    window.show_home()
    assert key in {entry.pdf_key for entry in window.history_entries}
    assert key in {entry.pdf_key for entry in window.history_panel.entries}


# --- Home shortcuts --------------------------------------------------------------------------------


def test_d_moves_the_selected_book_to_the_archive(tmp_path, window) -> None:
    pdf = pdf_factory.create_sample_pdf(tmp_path / "a.pdf")
    window.add_pdfs_to_library([pdf])
    key = resolve_pdf_key(pdf)
    window.show()
    window.show_home()
    panel = window.history_panel
    panel.selected_pdf_key = key

    panel.search_edit.setFocus()
    QTest.keyClick(panel.search_edit, Qt.Key_D)
    assert panel.search_edit.text() == "d"  # typing in the search field is untouched
    assert key not in load_library().archived
    panel.search_edit.clear()

    panel.setFocus()
    QTest.keyClick(panel, Qt.Key_D)
    assert key in load_library().archived


def test_delete_key_works_with_focus_anywhere_on_home(tmp_path, window) -> None:
    pdf = pdf_factory.create_sample_pdf(tmp_path / "a.pdf")
    window.add_pdfs_to_library([pdf])
    key = resolve_pdf_key(pdf)
    window.show()
    window.show_home()
    window.history_panel.selected_pdf_key = key
    window.history_panel.notebooks_button.setFocus()
    QTest.keyClick(window.history_panel.notebooks_button, Qt.Key_Delete)
    assert key in load_library().archived


# --- Reader keys and touchpad zoom -------------------------------------------------------------------


def test_left_and_right_turn_pages_whichever_reader_part_has_focus(tmp_path, window) -> None:
    pdf = pdf_factory.create_sample_pdf(tmp_path / "a.pdf", page_count=4)
    window.resize(1000, 700)
    window.show()
    window.load_pdf(pdf)
    for target in (window.scroll_area, window.scroll_area.viewport(), window.page_canvases.get(0) or window.scroll_area):
        target.setFocus()
        window.go_to_page(1)
        QTest.keyClick(target, Qt.Key_Right)
        assert window.page_index == 2, type(target).__name__
        QTest.keyClick(target, Qt.Key_Left)
        assert window.page_index == 1
    # A text field keeps its arrow keys.
    window.find_bar.show() if hasattr(window, "find_bar") else None
    window.zoom_spin.setFocus()
    QTest.keyClick(window.zoom_spin, Qt.Key_Right)
    assert window.page_index == 1


def test_trackpad_pinch_zooms(tmp_path, window) -> None:
    pdf = pdf_factory.create_sample_pdf(tmp_path / "a.pdf", page_count=2)
    window.show()
    window.load_pdf(pdf)
    before = window.zoom

    class Pinch:  # QNativeGestureEvent (macOS trackpad), as far as the reader looks at it
        def type(self):
            return QEvent.NativeGesture

        def gestureType(self):  # noqa: N802 - Qt name
            return Qt.ZoomNativeGesture

        def value(self):
            return 0.2  # +20 %

        def accept(self):
            self.accepted = True

    assert window.eventFilter(window.scroll_area.viewport(), Pinch())
    assert abs(window.zoom - before * 1.2) < 0.01


def test_touchpad_ctrl_wheel_steps_zoom_proportionally() -> None:
    class Wheel:
        def __init__(self, angle: int, pixel: int = 0) -> None:
            self._angle, self._pixel = angle, pixel

        def angleDelta(self):  # noqa: N802 - Qt name
            return QPoint(0, self._angle)

        def pixelDelta(self):  # noqa: N802 - Qt name
            return QPoint(0, self._pixel)

    assert wheel_zoom_delta(Wheel(120)) == 0.1  # one mouse-wheel notch, as before
    assert abs(wheel_zoom_delta(Wheel(12)) - 0.01) < 1e-9  # one small touchpad step
    assert wheel_zoom_delta(Wheel(-2400)) == -0.25  # capped
    assert wheel_zoom_delta(Wheel(0, 24)) > 0


# --- Storage settings page ----------------------------------------------------------------------------


def test_storage_page_shows_each_path_once(tmp_path, window) -> None:
    data_dir = default_data_dir()
    dialog = SettingsDialog(
        settings=window.settings,
        themes=window.themes,
        data_dir=data_dir,
        note_json_path=data_dir / "notebooks" / "a" / "note" / "notes.json",
        markdown_dir=tmp_path / "md",
        theme_dir=data_dir / "themes",
    )
    try:
        row_labels = [label.text() for label in dialog.findChildren(QLabel, "SettingsPathLabel")]
        assert "Data folder" not in row_labels
        assert row_labels.count("PDFNest data folder") == 1
        texts = [label.text() for label in dialog.findChildren(QLabel)]
        assert not any(text == str(data_dir) for text in texts)  # only in the editable field
        assert any(text.endswith(str(Path("notebooks") / "a" / "note" / "notes.json")) and text.startswith("…") for text in texts)
        assert any(label.toolTip() == str(settings_path(data_dir)) for label in dialog.findChildren(QLabel))
    finally:
        dialog.close()


def test_adding_the_pdf_on_a_second_computer_attaches_it_to_the_book(tmp_path, window, monkeypatch) -> None:
    import pdf_notes_reader.history as history_module
    import pdf_notes_reader.notes as notes_module
    from pdf_notes_reader.notes import machine_id

    this_computer = machine_id()
    # The book was added on another computer, from a path that does not exist here.
    for module in (history_module, notes_module):
        monkeypatch.setattr(module, "machine_id", lambda: "other-computer")
    elsewhere = tmp_path / "other-computer" / "a.pdf"
    elsewhere.parent.mkdir()
    pdf_factory.create_sample_pdf(elsewhere, page_count=3)
    key = resolve_pdf_key(elsewhere)
    entries = []
    upsert_history_entry(entries, pdf_key=key, path=elsewhere, page_count=3, last_page_index=2)
    save_history(entries, touched_pdf_keys={key})  # with the notebook (manifest, cover), as that computer did
    for module in (history_module, notes_module):
        monkeypatch.setattr(module, "machine_id", lambda: this_computer)
    here = tmp_path / "here" / "a copy.pdf"
    here.parent.mkdir()
    shutil.copy2(elsewhere, here)
    shutil.rmtree(elsewhere.parent)
    window.refresh_library_from_disk(force=True)
    [entry] = window.history_entries
    assert not entry.exists and not entry.located_here

    added, already = window.add_pdfs_to_library([here])
    assert (added, already) == (0, 1)
    [entry] = window.history_entries
    assert Path(entry.path) == here.resolve() and entry.located_here
    assert entry.last_page_index == 2  # reading position kept
    saved = json.loads((default_data_dir() / "recentnotes.json").read_text(encoding="utf-8"))["entries"][0]
    assert saved["machine_paths"] == {"other-computer": str(elsewhere), machine_id(): str(here.resolve())}
