"""Home page: recent PDFs and the virtual-folder library."""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QSignalBlocker, Signal
from PySide6.QtGui import QAction, QFont, QPixmap
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
from pdf_notes_reader.ui.widgets import ElidedLabel, LibraryFolderTree


class HistoryPanel(QWidget):
    open_requested = Signal(str)
    archive_requested = Signal(str)
    remove_requested = Signal(str)
    export_requested = Signal(str)
    add_notebook_requested = Signal(str)
    rename_requested = Signal(str, str)
    restore_requested = Signal(str)
    settings_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[PdfHistoryEntry] = []
        self.library_state = load_library()
        self.folder_filter = ""
        self.home_mode = "recent"
        self.view_mode = "list"
        self.sort_mode = "time"
        self.selected_pdf_key = ""
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
        self.search_edit.textChanged.connect(self._rebuild_files)

        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("LibrarySortCombo")
        self.sort_combo.addItem("Time", "time")
        self.sort_combo.addItem("Name", "name")
        self.sort_combo.currentIndexChanged.connect(self._set_sort_from_combo)

        self.new_notebook_button = self._icon_tool_button("new-notebook.png", "Add planned PDF", "LibraryNewNotebookButton")
        self.new_notebook_button.clicked.connect(lambda: self.add_notebook_requested.emit(self.folder_filter if self.home_mode == "notebooks" else ""))
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
        self._rebuild_files()

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
        self.folder_filter = str(item.data(0, Qt.UserRole) or "") if item is not None else ""
        self._rebuild_files()

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

    def _show_folder_context_menu(self, pos: QPoint) -> None:
        item = self.folder_tree.itemAt(pos)
        if item is None:
            return
        folder_id = str(item.data(0, Qt.UserRole) or "")
        menu = QMenu(self)
        new_child_action = menu.addAction("New subfolder" if folder_id else "New folder")
        rename_action = menu.addAction("Rename") if folder_id and folder_id != UNFILED_FOLDER_ID else None
        delete_action = menu.addAction("Delete") if folder_id and folder_id != UNFILED_FOLDER_ID else None
        chosen = menu.exec(self.folder_tree.viewport().mapToGlobal(pos))
        if chosen == new_child_action:
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

        path = ElidedLabel(entry.path)
        path.setObjectName("HistoryRowPath")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path.setWordWrap(False)
        self._install_entry_context_menu(path, entry)

        page = entry.last_page_index + 1 if entry.page_count else 1
        last_read = f"{page}"
        if entry.page_count:
            last_read += f" / {entry.page_count}"
        if not entry.exists:
            last_read += " Missing"

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
            self.selected_pdf_key = key
            if event.button() == Qt.LeftButton:
                widget.setProperty("_pdfnest_drag_key", key)
                widget.setProperty("_pdfnest_drag_start", self._mouse_event_pos(event))
            original_mouse_press(event)

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
                self._start_entry_drag(widget, key)
                return
            original_mouse_move(event)

        def handle_mouse_release(event) -> None:
            widget.setProperty("_pdfnest_drag_start", None)
            widget.setProperty("_pdfnest_drag_key", "")
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

    def _start_entry_drag(self, _source: QWidget, pdf_key: str) -> None:
        self._dragging_pdf_key = pdf_key
        if not self._drag_cursor_active:
            QApplication.setOverrideCursor(Qt.ClosedHandCursor)
            self._drag_cursor_active = True

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

    def _show_entry_context_menu(self, pdf_key: str, global_pos: QPoint) -> None:
        entry = self._entry_by_key.get(pdf_key)
        if entry is None:
            return
        menu = QMenu(self)
        open_action = menu.addAction("Open")
        rename_action = menu.addAction("Rename")
        export_action = menu.addAction("Export all notes")
        move_menu = menu.addMenu("Move to folder")
        move_actions: dict[QAction, str] = {}
        unfiled_action = move_menu.addAction("Unfiled")
        move_actions[unfiled_action] = UNFILED_FOLDER_ID
        for folder in self.library_state.folders:
            if folder.id == UNFILED_FOLDER_ID:
                continue
            action = move_menu.addAction(self._folder_path_label(folder.id))
            move_actions[action] = folder.id
        restore_action = menu.addAction("Restore") if pdf_key in self.library_state.archived else None
        archive_action = menu.addAction("Move to archive") if pdf_key not in self.library_state.archived else None
        delete_action = menu.addAction("Permanent delete")
        chosen = menu.exec(global_pos)
        if chosen == open_action:
            self.open_requested.emit(pdf_key)
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
        if folder_id == UNFILED_FOLDER_ID:
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
