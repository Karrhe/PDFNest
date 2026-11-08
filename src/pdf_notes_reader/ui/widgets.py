"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QTreeWidget, QTreeWidgetItem


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


PDF_KEY_MIME_TYPE = "application/x-pdfnest-pdf-key"


class LibraryFolderTree(QTreeWidget):
    """The library's folder list. Library books dragged onto a folder are filed there."""

    folder_drop_requested = Signal(str, str)  # pdf key, folder id ("" for the top level = unfiled)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self._drop_hover_item: QTreeWidgetItem | None = None

    @staticmethod
    def dragged_pdf_key(event) -> str:
        mime = event.mimeData()
        if mime is None or not mime.hasFormat(PDF_KEY_MIME_TYPE):
            return ""
        return bytes(mime.data(PDF_KEY_MIME_TYPE)).decode("utf-8", "replace").strip()

    def _set_drop_hover(self, item: QTreeWidgetItem | None) -> None:
        if item is self._drop_hover_item:
            return
        if self._drop_hover_item is not None:
            try:
                self._drop_hover_item.setBackground(0, QBrush())
            except RuntimeError:  # the item was rebuilt meanwhile
                pass
        self._drop_hover_item = item
        if item is not None:
            item.setBackground(0, QBrush(self.palette().highlight().color().lighter(150)))

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.dragged_pdf_key(event):
            event.acceptProposedAction()
        else:
            event.ignore()  # files from Explorer/Finder: the library panel handles those

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if not self.dragged_pdf_key(event):
            event.ignore()
            return
        item = self.itemAt(event.position().toPoint())
        self._set_drop_hover(item)
        if item is None:
            event.ignore()
            return
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._set_drop_hover(None)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        pdf_key = self.dragged_pdf_key(event)
        item = self.itemAt(event.position().toPoint())
        self._set_drop_hover(None)
        if not pdf_key or item is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.folder_drop_requested.emit(pdf_key, str(item.data(0, Qt.UserRole) or ""))

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
