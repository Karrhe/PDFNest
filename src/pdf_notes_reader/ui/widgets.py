"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QTreeWidget


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", *, mode: Qt.TextElideMode = Qt.ElideRight) -> None:
        super().__init__()
        self._full_text = ""
        self._elide_mode = mode
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        self._full_text = text
        self.setToolTip(text)
        self._refresh_elided_text()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._refresh_elided_text()

    def _refresh_elided_text(self) -> None:
        available_width = max(0, self.width() - 2)
        if available_width <= 0:
            super().setText(self._full_text)
            return
        super().setText(self.fontMetrics().elidedText(self._full_text, self._elide_mode, available_width))


class LibraryFolderTree(QTreeWidget):
    folder_drop_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(QPen(QColor(58, 58, 58), 1, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
        item = self.topLevelItem(0)
        while item is not None:
            if item.childCount():
                rect = self.visualItemRect(item)
                if rect.isValid() and rect.intersects(event.rect()):
                    x = max(3, rect.left() - 14)
                    cy = rect.center().y()
                    if item.isExpanded():
                        painter.drawLine(x, cy - 2, x + 4, cy + 2)
                        painter.drawLine(x + 4, cy + 2, x + 8, cy - 2)
                    else:
                        painter.drawLine(x + 2, cy - 4, x + 6, cy)
                        painter.drawLine(x + 6, cy, x + 2, cy + 4)
            item = self.itemBelow(item)
        painter.end()
