"""Reader find bar (Ctrl+F): query, options, previous/next and a hit counter."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from pdf_notes_reader.pdf.search import SearchOptions


class FindBar(QWidget):
    search_requested = Signal(str, object)  # query, SearchOptions
    next_requested = Signal()
    previous_requested = Signal()
    closed = Signal()

    DEBOUNCE_MS = 250

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("FindBar")
        self.query_edit = QLineEdit()
        self.query_edit.setObjectName("FindQuery")
        self.query_edit.setPlaceholderText("Find in PDF")
        self.query_edit.setClearButtonEnabled(True)
        self.case_checkbox = QCheckBox("Match case")
        self.word_checkbox = QCheckBox("Whole words")
        self.previous_button = QPushButton("↑")
        self.previous_button.setToolTip("Previous match (Shift+Enter, Shift+F3)")
        self.next_button = QPushButton("↓")
        self.next_button.setToolTip("Next match (Enter, F3)")
        self.status_label = QLabel("")
        self.status_label.setObjectName("FindStatus")
        self.close_button = QPushButton("×")
        self.close_button.setToolTip("Close (Esc)")
        for button in (self.previous_button, self.next_button, self.close_button):
            button.setFixedWidth(30)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        layout.addWidget(self.query_edit, 3)
        layout.addWidget(self.previous_button)
        layout.addWidget(self.next_button)
        layout.addWidget(self.case_checkbox)
        layout.addWidget(self.word_checkbox)
        layout.addWidget(self.status_label, 2)
        layout.addWidget(self.close_button)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self.DEBOUNCE_MS)
        self._debounce.timeout.connect(self.emit_search)
        self.query_edit.textChanged.connect(lambda _text: self._debounce.start())
        self.case_checkbox.toggled.connect(lambda _checked: self.emit_search())
        self.word_checkbox.toggled.connect(lambda _checked: self.emit_search())
        self.query_edit.returnPressed.connect(self._on_return)
        self.next_button.clicked.connect(self.next_requested.emit)
        self.previous_button.clicked.connect(self.previous_requested.emit)
        self.close_button.clicked.connect(self.close_bar)
        self.hide()

    def is_open(self) -> bool:
        """Open as far as the user is concerned, even while the window itself is hidden."""
        return not self.isHidden()

    def options(self) -> SearchOptions:
        return SearchOptions(case_sensitive=self.case_checkbox.isChecked(), whole_word=self.word_checkbox.isChecked())

    def open_bar(self, initial_text: str = "") -> None:
        if initial_text:
            self.query_edit.setText(initial_text)
        self.show()
        self.query_edit.setFocus(Qt.ShortcutFocusReason)
        self.query_edit.selectAll()

    def close_bar(self) -> None:
        self._debounce.stop()
        self.hide()
        self.closed.emit()

    def emit_search(self) -> None:
        self._debounce.stop()
        self.search_requested.emit(self.query_edit.text(), self.options())

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _on_return(self) -> None:
        if self._debounce.isActive():  # Enter right after typing searches immediately.
            self.emit_search()
            return
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            self.previous_requested.emit()
        else:
            self.next_requested.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key_Escape:
            self.close_bar()
            return
        super().keyPressEvent(event)
