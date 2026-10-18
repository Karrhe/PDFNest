"""Qt-free logic extracted from MainWindow."""

from __future__ import annotations

import random
import re

import pytest

from pdf_notes_reader.notes import Note
from pdf_notes_reader.services.chapters import ChapterIndex, counter_key, location_label, single_line_title
from pdf_notes_reader.services.export import ExportError, export_note_markdown, safe_filename


def _linear_scan(toc, page_index):
    """The original MainWindow._chapter_for_document algorithm, kept as the reference."""
    best = None
    for raw in toc:
        if len(raw) < 3:
            continue
        toc_page_index = max(0, int(raw[2]) - 1)
        if toc_page_index <= page_index:
            title = re.sub(r"\s+", " ", str(raw[1])).strip()
            if title:
                best = (title, toc_page_index)
        else:
            break
    return best


@pytest.mark.parametrize("seed", range(40))
def test_chapter_index_matches_original_linear_scan(seed):
    rng = random.Random(seed)
    toc = []
    for _ in range(rng.randint(0, 25)):
        title = rng.choice(["Intro", "  Methods ", "", "Results\nPart", "Appendix"])
        toc.append([rng.randint(1, 3), title, rng.randint(1, 40)])
    if seed % 3 == 0:
        toc.sort(key=lambda row: row[2])
    index = ChapterIndex.from_toc(toc)
    for page_index in range(0, 42):
        assert index.chapter_for_page(page_index) == _linear_scan(toc, page_index), (toc, page_index)


def test_counter_key_and_location_label():
    assert counter_key(None, 4) == "page:4"
    assert counter_key(("Intro", 0), 4) == "toc:0:Intro"
    assert location_label(None, 4) == "page-5"
    assert location_label(("Intro", 0), 4) == "Intro"
    assert single_line_title(" a\n b\t") == "a b"


def test_safe_filename_strips_invalid_characters_and_hashes_long_names():
    assert safe_filename('a<b>:c"/d\\e|f?g*') == "a_b_c_d_e_f_g"
    assert safe_filename("...") == "untitled"
    long_name = "x" * 200
    shortened = safe_filename(long_name, max_length=48)
    assert len(shortened) == 48 and shortened == safe_filename(long_name, max_length=48)


def test_export_writes_unique_files_and_replaces_on_request(tmp_path):
    note = Note.create(pdf_key="k", page_index=0, x_norm=0.1, y_norm=0.1, markdown="# one", note_number=1)
    first = export_note_markdown(note, pdf_path=tmp_path / "Doc.pdf", export_root=tmp_path / "out", location="Intro", note_number=1)
    second = export_note_markdown(note, pdf_path=tmp_path / "Doc.pdf", export_root=tmp_path / "out", location="Intro", note_number=1)
    assert first != second and first.parent == second.parent == tmp_path / "out" / "Doc"

    note.markdown = "# changed"
    replaced = export_note_markdown(
        note, pdf_path=tmp_path / "Doc.pdf", export_root=tmp_path / "out", location="Intro", note_number=1, replace_existing=True
    )
    assert replaced == second and replaced.read_text(encoding="utf-8") == "# changed"


def test_export_failure_raises_user_facing_error(tmp_path):
    blocker = tmp_path / "out"
    blocker.write_text("a file where the export folder should be", encoding="utf-8")
    note = Note.create(pdf_key="k", page_index=0, x_norm=0.1, y_norm=0.1, markdown="x")
    with pytest.raises(ExportError, match="Could not write"):
        export_note_markdown(note, pdf_path=tmp_path / "Doc.pdf", export_root=blocker, location="p", note_number=1)
    assert note.exported_markdown_path == ""
