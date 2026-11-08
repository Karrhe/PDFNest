"""Right sidebar: the Markdown note editor and preview, and the highlights summary."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdf_notes_reader.markdown_render import render_markdown_preview
from pdf_notes_reader.notes import Note
from pdf_notes_reader.services.annotation_summary import SummaryGroup, annotation_note_body, single_line
from pdf_notes_reader.services.note_search import note_matches

ANNOTATION_ROLE = Qt.UserRole
NOTE_ROW_ROLE = Qt.UserRole + 1
DEFAULT_ANNOTATION_COLORS = {"highlight": "#fde68a", "underline": "#2563eb"}


class NotePanel(QWidget):
    jump_note_requested = Signal()
    save_requested = Signal(str)
    export_requested = Signal(str)
    delete_requested = Signal()
    note_selected_requested = Signal(str)
    # A pdfnest:// link clicked in the preview; the main window opens it in place.
    pdfnest_link_requested = Signal(str)
    # Summary tab: go to a highlight/underline, add or open its note, delete its note, export.
    annotation_activated = Signal(str)
    annotation_note_requested = Signal(str)
    annotation_note_remove_requested = Signal(str)
    summary_export_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._current_note_id: str | None = None
        # The note text the editor was last loaded with; if the note changes underneath the editor
        # (an Obsidian edit pulled in while typing), saving the editor is a conflict.
        self.loaded_markdown = ""
        self._notes: list[Note] = []
        self._summary_annotations: dict[str, Note] = {}

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
        self.preview.setOpenLinks(False)
        self.preview.anchorClicked.connect(self._open_preview_link)

        tabs = QTabWidget()
        tabs.addTab(self.editor, "Edit")
        tabs.addTab(self.preview, "Preview")

        self.save_button = QPushButton("Save")
        self.export_button = QPushButton("Export MD")
        self.export_button.setToolTip("Export this note as a Markdown file")
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

        self.note_page = QWidget()
        note_layout = QVBoxLayout(self.note_page)
        note_layout.setContentsMargins(0, 0, 0, 0)
        note_layout.addWidget(self.note_filter)
        note_layout.addWidget(self.note_selector)
        note_layout.addWidget(tabs, 1)
        note_layout.addLayout(buttons)

        self.summary_tree = QTreeWidget()
        self.summary_tree.setObjectName("AnnotationSummary")
        self.summary_tree.setHeaderHidden(True)
        self.summary_tree.setWordWrap(True)
        self.summary_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.summary_tree.itemClicked.connect(self._summary_item_clicked)
        self.summary_tree.itemDoubleClicked.connect(self._summary_item_double_clicked)
        self.summary_tree.customContextMenuRequested.connect(self._summary_context_menu)
        self.summary_export_button = QPushButton("Export summary")
        self.summary_export_button.setToolTip("Export all highlights and underlines, grouped by section or page, as Markdown")
        self.summary_export_button.clicked.connect(self.summary_export_requested.emit)

        self.summary_page = QWidget()
        summary_layout = QVBoxLayout(self.summary_page)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.addWidget(self.summary_tree, 1)
        summary_layout.addWidget(self.summary_export_button)

        self.view_tabs = QTabWidget()
        self.view_tabs.setObjectName("NotePanelTabs")
        self.view_tabs.addTab(self.note_page, "Note")
        self.view_tabs.addTab(self.summary_page, "Summary")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view_tabs)

        self.set_enabled(False)
        self.set_summary([])

    @property
    def current_note_id(self) -> str | None:
        return self._current_note_id

    def set_note(self, note: Note | None) -> None:
        self._current_note_id = note.id if note else None
        self.loaded_markdown = note.markdown if note else ""
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
        """The notes the user writes in: point notes, and highlights/underlines with an added note."""
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

    def set_obsidian_mode(self, enabled: bool) -> None:
        """With an Obsidian vault set, notes are files in the vault and this button opens them."""
        if enabled:
            self.export_button.setText("Open in Obsidian")
            self.export_button.setToolTip("Save this note to the Obsidian vault and open it in Obsidian (Ctrl+Shift+S)")
        else:
            self.export_button.setText("Export MD")
            self.export_button.setToolTip("Export this note as a Markdown file")

    def _open_preview_link(self, url: QUrl) -> None:
        if url.scheme().lower() == "pdfnest":
            self.pdfnest_link_requested.emit(url.toString(QUrl.FullyEncoded))
        else:
            QDesktopServices.openUrl(url)

    # --- summary of highlights and underlines --------------------------------------------------

    def set_summary(self, groups: list[SummaryGroup]) -> None:
        """Shows highlights/underlines grouped by section (or by page where there is no section),
        each followed by its note when it has one."""
        selected = self.selected_annotation_id()
        collapsed = {
            str(self.summary_tree.topLevelItem(index).data(0, ANNOTATION_ROLE) or "")
            for index in range(self.summary_tree.topLevelItemCount())
            if not self.summary_tree.topLevelItem(index).isExpanded()
        }
        self._summary_annotations = {}
        with QSignalBlocker(self.summary_tree):
            self.summary_tree.clear()
            bold = QFont(self.summary_tree.font())
            bold.setBold(True)
            italic = QFont(self.summary_tree.font())
            italic.setItalic(True)
            for group in groups:
                group_id = f"group:{group.key}"
                group_item = QTreeWidgetItem([f"{group.title}  ({len(group.annotations)})"])
                group_item.setFont(0, bold)
                group_item.setData(0, ANNOTATION_ROLE, group_id)
                group_item.setToolTip(0, f"{group.title} - page {group.first_page_index + 1}")
                self.summary_tree.addTopLevelItem(group_item)
                for note in group.annotations:
                    self._summary_annotations[note.id] = note
                    text = single_line(note.selected_text) or "(no text)"
                    label = f"p.{note.page_index + 1}  {text}" if group.is_section else text
                    item = QTreeWidgetItem([label])
                    item.setData(0, ANNOTATION_ROLE, note.id)
                    item.setIcon(0, self._annotation_icon(note))
                    kind = "Highlight" if note.note_type == "highlight" else "Underline"
                    hint = "Click the note to open it." if note.has_note else "Double-click to add a note."
                    item.setToolTip(0, f"{kind}, page {note.page_index + 1}. {hint}\n\n{note.selected_text}")
                    group_item.addChild(item)
                    if note.has_note:
                        body = single_line(annotation_note_body(note))
                        note_item = QTreeWidgetItem([f"✎ {body[:160]}" if body else "✎ Note"])
                        note_item.setFont(0, italic)
                        note_item.setData(0, ANNOTATION_ROLE, note.id)
                        note_item.setData(0, NOTE_ROW_ROLE, True)
                        note_item.setToolTip(0, "Open the note")
                        item.addChild(note_item)
                        item.setExpanded(True)
                group_item.setExpanded(group_id not in collapsed)
            if not groups:
                empty = QTreeWidgetItem(["No highlights or underlines yet."])
                empty.setFlags(Qt.NoItemFlags)
                empty.setToolTip(0, "Select text in the PDF and right-click to highlight or underline it.")
                self.summary_tree.addTopLevelItem(empty)
        self.summary_export_button.setEnabled(bool(groups))
        if selected:
            self._select_summary_row(selected)

    def summary_annotation_ids(self) -> list[str]:
        return list(self._summary_annotations)

    def selected_annotation_id(self) -> str | None:
        return self._row_note_id(self.summary_tree.currentItem())

    def show_annotation_in_summary(self, note_id: str) -> bool:
        if note_id not in self._summary_annotations:
            return False
        self.view_tabs.setCurrentWidget(self.summary_page)
        return self._select_summary_row(note_id)

    def show_note_editor(self) -> None:
        self.view_tabs.setCurrentWidget(self.note_page)

    def _select_summary_row(self, note_id: str) -> bool:
        for group_index in range(self.summary_tree.topLevelItemCount()):
            group_item = self.summary_tree.topLevelItem(group_index)
            for child_index in range(group_item.childCount()):
                item = group_item.child(child_index)
                if item.data(0, ANNOTATION_ROLE) == note_id:
                    with QSignalBlocker(self.summary_tree):
                        group_item.setExpanded(True)
                        self.summary_tree.setCurrentItem(item)
                    self.summary_tree.scrollToItem(item)
                    return True
        return False

    @staticmethod
    def _annotation_icon(note: Note) -> QIcon:
        color = QColor(note.color or DEFAULT_ANNOTATION_COLORS.get(note.note_type, "#fde68a"))
        pixmap = QPixmap(12, 12)
        if note.note_type == "highlight":
            pixmap.fill(color)
        else:
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setPen(QPen(color, 3))
            painter.drawLine(0, 10, 12, 10)
            painter.end()
        return QIcon(pixmap)

    def _row_note_id(self, item: QTreeWidgetItem | None) -> str | None:
        if item is None:
            return None
        value = str(item.data(0, ANNOTATION_ROLE) or "")
        return value if value in self._summary_annotations else None

    def _summary_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        note_id = self._row_note_id(item)
        if note_id is None:
            return
        if item.data(0, NOTE_ROW_ROLE):
            self.annotation_note_requested.emit(note_id)
        else:
            self.annotation_activated.emit(note_id)

    def _summary_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        note_id = self._row_note_id(item)
        if note_id is not None and not item.data(0, NOTE_ROW_ROLE):
            self.annotation_note_requested.emit(note_id)

    def _summary_context_menu(self, pos) -> None:
        note_id = self._row_note_id(self.summary_tree.itemAt(pos))
        if note_id is None:
            return
        note = self._summary_annotations[note_id]
        menu = QMenu(self)
        go_action = QAction("Go to text", menu)
        note_action = QAction("Open note" if note.has_note else "Add note", menu)
        remove_action = QAction("Delete note", menu)
        menu.addAction(go_action)
        menu.addAction(note_action)
        if note.has_note:
            menu.addAction(remove_action)
        chosen = menu.exec(self.summary_tree.viewport().mapToGlobal(pos))
        if chosen == go_action:
            self.annotation_activated.emit(note_id)
        elif chosen == note_action:
            self.annotation_note_requested.emit(note_id)
        elif chosen == remove_action:
            self.annotation_note_remove_requested.emit(note_id)
