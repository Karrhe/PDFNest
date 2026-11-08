"""Shared base for Qt tests. Import this before any pdf_notes_reader module."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import pdf_factory  # noqa: E402

DATA_DIR_ENV = "PDF_NOTES_READER_DATA_DIR"


class StorageIsolationMixin:
    """Keeps tests from leaking the data-dir env var or writing the real storage pointer file."""

    def setUp(self) -> None:
        super().setUp()
        previous = os.environ.get(DATA_DIR_ENV)
        self.addCleanup(self._restore_data_dir_env, previous)
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        # Default data dir per test; tests that need a specific one still overwrite the env var.
        os.environ[DATA_DIR_ENV] = str(Path(scratch.name) / "data")
        pointer = patch(
            "pdf_notes_reader.notes.storage_pointer_path",
            return_value=Path(scratch.name) / "storage_location.json",
        )
        pointer.start()
        self.addCleanup(pointer.stop)

    @staticmethod
    def _restore_data_dir_env(previous: str | None) -> None:
        if previous is None:
            os.environ.pop(DATA_DIR_ENV, None)
        else:
            os.environ[DATA_DIR_ENV] = previous


class GuiTestCase(StorageIsolationMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _create_sample_pdf(
        path: Path,
        page_count: int = 1,
        toc: list[list] | None = None,
        page_size: tuple[int, int] = (300, 200),
    ) -> None:
        pdf_factory.create_sample_pdf(path, page_count=page_count, toc=toc, page_size=page_size)

    @staticmethod
    def _press_key(window, key: Qt.Key) -> None:
        event = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
        window.keyPressEvent(event)

    @staticmethod
    def _horizontal_page_margins(window) -> int:
        margins = window.pages_layout.contentsMargins()
        return margins.left() + margins.right()

    @staticmethod
    def _vertical_page_margins(window) -> int:
        margins = window.pages_layout.contentsMargins()
        return margins.top() + margins.bottom()
