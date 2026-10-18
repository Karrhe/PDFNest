"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from pdf_notes_reader.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    if window.restore_window_maximized:
        window.showMaximized()
    else:
        window.show()
    return app.exec()
