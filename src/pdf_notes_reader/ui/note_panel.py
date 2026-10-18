"""Right sidebar: Markdown note editor and preview."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPushButton, QPlainTextEdit, QTabWidget, QTextBrowser, QVBoxLayout, QWidget

from pdf_notes_reader.markdown_render import render_markdown_preview
from pdf_notes_reader.notes import Note
from pdf_notes_reader.services.note_search import note_matches


class NotePanel(QWidget):
    jump_note_requested = Signal()
    save_requested = Signal(str)
    export_requested = Signal(str)
    delete_requested = Signal()
    note_selected_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._current_note_id: str | None = None
        self._notes: list[Note] = []

        self.note_selector = QComboBox()
        self.note_selector.setMinimumWidth(150)
        self.note_selector.activated.connect(self._emit_selected_note)

        self.note_filter = QLineEdit()
        self.note_filter.setObjectName("NoteFilter")
        self.note_filter.setPlaceholderText("Filter notes by text...")
        self.note_filter.setClearButtonEnabled(True)
        self.note_filter.textChanged.connect(lambda _text: self._rebuild_selector())

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Write Markdown notes here...")
        self.editor.textChanged.connect(self._update_preview)

        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)

        tabs = QTabWidget()
        tabs.addTab(self.editor, "Edit")
        tabs.addTab(self.preview, "Preview")

        self.save_button = QPushButton("Save")
        self.export_button = QPushButton("Export MD")
        self.delete_button = QPushButton("Delete")
        self.folder_button = QPushButton("Go to note")
        self.folder_button.setToolTip("Jump to this note in the PDF")
        self.save_button.clicked.connect(self._emit_save)
        self.export_button.clicked.connect(self._emit_export)
        self.delete_button.clicked.connect(self.delete_requested.emit)
        self.folder_button.clicked.connect(self.jump_note_requested.emit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.folder_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.note_filter)
        layout.addWidget(self.note_selector)
        layout.addWidget(tabs, 1)
        layout.addLayout(buttons)

        self.set_enabled(False)

    @property
    def current_note_id(self) -> str | None:
        return self._current_note_id

    def set_note(self, note: Note | None) -> None:
        self._current_note_id = note.id if note else None
        self.set_enabled(note is not None)
        self._sync_selector_current()

        if note is None:
            self.editor.blockSignals(True)
            self.editor.clear()
            self.editor.blockSignals(False)
            self.preview.clear()
            return

        self.editor.blockSignals(True)
        self.editor.setPlainText(note.markdown)
        self.editor.blockSignals(False)
        self._update_preview()

    def set_notes(self, notes: list[Note], current_note_id: str | None = None) -> None:
        self._notes = sorted((note for note in notes if note.note_type != "excerpt"), key=lambda item: (item.page_index, item.created_at))
        if current_note_id is not None:
            self._current_note_id = current_note_id

        self._rebuild_selector()

    def visible_notes(self) -> list[Note]:
        query = self.note_filter.text()
        return [note for note in self._notes if note_matches(note, query)]

    def _rebuild_selector(self) -> None:
        visible = self.visible_notes()
        with QSignalBlocker(self.note_selector):
            self.note_selector.clear()
            if visible:
                for note in visible:
                    self.note_selector.addItem(self.note_label(note), note.id)
            elif self._notes:
                self.note_selector.addItem("No notes match the filter", "")
            else:
                self.note_selector.addItem("Select note...", "")
        self._sync_selector_current()

    @staticmethod
    def note_label(note: Note) -> str:
        for line in note.markdown.splitlines():
            label = line.strip()
            if label:
                return label[:120]
        return f"Page {note.page_index + 1} note"

    def set_enabled(self, enabled: bool) -> None:
        self.editor.setEnabled(enabled)
        self.preview.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.note_selector.setEnabled(bool(self._notes))

    def _emit_save(self) -> None:
        if self._current_note_id is not None:
            self.save_requested.emit(self.editor.toPlainText())

    def _emit_export(self) -> None:
        if self._current_note_id is not None:
            self.export_requested.emit(self.editor.toPlainText())

    def _emit_selected_note(self, _index: int) -> None:
        note_id = str(self.note_selector.currentData() or "")
        if note_id:
            self.note_selected_requested.emit(note_id)

    def _sync_selector_current(self) -> None:
        self.note_selector.setEnabled(bool(self._notes))
        if self._current_note_id is None:
            with QSignalBlocker(self.note_selector):
                if not self._notes and self.note_selector.count() == 0:
                    self.note_selector.addItem("Select note...", "")
                self.note_selector.setCurrentIndex(0 if not self._notes else -1)
            return

        index = self.note_selector.findData(self._current_note_id)
        if index >= 0:
            with QSignalBlocker(self.note_selector):
                self.note_selector.setCurrentIndex(index)

    def _update_preview(self) -> None:
        text = self.editor.toPlainText()
        self.preview.setHtml(render_markdown_preview(text))
