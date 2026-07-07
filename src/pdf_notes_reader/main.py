from __future__ import annotations

import sys
from pathlib import Path

import fitz
import markdown
from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pdf_notes_reader.notes import Note, find_note, load_notes, pdf_key_for_path, save_notes


class PdfCanvas(QWidget):
    add_note_requested = Signal(int, float, float)
    note_selected = Signal(str)

    def __init__(self, page_index: int = 0) -> None:
        super().__init__()
        self.page_index = page_index
        self._pixmap: QPixmap | None = None
        self._page_size = QSize(640, 480)
        self._notes: list[Note] = []
        self._marker_radius = 7
        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_page(self, pixmap: QPixmap | None, notes: list[Note], display_size: QSize | None = None) -> None:
        self._pixmap = pixmap
        self._notes = notes
        if pixmap is None:
            self._page_size = QSize(640, 480)
        else:
            self._page_size = display_size or pixmap.deviceIndependentSize().toSize()
        self.setFixedSize(self._page_size)
        self.update()

    def render_device_pixel_ratio(self) -> float:
        if self._pixmap is None:
            return 1.0
        return self._pixmap.devicePixelRatio()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f3f4f6"))

        if self._pixmap is None:
            painter.setPen(QColor("#6b7280"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Open a PDF to begin")
            return

        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(self.rect(), self._pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        for note in self._notes:
            center = self._note_center(note)
            painter.setBrush(QColor("#e11d48"))
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawEllipse(center, self._marker_radius, self._marker_radius)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._pixmap is None or not self._inside_page(event.pos()):
            return

        menu = QMenu(self)
        add_action = QAction("Add note", self)
        menu.addAction(add_action)
        chosen = menu.exec(event.globalPos())
        if chosen == add_action:
            x_norm, y_norm = self._point_to_norm(event.pos())
            self.add_note_requested.emit(self.page_index, x_norm, y_norm)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() != Qt.LeftButton or self._pixmap is None:
            return

        note = self._note_at(event.pos())
        if note is not None:
            self.note_selected.emit(note.id)

    def _inside_page(self, point: QPoint) -> bool:
        if self._pixmap is None:
            return False
        return 0 <= point.x() < self._page_size.width() and 0 <= point.y() < self._page_size.height()

    def _point_to_norm(self, point: QPoint) -> tuple[float, float]:
        if self._pixmap is None or self._page_size.width() == 0 or self._page_size.height() == 0:
            return 0.0, 0.0
        return point.x() / self._page_size.width(), point.y() / self._page_size.height()

    def _note_center(self, note: Note) -> QPoint:
        if self._pixmap is None:
            return QPoint()
        return QPoint(round(note.x_norm * self._page_size.width()), round(note.y_norm * self._page_size.height()))

    def _note_at(self, point: QPoint) -> Note | None:
        for note in reversed(self._notes):
            center = self._note_center(note)
            delta = center - point
            if delta.x() * delta.x() + delta.y() * delta.y() <= (self._marker_radius + 5) ** 2:
                return note
        return None


class NotePanel(QWidget):
    save_requested = Signal(str)
    delete_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._current_note_id: str | None = None

        self.title = QLabel("No note selected")
        self.title.setStyleSheet("font-weight: 600;")

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Write Markdown notes here...")
        self.editor.textChanged.connect(self._update_preview)

        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)

        tabs = QTabWidget()
        tabs.addTab(self.editor, "Edit")
        tabs.addTab(self.preview, "Preview")

        self.save_button = QPushButton("Save")
        self.delete_button = QPushButton("Delete")
        self.save_button.clicked.connect(self._emit_save)
        self.delete_button.clicked.connect(self.delete_requested.emit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.delete_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(tabs, 1)
        layout.addLayout(buttons)

        self.set_enabled(False)

    @property
    def current_note_id(self) -> str | None:
        return self._current_note_id

    def set_note(self, note: Note | None) -> None:
        self._current_note_id = note.id if note else None
        self.set_enabled(note is not None)

        if note is None:
            self.title.setText("No note selected")
            self.editor.blockSignals(True)
            self.editor.clear()
            self.editor.blockSignals(False)
            self.preview.clear()
            return

        self.title.setText(f"Page {note.page_index + 1} note")
        self.editor.blockSignals(True)
        self.editor.setPlainText(note.markdown)
        self.editor.blockSignals(False)
        self._update_preview()

    def set_enabled(self, enabled: bool) -> None:
        self.editor.setEnabled(enabled)
        self.preview.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    def _emit_save(self) -> None:
        if self._current_note_id is not None:
            self.save_requested.emit(self.editor.toPlainText())

    def _update_preview(self) -> None:
        text = self.editor.toPlainText()
        html = markdown.markdown(text, extensions=["fenced_code", "tables", "nl2br"])
        self.preview.setHtml(html)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDF Notes Reader")
        self.resize(1180, 820)

        self.document: fitz.Document | None = None
        self.pdf_path: Path | None = None
        self.pdf_key: str | None = None
        self.notes: list[Note] = []
        self.page_index = 0
        self.zoom = 1.25
        self.render_scale = 2.0
        self.continuous_scroll = True

        self.setFocusPolicy(Qt.StrongFocus)
        self.canvas = PdfCanvas()
        self.page_canvases: dict[int, PdfCanvas] = {}

        self.pages_container = QWidget()
        self.pages_layout = QVBoxLayout(self.pages_container)
        self.pages_layout.setContentsMargins(24, 24, 24, 24)
        self.pages_layout.setSpacing(18)
        self.pages_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.pages_container)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setBackgroundRole(self.backgroundRole())

        self.note_panel = NotePanel()
        self.note_panel.save_requested.connect(self.save_current_note)
        self.note_panel.delete_requested.connect(self.delete_current_note)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.scroll_area)
        splitter.addWidget(self.note_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([820, 320])
        self.setCentralWidget(splitter)

        self.page_label = QLabel("No PDF")
        self.zoom_label = QLabel("125%")
        self._build_toolbar()
        self._render_empty_state()
        self._refresh_actions()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("PDF controls")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_action = QAction("Open", self)
        open_action.triggered.connect(self.open_pdf)
        toolbar.addAction(open_action)

        self.prev_action = QAction("Previous", self)
        self.prev_action.triggered.connect(self.previous_page)
        toolbar.addAction(self.prev_action)

        self.next_action = QAction("Next", self)
        self.next_action.triggered.connect(self.next_page)
        toolbar.addAction(self.next_action)

        toolbar.addWidget(self.page_label)
        toolbar.addSeparator()

        self.continuous_action = QAction("Continuous Scroll", self)
        self.continuous_action.setCheckable(True)
        self.continuous_action.setChecked(self.continuous_scroll)
        self.continuous_action.triggered.connect(self.set_continuous_scroll)
        toolbar.addAction(self.continuous_action)

        toolbar.addSeparator()

        self.zoom_out_action = QAction("Zoom Out", self)
        self.zoom_out_action.triggered.connect(lambda: self.change_zoom(-0.15))
        toolbar.addAction(self.zoom_out_action)

        self.zoom_in_action = QAction("Zoom In", self)
        self.zoom_in_action.triggered.connect(lambda: self.change_zoom(0.15))
        toolbar.addAction(self.zoom_in_action)

        toolbar.addWidget(self.zoom_label)

    def open_pdf(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF files (*.pdf)")
        if not filename:
            return
        self.load_pdf(Path(filename))

    def load_pdf(self, path: Path) -> None:
        try:
            document = fitz.open(path)
        except Exception as exc:  # PyMuPDF raises several exception types.
            QMessageBox.critical(self, "Open failed", f"Could not open PDF:\n{exc}")
            return

        self.close_document()
        self.document = document
        self.pdf_path = path
        self.pdf_key = pdf_key_for_path(path)
        self.notes = load_notes(self.pdf_key)
        self.page_index = 0
        self.note_panel.set_note(None)
        self.render_page()

    def close_document(self) -> None:
        if self.document is not None:
            self.document.close()
        self.document = None

    def render_page(self) -> None:
        if self.document is None:
            self._render_empty_state()
            self._refresh_actions()
            return

        self._clear_page_widgets()
        page_indexes = range(self.document.page_count) if self.continuous_scroll else [self.page_index]
        for page_index in page_indexes:
            canvas = self._create_canvas(page_index)
            pixmap, display_size = self._render_page_pixmap(page_index)
            page_notes = [note for note in self.notes if note.page_index == page_index]
            canvas.set_page(pixmap, page_notes, display_size)
            self.pages_layout.addWidget(canvas, 0, Qt.AlignHCenter)
            self.page_canvases[page_index] = canvas

        self.canvas = self.page_canvases.get(self.page_index) or next(iter(self.page_canvases.values()))
        self._refresh_actions()
        if self.continuous_scroll:
            self._scroll_to_page(self.page_index)

    def _render_page_pixmap(self, page_index: int) -> tuple[QPixmap, QSize]:
        if self.document is None:
            raise RuntimeError("No document loaded")

        page = self.document.load_page(page_index)
        render_zoom = self.zoom * self.render_scale
        pix = page.get_pixmap(matrix=fitz.Matrix(render_zoom, render_zoom), alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(self.render_scale)
        display_size = QSize(round(pix.width / self.render_scale), round(pix.height / self.render_scale))
        return pixmap, display_size

    def _create_canvas(self, page_index: int) -> PdfCanvas:
        canvas = PdfCanvas(page_index)
        canvas.add_note_requested.connect(self.add_note)
        canvas.note_selected.connect(self.select_note)
        return canvas

    def _render_empty_state(self) -> None:
        self._clear_page_widgets()
        self.canvas = self._create_canvas(0)
        self.canvas.set_page(None, [])
        self.pages_layout.addWidget(self.canvas, 0, Qt.AlignHCenter)
        self.page_canvases[0] = self.canvas

    def _clear_page_widgets(self) -> None:
        while self.pages_layout.count():
            item = self.pages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.page_canvases = {}

    def add_note(self, *args: float) -> None:
        if self.document is None or self.pdf_key is None:
            return
        if len(args) == 2:
            page_index = self.page_index
            x_norm, y_norm = args
        elif len(args) == 3:
            page_index = int(args[0])
            x_norm, y_norm = args[1], args[2]
        else:
            raise TypeError("add_note expects x/y or page_index/x/y")

        note = Note.create(
            pdf_key=self.pdf_key,
            page_index=page_index,
            x_norm=x_norm,
            y_norm=y_norm,
            markdown="# New note\n",
        )
        self.page_index = page_index
        self.notes.append(note)
        self.persist_notes()
        self.render_page()
        self.note_panel.set_note(note)

    def select_note(self, note_id: str) -> None:
        self.note_panel.set_note(find_note(self.notes, note_id))

    def save_current_note(self, markdown_text: str) -> None:
        note_id = self.note_panel.current_note_id
        if note_id is None:
            return

        note = find_note(self.notes, note_id)
        if note is None:
            self.note_panel.set_note(None)
            return

        note.update_markdown(markdown_text)
        self.persist_notes()
        self.note_panel.set_note(note)

    def delete_current_note(self) -> None:
        note_id = self.note_panel.current_note_id
        if note_id is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete note",
            "Delete this note?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.notes = [note for note in self.notes if note.id != note_id]
        self.persist_notes()
        self.note_panel.set_note(None)
        self.render_page()

    def persist_notes(self) -> None:
        if self.pdf_path is None or self.pdf_key is None:
            return
        save_notes(pdf_key=self.pdf_key, pdf_path=self.pdf_path, notes=self.notes)

    def previous_page(self) -> None:
        if self.document is None or self.page_index <= 0:
            return
        self.go_to_page(self.page_index - 1)

    def next_page(self) -> None:
        if self.document is None or self.page_index >= self.document.page_count - 1:
            return
        self.go_to_page(self.page_index + 1)

    def go_to_page(self, page_index: int) -> None:
        if self.document is None:
            return
        self.page_index = max(0, min(page_index, self.document.page_count - 1))
        self.note_panel.set_note(None)
        if self.continuous_scroll:
            self.canvas = self.page_canvases.get(self.page_index, self.canvas)
            self._refresh_actions()
            self._scroll_to_page(self.page_index)
        else:
            self.render_page()

    def _scroll_to_page(self, page_index: int) -> None:
        canvas = self.page_canvases.get(page_index)
        if canvas is not None:
            self.scroll_area.ensureWidgetVisible(canvas, 0, 0)

    def set_continuous_scroll(self, checked: bool) -> None:
        self.continuous_scroll = checked
        self.note_panel.set_note(None)
        self.render_page()

    def change_zoom(self, delta: float) -> None:
        if self.document is None:
            return
        self.zoom = max(0.3, min(4.0, self.zoom + delta))
        self.render_page()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        focus = QApplication.focusWidget()
        if focus is not None and (
            focus is self.note_panel.editor
            or self.note_panel.editor.isAncestorOf(focus)
            or focus is self.note_panel.preview
            or self.note_panel.preview.isAncestorOf(focus)
        ):
            super().keyPressEvent(event)
            return

        if event.key() in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp):
            self.previous_page()
            event.accept()
            return
        if event.key() in (Qt.Key_Right, Qt.Key_Down, Qt.Key_PageDown):
            self.next_page()
            event.accept()
            return
        super().keyPressEvent(event)

    def _refresh_actions(self) -> None:
        has_document = self.document is not None
        page_count = self.document.page_count if self.document is not None else 0
        self.prev_action.setEnabled(has_document and self.page_index > 0)
        self.next_action.setEnabled(has_document and self.page_index < page_count - 1)
        self.zoom_in_action.setEnabled(has_document)
        self.zoom_out_action.setEnabled(has_document)
        self.continuous_action.setEnabled(has_document)

        if has_document:
            self.page_label.setText(f"Page {self.page_index + 1} / {page_count}")
        else:
            self.page_label.setText("No PDF")
        self.zoom_label.setText(f"{round(self.zoom * 100)}%")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.close_document()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
