"""#5: in-PDF full-text search and note search."""

from __future__ import annotations

import os
import time

import fitz
import pytest

import pdf_factory
from pdf_notes_reader.notes import Note, pdf_key_for_path, save_notes
from pdf_notes_reader.pdf.search import DocumentSearch, SearchOptions, search_page
from pdf_notes_reader.pdf.text import page_words
from pdf_notes_reader.services.note_search import NotebookSearchIndex, note_matches

pytestmark = pytest.mark.gui


def _pdf(path, pages):
    document = fitz.open()
    for text in pages:
        page = document.new_page(width=300, height=200)
        page.insert_text((30, 60), text, fontsize=12)
    document.save(path)
    document.close()
    return path


# --- engine ------------------------------------------------------------------------------------


def test_search_page_options(tmp_path):
    path = _pdf(tmp_path / "s.pdf", ["Cat catalog CAT category cat."])
    page = fitz.open(path)[0]
    assert len(search_page(page, "cat")) == 5
    assert len(search_page(page, "cat", SearchOptions(case_sensitive=True))) == 3  # catalog, category, cat.
    assert len(search_page(page, "cat", SearchOptions(whole_word=True))) == 3
    assert len(search_page(page, "cat", SearchOptions(case_sensitive=True, whole_word=True))) == 1
    assert search_page(page, "   ") == []


def test_search_handles_cjk_and_scanned_pages(tmp_path):
    cjk = fitz.open(pdf_factory.create_cjk_pdf(tmp_path / "cjk.pdf"))[0]
    assert len(search_page(cjk, "检索")) == 1
    scanned = fitz.open(pdf_factory.create_image_only_pdf(tmp_path / "scan.pdf"))[0]
    assert search_page(scanned, "anything") == []


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_hit_rects_use_displayed_page_coordinates(tmp_path, rotation):
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((40, 80), "needle", fontsize=14)
    page.set_rotation(rotation)
    path = tmp_path / "rot.pdf"
    document.save(path)
    page = fitz.open(path)[0]
    hit = search_page(page, "needle")[0].rect
    word = next(w["rect"] for w in page_words(page) if w["text"] == "needle")
    assert all(abs(a - b) < 0.03 for a, b in zip(hit, word))


def test_document_search_wraps_from_start_page_and_cancels(tmp_path):
    path = _pdf(tmp_path / "w.pdf", [f"page {i} {'target' if i in (1, 4) else ''}" for i in range(6)])
    document = fitz.open(path)
    search = DocumentSearch(document, "target", start_page=3)
    first = search.step(max_pages=2)
    assert [hit.page_index for hit in first] == [4]  # pages 3, 4 searched first
    search.run_to_end()
    assert [hit.page_index for hit in search.hits] == [1, 4]  # reported in document order

    cancelled = DocumentSearch(document, "target")
    cancelled.cancel()
    assert cancelled.done and cancelled.step() == []


def test_search_steps_respect_time_budget(tmp_path):
    path = _pdf(tmp_path / "many.pdf", ["lorem ipsum"] * 300)
    search = DocumentSearch(fitz.open(path), "ipsum")
    started = time.perf_counter()
    search.step(max_pages=1000, max_seconds=0.005)
    assert time.perf_counter() - started < 0.2
    assert 0 < search.pages_searched < 300


# --- reader find bar ---------------------------------------------------------------------------


def _search(window, qapp, query):
    qapp.processEvents()  # let load_pdf's deferred search reset run first
    window.open_find_bar()
    window.find_bar.query_edit.setText(query)
    window.find_bar.emit_search()
    _finish(window, qapp)


def _finish(window, qapp, timeout=10.0):
    deadline = time.perf_counter() + timeout
    while window.search is not None and not window.search.done and time.perf_counter() < deadline:
        qapp.processEvents()
    qapp.processEvents()


def test_find_bar_finds_highlights_and_cycles(tmp_path, window, qapp):
    path = _pdf(tmp_path / "f.pdf", ["alpha", "beta needle", "gamma", "needle and needle", "delta"])
    window.load_pdf(path)
    _search(window, qapp, "needle")
    assert window.find_bar.is_open()

    assert len(window.search_hits) == 3
    assert window.search_index == 0 and window.page_index == 1
    assert window.find_bar.status_label.text() == "1 of 3"
    assert window.page_canvases[1]._search_hits and window.page_canvases[1]._current_search_hit == 0

    window.next_search_hit()
    assert window.page_index == 3 and window.find_bar.status_label.text() == "2 of 3"
    window.next_search_hit()
    window.next_search_hit()  # wraps around
    assert window.search_index == 0 and window.page_index == 1
    window.previous_search_hit()
    assert window.search_index == 2

    rasterized = window.render_cache.rasterizations
    window._refresh_search_overlays()
    assert window.render_cache.rasterizations == rasterized  # overlays never re-rasterize

    window.find_bar.close_bar()
    assert window.search_hits == [] and not window.page_canvases[1]._search_hits


def test_search_is_cleared_when_switching_documents(tmp_path, window, qapp):
    first = _pdf(tmp_path / "a.pdf", ["needle"])
    second = _pdf(tmp_path / "b.pdf", ["nothing here", "still nothing"])
    window.load_pdf(first)
    _search(window, qapp, "needle")
    assert window.search_hits

    window.load_pdf(second)
    qapp.processEvents()  # deferred restart on the new document
    _finish(window, qapp)
    assert window.search_hits == []
    assert window.find_bar.status_label.text() == "No matches"


def test_no_match_status(tmp_path, window, qapp):
    window.load_pdf(_pdf(tmp_path / "n.pdf", ["text"]))
    _search(window, qapp, "absent")
    assert window.find_bar.status_label.text() == "No matches"


# --- note search -------------------------------------------------------------------------------


def _note(key, markdown, selected=""):
    return Note.create(pdf_key=key, page_index=0, x_norm=0.5, y_norm=0.5, markdown=markdown, selected_text=selected)


def test_note_matches_all_terms_in_markdown_or_captured_text():
    note = _note("k", "# Volatility clustering\nGARCH model", selected="heavy tails")
    assert note_matches(note, "garch volatility")
    assert note_matches(note, "HEAVY")
    assert not note_matches(note, "garch levy")
    assert note_matches(note, "  ")


def test_note_panel_filter(tmp_path, window):
    path = _pdf(tmp_path / "np.pdf", ["x"])
    window.load_pdf(path)
    window.add_note(0, 0.2, 0.2)
    window.save_current_note("# Alpha topic")
    window.add_note(0, 0.6, 0.6)
    window.save_current_note("# Beta topic")
    panel = window.note_panel
    assert panel.note_selector.count() == 2

    panel.note_filter.setText("beta")
    assert [panel.note_selector.itemText(i) for i in range(panel.note_selector.count())] == ["# Beta topic"]
    panel.note_filter.setText("zzz")
    assert panel.note_selector.itemText(0) == "No notes match the filter"
    panel.note_filter.setText("")
    assert panel.note_selector.count() == 2


def test_notebook_index_counts_and_refreshes_on_change(tmp_path):
    pdf_path = tmp_path / "idx.pdf"
    key = pdf_key_for_path(pdf_path)
    save_notes(pdf_key=key, pdf_path=pdf_path, notes=[_note(key, "momentum factor"), _note(key, "value factor")])
    index = NotebookSearchIndex()
    assert index.match_counts([key], "factor") == {key: 2}
    assert index.match_counts([key], "momentum") == {key: 1}

    notes_file = next((tmp_path / "data" / "notebooks").glob("*/note/notes.json"))
    save_notes(pdf_key=key, pdf_path=pdf_path, notes=[_note(key, "carry trade")])
    os.utime(notes_file, ns=(time.time_ns(), time.time_ns() + 1_000_000))  # make the change visible to mtime
    assert index.match_counts([key], "factor") == {}
    assert index.match_counts([key], "carry") == {key: 1}


def test_home_search_finds_notebooks_by_note_content(tmp_path, window):
    pdf_path = _pdf(tmp_path / "Unrelated Title.pdf", ["x"])
    window.load_pdf(pdf_path)
    window.add_note(0, 0.3, 0.3)
    window.save_current_note("Discussion of stochastic volatility")
    window.show_home()

    panel = window.history_panel
    panel.search_edit.setText("stochastic")
    entries = panel._filtered_entries()
    assert [entry.pdf_key for entry in entries] == [window.pdf_key or pdf_key_for_path(pdf_path)]
    assert panel.note_match_counts == {entries[0].pdf_key: 1}
    panel.search_edit.setText("unrelated")  # title matches still work
    assert len(panel._filtered_entries()) == 1
    panel.search_edit.setText("nothing-like-this")
    assert panel._filtered_entries() == []
