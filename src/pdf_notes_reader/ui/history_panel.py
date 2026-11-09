"""Home page: recent PDFs and the virtual-folder library."""

from __future__ import annotations

import os
import re

from PySide6.QtCore import QEvent, QMimeData, QPoint, QSize, Qt, QSignalBlocker, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdf_notes_reader.history import PdfHistoryEntry
from pdf_notes_reader.library import LibraryFolder, UNFILED_FOLDER_ID, load_library, save_library
from pdf_notes_reader.notes import notebook_dir_for_key
from pdf_notes_reader.services.note_search import NotebookSearchIndex
from pdf_notes_reader.ui.resources import pic_icon
from pdf_notes_reader.ui.widgets import PDF_KEY_MIME_TYPE, ElidedLabel, LibraryFolderTree


class HistoryPanel(QWidget):
    open_requested = Signal(str)
    archive_requested = Signal(str)
    remove_requested = Signal(str)
    # Several selected books at once (pdf keys).
    archive_many_requested = Signal(list)
    restore_many_requested = Signal(list)
    remove_many_requested = Signal(list)
    export_requested = Signal(str)
    add_notebook_requested = Signal(str)  # folder id: pick PDF files to add
    add_folder_requested = Signal(str)  # folder id: pick a disk folder whose PDFs are added
    pdfs_dropped = Signal(list, str)  # dropped file/folder paths, library folder id
    rename_requested = Signal(str, str)
    restore_requested = Signal(str)
    locate_requested = Signal(str)  # the PDF is not on this computer (yet): pick its file
    settings_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[PdfHistoryEntry] = []
        self.library_state = load_library()
        self.folder_filter = ""
        self.home_mode = "recent"
        self.view_mode = "list"
        self.sort_mode = "time"
        # Selected books, in the order they were selected; the anchor is where Shift+click ranges start.
        self._selected_keys: list[str] = []
        self._selection_anchor = ""
        self._displayed_keys: list[str] = []  # the books shown now, in display order
        self._entry_widgets: dict[str, list[QWidget]] = {}  # row and card of each shown book
        self._cover_cache: dict[tuple[str, int, int], QPixmap] = {}
        self._entry_by_key: dict[str, PdfHistoryEntry] = {}
        self._folder_by_id: dict[str, LibraryFolder] = {}
        self._folder_children: dict[str, list[LibraryFolder]] = {}
        self._folder_counts: dict[str, int] = {}
        self._list_column_sizes = [520, 110, 110, 80, 360]
        self._list_row_splitters: list[QSplitter] = []
        self._syncing_list_splitters = False
        self._dragging_pdf_key = ""
        self._drag_cursor_active = False
        self.setFocusPolicy(Qt.ClickFocus)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.recent_button = self._nav_button("recent.png", "Recent", "HomeRecentButton")
        self.notebooks_button = self._nav_button("notebooks.png", "Notebooks", "HomeNotebooksButton")
        self.trash_button = self._nav_button("note-del.png", "Archive", "HomeArchiveButton")
        self.recent_button.clicked.connect(lambda: self._set_home_mode("recent"))
        self.notebooks_button.clicked.connect(lambda: self._set_home_mode("notebooks"))
        self.trash_button.clicked.connect(lambda: self._set_home_mode("archive"))

        self.folder_tree = LibraryFolderTree()
        self.folder_tree.setObjectName("LibraryFolderTree")
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.setMinimumWidth(250)
        self.folder_tree.itemSelectionChanged.connect(self._handle_folder_selection)
        self.folder_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_tree.customContextMenuRequested.connect(self._show_folder_context_menu)
        self.folder_tree.folder_drop_requested.connect(self._assign_entry_folder)
        self.folder_tree.folder_drop_keys_requested.connect(self._assign_entries_folder)

        title = QLabel("Recent PDFs")
        title.setObjectName("HistoryTitle")
        self.title_label = title
        self.folder_count_label = QLabel("(0)")
        self.folder_count_label.setObjectName("LibraryCountLabel")

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("LibrarySearch")
        self.search_edit.setPlaceholderText("Search notebooks and notes")
        self.note_index = NotebookSearchIndex()
        self.note_match_counts: dict[str, int] = {}
        self.search_edit.textChanged.connect(self._rebuild_view)

        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("LibrarySortCombo")
        self.sort_combo.addItem("Time", "time")
        self.sort_combo.addItem("Name", "name")
        self.sort_combo.currentIndexChanged.connect(self._set_sort_from_combo)

        self.new_notebook_button = self._icon_tool_button(
            "new-notebook.png", "Add PDFs to the library (or drop PDFs and folders here)", "LibraryNewNotebookButton"
        )
        add_menu = QMenu(self.new_notebook_button)
        self.add_files_action = add_menu.addAction("Add PDF files…")
        self.add_files_action.triggered.connect(lambda: self.add_notebook_requested.emit(self._target_folder_id()))
        self.add_folder_action = add_menu.addAction("Add all PDFs in a folder…")
        self.add_folder_action.triggered.connect(lambda: self.add_folder_requested.emit(self._target_folder_id()))
        self.new_notebook_button.setMenu(add_menu)
        self.new_notebook_button.setPopupMode(QToolButton.InstantPopup)
        self.new_notebook_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.setAcceptDrops(True)
        self.new_folder_button = self._icon_tool_button("new-notegroup.png", "New folder", "LibraryNewFolderButton")
        self.new_folder_button.clicked.connect(lambda: self._create_virtual_folder(parent_id=self.folder_filter))
        self.view_toggle_button = self._icon_tool_button("iconmode.png", "Icon view", "LibraryViewToggleButton")
        self.view_toggle_button.clicked.connect(self._toggle_view_mode)
        self.list_mode_button = self.view_toggle_button
        self.icon_mode_button = self.view_toggle_button

        self.settings_button = QToolButton()
        self.settings_button.setObjectName("HomeSettingsButton")
        self.settings_button.setIcon(pic_icon("settings.png"))
        self.settings_button.setIconSize(QSize(22, 22))
        self.settings_button.setToolTip("Settings")
        self.settings_button.setAutoRaise(True)
        self.settings_button.clicked.connect(self.settings_requested.emit)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(title)
        header.addWidget(self.folder_count_label)
        header.addStretch(1)
        header.addWidget(self.search_edit, 2)
        header.addWidget(self.sort_combo)
        header.addWidget(self.new_notebook_button)
        header.addWidget(self.new_folder_button)
        header.addWidget(self.view_toggle_button)
        header.addWidget(self.settings_button)

        self.content_stack = QStackedWidget()
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_layout.setAlignment(Qt.AlignTop)

        list_scroll = QScrollArea()
        list_scroll.setWidget(self.list_container)
        list_scroll.setWidgetResizable(True)
        list_scroll.setFrameShape(QScrollArea.NoFrame)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(16, 16, 16, 16)
        self.grid_layout.setHorizontalSpacing(28)
        self.grid_layout.setVerticalSpacing(28)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        grid_scroll = QScrollArea()
        grid_scroll.setWidget(self.grid_container)
        grid_scroll.setWidgetResizable(True)
        grid_scroll.setFrameShape(QScrollArea.NoFrame)

        self.content_stack.addWidget(list_scroll)
        self.content_stack.addWidget(grid_scroll)

        left_panel = QWidget()
        left_panel.setObjectName("LibraryLeftPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 10, 0, 10)
        left_layout.setSpacing(8)
        tree_title = QLabel("Folders")
        tree_title.setObjectName("LibrarySidebarTitle")
        left_layout.addWidget(tree_title)
        left_layout.addWidget(self.folder_tree, 1)

        nav_panel = QWidget()
        nav_panel.setObjectName("HomeNavPanel")
        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(6, 8, 6, 8)
        nav_layout.setSpacing(8)
        nav_layout.addWidget(self.recent_button)
        nav_layout.addWidget(self.notebooks_button)
        nav_layout.addWidget(self.trash_button)
        nav_layout.addStretch(1)

        right_panel = QWidget()
        right_panel.setObjectName("LibraryRightPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 10, 10, 10)
        right_layout.setSpacing(10)
        right_layout.addLayout(header)
        right_layout.addWidget(self.content_stack, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("LibrarySplitter")
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 900])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(nav_panel, 0)
        row.addWidget(splitter, 1)
        layout.addLayout(row, 1)
        self._set_home_mode("recent")

    def set_entries(self, entries: list[PdfHistoryEntry]) -> None:
        self.entries = entries
        self._entry_by_key = {entry.pdf_key: entry for entry in entries}
        self.library_state = load_library()
        self._rebuild_library_indexes()
        self._rebuild_folders()
        self._rebuild_files()

    @staticmethod
    def _nav_button(icon_name: str, tooltip: str, object_name: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName(object_name)
        button.setIcon(pic_icon(icon_name))
        button.setIconSize(QSize(30, 30))
        button.setToolTip(tooltip)
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setFixedSize(48, 48)
        return button

    @staticmethod
    def _mode_button(icon_name: str, tooltip: str, object_name: str) -> QToolButton:
        return HistoryPanel._icon_tool_button(icon_name, tooltip, object_name, checkable=True)

    @staticmethod
    def _icon_tool_button(icon_name: str, tooltip: str, object_name: str, *, checkable: bool = False) -> QToolButton:
        button = QToolButton()
        button.setObjectName(object_name)
        button.setIcon(pic_icon(icon_name))
        button.setIconSize(QSize(22, 22))
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        button.setAutoRaise(True)
        button.setFixedSize(34, 34)
        return button

    def _set_home_mode(self, mode: str) -> None:
        self.home_mode = mode if mode in {"recent", "notebooks", "archive"} else "recent"
        self.recent_button.setChecked(self.home_mode == "recent")
        self.notebooks_button.setChecked(self.home_mode == "notebooks")
        self.trash_button.setChecked(self.home_mode == "archive")
        self.title_label.setText({"recent": "Recent PDFs", "notebooks": "Notebooks", "archive": "Archive"}[self.home_mode])
        self.folder_tree.parentWidget().setVisible(self.home_mode == "notebooks")
        self.new_folder_button.setVisible(self.home_mode == "notebooks")
        self._rebuild_view()

    def _set_sort_from_combo(self) -> None:
        self.sort_mode = str(self.sort_combo.currentData() or "time")
        self._rebuild_library_indexes()
        self._rebuild_folders()
        self._rebuild_files()

    def _set_view_mode(self, mode: str) -> None:
        self.view_mode = "icon" if mode == "icon" else "list"
        self.content_stack.setCurrentIndex(1 if self.view_mode == "icon" else 0)
        self._refresh_view_toggle_button()
        self._rebuild_files()

    def _toggle_view_mode(self) -> None:
        self._set_view_mode("icon" if self.view_mode == "list" else "list")

    def _refresh_view_toggle_button(self) -> None:
        if self.view_mode == "list":
            self.view_toggle_button.setIcon(pic_icon("iconmode.png"))
            self.view_toggle_button.setToolTip("Icon view")
        else:
            self.view_toggle_button.setIcon(pic_icon("listmode.png"))
            self.view_toggle_button.setToolTip("List view")

    def _entry_folder_id(self, entry: PdfHistoryEntry) -> str:
        return self.library_state.assignments.get(entry.pdf_key, UNFILED_FOLDER_ID)

    def _rebuild_library_indexes(self) -> None:
        self._folder_by_id = {folder.id: folder for folder in self.library_state.folders}
        self._folder_children = {"": []}
        for folder in self.library_state.folders:
            self._folder_children.setdefault(folder.parent_id, []).append(folder)
            self._folder_children.setdefault(folder.id, [])
        for children in self._folder_children.values():
            unfiled = [folder for folder in children if folder.id == UNFILED_FOLDER_ID]
            sortable = [folder for folder in children if folder.id != UNFILED_FOLDER_ID]
            if self.sort_mode == "name":
                sortable.sort(key=lambda item: (item.name.casefold(), item.created_at))
            else:
                sortable.sort(key=lambda item: item.created_at, reverse=True)
            children[:] = unfiled + sortable
        self._folder_counts = {folder.id: 0 for folder in self.library_state.folders}
        for entry in self.entries:
            folder_id = self._entry_folder_id(entry)
            if folder_id in self._folder_counts:
                self._folder_counts[folder_id] += 1

    def _folder_descendant_ids(self, folder_id: str) -> set[str]:
        result = {folder_id} if folder_id else set()
        pending = list(self._folder_children.get(folder_id, []))
        while pending:
            folder = pending.pop()
            if folder.id in result:
                continue
            result.add(folder.id)
            pending.extend(self._folder_children.get(folder.id, []))
        return result

    def _folder_total_count(self, folder_id: str) -> int:
        if not folder_id:
            return len(self.entries)
        return sum(self._folder_counts.get(folder, 0) for folder in self._folder_descendant_ids(folder_id))

    def _entry_matches_folder(self, entry: PdfHistoryEntry) -> bool:
        archived = entry.pdf_key in self.library_state.archived
        if self.home_mode == "archive":
            return archived
        if archived:
            return False
        if self.home_mode == "recent":
            return True
        if not self.folder_filter:
            return True
        if self.folder_filter == UNFILED_FOLDER_ID:
            return self._entry_folder_id(entry) == UNFILED_FOLDER_ID
        return self._entry_folder_id(entry) in self._folder_descendant_ids(self.folder_filter)

    def _filtered_entries(self) -> list[PdfHistoryEntry]:
        query = self.search_edit.text().strip().casefold()
        entries = [entry for entry in self.entries if self._entry_matches_folder(entry)]
        self.note_match_counts = {}
        if query:
            # Notebooks match by name/path, or when any of their notes contains every search term.
            self.note_match_counts = self.note_index.match_counts([entry.pdf_key for entry in entries], query)
            entries = [
                entry
                for entry in entries
                if query in self._entry_title(entry).casefold()
                or query in entry.path.casefold()
                or entry.pdf_key in self.note_match_counts
            ]
        if self.sort_mode == "name":
            entries.sort(key=lambda entry: (self._entry_title(entry).casefold(), entry.updated_at))
        else:
            entries.sort(key=lambda entry: entry.updated_at, reverse=True)
        return entries

    def _entry_title(self, entry: PdfHistoryEntry) -> str:
        return self.library_state.aliases.get(entry.pdf_key) or entry.title

    def _rebuild_folders(self) -> None:
        selected_id = self.folder_filter
        expanded_ids = self._expanded_folder_ids()
        blocker = QSignalBlocker(self.folder_tree)
        self.folder_tree.clear()
        root = QTreeWidgetItem([f"All ({len(self.entries)})"])
        root.setData(0, Qt.UserRole, "")
        self.folder_tree.addTopLevelItem(root)

        def add_children(parent_item: QTreeWidgetItem, parent_id: str) -> None:
            for folder in self._folder_children.get(parent_id, []):
                item = QTreeWidgetItem([f"{folder.name} ({self._folder_total_count(folder.id)})"])
                item.setData(0, Qt.UserRole, folder.id)
                parent_item.addChild(item)
                add_children(item, folder.id)
                item.setExpanded(folder.id in expanded_ids)

        root.setExpanded(True)
        add_children(root, "")
        self._select_folder(selected_id, fallback_to_root=True)
        del blocker
        self._handle_folder_selection()

    def _expanded_folder_ids(self) -> set[str]:
        expanded: set[str] = set()

        def collect(item: QTreeWidgetItem) -> None:
            folder_id = str(item.data(0, Qt.UserRole) or "")
            if folder_id and item.isExpanded():
                expanded.add(folder_id)
            for index in range(item.childCount()):
                collect(item.child(index))

        root = self.folder_tree.topLevelItem(0)
        if root is not None:
            collect(root)
        return expanded

    def _handle_folder_selection(self) -> None:
        item = self.folder_tree.currentItem()
        previous = self.folder_filter
        self.folder_filter = str(item.data(0, Qt.UserRole) or "") if item is not None else ""
        if self.folder_filter != previous:
            self._rebuild_view()
        else:
            self._rebuild_files()  # the folder list was rebuilt: the same view

    def _create_virtual_folder(self, *, parent_id: str = "") -> None:
        if parent_id == UNFILED_FOLDER_ID:
            parent_id = ""
        name, accepted = QInputDialog.getText(self, "New folder", "Folder name:")
        if not accepted or not name.strip():
            return
        folder = LibraryFolder.create(name, parent_id=parent_id)
        self.library_state.folders.append(folder)
        save_library(self.library_state)
        self.folder_filter = folder.id
        self._rebuild_library_indexes()
        self._rebuild_folders()

    def _select_folder(self, folder_id: str, *, fallback_to_root: bool = False) -> None:
        root = self.folder_tree.topLevelItem(0)
        if root is None:
            return

        def find_item(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            if item.data(0, Qt.UserRole) == folder_id:
                return item
            for index in range(item.childCount()):
                found = find_item(item.child(index))
                if found is not None:
                    return found
            return None

        found = find_item(root)
        if found is not None:
            self.folder_tree.setCurrentItem(found)
        elif fallback_to_root:
            self.folder_tree.setCurrentItem(root)

    def _target_folder_id(self) -> str:
        """The library folder new PDFs go into: the open folder in Notebooks view, otherwise none."""
        return self.folder_filter if self.home_mode == "notebooks" else ""

    # --- dropping PDFs and folders from Explorer -----------------------------------------------

    @staticmethod
    def _dropped_paths(event) -> list[str]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        return [path for path in paths if path.lower().endswith(".pdf") or os.path.isdir(path)]

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._dropped_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._dropped_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        paths = self._dropped_paths(event)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        folder_id = self._target_folder_id()
        # Dropped onto a folder in the folder tree: add into that folder.
        tree_pos = self.folder_tree.viewport().mapFrom(self, event.position().toPoint())
        if self.folder_tree.isVisible() and self.folder_tree.viewport().rect().contains(tree_pos):
            item = self.folder_tree.itemAt(tree_pos)
            if item is not None:
                folder_id = str(item.data(0, Qt.UserRole) or "")
        self.pdfs_dropped.emit(paths, folder_id)

    def _show_folder_context_menu(self, pos: QPoint) -> None:
        item = self.folder_tree.itemAt(pos)
        if item is None:
            return
        folder_id = str(item.data(0, Qt.UserRole) or "")
        menu = QMenu(self)
        add_files_action = menu.addAction("Add PDF files here…")
        add_folder_action = menu.addAction("Add all PDFs in a folder here…")
        menu.addSeparator()
        new_child_action = menu.addAction("New subfolder" if folder_id else "New folder")
        rename_action = menu.addAction("Rename") if folder_id and folder_id != UNFILED_FOLDER_ID else None
        delete_action = menu.addAction("Delete") if folder_id and folder_id != UNFILED_FOLDER_ID else None
        chosen = menu.exec(self.folder_tree.viewport().mapToGlobal(pos))
        if chosen == add_files_action:
            self.add_notebook_requested.emit(folder_id)
        elif chosen == add_folder_action:
            self.add_folder_requested.emit(folder_id)
        elif chosen == new_child_action:
            self._create_virtual_folder(parent_id=folder_id)
        elif rename_action is not None and chosen == rename_action:
            self._rename_folder(folder_id)
        elif delete_action is not None and chosen == delete_action:
            self._delete_folder(folder_id)

    def _rename_folder(self, folder_id: str) -> None:
        folder = self._folder_by_id.get(folder_id)
        if folder is None or folder.id == UNFILED_FOLDER_ID:
            return
        name, accepted = QInputDialog.getText(self, "Rename folder", "Folder name:", text=folder.name)
        if not accepted or not name.strip():
            return
        folder.name = name.strip()
        save_library(self.library_state)
        self._rebuild_library_indexes()
        self._rebuild_folders()
        self._select_folder(folder.id)

    def _delete_folder(self, folder_id: str) -> None:
        if not folder_id or folder_id == UNFILED_FOLDER_ID:
            return
        delete_ids = self._folder_descendant_ids(folder_id)
        parent_id = self._folder_by_id.get(folder_id).parent_id if folder_id in self._folder_by_id else ""
        self.library_state.folders = [folder for folder in self.library_state.folders if folder.id not in delete_ids]
        self.library_state.assignments = {
            key: value for key, value in self.library_state.assignments.items() if value not in delete_ids
        }
        save_library(self.library_state)
        self.folder_filter = parent_id if parent_id in {folder.id for folder in self.library_state.folders} else ""
        self._rebuild_library_indexes()
        self._rebuild_folders()

    def _rebuild_files(self) -> None:
        entries = self._filtered_entries()
        self.folder_count_label.setText(f"({len(entries)})")
        self._list_row_splitters = []
        self._entry_widgets = {}
        self._displayed_keys = [entry.pdf_key for entry in entries]
        # Books gone from the library leave the selection. One that just moved out of view (archived,
        # filed elsewhere) stays selected until the view changes, so Shift+Delete still removes it.
        self._selected_keys = [key for key in self._selected_keys if key in self._entry_by_key]
        self._clear_layout_widgets(self.list_layout)
        self._clear_layout_widgets(self.grid_layout)

        if not entries:
            list_empty = QLabel("No PDFs opened yet.")
            list_empty.setObjectName("HistoryEmpty")
            grid_empty = QLabel("No PDFs opened yet.")
            grid_empty.setObjectName("HistoryEmpty")
            self.list_layout.addWidget(list_empty)
            self.grid_layout.addWidget(grid_empty, 0, 0)
            return

        self.list_layout.addWidget(self._build_list_header())
        for entry in entries:
            self.list_layout.addWidget(self._build_row(entry))

        for index, entry in enumerate(entries):
            self.grid_layout.addWidget(self._build_grid_card(entry), index // 5, index % 5)
        self._refresh_selection_marks()

    # --- selecting books -------------------------------------------------------------------------

    def _rebuild_view(self, *_args) -> None:
        """Shows another view (mode, folder, search): books it does not show are no longer selected."""
        self._rebuild_files()
        shown = set(self._displayed_keys)
        if any(key not in shown for key in self._selected_keys):
            self.set_selected_pdf_keys([key for key in self._selected_keys if key in shown])

    @property
    def selected_pdf_key(self) -> str:
        """The book clicked last among the selected ones ("" when nothing is selected)."""
        if self._selection_anchor in self._selected_keys:
            return self._selection_anchor
        return self._selected_keys[-1] if self._selected_keys else ""

    @selected_pdf_key.setter
    def selected_pdf_key(self, pdf_key: str) -> None:
        self.set_selected_pdf_keys([pdf_key] if pdf_key else [])

    @property
    def selected_pdf_keys(self) -> list[str]:
        return list(self._selected_keys)

    def set_selected_pdf_keys(self, pdf_keys, anchor: str | None = None) -> None:
        self._selected_keys = list(dict.fromkeys(key for key in pdf_keys if key))
        self._selection_anchor = anchor if anchor is not None else (self._selected_keys[-1] if self._selected_keys else "")
        self._refresh_selection_marks()

    def select_all_entries(self) -> None:
        """Ctrl+A: every book shown in the current view."""
        self.set_selected_pdf_keys(self._displayed_keys, anchor=self._displayed_keys[0] if self._displayed_keys else "")

    def _click_select(self, pdf_key: str, modifiers) -> None:
        """Ctrl+click adds or removes one book, Shift+click selects the range from the last click."""
        if modifiers & Qt.ControlModifier:
            if pdf_key in self._selected_keys:
                self._selected_keys.remove(pdf_key)
            else:
                self._selected_keys.append(pdf_key)
            self._selection_anchor = pdf_key
            self._refresh_selection_marks()
        elif modifiers & Qt.ShiftModifier and self._selection_anchor in self._displayed_keys and pdf_key in self._displayed_keys:
            start = self._displayed_keys.index(self._selection_anchor)
            end = self._displayed_keys.index(pdf_key)
            low, high = min(start, end), max(start, end)
            self._selected_keys = self._displayed_keys[low : high + 1]
            self._refresh_selection_marks()  # the anchor stays, so the range can be changed again
        else:
            self.set_selected_pdf_keys([pdf_key])

    def _refresh_selection_marks(self) -> None:
        selected = set(self._selected_keys)
        for key, widgets in self._entry_widgets.items():
            for widget in widgets:
                try:
                    if bool(widget.property("selected")) == (key in selected):
                        continue
                    widget.setProperty("selected", key in selected)
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)
                    widget.update()
                except RuntimeError:  # deleted with an earlier rebuild
                    continue

    def _build_list_header(self) -> QWidget:
        row = QWidget()
        row.setObjectName("LibraryListHeader")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(10)
        labels = ("Name", "Created", "Last read", "Pages", "Path")
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("LibraryHeaderSplitter")
        splitter.setHandleWidth(1)
        for label in labels:
            widget = ElidedLabel(label)
            widget.setObjectName("LibraryListHeaderLabel")
            splitter.addWidget(widget)
        for index, stretch in enumerate((6, 1, 1, 1, 4)):
            splitter.setStretchFactor(index, stretch)
            splitter.setCollapsible(index, True)
        splitter.setSizes(self._list_column_sizes)
        splitter.splitterMoved.connect(lambda _pos, _index, source=splitter: self._sync_list_column_sizes(source))
        layout.addWidget(splitter)
        return row

    @staticmethod
    def _clear_layout_widgets(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _build_row(self, entry: PdfHistoryEntry) -> QWidget:
        row = QWidget()
        row.setObjectName("LibraryRowMissing" if not entry.exists else "LibraryRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        self._entry_widgets.setdefault(entry.pdf_key, []).append(row)
        self._install_entry_context_menu(row, entry)

        cover = QLabel()
        cover.setObjectName("LibraryRowCover")
        cover.setFixedSize(34, 46)
        cover.setAlignment(Qt.AlignCenter)
        self._install_entry_context_menu(cover, entry)
        pixmap = self._cover_pixmap(entry, QSize(34, 46))
        if pixmap is not None:
            cover.setPixmap(pixmap)
        else:
            cover.setText("PDF")

        title_text = self._entry_title(entry)
        matches = self.note_match_counts.get(entry.pdf_key, 0)
        if matches:
            title_text += f"  ·  {matches} matching note{'s' if matches != 1 else ''}"
        title = ElidedLabel(title_text)
        title.setObjectName("HistoryRowTitle")
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title.setWordWrap(False)
        title.setFont(self._library_title_font())
        self._install_entry_context_menu(title, entry)

        path = ElidedLabel(entry.path if entry.exists else self._not_here_text(entry))
        path.setObjectName("HistoryRowPath")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path.setWordWrap(False)
        self._install_entry_context_menu(path, entry)

        page = entry.last_page_index + 1 if entry.page_count else 1
        last_read = f"{page}"
        if entry.page_count:
            last_read += f" / {entry.page_count}"
        if not entry.exists:
            last_read += " · not here"

        name_box = QWidget()
        name_box.setMinimumWidth(0)
        name_box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._install_entry_context_menu(name_box, entry)
        name_layout = QHBoxLayout(name_box)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(8)
        name_layout.addWidget(cover)
        name_layout.addWidget(title, 1)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("LibraryRowSplitter")
        splitter.setHandleWidth(1)
        for widget in (
            name_box,
            self._list_cell_label(entry.opened_at[:10]),
            self._list_cell_label(last_read),
            self._list_cell_label(str(entry.page_count or "")),
            path,
        ):
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            splitter.addWidget(widget)
        for index, stretch in enumerate((6, 1, 1, 1, 4)):
            splitter.setStretchFactor(index, stretch)
            splitter.setCollapsible(index, True)
        splitter.setSizes(self._list_column_sizes)
        splitter.splitterMoved.connect(lambda _pos, _index, source=splitter: self._sync_list_column_sizes(source))
        self._list_row_splitters.append(splitter)
        layout.addWidget(splitter)
        return row

    @staticmethod
    def _list_cell_label(text: str) -> ElidedLabel:
        label = ElidedLabel(text)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        return label

    def _sync_list_column_sizes(self, source: QSplitter) -> None:
        if self._syncing_list_splitters:
            return
        self._syncing_list_splitters = True
        try:
            self._list_column_sizes = source.sizes()
            for splitter in self.findChildren(QSplitter):
                if splitter is source:
                    continue
                if splitter.objectName() in {"LibraryRowSplitter", "LibraryHeaderSplitter"} and splitter.count() == len(self._list_column_sizes):
                    splitter.setSizes(self._list_column_sizes)
        finally:
            self._syncing_list_splitters = False

    def _build_grid_card(self, entry: PdfHistoryEntry) -> QWidget:
        card = QWidget()
        card.setObjectName("LibraryGridCardMissing" if not entry.exists else "LibraryGridCard")
        card.setFixedSize(214, 292)
        card.setAttribute(Qt.WA_StyledBackground, True)
        self._entry_widgets.setdefault(entry.pdf_key, []).append(card)
        self._install_entry_context_menu(card, entry)

        cover = QLabel()
        cover.setObjectName("LibraryGridCover")
        cover.setFixedSize(156, 200)
        cover.setAlignment(Qt.AlignCenter)
        self._install_entry_context_menu(cover, entry)
        pixmap = self._cover_pixmap(entry, QSize(156, 200))
        if pixmap is not None:
            cover.setPixmap(pixmap)
        else:
            cover.setText("PDF")

        display_title = self._entry_title(entry)
        title = QLabel(display_title)
        title.setObjectName("LibraryGridTitle")
        title.setText(self._middle_elide_text(display_title, max_chars=86))
        title.setToolTip(display_title)
        title.setFixedSize(190, 58)
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        title.setFont(self._library_title_font())
        self._install_entry_context_menu(title, entry)

        card.mouseDoubleClickEvent = lambda _event, key=entry.pdf_key: self.open_requested.emit(key)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.addWidget(cover, 0, Qt.AlignHCenter)
        layout.addWidget(title, 0, Qt.AlignHCenter)
        return card

    @staticmethod
    def _middle_elide_text(value: str, *, max_chars: int) -> str:
        text = re.sub(r"\s+", " ", value).strip()
        if len(text) <= max_chars:
            return text
        keep_front = max(8, max_chars // 2 - 2)
        keep_back = max(8, max_chars - keep_front - 3)
        return f"{text[:keep_front].rstrip()}...{text[-keep_back:].lstrip()}"

    @staticmethod
    def _library_title_font() -> QFont:
        font = QFont("Segoe UI", 10)
        font.setWeight(QFont.Medium)
        font.setStyleStrategy(QFont.PreferAntialias)
        return font

    def _install_entry_context_menu(self, widget: QWidget, entry: PdfHistoryEntry) -> None:
        widget.setContextMenuPolicy(Qt.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda pos, key=entry.pdf_key, source=widget: self._show_entry_context_menu(key, source.mapToGlobal(pos))
        )
        original_mouse_press = widget.mousePressEvent
        original_mouse_move = widget.mouseMoveEvent
        original_mouse_release = widget.mouseReleaseEvent
        original_mouse_double_click = widget.mouseDoubleClickEvent

        def handle_mouse_press(event, key=entry.pdf_key) -> None:
            # Take keyboard focus from the search field, so D / Delete / Ctrl+A act on the books.
            self.setFocus(Qt.MouseFocusReason)
            modifiers = event.modifiers()
            if event.button() == Qt.LeftButton:
                if key in self._selected_keys and len(self._selected_keys) > 1 and not modifiers & (Qt.ControlModifier | Qt.ShiftModifier):
                    # Pressing on a selected book keeps the selection, so all of them can be dragged;
                    # a click without a drag selects just this book (on release).
                    widget.setProperty("_pdfnest_collapse_to", key)
                    self._selection_anchor = key
                else:
                    self._click_select(key, modifiers)
                widget.setProperty("_pdfnest_drag_key", key)
                widget.setProperty("_pdfnest_drag_start", self._mouse_event_pos(event))
            elif event.button() == Qt.RightButton and key not in self._selected_keys:
                self.set_selected_pdf_keys([key])
            original_mouse_press(event)
            if event.button() in (Qt.LeftButton, Qt.RightButton):
                event.accept()  # the row or card it sits in must not handle the same click again

        def handle_mouse_move(event, key=entry.pdf_key) -> None:
            start = widget.property("_pdfnest_drag_start")
            drag_key = widget.property("_pdfnest_drag_key")
            if (
                drag_key == key
                and event.buttons() & Qt.LeftButton
                and isinstance(start, QPoint)
                and (self._mouse_event_pos(event) - start).manhattanLength() >= QApplication.startDragDistance()
            ):
                widget.setProperty("_pdfnest_drag_start", None)
                widget.setProperty("_pdfnest_collapse_to", "")
                self._start_entry_drag(widget, key)
                return
            original_mouse_move(event)

        def handle_mouse_release(event) -> None:
            collapse_to = widget.property("_pdfnest_collapse_to")
            widget.setProperty("_pdfnest_collapse_to", "")
            widget.setProperty("_pdfnest_drag_start", None)
            widget.setProperty("_pdfnest_drag_key", "")
            if collapse_to and event.button() == Qt.LeftButton:
                self.set_selected_pdf_keys([collapse_to])
            original_mouse_release(event)

        def handle_mouse_double_click(event, key=entry.pdf_key) -> None:
            if event.button() == Qt.LeftButton:
                self.open_requested.emit(key)
                event.accept()
                return
            original_mouse_double_click(event)

        widget.mousePressEvent = handle_mouse_press
        widget.mouseMoveEvent = handle_mouse_move
        widget.mouseReleaseEvent = handle_mouse_release
        widget.mouseDoubleClickEvent = handle_mouse_double_click

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt override
        if self._dragging_pdf_key:
            if event.type() == QEvent.MouseMove:
                self._update_folder_drag_hover(self._mouse_event_global_pos(event))
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._finish_entry_drag(self._mouse_event_global_pos(event))
            elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._cancel_entry_drag()
        return super().eventFilter(watched, event)

    @staticmethod
    def _mouse_event_pos(event) -> QPoint:
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    @staticmethod
    def _mouse_event_global_pos(event) -> QPoint:
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        return event.globalPos()

    def entry_drag_mime(self, pdf_keys: str | list[str]) -> QMimeData:
        """Drag data naming one book or several (one key per line)."""
        keys = [pdf_keys] if isinstance(pdf_keys, str) else list(pdf_keys)
        mime = QMimeData()
        mime.setData(PDF_KEY_MIME_TYPE, "\n".join(keys).encode("utf-8"))
        return mime

    def _start_entry_drag(self, source: QWidget, pdf_key: str) -> None:
        """Drags a book (shown as a picture of its row or card) onto a folder in the folder list.
        Dragging one of several selected books drags all of them; the picture shows how many.

        The folder list is shown while dragging even from Recent, so there is always somewhere to drop.
        """
        keys = self.selected_pdf_keys if pdf_key in self._selected_keys else [pdf_key]
        drag = QDrag(self)  # not the row: dropping rebuilds the rows, which would delete the drag's owner
        drag.setMimeData(self.entry_drag_mime(keys))
        picture = source.grab()
        if not picture.isNull():
            if picture.width() > 360:
                picture = picture.scaledToWidth(360, Qt.SmoothTransformation)
            if len(keys) > 1:
                self._paint_drag_count(picture, len(keys))
            drag.setPixmap(picture)
            drag.setHotSpot(QPoint(min(24, picture.width() // 2), picture.height() // 2))
        sidebar = self.folder_tree.parentWidget()
        was_hidden = sidebar is not None and not sidebar.isVisible()
        if was_hidden:
            sidebar.setVisible(True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            if was_hidden and self.home_mode != "notebooks":
                sidebar.setVisible(False)

    @staticmethod
    def _paint_drag_count(picture: QPixmap, count: int) -> None:
        painter = QPainter(picture)
        painter.setRenderHint(QPainter.Antialiasing, True)
        size = min(28, picture.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(37, 99, 235))
        painter.drawEllipse(picture.width() - size - 2, 2, size, size)
        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(picture.width() - size - 2, 2, size, size, Qt.AlignCenter, str(count))
        painter.end()

    def _update_folder_drag_hover(self, global_pos: QPoint) -> None:
        item = self.folder_tree.itemAt(self.folder_tree.viewport().mapFromGlobal(global_pos))
        if item is not None:
            self.folder_tree.setCurrentItem(item)

    def _finish_entry_drag(self, global_pos: QPoint) -> None:
        pdf_key = self._dragging_pdf_key
        self._cancel_entry_drag()
        if not pdf_key:
            return
        item = self.folder_tree.itemAt(self.folder_tree.viewport().mapFromGlobal(global_pos))
        if item is None:
            return
        folder_id = str(item.data(0, Qt.UserRole) or "")
        self._assign_entry_folder(pdf_key, folder_id)

    def _cancel_entry_drag(self) -> None:
        self._dragging_pdf_key = ""
        if self._drag_cursor_active:
            QApplication.restoreOverrideCursor()
            self._drag_cursor_active = False

    @staticmethod
    def _exec_menu(menu: QMenu, global_pos: QPoint) -> QAction | None:
        """Shows a book menu and returns the chosen action (tests replace this)."""
        return menu.exec(global_pos)

    def _add_move_to_folder_menu(self, menu: QMenu) -> dict[QAction, str]:
        move_menu = menu.addMenu("Move to folder")
        move_actions: dict[QAction, str] = {}
        unfiled_action = move_menu.addAction("Unfiled")
        move_actions[unfiled_action] = UNFILED_FOLDER_ID
        for folder in self.library_state.folders:
            if folder.id == UNFILED_FOLDER_ID:
                continue
            action = move_menu.addAction(self._folder_path_label(folder.id))
            move_actions[action] = folder.id
        return move_actions

    def _show_selection_context_menu(self, pdf_keys: list[str], global_pos: QPoint) -> None:
        """The menu for several selected books: move, archive or restore, or remove them together."""
        count = len(pdf_keys)
        menu = QMenu(self)
        title = menu.addAction(f"{count} PDFs selected")
        title.setEnabled(False)
        menu.addSeparator()
        move_actions = self._add_move_to_folder_menu(menu)
        archived = [key for key in pdf_keys if key in self.library_state.archived]
        active = [key for key in pdf_keys if key not in self.library_state.archived]
        restore_action = menu.addAction(f"Restore {len(archived)}" if active else "Restore") if archived else None
        archive_action = menu.addAction(f"Move {len(active)} to archive" if archived else "Move to archive") if active else None
        delete_action = menu.addAction(f"Permanent delete {count} PDFs…")
        chosen = self._exec_menu(menu, global_pos)
        if chosen is None:
            return
        if chosen in move_actions:
            self._assign_entries_folder(pdf_keys, move_actions[chosen])
        elif restore_action is not None and chosen == restore_action:
            self.restore_many_requested.emit(archived)
        elif archive_action is not None and chosen == archive_action:
            self.archive_many_requested.emit(active)
        elif chosen == delete_action:
            self.remove_many_requested.emit(list(pdf_keys))

    def _show_entry_context_menu(self, pdf_key: str, global_pos: QPoint) -> None:
        entry = self._entry_by_key.get(pdf_key)
        if entry is None:
            return
        if pdf_key in self._selected_keys and len(self._selected_keys) > 1:
            self._show_selection_context_menu(self.selected_pdf_keys, global_pos)
            return
        menu = QMenu(self)
        open_action = menu.addAction("Open")
        locate_action = menu.addAction("Locate PDF on this computer…" if not entry.exists else "Change PDF file…")
        rename_action = menu.addAction("Rename")
        export_action = menu.addAction("Export all notes")
        move_actions = self._add_move_to_folder_menu(menu)
        restore_action = menu.addAction("Restore") if pdf_key in self.library_state.archived else None
        archive_action = menu.addAction("Move to archive") if pdf_key not in self.library_state.archived else None
        delete_action = menu.addAction("Permanent delete")
        chosen = self._exec_menu(menu, global_pos)
        if chosen == open_action:
            self.open_requested.emit(pdf_key)
        elif chosen == locate_action:
            self.locate_requested.emit(pdf_key)
        elif chosen == rename_action:
            name, accepted = QInputDialog.getText(self, "Rename notebook", "Display name:", text=self._entry_title(entry))
            if accepted and name.strip():
                self.rename_requested.emit(pdf_key, name.strip())
        elif chosen == export_action:
            self.export_requested.emit(pdf_key)
        elif restore_action is not None and chosen == restore_action:
            self.restore_requested.emit(pdf_key)
        elif archive_action is not None and chosen == archive_action:
            self.archive_requested.emit(pdf_key)
        elif chosen == delete_action:
            self.remove_requested.emit(pdf_key)
        elif chosen in move_actions:
            self._assign_entry_folder(pdf_key, move_actions[chosen])

    @staticmethod
    def _not_here_text(entry: PdfHistoryEntry) -> str:
        if entry.in_cloud_only:
            return "In iCloud only: double-click to download and open it"
        if entry.located_here:
            return f"Moved or deleted ({entry.path}): double-click to locate it"
        return "Not on this computer yet: double-click to locate the PDF (notes and cover are already here)"

    def _folder_path_label(self, folder_id: str) -> str:
        folder = self._folder_by_id.get(folder_id)
        if folder is None:
            return "Unfiled"
        parts = [folder.name]
        parent_id = folder.parent_id
        seen = {folder.id}
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = self._folder_by_id.get(parent_id)
            if parent is None:
                break
            parts.append(parent.name)
            parent_id = parent.parent_id
        return " / ".join(reversed(parts))

    def _assign_entry_folder(self, pdf_key: str, folder_id: str) -> None:
        self._assign_entries_folder([pdf_key], folder_id)

    def _assign_entries_folder(self, pdf_keys: list[str], folder_id: str) -> None:
        """Files the books into ``folder_id`` with one save (the top level or Unfiled: no folder)."""
        for pdf_key in pdf_keys:
            if not folder_id or folder_id == UNFILED_FOLDER_ID:  # the top level means "in no folder"
                self.library_state.assignments.pop(pdf_key, None)
            else:
                self.library_state.assignments[pdf_key] = folder_id
        save_library(self.library_state)
        self._rebuild_library_indexes()
        self._rebuild_folders()
        if self.folder_filter:
            self._select_folder(self.folder_filter)
        self._rebuild_files()

    def _cover_pixmap(self, entry: PdfHistoryEntry, size: QSize) -> QPixmap | None:
        cache_key = (entry.pdf_key, size.width(), size.height())
        if cache_key in self._cover_cache:
            return self._cover_cache[cache_key]
        notebook_dir = notebook_dir_for_key(entry.pdf_key)
        if notebook_dir is None:
            return None
        cover_path = notebook_dir / "cover.png"
        if not cover_path.exists():
            return None
        pixmap = QPixmap(str(cover_path))
        if pixmap.isNull():
            return None
        scaled = pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._cover_cache[cache_key] = scaled
        return scaled
