"""Highlights/underlines: optional single note, summary grouped by section or page, Notes toggle."""

from __future__ import annotations

from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox

from pdf_factory import create_sample_pdf
from pdf_notes_reader.notes import Note, load_notes, shows_as_note
from pdf_notes_reader.services.annotation_summary import annotation_note_body, group_annotations, summary_markdown
from pdf_notes_reader.services.obsidian import has_file


def _annotation(page: int, text: str, *, note_type: str = "highlight", y: float = 0.2) -> Note:
    return Note.create(
        pdf_key="k",
        page_index=page,
        x_norm=0.5,
        y_norm=y,
        note_type=note_type,
        rects_norm=[[0.1, y, 0.4, y + 0.05]],
        selected_text=text,
        has_note=False,
    )


def test_groups_by_section_and_by_page_only_where_there_is_no_section():
    notes = [
        _annotation(4, "in chapter two"),
        _annotation(0, "before any section"),
        _annotation(2, "chapter one, later", y=0.6),
        _annotation(2, "chapter one, first", y=0.1, note_type="underline"),
        Note.create(pdf_key="k", page_index=2, x_norm=0.5, y_norm=0.5, markdown="# point"),
    ]

    def chapter(page: int):
        if page >= 4:
            return ("Chapter 2", 4)
        if page >= 1:
            return ("Chapter 1", 1)
        return None

    groups = group_annotations(notes, chapter)

    assert [(group.title, group.is_section) for group in groups] == [
        ("Page 1", False),
        ("Chapter 1", True),
        ("Chapter 2", True),
    ]
    assert [note.selected_text for note in groups[1].annotations] == ["chapter one, first", "chapter one, later"]


def test_groups_by_page_when_the_pdf_has_no_sections():
    notes = [_annotation(1, "b"), _annotation(0, "a"), _annotation(1, "c", y=0.5)]
    groups = group_annotations(notes, lambda _page: None)
    assert [(group.title, len(group.annotations)) for group in groups] == [("Page 1", 1), ("Page 2", 2)]


def test_summary_markdown_lists_marked_text_and_notes():
    highlight = _annotation(2, "key idea")
    highlight.has_note = True
    highlight.markdown = "# Chapter 1-1\n\n> key idea\n\nMy thought.\n"
    underline = _annotation(3, "detail", note_type="underline")
    groups = group_annotations([highlight, underline], lambda _page: ("Chapter 1", 1))

    text = summary_markdown("Book", groups)

    assert "## Chapter 1 (p.2)" in text
    assert "- ==key idea== (p.3)" in text
    assert "    My thought." in text
    assert "- <u>detail</u> (p.4)" in text
    assert annotation_note_body(underline) == ""


def test_legacy_annotations_with_only_the_generated_note_have_no_note():
    base = _annotation(0, "text").to_dict()
    del base["has_note"]
    generated = Note.from_dict({**base, "markdown": "# page-1-1\n\n> text\n> — [p.1](pdfnest://x)\n\n"})
    written = Note.from_dict({**base, "markdown": "# page-1-1\n\n> text\n\nI wrote this.\n"})
    point = Note.from_dict({**base, "note_type": "point", "markdown": ""})

    assert not generated.has_note and not shows_as_note(generated) and not has_file(generated)
    assert written.has_note and shows_as_note(written) and has_file(written)
    assert shows_as_note(point)


def test_annotation_has_at_most_one_note_and_deleting_it_keeps_the_highlight(tmp_path, window):
    pdf_path = create_sample_pdf(tmp_path / "sample.pdf", page_count=2)
    window.load_pdf(pdf_path)
    window.add_text_annotation(1, "underline", [[0.1, 0.2, 0.4, 0.25]], "marked", "#2563eb")
    annotation = window.notes[0]
    assert not annotation.has_note
    assert window.note_panel.visible_notes() == []

    window.add_annotation_note(annotation.id)
    window.note_panel.editor.setPlainText(annotation.markdown + "My note\n")
    window.save_current_note(window.note_panel.editor.toPlainText())
    window.add_annotation_note(annotation.id)  # Opens the same note; never a second one.

    assert len(window.notes) == 1
    assert [note.id for note in window.note_panel.visible_notes()] == [annotation.id]
    assert window.note_panel.current_note_id == annotation.id
    assert "My note" in window.note_panel.editor.toPlainText()

    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        window.delete_current_note()

    assert len(window.notes) == 1
    assert window.notes[0].note_type == "underline"
    assert not window.notes[0].has_note
    assert window.notes[0].markdown == ""
    assert window.note_panel.current_note_id is None
    assert window.note_panel.summary_annotation_ids() == [annotation.id]
    stored = load_notes(window.pdf_key)
    assert len(stored) == 1 and not stored[0].has_note


def test_summary_uses_sections_from_the_pdf_outline(tmp_path, window):
    pdf_path = create_sample_pdf(tmp_path / "toc.pdf", page_count=3, toc=[[1, "Intro", 2]])
    window.load_pdf(pdf_path)
    window.add_text_annotation(0, "highlight", [[0.1, 0.2, 0.4, 0.25]], "cover text")
    window.add_text_annotation(2, "highlight", [[0.1, 0.2, 0.4, 0.25]], "intro text")

    tree = window.note_panel.summary_tree
    titles = [tree.topLevelItem(index).text(0) for index in range(tree.topLevelItemCount())]
    assert titles == ["Page 1  (1)", "Intro  (1)"]
    assert tree.topLevelItem(1).child(0).text(0) == "p.3  intro text"

    window.note_export_dir = tmp_path / "export"
    path = window.export_annotation_summary()
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "## Page 1" in text and "## Intro (p.2)" in text and "==intro text== (p.3)" in text


def test_notes_button_shows_and_hides_the_notes_panel(tmp_path, window):
    pdf_path = create_sample_pdf(tmp_path / "sample.pdf")
    window.load_pdf(pdf_path)
    assert window.notes_toggle_button.isEnabled()
    assert window.notes_toggle_button.isChecked()

    window.notes_toggle_button.click()
    assert window.note_panel.isHidden()
    assert not window.notes_toggle_button.isChecked()
    assert not window.notes_action.isChecked()

    window.notes_toggle_button.click()
    assert not window.note_panel.isHidden()
    assert window.notes_toggle_button.isChecked()

    # Adding a note shows the panel again.
    window.set_notes_visible(False)
    window.add_note(0, 0.5, 0.5)
    assert not window.note_panel.isHidden()
    assert window.notes_toggle_button.isChecked()
