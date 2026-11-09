"""Obsidian vault sync: the file format and sync rules, and the reader's use of them."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import pdf_factory
from pdf_notes_reader.notes import Note, load_notes
from pdf_notes_reader.services import obsidian
from pdf_notes_reader.services.obsidian import (
    INDEX_NAME,
    VaultConfig,
    parse_note_file,
    parse_pdfnest_url,
    pdfnest_url,
    pull_notes,
    push_notes,
    render_note_file,
    trash_note_file,
)

PDF = Path(r"F:\books\An Intro (Mantegna) [z-lib] #2.pdf")


def _note(markdown: str = "# Scaling-1\n\n> 中文 quote\n", page: int = 24, **extra) -> Note:
    return Note.create(pdf_key="k", page_index=page, x_norm=0.5, y_norm=0.5, markdown=markdown, **extra)


def _push(config: VaultConfig, notes: list[Note]) -> obsidian.SyncReport:
    return push_notes(config, PDF, notes, lambda note: f"page-{note.page_index + 1}-1")


# --- service --------------------------------------------------------------------------------------


def test_note_file_layout_and_front_matter(tmp_path) -> None:
    config = VaultConfig(tmp_path / "vault")
    note = _note()
    _push(config, [note])

    path = config.vault_dir / note.vault_path
    assert path.parent == config.root / "An Intro (Mantegna) (z-lib) -2"  # no [ ] # in wiki-link targets
    assert path.name == "p25 Scaling-1.md"
    text = path.read_text(encoding="utf-8")
    blocks, body = parse_note_file(text)
    assert obsidian.front_matter_value(blocks, "pdfnest_id") == note.id
    assert obsidian.front_matter_value(blocks, "pdf") == str(PDF)
    assert obsidian.front_matter_value(blocks, "page") == "25"
    assert body == note.markdown
    request = parse_pdfnest_url(obsidian.front_matter_value(blocks, "link"))
    assert request == obsidian.OpenRequest(PDF, 25, note.id, note.pdf_key)

    index = (path.parent / INDEX_NAME).read_text(encoding="utf-8")
    assert "[[PDFNest/An Intro (Mantegna) (z-lib) -2/p25 Scaling-1|Scaling-1]]" in index


def test_excerpt_markers_get_no_file(tmp_path) -> None:
    config = VaultConfig(tmp_path / "vault")
    parent = _note()
    excerpt = _note("", note_type="excerpt", linked_note_id=parent.id)
    _push(config, [parent, excerpt])
    assert excerpt.vault_path == ""
    assert len(list(config.root.rglob("p*.md"))) == 1


def test_long_titles_and_title_free_notes_get_safe_names(tmp_path) -> None:
    config = VaultConfig(tmp_path / "vault")
    long_note = _note("# " + "非常长的标题 " * 40 + "\n")
    quote_only = _note("> just a quote\n", page=3)
    _push(config, [long_note, quote_only])
    assert len(Path(long_note.vault_path).name) <= 93
    assert Path(quote_only.vault_path).name == "p4 page-4-1.md"


def test_pull_takes_obsidian_edits_and_keeps_user_properties(tmp_path) -> None:
    config = VaultConfig(tmp_path / "vault")
    note = _note()
    _push(config, [note])
    path = config.vault_dir / note.vault_path
    edited = path.read_text(encoding="utf-8").replace("\n---\n", "\ntags:\n  - physics\n---\n", 1) + "my thoughts\n"
    path.write_text(edited, encoding="utf-8")

    report = pull_notes(config, PDF, [note])
    assert report.pulled == [note.id]
    assert note.markdown.endswith("my thoughts\n")

    note.update_markdown(note.markdown + "more from PDFNest\n")
    _push(config, [note])
    text = path.read_text(encoding="utf-8")
    assert "tags:\n  - physics\n" in text  # Obsidian properties survive PDFNest's rewrite
    assert text.endswith("more from PDFNest\n")


def test_unchanged_files_are_not_rewritten(tmp_path) -> None:
    config = VaultConfig(tmp_path / "vault")
    note = _note()
    _push(config, [note])
    assert _push(config, [note]).written == []
    assert pull_notes(config, PDF, [note]).pulled == []


def test_edits_on_both_sides_keep_obsidian_text_and_save_a_conflict_copy(tmp_path) -> None:
    config = VaultConfig(tmp_path / "vault")
    note = _note()
    _push(config, [note])
    path = config.vault_dir / note.vault_path
    path.write_text(path.read_text(encoding="utf-8") + "obsidian side\n", encoding="utf-8")
    note.update_markdown(note.markdown + "pdfnest side\n")

    report = _push(config, [note])
    assert note.markdown.endswith("obsidian side\n")
    assert path.read_text(encoding="utf-8").endswith("obsidian side\n")
    assert [conflict.name for conflict in report.conflicts] == ["p25 Scaling-1.pdfnest-conflict.md"]
    assert report.conflicts[0].read_text(encoding="utf-8").endswith("pdfnest side\n")


def test_renamed_or_moved_file_is_found_by_its_id(tmp_path) -> None:
    config = VaultConfig(tmp_path / "vault")
    note = _note()
    _push(config, [note])
    old = config.vault_dir / note.vault_path
    moved = config.root / "Elsewhere" / "My scaling note.md"
    moved.parent.mkdir(parents=True)
    old.rename(moved)

    pull_notes(config, PDF, [note])
    assert config.vault_dir / note.vault_path == moved
    note.update_markdown(note.markdown + "x\n")
    _push(config, [note])
    assert moved.read_text(encoding="utf-8").endswith("x\n")
    assert not old.exists()


def test_deleted_note_file_goes_to_the_vault_trash(tmp_path) -> None:
    config = VaultConfig(tmp_path / "vault")
    note = _note()
    _push(config, [note])
    path = config.vault_dir / note.vault_path
    trashed = trash_note_file(config, note)
    assert not path.exists()
    assert trashed == config.vault_dir / ".trash" / path.name
    assert trashed.read_text(encoding="utf-8")


def test_file_deleted_in_obsidian_is_written_again(tmp_path) -> None:
    config = VaultConfig(tmp_path / "vault")
    note = _note()
    _push(config, [note])
    (config.vault_dir / note.vault_path).unlink()
    pull_notes(config, PDF, [note])
    assert note.vault_path == ""
    _push(config, [note])
    assert (config.vault_dir / note.vault_path).is_file()


def test_urls_round_trip_and_plain_pdf_paths() -> None:
    url = pdfnest_url(PDF, 7, "abc")
    assert " " not in url and "(" not in url and "[" not in url
    assert parse_pdfnest_url(url) == obsidian.OpenRequest(PDF, 7, "abc")
    assert parse_pdfnest_url(str(PDF)) == obsidian.OpenRequest(PDF)
    assert parse_pdfnest_url("https://example.com") is None
    assert parse_pdfnest_url("pdfnest://open?page=3") is None


def test_vault_config_from_settings() -> None:
    assert VaultConfig.from_settings({"obsidian_vault_dir": ""}) is None
    config = VaultConfig.from_settings({"obsidian_vault_dir": "D:/v", "obsidian_subfolder": "Reading/PDF [notes]"})
    assert config.root == Path("D:/v/Reading/PDF (notes)")


def test_render_note_file_handles_crlf_and_quotes_paths() -> None:
    note = _note("# Title\r\nline\r\n")
    pdf_path = Path('C:/a "quoted" dir/b.pdf')
    text = render_note_file(note, pdf_path)
    blocks, body = parse_note_file(text)
    assert body == "# Title\nline\n"
    assert obsidian.front_matter_value(blocks, "pdf") == str(pdf_path)


# --- reader -----------------------------------------------------------------------------------------


@pytest.fixture
def vault_window(window, tmp_path):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    window.settings["obsidian_vault_dir"] = str(vault)
    window._apply_obsidian_settings()
    return window


def _book_dir(window, pdf_path: Path) -> Path:
    return window.vault.book_dir(pdf_path)


def test_reader_writes_notes_and_index_into_the_vault(tmp_path, vault_window) -> None:
    window = vault_window
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "book.pdf", page_count=3, toc=[[1, "Chapter One", 1]])
    window.load_pdf(pdf_path)
    assert window.note_panel.export_button.text() == "Open in Obsidian"

    window.add_note(0, 0.3, 0.4)
    note = window.notes[0]
    window.note_panel.editor.setPlainText("# Idea\n\nBody")
    window.save_current_note(window.note_panel.editor.toPlainText())

    path = window.vault.vault_dir / note.vault_path
    assert path.parent == _book_dir(window, pdf_path)
    assert path.name == "p1 Chapter One-1.md"  # named once, at creation; Obsidian may rename it
    assert path.read_text(encoding="utf-8").endswith("# Idea\n\nBody")
    assert (path.parent / INDEX_NAME).is_file()
    assert load_notes(window.pdf_key)[0].vault_path == note.vault_path  # sync state is persisted


def test_reader_pulls_obsidian_edits_when_window_is_activated(tmp_path, vault_window, qapp) -> None:
    window = vault_window
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "book.pdf", page_count=2)
    window.load_pdf(pdf_path)
    window.add_note(0, 0.3, 0.4)
    note = window.notes[0]
    path = window.vault.vault_dir / note.vault_path
    path.write_text(path.read_text(encoding="utf-8") + "written in Obsidian\n", encoding="utf-8")

    window._pull_from_vault()  # what activating the window does
    assert note.markdown.endswith("written in Obsidian\n")
    assert window.note_panel.editor.toPlainText().endswith("written in Obsidian\n")
    assert load_notes(window.pdf_key)[0].markdown.endswith("written in Obsidian\n")


def test_unsaved_editor_text_is_not_replaced_by_a_pull(tmp_path, vault_window) -> None:
    window = vault_window
    window.auto_save_current_note = False
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "book.pdf", page_count=2)
    window.load_pdf(pdf_path)
    window.add_note(0, 0.3, 0.4)
    note = window.notes[0]
    window.note_panel.editor.setPlainText("typing, not saved yet")
    path = window.vault.vault_dir / note.vault_path
    path.write_text(path.read_text(encoding="utf-8") + "obsidian\n", encoding="utf-8")

    window._pull_from_vault()
    assert window.note_panel.editor.toPlainText() == "typing, not saved yet"
    window.save_current_note_from_panel()  # both sides changed: nothing is lost
    conflicts = list(path.parent.glob("*.pdfnest-conflict.md"))
    assert len(conflicts) == 1 and conflicts[0].read_text(encoding="utf-8").endswith("typing, not saved yet")
    assert note.markdown.endswith("obsidian\n")


def test_appended_excerpts_link_back_to_their_marker(tmp_path, vault_window) -> None:
    window = vault_window
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "book.pdf", page_count=2)
    window.load_pdf(pdf_path)
    window.add_note(0, 0.3, 0.4)
    window.append_selected_text_to_current_note("quoted words", page_index=1, rects_norm=[[0.1, 0.1, 0.4, 0.2]])
    excerpt = next(note for note in window.notes if note.note_type == "excerpt")
    parent = window.notes[0]
    assert f"> quoted words\n> — [p.2]({pdfnest_url(pdf_path, 2, excerpt.id, window.pdf_key)})" in parent.markdown
    assert excerpt.linked_note_id == parent.id


def test_open_in_obsidian_button_opens_the_note_file(tmp_path, vault_window) -> None:
    window = vault_window
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "book.pdf", page_count=2)
    window.load_pdf(pdf_path)
    window.add_note(0, 0.3, 0.4)
    with patch("pdf_notes_reader.ui.main_window.QDesktopServices.openUrl") as open_url:
        window.export_current_note_from_panel()
    opened = open_url.call_args.args[0].toString()
    assert opened.startswith("obsidian://open?path=")
    assert "p1" in opened


def test_deleting_a_note_moves_its_file_to_the_vault_trash(tmp_path, vault_window) -> None:
    window = vault_window
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "book.pdf", page_count=2)
    window.load_pdf(pdf_path)
    window.add_note(0, 0.3, 0.4)
    path = window.vault.vault_dir / window.notes[0].vault_path
    window.delete_note_by_id(window.notes[0].id)
    assert not path.exists()
    assert (window.vault.vault_dir / ".trash" / path.name).is_file()
    assert "No notes yet." in (path.parent / INDEX_NAME).read_text(encoding="utf-8")


def test_existing_notes_are_written_when_a_vault_is_set(tmp_path, window) -> None:
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "book.pdf", page_count=2)
    window.load_pdf(pdf_path)
    window.add_note(0, 0.3, 0.4)
    assert window.notes[0].vault_path == ""
    window.settings["obsidian_vault_dir"] = str(tmp_path / "vault")
    window._apply_obsidian_settings()
    assert (window.vault.vault_dir / window.notes[0].vault_path).is_file()


def test_without_a_vault_export_is_unchanged(tmp_path, window) -> None:
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "book.pdf", page_count=2)
    window.load_pdf(pdf_path)
    assert window.vault is None
    assert window.note_panel.export_button.text() == "Export MD"
    window.add_note(0, 0.3, 0.4)
    window.append_selected_text_to_current_note("plain", page_index=0, rects_norm=[[0.1, 0.1, 0.2, 0.2]])
    assert "pdfnest://" not in window.notes[0].markdown
