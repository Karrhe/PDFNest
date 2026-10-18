"""Reader performance benchmark: PDF open time, rasterizations per scroll, and page-geometry cost.

Usage:
    .venv\\Scripts\\python.exe scripts\\bench_render.py [--pages 2000]

Runs offscreen against a generated PDF in a temporary data directory; it never touches real notes.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import fitz  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def build_pdf(path: Path, pages: int) -> None:
    document = fitz.open()
    for number in range(pages):
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Benchmark page {number + 1}", fontsize=18)
        page.insert_text((72, 140), "The quick brown fox jumps over the lazy dog. " * 2, fontsize=10)
    document.set_toc([[1, f"Chapter {i // 50 + 1}", i + 1] for i in range(0, pages, 50)])
    document.save(path)
    document.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=2000)
    parser.add_argument("--scroll-steps", type=int, default=30)
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="pdfnest-bench-"))
    os.environ["PDF_NOTES_READER_DATA_DIR"] = str(tmp / "data")
    pdf_path = tmp / "bench.pdf"
    build_pdf(pdf_path, args.pages)

    from pdf_notes_reader.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1200, 900)
    window.show()
    app.processEvents()

    calls = {"get_pixmap": 0}
    real_get_pixmap = fitz.Page.get_pixmap

    def counting_get_pixmap(self, *a, **k):
        calls["get_pixmap"] += 1
        return real_get_pixmap(self, *a, **k)

    fitz.Page.get_pixmap = counting_get_pixmap
    try:
        started = time.perf_counter()
        window.load_pdf(pdf_path)
        app.processEvents()
        open_seconds = time.perf_counter() - started
        open_rasters = calls["get_pixmap"]

        calls["get_pixmap"] = 0
        started = time.perf_counter()
        bar = window.scroll_area.verticalScrollBar()
        step = max(1, window.page_heights[0] // 3) if window.page_heights else 200
        for _ in range(args.scroll_steps):
            bar.setValue(bar.value() + step)
            app.processEvents()
            time.sleep(0.04)  # let the 35 ms window-render timer fire
            app.processEvents()
        scroll_seconds = time.perf_counter() - started
        scroll_rasters = calls["get_pixmap"]
        pages_passed = (args.scroll_steps * step) / max(1, window.page_heights[0] + window.pages_layout.spacing())
    finally:
        fitz.Page.get_pixmap = real_get_pixmap
        window.close()

    print(f"pages in PDF:              {args.pages}")
    print(f"open (load_pdf) time:      {open_seconds * 1000:8.1f} ms  ({open_rasters} rasterizations)")
    print(f"scroll {args.scroll_steps} steps:            {scroll_seconds * 1000:8.1f} ms  ({scroll_rasters} rasterizations, ~{pages_passed:.1f} pages passed)")
    print(f"rasterizations per page passed: {scroll_rasters / max(pages_passed, 0.1):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
