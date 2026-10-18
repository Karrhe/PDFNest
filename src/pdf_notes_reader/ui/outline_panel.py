"""Left sidebar: PDF contents (outline) and bookmarks."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QMenu, QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from pdf_notes_reader.notes import Bookmark
from pdf_notes_reader.ui.resources import pic_icon


class OutlinePanel(QWidget):
    page_requested = Signal(int)
    bookmark_add_requested = Signal()
    bookmark_delete_requested = Signal(str)
    outline_new_requested = Signal()
    outline_new_child_requested = Signal()
    outline_delete_requested = Signal()
    outline_save_requested = Signal()
    outline_restore_requested = Signal()
    export_all_notes_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("OutlinePanel")
        self.setMinimumWidth(220)
        self.setMaximumWidth(360)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemPressed.connect(self._open_outline_item)
        self.tree.itemActivated.connect(self._open_outline_item)

        self.bookmark_tree = QTreeWidget()
        self.bookmark_tree.setHeaderHidden(True)
        self.bookmark_tree.itemPressed.connect(self._open_bookmark_item)
        self.bookmark_tree.itemActivated.connect(self._open_bookmark_item)

        menu_button = self._icon_button("more.png", "More contents actions", "OutlineMoreButton")
        menu_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(menu_button)
        export_action = QAction(pic_icon("markdown.png"), "Export all notes", self)
        expand_action = QAction("Expand all", self)
        collapse_action = QAction("Collapse all", self)
        export_action.triggered.connect(self.export_all_notes_requested.emit)
        expand_action.triggered.connect(self.tree.expandAll)
        collapse_action.triggered.connect(self.tree.collapseAll)
        menu.addAction(expand_action)
        menu.addAction(collapse_action)
        restore_action = QAction("Restore original PDF", self)
        restore_action.triggered.connect(self.outline_restore_requested.emit)
        menu.addSeparator()
        menu.addAction(export_action)
        menu.addAction(restore_action)
        menu_button.setMenu(menu)

        add_outline_button = self._icon_button("siblingnode.png", "New contents item", "OutlineNewButton")
        add_child_button = self._icon_button("subnode.png", "New subcontents item", "OutlineChildButton")
        delete_outline_button = self._icon_button("note-del.png", "Delete selected contents item", "OutlineDeleteButton")
        save_outline_button = self._icon_button("save.png", "Save contents to PDF", "OutlineSaveButton")
        add_bookmark_button = self._icon_button("bookmarks.png", "Add bookmark for current page", "BookmarkAddButton")
        delete_bookmark_button = self._icon_button("note-del.png", "Delete selected bookmark", "BookmarkDeleteButton")

        add_outline_button.clicked.connect(self.outline_new_requested.emit)
        add_child_button.clicked.connect(self.outline_new_child_requested.emit)
        delete_outline_button.clicked.connect(self.outline_delete_requested.emit)
        save_outline_button.clicked.connect(self.outline_save_requested.emit)
        add_bookmark_button.clicked.connect(self.bookmark_add_requested.emit)
        delete_bookmark_button.clicked.connect(self._emit_delete_bookmark)

        contents_tab = QWidget()
        contents_tab.setObjectName("ContentsTab")
        contents_controls = QHBoxLayout()
        contents_controls.setContentsMargins(0, 0, 0, 0)
        contents_controls.setSpacing(3)
        contents_controls.addWidget(menu_button)
        contents_controls.addWidget(add_outline_button)
        contents_controls.addWidget(add_child_button)
        contents_controls.addWidget(delete_outline_button)
        contents_controls.addWidget(save_outline_button)
        contents_controls.addStretch(1)
        contents_layout = QVBoxLayout(contents_tab)
        contents_layout.setContentsMargins(0, 0, 0, 0)
        contents_layout.setSpacing(6)
        contents_layout.addLayout(contents_controls)
        contents_layout.addWidget(self.tree, 1)

        bookmarks_tab = QWidget()
        bookmarks_tab.setObjectName("BookmarksTab")
        bookmark_controls = QHBoxLayout()
        bookmark_controls.setContentsMargins(0, 0, 0, 0)
        bookmark_controls.setSpacing(3)
        bookmark_controls.addWidget(add_bookmark_button)
        bookmark_controls.addWidget(delete_bookmark_button)
        bookmark_controls.addStretch(1)
        bookmarks_layout = QVBoxLayout(bookmarks_tab)
        bookmarks_layout.setContentsMargins(0, 0, 0, 0)
        bookmarks_layout.setSpacing(6)
        bookmarks_layout.addLayout(bookmark_controls)
        bookmarks_layout.addWidget(self.bookmark_tree, 1)

        tabs = QTabWidget()
        tabs.addTab(contents_tab, "Contents")
        tabs.addTab(bookmarks_tab, "Bookmarks")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(tabs, 1)

    @staticmethod
    def _icon_button(icon_name: str, tooltip: str, object_name: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName(object_name)
        button.setIcon(pic_icon(icon_name))
        button.setIconSize(QSize(22, 22))
        button.setToolTip(tooltip)
        button.setFixedSize(36, 36)
        button.setAutoRaise(True)
        return button

    def set_outline(self, toc: list[list]) -> None:
        self.tree.clear()
        if not toc:
            item = QTreeWidgetItem(["No contents"])
            item.setDisabled(True)
            self.tree.addTopLevelItem(item)
            return

        parents: dict[int, QTreeWidgetItem] = {}
        for raw in toc:
            if len(raw) < 3:
                continue
            level = max(1, int(raw[0]))
            title = str(raw[1])
            page_index = max(0, int(raw[2]) - 1)
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.UserRole, page_index)
            parent = parents.get(level - 1)
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            parents[level] = item
            for stale_level in [key for key in parents if key > level]:
                del parents[stale_level]
        self.tree.expandToDepth(1)

    def set_bookmarks(self, bookmarks: list[Bookmark]) -> None:
        self.bookmark_tree.clear()
        if not bookmarks:
            item = QTreeWidgetItem(["No bookmarks"])
            item.setDisabled(True)
            self.bookmark_tree.addTopLevelItem(item)
            return

        for bookmark in sorted(bookmarks, key=lambda item: (item.page_index, item.created_at)):
            item = QTreeWidgetItem([f"{bookmark.title}  (p. {bookmark.page_index + 1})"])
            item.setData(0, Qt.UserRole, bookmark.page_index)
            item.setData(0, Qt.UserRole + 1, bookmark.id)
            self.bookmark_tree.addTopLevelItem(item)

    def add_outline_item(self, *, title: str, page_index: int, as_child: bool = False) -> None:
        if self.tree.topLevelItemCount() == 1 and self.tree.topLevelItem(0).isDisabled():
            self.tree.clear()

        item = QTreeWidgetItem([title])
        item.setData(0, Qt.UserRole, max(0, int(page_index)))
        selected = self.tree.currentItem()
        if as_child and selected is not None and not selected.isDisabled():
            selected.addChild(item)
            selected.setExpanded(True)
            self.tree.setCurrentItem(item)
            return

        if selected is not None and not selected.isDisabled():
            parent = selected.parent()
            if parent is None:
                index = self.tree.indexOfTopLevelItem(selected) + 1
                self.tree.insertTopLevelItem(index, item)
            else:
                parent.insertChild(parent.indexOfChild(selected) + 1, item)
        else:
            self.tree.addTopLevelItem(item)
        self.tree.setCurrentItem(item)

    def delete_selected_outline_item(self) -> bool:
        item = self.tree.currentItem()
        if item is None or item.isDisabled():
            return False
        parent = item.parent()
        if parent is None:
            index = self.tree.indexOfTopLevelItem(item)
            self.tree.takeTopLevelItem(index)
        else:
            parent.takeChild(parent.indexOfChild(item))
        if self.tree.topLevelItemCount() == 0:
            self.set_outline([])
        return True

    def outline_toc(self) -> list[list]:
        toc: list[list] = []

        def collect(item: QTreeWidgetItem, level: int) -> None:
            if item.isDisabled():
                return
            page_index = item.data(0, Qt.UserRole)
            if page_index is not None:
                toc.append([level, item.text(0), int(page_index) + 1])
            for child_index in range(item.childCount()):
                collect(item.child(child_index), level + 1)

        for index in range(self.tree.topLevelItemCount()):
            collect(self.tree.topLevelItem(index), 1)
        return toc

    def selected_outline_page_index(self) -> int | None:
        item = self.tree.currentItem()
        if item is None or item.isDisabled():
            return None
        page_index = item.data(0, Qt.UserRole)
        return int(page_index) if page_index is not None else None

    def _open_outline_item(self, item: QTreeWidgetItem) -> None:
        page_index = item.data(0, Qt.UserRole)
        if page_index is not None:
            self.page_requested.emit(int(page_index))

    def _open_bookmark_item(self, item: QTreeWidgetItem) -> None:
        page_index = item.data(0, Qt.UserRole)
        if page_index is not None:
            self.page_requested.emit(int(page_index))

    def _emit_delete_bookmark(self) -> None:
        item = self.bookmark_tree.currentItem()
        if item is None or item.isDisabled():
            return
        bookmark_id = str(item.data(0, Qt.UserRole + 1) or "")
        if bookmark_id:
            self.bookmark_delete_requested.emit(bookmark_id)
