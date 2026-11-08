"""#3/#7: different kinds of PDFs open and render, and the render cache never re-rasterizes needlessly."""

from __future__ import annotations

from unittest.mock import patch

import fitz
import pytest

import pdf_factory
from pdf_notes_reader.pdf.document import PdfOpenError, open_pdf, page_base_sizes
from pdf_notes_reader.pdf.render import MAX_PAGE_PIXELS, PageRenderCache, page_render_scale
from pdf_notes_reader.pdf.text import page_words

pytestmark = pytest.mark.gui

QUESTION = "pdf_notes_reader.ui.main_window.QInputDialog.getText"
CRITICAL = "pdf_notes_reader.ui.main_window.QMessageBox.critical"


# --- opening -----------------------------------------------------------------------------------


def test_password_prompt_unlocks_encrypted_pdf(tmp_path, window):
    path = pdf_factory.create_encrypted_pdf(tmp_path / "enc.pdf")
    with patch(QUESTION, return_value=(pdf_factory.USER_PASSWORD, True)) as ask:
        window.load_pdf(path)
    assert ask.call_count == 1
    assert window.document is not None and window.document.page_count == 2
    assert window.page_canvases
    assert window.pdf_tabs[window.pdf_key].password == pdf_factory.USER_PASSWORD


def test_wrong_password_three_times_shows_error(tmp_path, window):
    path = pdf_factory.create_encrypted_pdf(tmp_path / "enc.pdf")
    with patch(QUESTION, return_value=("nope", True)) as ask, patch(CRITICAL) as critical:
        window.load_pdf(path)
    assert ask.call_count == 3
    assert "password is not correct" in critical.call_args.args[2]
    assert window.document is None


def test_cancelled_password_prompt_opens_nothing(tmp_path, window):
    path = pdf_factory.create_encrypted_pdf(tmp_path / "enc.pdf")
    with patch(QUESTION, return_value=("", False)), patch(CRITICAL) as critical:
        window.load_pdf(path)
    assert "cancelled" in critical.call_args.args[2]
    assert window.document is None


@pytest.mark.parametrize(
    ("build", "message"),
    [(pdf_factory.create_not_a_pdf, "could not be read as a PDF"), (pdf_factory.create_empty_file, "empty")],
    ids=["not-a-pdf", "empty-file"],
)
def test_unreadable_files_show_clear_error(tmp_path, window, build, message):
    path = build(tmp_path / "bad.pdf")
    with patch(CRITICAL) as critical:
        window.load_pdf(path)
    assert message in critical.call_args.args[2]
    assert window.document is None


def test_repaired_pdf_opens_with_warning(tmp_path, window):
    path = pdf_factory.create_broken_xref_pdf(tmp_path / "broken.pdf")
    window.load_pdf(path)
    assert window.document.page_count == 3
    assert "repaired" in window.statusBar().currentMessage()


@pytest.mark.parametrize(
    "build",
    [
        pdf_factory.create_object_stream_pdf,
        pdf_factory.create_mixed_geometry_pdf,
        pdf_factory.create_image_only_pdf,
        pdf_factory.create_cjk_pdf,
        lambda p: pdf_factory.create_encrypted_pdf(p, user_password=""),
    ],
    ids=["object-streams", "mixed-geometry", "image-only", "cjk", "owner-encrypted"],
)
def test_problem_pdfs_open_and_render_every_page(tmp_path, window, build):
    path = build(tmp_path / "doc.pdf")
    window.load_pdf(path)
    assert window.document is not None
    for page_index in range(window.document.page_count):
        window.go_to_page(page_index)
        assert page_index in window.page_canvases


def test_open_pdf_api_rejects_zero_page_document(tmp_path, monkeypatch):
    path = pdf_factory.create_sample_pdf(tmp_path / "one.pdf")
    monkeypatch.setattr(fitz.Document, "page_count", property(lambda self: 0))
    with pytest.raises(PdfOpenError, match="no pages"):
        open_pdf(path)


def test_page_sizes_survive_a_broken_page(tmp_path, monkeypatch):
    path = pdf_factory.create_mixed_geometry_pdf(tmp_path / "mixed.pdf")
    document = fitz.open(path)
    real_load = fitz.Document.load_page

    def flaky(self, index):
        if index == 2:
            raise RuntimeError("broken page tree entry")
        return real_load(self, index)

    monkeypatch.setattr(fitz.Document, "load_page", flaky)
    sizes = page_base_sizes(document)
    assert len(sizes) == 4 and sizes[2] == sizes[1]


# --- rendering ---------------------------------------------------------------------------------


def test_cache_rasterizes_each_page_and_zoom_once(tmp_path, qapp):
    document = fitz.open(pdf_factory.create_sample_pdf(tmp_path / "c.pdf", page_count=3))
    cache = PageRenderCache()
    for _ in range(3):
        for page_index in range(3):
            cache.render(document, page_index, 1.25, 2.0)
    assert cache.rasterizations == 3
    cache.render(document, 0, 1.5, 2.0)
    assert cache.rasterizations == 4

    other = fitz.open(pdf_factory.create_sample_pdf(tmp_path / "d.pdf", page_count=1))
    cache.render(other, 0, 1.25, 2.0)
    assert len(cache) == 1  # switching documents drops the old pages


def test_cache_respects_pixel_budget(tmp_path, qapp):
    document = fitz.open(pdf_factory.create_sample_pdf(tmp_path / "c.pdf", page_count=6))
    one_page = 300 * 200 * 4  # zoom 1 x render scale 2 in each direction
    cache = PageRenderCache(max_pixels=one_page * 2)
    for page_index in range(6):
        cache.render(document, page_index, 1.0, 2.0)
    assert len(cache) == 2


def test_scrolling_the_reader_does_not_rerasterize_rendered_pages(tmp_path, window, qapp):
    path = pdf_factory.create_sample_pdf(tmp_path / "long.pdf", page_count=40, page_size=(300, 400))
    window.resize(900, 700)
    window.load_pdf(path)
    before = window.render_cache.rasterizations
    for _ in range(4):
        window.render_page(center_current=False)  # what every page-window refresh does
    assert window.render_cache.rasterizations == before


def test_huge_page_is_rendered_under_pixel_limit(tmp_path, window):
    path = pdf_factory.create_poster_pdf(tmp_path / "poster.pdf", width=6000, height=6000)
    window.load_pdf(path)
    pixmap = window.page_canvases[0]._pixmap
    assert pixmap.width() * pixmap.height() <= MAX_PAGE_PIXELS * 1.01
    assert page_render_scale(6000, 6000, 1.25, 2.0) < 2.0


def test_broken_page_shows_placeholder_and_others_render(tmp_path, window, monkeypatch):
    path = pdf_factory.create_sample_pdf(tmp_path / "flaky.pdf", page_count=3)
    real = fitz.Page.get_pixmap

    def flaky(self, *args, **kwargs):
        if self.number == 1:
            raise RuntimeError("cannot decode image")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_pixmap", flaky)
    window.load_pdf(path)
    for page_index in range(3):
        window.go_to_page(page_index)
        assert page_index in window.page_canvases
    assert not window.render_cache._entries.get((1, 12500, 20000))  # failures are not cached


# --- text geometry -----------------------------------------------------------------------------


def _ink_box(page):
    pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    dark = [(x, y) for y in range(pix.height) for x in range(pix.width) if sum(pix.pixel(x, y)) < 300]
    return (
        min(d[0] for d in dark) / pix.width,
        min(d[1] for d in dark) / pix.height,
        max(d[0] for d in dark) / pix.width,
        max(d[1] for d in dark) / pix.height,
    )


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_word_rects_line_up_with_rendered_text_on_rotated_pages(tmp_path, rotation):
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((40, 80), "Rotated words", fontsize=14)
    page.set_rotation(rotation)
    path = tmp_path / f"rot{rotation}.pdf"
    document.save(path)
    document.close()

    page = fitz.open(path)[0]
    rects = [word["rect"] for word in page_words(page)]
    box = (min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects))
    ink = _ink_box(page)
    tolerance = 0.06
    assert box[0] - tolerance <= ink[0] and ink[2] <= box[2] + tolerance
    assert box[1] - tolerance <= ink[1] and ink[3] <= box[3] + tolerance
