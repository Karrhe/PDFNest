"""Page rendering in worker processes: the job itself, the process pool and the reader's use of it."""

from __future__ import annotations

import os
import time

import fitz
import pytest
from PySide6.QtTest import QTest

import pdf_factory
from pdf_notes_reader.pdf import render_worker
from pdf_notes_reader.pdf.render import rasterize_page, rendered_page_from_result
from pdf_notes_reader.pdf.render_worker import RenderJob, RenderWorkerPool, render_in_worker


def _wait_until(condition, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        QTest.qWait(20)
    return True


def test_worker_job_matches_in_process_rendering(tmp_path, qapp) -> None:
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "job.pdf", page_count=3) or tmp_path / "job.pdf"
    result = render_in_worker(RenderJob(str(pdf_path), None, 1, 1.5, 1.25))
    assert not result.error
    assert result.words  # text geometry comes back with the pixels

    document = fitz.open(pdf_path)
    expected = rasterize_page(document, 1, 1.5, 1.25)
    rect = document.load_page(1).rect
    rendered = rendered_page_from_result(result, rect.width, rect.height, 1.5)
    assert rendered.pixmap.size() == expected.pixmap.size()
    assert rendered.display_size == expected.display_size
    assert rendered.pixmap.devicePixelRatio() == expected.pixmap.devicePixelRatio()
    assert rendered.pixmap.toImage() == expected.pixmap.toImage()
    document.close()


def test_worker_job_reports_errors_instead_of_raising(tmp_path) -> None:
    pdf_path = tmp_path / "short.pdf"
    pdf_factory.create_sample_pdf(pdf_path, page_count=1)
    assert render_in_worker(RenderJob(str(pdf_path), None, 5, 1.0, 1.0)).error
    assert render_in_worker(RenderJob(str(tmp_path / "missing.pdf"), None, 0, 1.0, 1.0)).error


def test_worker_unlocks_encrypted_pdf(tmp_path) -> None:
    pdf_path = tmp_path / "locked.pdf"
    pdf_factory.create_encrypted_pdf(pdf_path)
    assert render_in_worker(RenderJob(str(pdf_path), "wrong", 0, 1.0, 1.0)).error
    assert not render_in_worker(RenderJob(str(pdf_path), pdf_factory.USER_PASSWORD, 0, 1.0, 1.0)).error


def test_worker_reopens_a_rewritten_file(tmp_path) -> None:
    pdf_path = tmp_path / "rewritten.pdf"
    pdf_factory.create_sample_pdf(pdf_path, page_count=1, page_size=(300, 200))
    first = render_in_worker(RenderJob(str(pdf_path), None, 0, 1.0, 1.0))
    pdf_factory.create_sample_pdf(pdf_path, page_count=1, page_size=(200, 300))
    stat = os.stat(pdf_path)
    os.utime(pdf_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    second = render_in_worker(RenderJob(str(pdf_path), None, 0, 1.0, 1.0))
    assert (first.width, first.height) == (300, 200)
    assert (second.width, second.height) == (200, 300)


def test_pool_renders_in_a_separate_process(tmp_path) -> None:
    pdf_path = tmp_path / "pool.pdf"
    pdf_factory.create_sample_pdf(pdf_path, page_count=2)
    pool = RenderWorkerPool(1)
    try:
        future = pool.submit(RenderJob(str(pdf_path), None, 0, 1.0, 2.0))
        assert future is not None
        result = future.result(timeout=120)
        assert not result.error
        assert (result.width, result.height) == (600, 400)
    finally:
        pool.shutdown()


def test_pool_disabled_by_environment(monkeypatch) -> None:
    monkeypatch.setenv(render_worker.WORKERS_ENV, "0")
    pool = RenderWorkerPool()
    assert not pool.available
    assert pool.submit(RenderJob("x.pdf", None, 0, 1.0, 1.0)) is None


@pytest.fixture
def worker_window(qapp, monkeypatch):
    monkeypatch.setenv(render_worker.WORKERS_ENV, "1")
    from pdf_notes_reader.main import MainWindow

    window = MainWindow()
    window.resize(900, 600)
    window.show()
    yield window
    window.close()


def _no_pending(window) -> bool:
    return not any(canvas.is_pending() for canvas in window.page_canvases.values())


def test_reader_fills_buffer_pages_from_workers(tmp_path, worker_window) -> None:
    window = worker_window
    pdf_path = tmp_path / "reader.pdf"
    pdf_factory.create_sample_pdf(pdf_path, page_count=12)
    window.load_pdf(pdf_path)
    in_process = window.render_cache.rasterizations
    assert any(canvas.is_pending() for canvas in window.page_canvases.values())

    assert _wait_until(lambda: _no_pending(window), timeout=120)
    assert window.render_cache.rasterizations == in_process  # buffer pages came from the worker
    assert window.render_workers.available
    filled = max(window.page_canvases)
    assert window.page_canvases[filled].render_device_pixel_ratio() == window.render_scale
    assert window.page_text_words_cache.get(filled)  # selection text came along


def test_slow_documents_render_visible_pages_in_workers_while_scrolling(tmp_path, worker_window) -> None:
    window = worker_window
    pdf_path = tmp_path / "slow.pdf"
    pdf_factory.create_sample_pdf(pdf_path, page_count=30)
    window.load_pdf(pdf_path)
    assert _wait_until(lambda: _no_pending(window), timeout=120)

    window._raster_seconds_estimate = 1.0  # pretend this is a scanned book
    in_process = window.render_cache.rasterizations
    window.scroll_area.verticalScrollBar().setValue(window.page_tops[15])
    window._sync_current_page_from_scroll()
    assert _wait_until(lambda: 15 in window.page_canvases, timeout=10)
    assert _wait_until(lambda: _no_pending(window), timeout=120)
    assert window.render_cache.rasterizations == in_process


def test_reader_falls_back_to_in_process_rendering(tmp_path, worker_window, monkeypatch) -> None:
    window = worker_window

    def broken_submit(job):
        window.render_workers.mark_failed(RuntimeError("no processes here"))
        return None

    monkeypatch.setattr(window.render_workers, "submit", broken_submit)
    pdf_path = tmp_path / "fallback.pdf"
    pdf_factory.create_sample_pdf(pdf_path, page_count=12)
    window.load_pdf(pdf_path)
    assert _wait_until(lambda: _no_pending(window), timeout=30)
    assert not window.render_workers.available


def test_zooming_a_slow_document_shows_the_earlier_render_until_the_worker_is_done(tmp_path, worker_window) -> None:
    window = worker_window
    pdf_path = tmp_path / "zoom.pdf"
    pdf_factory.create_sample_pdf(pdf_path, page_count=6)
    window.load_pdf(pdf_path)
    assert _wait_until(lambda: _no_pending(window), timeout=120)

    window._raster_seconds_estimate = 1.0  # pretend this is a scanned book
    in_process = window.render_cache.rasterizations
    window.change_zoom(0.5)
    canvas = window.page_canvases[window.page_index]
    assert canvas.is_pending()  # the UI did not block on rasterizing
    assert canvas._preview is not None
    assert _wait_until(lambda: _no_pending(window), timeout=120)
    assert window.render_cache.rasterizations == in_process
    assert window.page_canvases[window.page_index].size() == window._page_display_size(window.page_index)
