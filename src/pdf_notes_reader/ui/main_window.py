"""The main window: tabs, reader, notes, outline and library wiring."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz
from PySide6.QtCore import QEvent, QSize, Qt, QSignalBlocker, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QDoubleSpinBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pdf_notes_reader.history import find_history_entry, load_history, remove_history_entry, save_history, upsert_history_entry
from pdf_notes_reader.library import UNFILED_FOLDER_ID, load_library, save_library
from pdf_notes_reader.notes import (
    Bookmark,
    Note,
    app_local_data_dir,
    default_data_dir,
    drain_storage_issues,
    find_note,
    load_notes_data,
    notes_path_for_key,
    pdf_key_for_path,
    save_notes,
    utc_now,
)
from pdf_notes_reader.pdf.document import DEFAULT_PAGE_SIZE, MAX_PASSWORD_ATTEMPTS, PdfOpenError, open_pdf, page_base_sizes, reopen_pdf
from pdf_notes_reader.pdf.outline_writer import (
    TocSaveResult,
    TocValidationError,
    backup_path_for,
    normalize_toc,
    refusal_reason,
    restore_backup,
    save_toc_safely,
)
from pdf_notes_reader.settings import (
    clamp_marker_radius,
    clamp_window_dimension,
    clamp_wheel_scroll_lines,
    load_settings,
    load_theme_files,
    save_settings,
    themes_dir,
)
from pdf_notes_reader.storage_migration import migrate_storage
from pdf_notes_reader.ui.canvas import PdfCanvas
from pdf_notes_reader.ui.constants import APP_TITLE, EXCERPT_MARKER_COLOR, EXCERPT_MARKER_STYLES, SELECTION_COLOR_SETTINGS, SELECTION_SHORTCUTS
from pdf_notes_reader.ui.find_bar import FindBar
from pdf_notes_reader.ui.history_panel import HistoryPanel
from pdf_notes_reader.ui.note_panel import NotePanel
from pdf_notes_reader.ui.outline_panel import OutlinePanel
from pdf_notes_reader.ui.resources import PACKAGE_DIR, PROJECT_DIR
from pdf_notes_reader.ui.resources import app_resource_path, pic_icon
from pdf_notes_reader.ui.settings_dialog import SettingsDialog
from pdf_notes_reader.pdf.render import PageRenderCache
from pdf_notes_reader.pdf.search import DocumentSearch, SearchHit, SearchOptions
from pdf_notes_reader.pdf.text import page_words
from pdf_notes_reader.services.chapters import ChapterLookup, counter_key, location_label, single_line_title
from pdf_notes_reader.services.export import ExportError, export_note_markdown
from pdf_notes_reader.ui.styles import build_app_stylesheet


@dataclass
class PdfTabState:
    pdf_key: str
    pdf_path: Path
    document: fitz.Document
    notes: list[Note]
    note_counters: dict[str, int]
    bookmarks: list[Bookmark]
    page_index: int
    zoom: float
    fit_mode: str | None
    current_note_id: str = ""
    page_text_words_cache: dict[int, list[dict[str, object]]] | None = None
    reader_return_stack: list[tuple[int, int]] | None = None
    password: str | None = None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self._set_app_icon()
        self.resize(1180, 820)

        migrate_storage()
        self.settings = load_settings()
        self.resize(
            clamp_window_dimension(self.settings.get("window_width"), 1180),
            clamp_window_dimension(self.settings.get("window_height"), 820),
        )
        self.restore_window_maximized = bool(self.settings.get("window_maximized"))
        if self.restore_window_maximized:
            self.setWindowState(self.windowState() | Qt.WindowMaximized)
        self.themes = load_theme_files()
        self.theme_name = str(self.settings.get("theme") or "beige")
        if self.theme_name not in self.themes:
            self.theme_name = "beige"
            self.settings["theme"] = self.theme_name
        self.note_marker_radius = clamp_marker_radius(self.settings.get("note_marker_radius"))
        self.wheel_scroll_lines = clamp_wheel_scroll_lines(self.settings.get("wheel_scroll_lines"))
        self.auto_save_current_note = bool(self.settings.get("auto_save_current_note", True))
        self.document: fitz.Document | None = None
        self.document_password: str | None = None
        self.render_cache = PageRenderCache()
        self.pdf_path: Path | None = None
        self.pdf_key: str | None = None
        self.pdf_tabs: dict[str, PdfTabState] = {}
        self.active_pdf_key: str | None = None
        self._updating_pdf_tabs = False
        self._updating_document_title_combo = False
        self.notes: list[Note] = []
        self.note_counters: dict[str, int] = {}
        self.bookmarks: list[Bookmark] = []
        self.history_entries = load_history()
        self.page_index = 0
        self.zoom = 1.25
        self.fit_mode: str | None = None
        self.render_scale = 2.0
        self.render_page_buffer = 4
        self.page_margin = 24
        self.continuous_scroll = True
        self.note_export_dir = Path(str(self.settings.get("markdown_export_dir") or app_local_data_dir() / "markdown_notes")).expanduser()
        self.page_widgets: dict[int, QWidget] = {}
        self.page_base_sizes: list[tuple[float, float]] = []
        self.page_tops: list[int] = []
        self.page_heights: list[int] = []
        self.page_widths: list[int] = []
        self.page_text_words_cache: dict[int, list[dict[str, object]]] = {}
        self.chapter_lookup = ChapterLookup()
        self.export_errors: list[str] = []
        self.document_content_size = QSize(1, 1)
        self.reader_return_stack: list[tuple[int, int]] = []
        self._suppress_scroll_sync = False
        self._pending_scroll_id = 0
        self._fit_refresh_token = 0
        self._page_window_render_token = 0

        self.setFocusPolicy(Qt.StrongFocus)
        self.canvas = PdfCanvas()
        self.page_canvases: dict[int, PdfCanvas] = {}

        self.pages_container = QWidget()
        self.pages_container.setObjectName("PagesContainer")
        self.pages_layout = QVBoxLayout(self.pages_container)
        self.pages_layout.setContentsMargins(self.page_margin, self.page_margin, self.page_margin, self.page_margin)
        self.pages_layout.setSpacing(18)
        self.pages_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.pages_container)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setBackgroundRole(self.backgroundRole())
        self.scroll_area.viewport().setObjectName("ReaderViewport")
        self.scroll_area.viewport().setAutoFillBackground(True)
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._sync_current_page_from_scroll)

        self.note_panel = NotePanel()
        self.note_panel.jump_note_requested.connect(self.jump_to_current_note)
        self.note_panel.save_requested.connect(self.save_current_note)
        self.note_panel.export_requested.connect(self.export_current_note)
        self.note_panel.delete_requested.connect(self.delete_current_note)
        self.note_panel.note_selected_requested.connect(self.select_note)

        self.prev_page_button = QPushButton("-")
        self.prev_page_button.setObjectName("PageNavButton")
        self.prev_page_button.clicked.connect(self.previous_page)
        self.next_page_button = QPushButton("+")
        self.next_page_button.setObjectName("PageNavButton")
        self.next_page_button.clicked.connect(self.next_page)
        self.return_position_button = QToolButton()
        self.return_position_button.setObjectName("PageNavButton")
        self.return_position_button.setToolTip("Return to previous reading position")
        self.return_position_button.setIcon(pic_icon("redo-disabled.png"))
        self.return_position_button.setIconSize(QSize(16, 16))
        self.return_position_button.clicked.connect(self.return_to_previous_reading_position)
        self.page_spin = QLineEdit()
        self.page_spin.setObjectName("PageSpin")
        self.page_spin.setAlignment(Qt.AlignCenter)
        self.page_spin.setFixedWidth(86)
        self.page_spin.returnPressed.connect(self.commit_page_number_input)
        self.page_spin.editingFinished.connect(self.reset_page_number_input)
        self.page_spin.installEventFilter(self)
        self.page_count_label = QLabel("/ 0")
        self.page_count_label.setObjectName("BottomPageLabel")
        self.zoom_spin = QDoubleSpinBox()
        self.zoom_spin.setObjectName("ZoomSpin")
        self.zoom_spin.setRange(30.0, 400.0)
        self.zoom_spin.setDecimals(0)
        self.zoom_spin.setSuffix("%")
        self.zoom_spin.setSingleStep(10.0)
        self.zoom_spin.setValue(self.zoom * 100)
        self.zoom_spin.valueChanged.connect(self.set_zoom_percent)

        footer = QWidget()
        footer.setObjectName("PageFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 4, 0, 6)
        footer_layout.setSpacing(8)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.return_position_button)
        footer_layout.addWidget(self.prev_page_button)
        footer_layout.addWidget(self.page_spin)
        footer_layout.addWidget(self.page_count_label)
        footer_layout.addWidget(self.next_page_button)
        footer_layout.addSpacing(18)
        footer_layout.addWidget(QLabel("Zoom"))
        footer_layout.addWidget(self.zoom_spin)
        footer_layout.addStretch(1)

        self.reader_area = QWidget()
        self.reader_area.setObjectName("ReaderArea")
        reader_layout = QVBoxLayout(self.reader_area)
        reader_layout.setContentsMargins(0, 0, 0, 0)
        reader_layout.setSpacing(0)
        self.find_bar = FindBar()
        self.find_bar.search_requested.connect(self.start_search)
        self.find_bar.next_requested.connect(self.next_search_hit)
        self.find_bar.previous_requested.connect(self.previous_search_hit)
        self.find_bar.closed.connect(self.close_search)
        self.search: DocumentSearch | None = None
        self.search_hits: list[SearchHit] = []
        self.search_index = -1
        self._search_jumped = False
        self._search_timer = QTimer(self)
        self._search_timer.setInterval(0)
        self._search_timer.timeout.connect(self._search_tick)
        reader_layout.addWidget(self.find_bar, 0)
        reader_layout.addWidget(self.scroll_area, 1)
        reader_layout.addWidget(footer, 0)

        self.outline_panel = OutlinePanel()
        self.outline_panel.page_requested.connect(self.jump_to_page_from_navigation)
        self.outline_panel.bookmark_add_requested.connect(self.add_bookmark)
        self.outline_panel.bookmark_delete_requested.connect(self.delete_bookmark)
        self.outline_panel.outline_new_requested.connect(self.add_outline_item)
        self.outline_panel.outline_new_child_requested.connect(self.add_outline_child_item)
        self.outline_panel.outline_delete_requested.connect(self.delete_outline_item)
        self.outline_panel.outline_save_requested.connect(self.save_outline_to_pdf)
        self.outline_panel.outline_restore_requested.connect(self.restore_pdf_backup)
        self.outline_panel.export_all_notes_requested.connect(self.export_all_notes)

        self.reader_splitter = QSplitter(Qt.Horizontal)
        self.reader_splitter.addWidget(self.outline_panel)
        self.reader_splitter.addWidget(self.reader_area)
        self.reader_splitter.addWidget(self.note_panel)
        self.reader_splitter.setStretchFactor(0, 0)
        self.reader_splitter.setStretchFactor(1, 1)
        self.reader_splitter.setStretchFactor(2, 0)
        self.reader_splitter.setSizes([220, 820, 320])
        self.reader_splitter.splitterMoved.connect(self._handle_reader_splitter_moved)

        self.history_panel = HistoryPanel()
        self.history_panel.open_requested.connect(self.open_history_entry)
        self.history_panel.archive_requested.connect(self.archive_history_entry)
        self.history_panel.remove_requested.connect(self.remove_history_entry)
        self.history_panel.export_requested.connect(self.export_history_entry_notes)
        self.history_panel.add_notebook_requested.connect(self.add_planned_notebook)
        self.history_panel.rename_requested.connect(self.rename_history_entry)
        self.history_panel.restore_requested.connect(self.restore_history_entry)
        self.history_panel.settings_requested.connect(self.open_settings)
        self.history_panel.set_entries(self.history_entries)

        self.main_stack = QStackedWidget()
        self.main_stack.addWidget(self.history_panel)
        self.main_stack.addWidget(self.reader_splitter)
        self.document_tab_bar = QTabBar()
        self.document_tab_bar.setObjectName("DocumentTabBar")
        self.document_tab_bar.setDocumentMode(True)
        self.document_tab_bar.setExpanding(False)
        self.document_tab_bar.setMovable(True)
        self.document_tab_bar.setTabsClosable(False)
        self.document_tab_bar.addTab("Home")
        self.document_tab_bar.setTabData(0, "")
        self.document_tab_bar.currentChanged.connect(self._handle_document_tab_changed)

        self.open_tab_button = QPushButton("+ Open")
        self.open_tab_button.setObjectName("OpenTabButton")
        self.open_tab_button.clicked.connect(self.open_pdf)

        tab_strip = QWidget()
        tab_strip.setObjectName("DocumentTabStrip")
        tab_strip_layout = QHBoxLayout(tab_strip)
        tab_strip_layout.setContentsMargins(0, 0, 0, 0)
        tab_strip_layout.setSpacing(0)
        tab_strip_layout.addWidget(self.document_tab_bar, 1)
        tab_strip_layout.addWidget(self.open_tab_button, 0)

        self.outline_toggle_button = QToolButton()
        self.outline_toggle_button.setObjectName("OutlineToggleButton")
        self.outline_toggle_button.setText("Contents")
        self.outline_toggle_button.setCheckable(True)
        self.outline_toggle_button.setChecked(True)
        self.outline_toggle_button.clicked.connect(self.set_outline_visible)

        self.document_title_combo = QComboBox()
        self.document_title_combo.setObjectName("DocumentTitleCombo")
        self.document_title_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document_title_combo.activated.connect(self.switch_to_document_title_index)

        title_bar = QWidget()
        title_bar.setObjectName("DocumentTitleBar")
        self.document_title_bar = title_bar
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(4, 2, 8, 2)
        title_bar_layout.setSpacing(8)
        title_bar_layout.addWidget(self.outline_toggle_button, 0)
        title_bar_layout.addWidget(self.document_title_combo, 1)

        window_content = QWidget()
        window_content.setObjectName("WindowContent")
        window_layout = QVBoxLayout(window_content)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.setSpacing(0)
        window_layout.addWidget(tab_strip, 0)
        window_layout.addWidget(title_bar, 0)
        window_layout.addWidget(self.main_stack, 1)
        self.setCentralWidget(window_content)
        self.statusBar().setSizeGripEnabled(False)

        self._build_toolbar()
        self._build_shortcuts()
        self._render_empty_state()
        self._apply_wheel_scroll_lines()
        self.apply_theme()
        self.restore_last_session()
        self._refresh_actions()
        self.report_storage_issues()

    def _ask_pdf_password(self, path: Path, attempt: int, previous_failed: bool) -> str | None:
        prompt = f"{path.name} is password protected.\nPassword:"
        if previous_failed:
            prompt = f"The password was not correct (attempt {attempt} of {MAX_PASSWORD_ATTEMPTS}).\n{prompt}"
        password, accepted = QInputDialog.getText(self, "Password required", prompt, QLineEdit.Password)
        return password if accepted else None

    def report_storage_issues(self) -> None:
        """Tells the user about unreadable data files that were set aside instead of overwritten."""
        issues = drain_storage_issues()
        if not issues:
            return
        lines = []
        for issue in issues:
            line = f"- {issue.message}\n  {issue.path}"
            if issue.quarantined_path is not None:
                line += f"\n  Saved copy: {issue.quarantined_path}"
            lines.append(line)
        self.statusBar().showMessage(f"{len(issues)} PDFNest data file(s) could not be read. See the warning for details.", 8000)
        box = QMessageBox(QMessageBox.Warning, "PDFNest data problem", "Some PDFNest data files could not be read.", QMessageBox.Ok, self)
        box.setInformativeText("The unreadable files were kept so nothing is lost. PDFNest continues with what it could read.")
        box.setDetailedText("\n".join(lines))
        box.setModal(False)
        box.show()
        self.last_storage_issue_box = box

    def _build_toolbar(self) -> None:
        self.home_action = QAction("Home", self)
        self.home_action.triggered.connect(self.show_home)

        self.open_action = QAction("Open", self)
        self.open_action.triggered.connect(self.open_pdf)

        self.reader_action = QAction("Reader", self)
        self.reader_action.triggered.connect(self.show_reader)

        self.outline_action = QAction("Contents", self)
        self.outline_action.setCheckable(True)
        self.outline_action.setChecked(True)
        self.outline_action.triggered.connect(self.set_outline_visible)

    def _build_shortcuts(self) -> None:
        self.save_note_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_note_shortcut.setContext(Qt.ApplicationShortcut)
        self.save_note_shortcut.activated.connect(self.save_current_note_from_panel)

        self.export_note_shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        self.export_note_shortcut.setContext(Qt.ApplicationShortcut)
        self.export_note_shortcut.activated.connect(self.export_current_note_from_panel)

        self.append_selection_shortcut = QShortcut(self._append_selection_key_sequence(), self)
        self.append_selection_shortcut.setContext(Qt.ApplicationShortcut)
        self.append_selection_shortcut.activated.connect(self.append_selected_text_to_current_note_from_shortcut)

        self.selection_action_shortcuts: dict[str, QShortcut] = {}
        shortcut_handlers = {
            "highlight_selection_shortcut": lambda: self.annotate_selected_text_from_shortcut("highlight"),
            "underline_selection_shortcut": lambda: self.annotate_selected_text_from_shortcut("underline"),
            "append_highlight_selection_shortcut": lambda: self.append_selected_text_with_style_from_shortcut("highlight"),
            "append_underline_selection_shortcut": lambda: self.append_selected_text_with_style_from_shortcut("underline"),
        }
        for setting_key, handler in shortcut_handlers.items():
            shortcut = QShortcut(self._selection_key_sequence(setting_key), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(handler)
            self.selection_action_shortcuts[setting_key] = shortcut

        self.close_tab_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        self.close_tab_shortcut.setContext(Qt.ApplicationShortcut)
        self.close_tab_shortcut.activated.connect(self.close_current_pdf_tab)

        self.find_shortcuts = []
        for sequence, handler in (
            (QKeySequence.Find, self.open_find_bar),
            (QKeySequence("F3"), self.next_search_hit),
            (QKeySequence("Shift+F3"), self.previous_search_hit),
        ):
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(handler)
            self.find_shortcuts.append(shortcut)

        self.tab_switch_shortcuts: list[QShortcut] = []
        for tab_number in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{tab_number}"), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(lambda pdf_index=tab_number: self.switch_to_document_tab(pdf_index))
            self.tab_switch_shortcuts.append(shortcut)

    def _append_selection_key_sequence(self) -> QKeySequence:
        shortcut_text = str(self.settings.get("append_selection_shortcut") or "Ctrl+Shift+C")
        sequence = QKeySequence(shortcut_text)
        if sequence.isEmpty():
            sequence = QKeySequence("Ctrl+Shift+C")
        return sequence

    def _selection_key_sequence(self, setting_key: str) -> QKeySequence:
        default_shortcut = SELECTION_SHORTCUTS[setting_key][1]
        sequence = QKeySequence(str(self.settings.get(setting_key) or default_shortcut))
        return sequence if not sequence.isEmpty() else QKeySequence(default_shortcut)

    def _refresh_append_selection_shortcut(self) -> None:
        self.append_selection_shortcut.setKey(self._append_selection_key_sequence())
        for setting_key, shortcut in self.selection_action_shortcuts.items():
            shortcut.setKey(self._selection_key_sequence(setting_key))

    def _apply_wheel_scroll_lines(self) -> None:
        lines = clamp_wheel_scroll_lines(self.wheel_scroll_lines)
        self.wheel_scroll_lines = lines
        app = QApplication.instance()
        if app is not None:
            app.setWheelScrollLines(lines)

    def _save_runtime_settings(self) -> None:
        normal_geometry = self.normalGeometry()
        width = normal_geometry.width() if self.isMaximized() and normal_geometry.isValid() else self.width()
        height = normal_geometry.height() if self.isMaximized() and normal_geometry.isValid() else self.height()
        self.settings["window_width"] = clamp_window_dimension(width, 1180)
        self.settings["window_height"] = clamp_window_dimension(height, 820)
        self.settings["window_maximized"] = self.isMaximized()
        self.settings["theme"] = self.theme_name
        self.settings["note_marker_radius"] = self.note_marker_radius
        self.settings["wheel_scroll_lines"] = self.wheel_scroll_lines
        self.settings["auto_save_current_note"] = self.auto_save_current_note
        save_settings(self.settings)

    def _set_app_icon(self) -> None:
        frozen_base = Path(getattr(sys, "_MEIPASS", PACKAGE_DIR))
        candidates = [
            frozen_base / "pdf_notes_reader" / "assets" / "Icon.png",
            PACKAGE_DIR / "assets" / "Icon.png",
            Path.cwd() / "Icon.png",
            PROJECT_DIR / "Icon.png",
            Path(sys.executable).resolve().parent / "Icon.png",
            Path.cwd() / "PDFNest-Icon.png",
            PROJECT_DIR / "PDFNest-Icon.png",
        ]
        for icon_path in candidates:
            if icon_path.exists():
                icon = QIcon(str(icon_path))
                self.setWindowIcon(icon)
                app = QApplication.instance()
                if app is not None:
                    app.setWindowIcon(icon)
                return

    def _tab_title_for_path(self, path: Path) -> str:
        title = path.stem or path.name or "Untitled"
        return title if len(title) <= 28 else f"{title[:25]}..."

    def _pdf_tab_index(self, pdf_key: str) -> int:
        for index in range(1, self.document_tab_bar.count()):
            if self.document_tab_bar.tabData(index) == pdf_key:
                return index
        return -1

    def _set_current_document_tab(self, index: int) -> None:
        self._updating_pdf_tabs = True
        try:
            if 0 <= index < self.document_tab_bar.count():
                self.document_tab_bar.setCurrentIndex(index)
        finally:
            self._updating_pdf_tabs = False

    def _add_pdf_tab(self, state: PdfTabState) -> None:
        index = self.document_tab_bar.addTab(self._tab_title_for_path(state.pdf_path))
        self.document_tab_bar.setTabData(index, state.pdf_key)
        self.document_tab_bar.setTabToolTip(index, str(state.pdf_path))
        close_button = QToolButton()
        close_button.setObjectName("DocumentTabCloseButton")
        close_button.setIcon(pic_icon("closebtn.png"))
        close_button.setIconSize(QSize(9, 9))
        close_button.setToolTip("Close tab")
        close_button.setAutoRaise(True)
        close_button.setFixedSize(18, 18)
        close_button.clicked.connect(lambda _checked=False, key=state.pdf_key: self.close_pdf_tab_by_key(key))
        self.document_tab_bar.setTabButton(index, QTabBar.RightSide, close_button)

    def _save_active_pdf_tab_state(self) -> None:
        if self.active_pdf_key is None or self.document is None:
            return
        state = self.pdf_tabs.get(self.active_pdf_key)
        if state is None:
            return

        self._auto_save_current_note()
        self._record_current_pdf()
        state.pdf_path = self.pdf_path or state.pdf_path
        state.document = self.document
        state.notes = self.notes
        state.note_counters = self.note_counters
        state.bookmarks = self.bookmarks
        state.page_text_words_cache = self.page_text_words_cache
        state.page_index = self.page_index
        state.zoom = self.zoom
        state.fit_mode = self.fit_mode
        state.current_note_id = self.note_panel.current_note_id or ""
        state.reader_return_stack = list(self.reader_return_stack)

    def _activate_pdf_tab(self, pdf_key: str) -> None:
        state = self.pdf_tabs.get(pdf_key)
        if state is None:
            self.show_home()
            return

        if self.active_pdf_key == pdf_key and self.document is state.document and self.page_canvases:
            self.main_stack.setCurrentWidget(self.reader_splitter)
            self._set_current_document_tab(self._pdf_tab_index(pdf_key))
            self._refresh_document_chrome()
            self._refresh_actions()
            return

        if self.active_pdf_key != pdf_key:
            self._save_active_pdf_tab_state()

        self.active_pdf_key = pdf_key
        self.document = state.document
        self.document_password = state.password
        self._cancel_search(clear=True)
        QTimer.singleShot(0, self._restart_search_for_document_change)
        self.pdf_path = state.pdf_path
        self.pdf_key = state.pdf_key
        self.notes = state.notes
        self.note_counters = state.note_counters
        self.bookmarks = state.bookmarks
        self.page_text_words_cache = state.page_text_words_cache or {}
        self.reader_return_stack = list(state.reader_return_stack or [])
        self.page_index = max(0, min(state.page_index, max(self.document.page_count - 1, 0)))
        self.zoom = state.zoom
        self.fit_mode = state.fit_mode
        self._cache_page_base_sizes()
        self.note_panel.set_note(None)
        restored_note = find_note(self.notes, state.current_note_id) if state.current_note_id else None
        if restored_note is not None:
            self.note_panel.set_note(restored_note)
            self._refresh_note_selector(restored_note.id)
        else:
            self._refresh_note_selector()
        self.outline_panel.set_outline(self.document.get_toc())
        self.outline_panel.set_bookmarks(self.bookmarks)
        self.main_stack.setCurrentWidget(self.reader_splitter)
        tab_index = self._pdf_tab_index(pdf_key)
        self._set_current_document_tab(tab_index)
        if self.fit_mode is None:
            self.render_page()
        else:
            self._apply_fit_mode(anchor_page=self.page_index, force=True)
            self._schedule_fit_refresh(anchor_page=self.page_index)
        self._refresh_document_chrome()
        self._refresh_actions()

    def switch_to_document_tab(self, index: int) -> None:
        if index == 0:
            self.show_home()
            return
        if not (0 <= index < self.document_tab_bar.count()):
            return
        pdf_key = str(self.document_tab_bar.tabData(index) or "")
        if pdf_key:
            self._activate_pdf_tab(pdf_key)

    def switch_to_document_title_index(self, index: int) -> None:
        if self._updating_document_title_combo:
            return
        pdf_key = str(self.document_title_combo.itemData(index) or "")
        if pdf_key:
            self._activate_pdf_tab(pdf_key)

    def _handle_document_tab_changed(self, index: int) -> None:
        if self._updating_pdf_tabs:
            return
        self.switch_to_document_tab(index)

    def close_current_pdf_tab(self) -> None:
        index = self.document_tab_bar.currentIndex()
        if index <= 0:
            return
        self.close_pdf_tab_at_index(index)

    def close_pdf_tab_by_key(self, pdf_key: str) -> None:
        index = self._pdf_tab_index(pdf_key)
        if index > 0:
            self.close_pdf_tab_at_index(index)

    def close_pdf_tab_at_index(self, index: int) -> None:
        if index <= 0 or index >= self.document_tab_bar.count():
            return
        pdf_key = str(self.document_tab_bar.tabData(index) or "")
        state = self.pdf_tabs.get(pdf_key)
        if state is None:
            return

        closing_active = pdf_key == self.active_pdf_key
        if closing_active:
            self._save_active_pdf_tab_state()

        state.document.close()
        self.pdf_tabs.pop(pdf_key, None)
        self._updating_pdf_tabs = True
        try:
            self.document_tab_bar.removeTab(index)
        finally:
            self._updating_pdf_tabs = False

        if not closing_active:
            return

        next_index = min(index, self.document_tab_bar.count() - 1)
        if next_index > 0:
            next_key = str(self.document_tab_bar.tabData(next_index) or "")
            if next_key:
                self._activate_pdf_tab(next_key)
                return

        self._clear_current_pdf_state()
        self.show_home()

    def _clear_current_pdf_state(self) -> None:
        self.active_pdf_key = None
        self.document = None
        self.pdf_path = None
        self.pdf_key = None
        self.notes = []
        self.note_counters = {}
        self.bookmarks = []
        self.page_index = 0
        self.zoom = 1.25
        self.fit_mode = None
        self.page_base_sizes = []
        self.page_tops = []
        self.page_heights = []
        self.page_widths = []
        self.page_text_words_cache = {}
        self.reader_return_stack = []
        self.document_content_size = QSize(1, 1)
        self.note_panel.set_note(None)
        self._refresh_note_selector()
        self.outline_panel.set_outline([])
        self.outline_panel.set_bookmarks([])
        self._render_empty_state()
        self._refresh_actions()
        self._refresh_document_chrome()

    def _close_all_pdf_tabs(self) -> None:
        self._save_active_pdf_tab_state()
        for state in list(self.pdf_tabs.values()):
            state.document.close()
        self.pdf_tabs.clear()
        self._updating_pdf_tabs = True
        try:
            while self.document_tab_bar.count() > 1:
                self.document_tab_bar.removeTab(1)
            self.document_tab_bar.setCurrentIndex(0)
        finally:
            self._updating_pdf_tabs = False
        self._clear_current_pdf_state()

    def _refresh_document_chrome(self) -> None:
        has_document = self.document is not None and self.pdf_path is not None
        self._refresh_document_title_combo()
        if self.main_stack.currentWidget() is self.history_panel:
            self.document_title_bar.setVisible(False)
            self.outline_toggle_button.setEnabled(False)
            self._set_current_document_tab(0)
            return

        self.document_title_bar.setVisible(True)
        self.outline_toggle_button.setEnabled(has_document)
        self.outline_toggle_button.setChecked(self.outline_panel.isVisible())
        if self.active_pdf_key is not None:
            index = self._pdf_tab_index(self.active_pdf_key)
            self._set_current_document_tab(index)

    def _refresh_document_title_combo(self) -> None:
        self._updating_document_title_combo = True
        try:
            self.document_title_combo.clear()
            current_index = -1
            for tab_index in range(1, self.document_tab_bar.count()):
                pdf_key = str(self.document_tab_bar.tabData(tab_index) or "")
                state = self.pdf_tabs.get(pdf_key)
                if state is None:
                    continue
                combo_index = self.document_title_combo.count()
                self.document_title_combo.addItem(state.pdf_path.name, pdf_key)
                self.document_title_combo.setItemData(combo_index, str(state.pdf_path), Qt.ToolTipRole)
                if pdf_key == self.active_pdf_key:
                    current_index = combo_index
            if self.document_title_combo.count() == 0:
                self.document_title_combo.addItem(APP_TITLE, "")
                self.document_title_combo.setEnabled(False)
            else:
                self.document_title_combo.setEnabled(True)
                if current_index >= 0:
                    self.document_title_combo.setCurrentIndex(current_index)
        finally:
            self._updating_document_title_combo = False

    def open_settings(self) -> None:
        old_data_dir = default_data_dir()
        self.themes = load_theme_files()
        if self.theme_name not in self.themes:
            self.theme_name = "beige"
            self.settings["theme"] = self.theme_name
        note_json_path = notes_path_for_key(self.pdf_key) if self.pdf_key is not None else None
        dialog = SettingsDialog(
            settings=self.settings,
            themes=self.themes,
            data_dir=default_data_dir(),
            note_json_path=note_json_path,
            markdown_dir=self.note_export_dir,
            theme_dir=themes_dir(default_data_dir()),
            parent=self,
        )
        dialog.setStyleSheet(self.styleSheet())
        if dialog.exec() != QDialog.Accepted:
            return

        self.theme_name = dialog.selected_theme
        self.settings["theme"] = self.theme_name
        self.note_marker_radius = dialog.marker_radius
        self.settings["note_marker_radius"] = self.note_marker_radius
        self.wheel_scroll_lines = dialog.wheel_scroll_lines
        self.settings["wheel_scroll_lines"] = self.wheel_scroll_lines
        self.auto_save_current_note = dialog.auto_save_current_note
        self.settings["auto_save_current_note"] = self.auto_save_current_note
        self.settings["append_selection_shortcut"] = dialog.append_selection_shortcut
        self.settings.update(dialog.selection_shortcuts)
        self.settings.update(dialog.selection_colors)
        self.settings["storage_dir"] = str(dialog.storage_dir)
        self.note_export_dir = dialog.markdown_dir
        self.settings["markdown_export_dir"] = str(self.note_export_dir)
        save_settings(self.settings)
        migrate_storage(dialog.storage_dir)
        self._refresh_append_selection_shortcut()
        self._apply_wheel_scroll_lines()
        if dialog.storage_dir != old_data_dir:
            self.history_entries = load_history()
            self.history_panel.set_entries(self.history_entries)
        self.themes = load_theme_files()
        self.apply_theme()
        self._refresh_canvas_appearance()

    def open_pdf(self) -> None:
        filename = self._choose_pdf_file("Open PDF")
        if not filename:
            return
        QApplication.processEvents()
        self.load_pdf(Path(filename))
        self.repaint()

    def _choose_pdf_file(self, title: str) -> str:
        self.repaint()
        QApplication.processEvents()
        dialog = QFileDialog(self, title, "", "PDF files (*.pdf)")
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("PDF files (*.pdf)")
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setWindowModality(Qt.ApplicationModal)
        if dialog.exec() != QDialog.Accepted:
            QApplication.processEvents()
            self.repaint()
            return ""
        selected = dialog.selectedFiles()
        QApplication.processEvents()
        self.repaint()
        return selected[0] if selected else ""

    def load_pdf(self, path: Path, *, pdf_key: str | None = None, restore_last_page: bool = True) -> None:
        key = pdf_key or pdf_key_for_path(path)
        if key in self.pdf_tabs:
            self._activate_pdf_tab(key)
            return

        try:
            opened = open_pdf(path, password_provider=self._ask_pdf_password)
        except PdfOpenError as exc:
            QMessageBox.critical(self, "Open failed", f"Could not open PDF:\n{path}\n\n{exc}")
            return
        document = opened.document

        self._save_active_pdf_tab_state()
        entry = find_history_entry(self.history_entries, key)
        self.document = document
        self.document_password = opened.password
        self._cancel_search(clear=True)
        QTimer.singleShot(0, self._restart_search_for_document_change)
        self.pdf_path = path
        self.pdf_key = key
        self.active_pdf_key = key
        self.notes, self.note_counters, self.bookmarks = load_notes_data(self.pdf_key)
        self.page_text_words_cache = {}
        self.reader_return_stack = []
        self.report_storage_issues()
        self._ensure_note_counters()
        self._cache_page_base_sizes()
        if restore_last_page and entry is not None:
            self.page_index = min(entry.last_page_index, max(document.page_count - 1, 0))
            self.zoom = entry.zoom
            self.fit_mode = entry.fit_mode or None
        else:
            self.page_index = 0
            self.zoom = 1.25
            self.fit_mode = None
        self.note_panel.set_note(None)
        self._refresh_note_selector()
        self.outline_panel.set_outline(document.get_toc())
        self.outline_panel.set_bookmarks(self.bookmarks)
        restored_note = find_note(self.notes, entry.last_note_id) if restore_last_page and entry is not None else None
        state = PdfTabState(
            pdf_key=key,
            pdf_path=path,
            document=document,
            notes=self.notes,
            note_counters=self.note_counters,
            bookmarks=self.bookmarks,
            page_index=self.page_index,
            zoom=self.zoom,
            fit_mode=self.fit_mode,
            current_note_id=restored_note.id if restored_note is not None else "",
            page_text_words_cache=self.page_text_words_cache,
            reader_return_stack=self.reader_return_stack,
            password=opened.password,
        )
        self.pdf_tabs[key] = state
        self._add_pdf_tab(state)
        self.main_stack.setCurrentWidget(self.reader_splitter)
        self._set_current_document_tab(self._pdf_tab_index(key))
        if self.fit_mode is None:
            self.render_page()
        else:
            self._apply_fit_mode(anchor_page=self.page_index, force=True)
            self._schedule_fit_refresh(anchor_page=self.page_index)
        if restored_note is not None:
            self.note_panel.set_note(restored_note)
            self._refresh_note_selector(restored_note.id)
        self._record_current_pdf()
        self._refresh_document_chrome()
        if opened.warnings:
            self.statusBar().showMessage(" ".join(opened.warnings), 10000)

    def close_document(self) -> None:
        self._save_active_pdf_tab_state()
        key = self.active_pdf_key
        state = self.pdf_tabs.pop(key, None) if key is not None else None
        if state is not None:
            state.document.close()
            index = self._pdf_tab_index(state.pdf_key)
            if index > 0:
                self._updating_pdf_tabs = True
                try:
                    self.document_tab_bar.removeTab(index)
                finally:
                    self._updating_pdf_tabs = False
        elif self.document is not None:
            self._auto_save_current_note()
            self._record_current_pdf()
            self.document.close()
        self._clear_current_pdf_state()

    def _record_current_pdf(self) -> None:
        if self.document is None or self.pdf_path is None or self.pdf_key is None:
            return
        current_note_id = self.note_panel.current_note_id
        if current_note_id is not None and find_note(self.notes, current_note_id) is None:
            current_note_id = None
        upsert_history_entry(
            self.history_entries,
            pdf_key=self.pdf_key,
            path=self.pdf_path,
            page_count=self.document.page_count,
            last_page_index=self.page_index,
            last_note_id=current_note_id or "",
            zoom=self.zoom,
            fit_mode=self.fit_mode or "",
        )
        save_history(self.history_entries, touched_pdf_keys={self.pdf_key})

    def open_history_entry(self, pdf_key: str) -> None:
        entry = find_history_entry(self.history_entries, pdf_key)
        if entry is None:
            self.history_panel.set_entries(self.history_entries)
            return

        path = Path(entry.path)
        if path.exists():
            self.load_pdf(path, pdf_key=entry.pdf_key, restore_last_page=True)
            return

        answer = QMessageBox.question(
            self,
            "PDF file not found",
            "This PDF path no longer exists. Relocate it?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        filename = self._choose_pdf_file("Relocate PDF")
        if filename:
            self.load_pdf(Path(filename), pdf_key=entry.pdf_key, restore_last_page=True)

    def remove_history_entry(self, pdf_key: str) -> None:
        self.history_entries = remove_history_entry(self.history_entries, pdf_key)
        save_history(self.history_entries)
        library = load_library()
        library.assignments.pop(pdf_key, None)
        library.aliases.pop(pdf_key, None)
        library.archived.pop(pdf_key, None)
        save_library(library)
        self.history_panel.set_entries(self.history_entries)

    def archive_history_entry(self, pdf_key: str) -> None:
        if not find_history_entry(self.history_entries, pdf_key):
            return
        library = load_library()
        library.archived[pdf_key] = utc_now()
        save_library(library)
        self.history_panel.set_entries(self.history_entries)
        self.statusBar().showMessage("Moved to archive.", 3000)

    def restore_history_entry(self, pdf_key: str) -> None:
        library = load_library()
        library.archived.pop(pdf_key, None)
        save_library(library)
        self.history_panel.set_entries(self.history_entries)
        self.statusBar().showMessage("Restored from archive.", 3000)

    def rename_history_entry(self, pdf_key: str, name: str) -> None:
        library = load_library()
        if name.strip():
            library.aliases[pdf_key] = name.strip()
        else:
            library.aliases.pop(pdf_key, None)
        save_library(library)
        self.history_panel.set_entries(self.history_entries)

    def add_planned_notebook(self, folder_id: str = "") -> None:
        filename = self._choose_pdf_file("Add planned PDF")
        if not filename:
            return
        path = Path(filename)
        pdf_key = pdf_key_for_path(path)
        page_count = 0
        try:
            document = fitz.open(path)
        except Exception:
            document = None
        if document is not None:
            try:
                page_count = document.page_count
            finally:
                document.close()

        upsert_history_entry(
            self.history_entries,
            pdf_key=pdf_key,
            path=path,
            page_count=page_count,
            last_page_index=0,
            zoom=1.25,
            fit_mode="",
        )
        save_history(self.history_entries, touched_pdf_keys={pdf_key})
        if folder_id and folder_id != UNFILED_FOLDER_ID:
            library = load_library()
            folder_ids = {folder.id for folder in library.folders}
            if folder_id in folder_ids:
                library.assignments[pdf_key] = folder_id
                save_library(library)
        self.history_panel.set_entries(self.history_entries)

    def export_history_entry_notes(self, pdf_key: str) -> None:
        if self.pdf_key == pdf_key:
            self.export_all_notes()
            return

        entry = find_history_entry(self.history_entries, pdf_key)
        if entry is None:
            return
        notes, counters, bookmarks = load_notes_data(pdf_key)
        exportable_notes = [note for note in notes if note.note_type != "excerpt"]
        if not exportable_notes:
            self.statusBar().showMessage("No notes to export.", 3000)
            return

        document = None
        path = Path(entry.path)
        if path.exists():
            try:
                document = fitz.open(path)
            except Exception:
                document = None
            if document is not None and document.needs_pass:
                document.close()  # Locked: export falls back to page-number file names.
                document = None

        exported = 0
        try:
            for note in sorted(exportable_notes, key=lambda item: (item.page_index, item.note_number, item.created_at)):
                exported_path = self.export_markdown_note_for_pdf(
                    pdf_path=path,
                    note=note,
                    document=document,
                    replace_existing=bool(note.exported_markdown_path),
                )
                if exported_path is not None:
                    exported += 1
        finally:
            if document is not None:
                document.close()
        save_notes(
            pdf_key=pdf_key,
            pdf_path=path,
            notes=notes,
            note_counters=counters,
            bookmarks=bookmarks,
        )
        self.statusBar().showMessage(f"Exported {exported} Markdown notes.", 5000)
        self._report_export_errors()

    def show_home(self) -> None:
        self._save_active_pdf_tab_state()
        self.history_panel.set_entries(self.history_entries)
        self.main_stack.setCurrentWidget(self.history_panel)
        self._refresh_document_chrome()
        self._refresh_actions()

    def show_reader(self) -> None:
        if self.document is not None:
            self.main_stack.setCurrentWidget(self.reader_splitter)
        self._refresh_document_chrome()
        self._refresh_actions()

    def set_outline_visible(self, visible: bool) -> None:
        anchor_page = self.page_index
        with QSignalBlocker(self.outline_action):
            self.outline_action.setChecked(visible)
        with QSignalBlocker(self.outline_toggle_button):
            self.outline_toggle_button.setChecked(visible)

        was_suppressed = self._suppress_scroll_sync
        self._suppress_scroll_sync = True
        try:
            self.outline_panel.setVisible(visible)
            self.reader_splitter.updateGeometry()
            self.reader_area.updateGeometry()
            if self.reader_area.layout() is not None:
                self.reader_area.layout().activate()
        finally:
            self._suppress_scroll_sync = was_suppressed

        self.page_index = anchor_page
        self._schedule_fit_refresh(anchor_page=anchor_page)

    def restore_last_session(self) -> bool:
        for entry in self.history_entries:
            path = Path(entry.path)
            if path.exists():
                self.load_pdf(path, pdf_key=entry.pdf_key, restore_last_page=True)
                return True
        self.show_home()
        return False

    def render_page(self, *, center_current: bool = True, render_neighbors: bool = True) -> None:
        if self.document is None:
            self._render_empty_state()
            self._refresh_actions()
            return

        self._update_page_layout_margins()
        was_suppressed = self._suppress_scroll_sync
        self._suppress_scroll_sync = True
        try:
            self._clear_page_widgets()
            self._recalculate_page_metrics()
            rendered_pages = set(self._page_indexes_to_render(render_neighbors=render_neighbors))
            if self.continuous_scroll:
                self._populate_continuous_pages(rendered_pages)
            else:
                self._add_rendered_page(self.page_index)

            self._lock_pages_container_to_layout()
            self.canvas = self.page_canvases.get(self.page_index) or next(iter(self.page_canvases.values()))
            self._refresh_actions()
        finally:
            self._suppress_scroll_sync = was_suppressed
        if self.continuous_scroll and center_current:
            self._scroll_to_page(self.page_index, center=True)

    def render_page_preserving_view(self, *, render_neighbors: bool = True) -> None:
        if self.document is None or not self.continuous_scroll:
            self.render_page(render_neighbors=render_neighbors)
            return

        view = self._current_view_snapshot()
        self.render_page(center_current=False, render_neighbors=render_neighbors)
        self._restore_view_snapshot(view)

    def _current_view_snapshot(self) -> tuple[int, int] | None:
        if self.document is None:
            return None
        scroll_value = self.scroll_area.verticalScrollBar().value()
        page_index = self.page_index
        if not self.continuous_scroll:
            return page_index, scroll_value
        if not self._has_page_geometry(page_index):
            return page_index, scroll_value
        return page_index, scroll_value - self.page_tops[page_index]

    def _restore_view_snapshot(self, snapshot: tuple[int, int] | None) -> None:
        if snapshot is None:
            return
        page_index, page_offset = snapshot
        self._restore_reader_position(page_index, page_offset, rerender=False)
        for delay in (0, 50, 150):
            QTimer.singleShot(delay, lambda page=page_index, offset=page_offset: self._restore_reader_position(page, offset, rerender=False))

    def _push_reader_return_position(self) -> None:
        snapshot = self._current_view_snapshot()
        if snapshot is None:
            return
        self.reader_return_stack.append(snapshot)
        if len(self.reader_return_stack) > 100:
            self.reader_return_stack = self.reader_return_stack[-100:]
        self._refresh_actions()

    def _restore_reader_position(self, page_index: int, page_offset: int, *, rerender: bool = True) -> None:
        if self.document is None:
            return
        page_index = max(0, min(page_index, self.document.page_count - 1))
        self.page_index = page_index
        if rerender:
            self.render_page(center_current=False)
        if self.continuous_scroll:
            self._restore_page_offset(page_index, page_offset)
        else:
            self._restore_scroll_position(page_offset, page_index)

    def _restore_page_offset(self, page_index: int, page_offset: int) -> None:
        if self.document is None:
            return
        if self._has_page_geometry(page_index):
            scroll_value = self.page_tops[page_index] + page_offset
        else:
            scroll_value = page_offset
        self._restore_scroll_position(scroll_value, page_index)

    def _restore_scroll_position(self, scroll_value: int, page_index: int) -> None:
        if self.document is None:
            return
        self._pending_scroll_id += 1
        scroll_bar = self.scroll_area.verticalScrollBar()
        was_suppressed = self._suppress_scroll_sync
        self._suppress_scroll_sync = True
        try:
            scroll_bar.setValue(max(0, min(scroll_value, scroll_bar.maximum())))
            self.page_index = max(0, min(page_index, self.document.page_count - 1))
            if self.page_index in self.page_canvases:
                self.canvas = self.page_canvases[self.page_index]
            self._refresh_actions()
        finally:
            self._suppress_scroll_sync = was_suppressed

    def _page_indexes_to_render(self, *, render_neighbors: bool = True) -> list[int]:
        if self.document is None:
            return []
        if not self.continuous_scroll or not render_neighbors:
            return [self.page_index]
        start = max(0, self.page_index - self.render_page_buffer)
        end = min(self.document.page_count, self.page_index + self.render_page_buffer + 1)
        page_indexes = set(range(start, end))
        page_indexes.update(self._visible_page_indexes())
        return sorted(page_indexes)

    def _visible_page_indexes(self, *, margin: int = 0) -> list[int]:
        if self.document is None or not self.page_tops:
            return []
        scroll_bar = self.scroll_area.verticalScrollBar()
        viewport_top = scroll_bar.value() - margin
        viewport_bottom = scroll_bar.value() + self.scroll_area.viewport().height() + margin
        visible_pages: list[int] = []
        for page_index, page_top in enumerate(self.page_tops):
            if page_index >= len(self.page_heights):
                break
            page_bottom = page_top + self.page_heights[page_index]
            if page_bottom >= viewport_top and page_top <= viewport_bottom:
                visible_pages.append(page_index)
        return visible_pages

    def _render_page_pixmap(self, page_index: int) -> tuple[QPixmap, QSize]:
        if self.document is None:
            raise RuntimeError("No document loaded")

        rendered = self.render_cache.render(self.document, page_index, self.zoom, self.render_scale)
        return rendered.pixmap, rendered.display_size

    def _page_text_words(self, page_index: int) -> list[dict[str, object]]:
        if self.document is None:
            return []
        cached_words = self.page_text_words_cache.get(page_index)
        if cached_words is not None:
            return cached_words

        try:
            words = page_words(self.document.load_page(page_index))
        except Exception:  # A damaged page simply has no selectable text.
            words = []
        self.page_text_words_cache[page_index] = words
        return words

    def _cache_page_base_sizes(self) -> None:
        self.page_base_sizes = page_base_sizes(self.document) if self.document is not None else []

    def _recalculate_page_metrics(self) -> None:
        self.page_tops = []
        self.page_heights = []
        self.page_widths = []
        if self.document is None:
            self.document_content_size = QSize(1, 1)
            return
        if len(self.page_base_sizes) != self.document.page_count:
            self._cache_page_base_sizes()

        margins = self.pages_layout.contentsMargins()
        spacing = self.pages_layout.spacing()
        cursor = margins.top()
        max_width = 1
        for page_index in range(self.document.page_count):
            size = self._page_display_size(page_index)
            self.page_tops.append(cursor)
            self.page_widths.append(size.width())
            self.page_heights.append(size.height())
            max_width = max(max_width, size.width())
            cursor += size.height() + spacing

        if self.document.page_count:
            cursor -= spacing
        total_height = cursor + margins.bottom()
        total_width = margins.left() + margins.right() + max_width
        self.document_content_size = QSize(max(1, total_width), max(1, total_height))

    def _page_display_size(self, page_index: int) -> QSize:
        if self.document is None:
            return QSize(640, 480)
        if not 0 <= page_index < len(self.page_base_sizes):
            self._cache_page_base_sizes()
        if 0 <= page_index < len(self.page_base_sizes):
            width, height = self.page_base_sizes[page_index]
        else:
            width, height = DEFAULT_PAGE_SIZE
        return QSize(max(1, round(width * self.zoom)), max(1, round(height * self.zoom)))

    def _create_placeholder(self, page_index: int) -> QWidget:
        placeholder = QWidget()
        placeholder.setObjectName("PagePlaceholder")
        placeholder.setFixedSize(self._page_display_size(page_index))
        placeholder.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return placeholder

    def _create_page_spacer(self, start_page: int, end_page: int) -> QWidget:
        spacer = QWidget()
        spacer.setObjectName("PagePlaceholderRun")
        if end_page < start_page:
            spacer.setFixedSize(1, 1)
            return spacer

        spacing = self.pages_layout.spacing()
        width = max(self.page_widths[start_page : end_page + 1], default=1)
        height = sum(self.page_heights[start_page : end_page + 1])
        height += max(0, end_page - start_page) * spacing
        spacer.setFixedSize(QSize(max(1, width), max(1, height)))
        spacer.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return spacer

    def _populate_continuous_pages(self, rendered_pages: set[int]) -> None:
        if self.document is None:
            return

        next_page = 0
        for page_index in sorted(page for page in rendered_pages if 0 <= page < self.document.page_count):
            if page_index > next_page:
                spacer = self._create_page_spacer(next_page, page_index - 1)
                self.pages_layout.addWidget(spacer, 0, Qt.AlignHCenter)
            self._add_rendered_page(page_index)
            next_page = page_index + 1

        if next_page < self.document.page_count:
            spacer = self._create_page_spacer(next_page, self.document.page_count - 1)
            self.pages_layout.addWidget(spacer, 0, Qt.AlignHCenter)

    def _add_rendered_page(self, page_index: int) -> None:
        widget = self._create_canvas(page_index)
        pixmap, display_size = self._render_page_pixmap(page_index)
        page_notes = [note for note in self.notes if note.page_index == page_index]
        widget.set_page(pixmap, page_notes, display_size, self._page_text_words(page_index))
        self._apply_search_hits(page_index, widget)
        self.pages_layout.addWidget(widget, 0, Qt.AlignHCenter)
        self.page_canvases[page_index] = widget
        self.page_widgets[page_index] = widget

    # --- find in PDF ------------------------------------------------------------------------

    def open_find_bar(self) -> None:
        if self.document is None or self.main_stack.currentWidget() is not self.reader_splitter:
            return
        selected = ""
        for canvas in self.page_canvases.values():
            if canvas._selected_text:
                selected = " ".join(canvas._selected_text.split())[:200]
                break
        self.find_bar.open_bar(selected)

    def start_search(self, query: str, options: SearchOptions) -> None:
        self._cancel_search(clear=True)
        if self.document is None or not query.strip():
            self.find_bar.set_status("")
            return
        self.search = DocumentSearch(self.document, query, options, start_page=self.page_index)
        self._search_jumped = False
        self.find_bar.set_status("Searching...")
        self._search_timer.start()

    def _search_tick(self) -> None:
        search = self.search
        if search is None or search.document is not self.document:
            self._cancel_search(clear=True)
            return
        found = search.step()
        if found:
            current = self.search_hits[self.search_index] if 0 <= self.search_index < len(self.search_hits) else None
            self.search_hits = search.hits
            self.search_index = self.search_hits.index(current) if current in self.search_hits else self.search_index
            if not self._search_jumped:
                self._search_jumped = True
                self._show_search_hit(self.search_hits.index(found[0]))
            else:
                self._refresh_search_overlays()
        if search.done:
            self._search_timer.stop()
        self._update_search_status()

    def _update_search_status(self) -> None:
        search = self.search
        if search is None:
            self.find_bar.set_status("")
            return
        total = len(self.search_hits)
        if not search.done:
            text = f"Searching... {search.pages_searched}/{search.page_count} pages, {total} found"
        elif total == 0:
            text = "No matches"
        else:
            text = f"{self.search_index + 1} of {total}" if self.search_index >= 0 else f"{total} matches"
        self.find_bar.set_status(text)

    def next_search_hit(self) -> None:
        self._step_search_hit(1)

    def previous_search_hit(self) -> None:
        self._step_search_hit(-1)

    def _step_search_hit(self, direction: int) -> None:
        if not self.find_bar.is_open():
            self.open_find_bar()
            return
        if self.search is None:
            self.find_bar.emit_search()
            return
        if not self.search_hits:
            return
        index = (self.search_index + direction) % len(self.search_hits) if self.search_index >= 0 else 0
        self._show_search_hit(index)

    def _show_search_hit(self, index: int) -> None:
        if not 0 <= index < len(self.search_hits) or self.document is None:
            return
        self.search_index = index
        hit = self.search_hits[index]
        page_height = self._page_display_size(hit.page_index).height()
        viewport_height = self.scroll_area.viewport().height()
        offset = max(0, int(hit.rect[1] * page_height - viewport_height * 0.3))
        self._go_to_page_offset(hit.page_index, offset)
        self._refresh_search_overlays()
        self._update_search_status()

    def _apply_search_hits(self, page_index: int, canvas: PdfCanvas) -> None:
        rects = [hit.rect for hit in self.search_hits if hit.page_index == page_index]
        current = -1
        if 0 <= self.search_index < len(self.search_hits) and self.search_hits[self.search_index].page_index == page_index:
            current = rects.index(self.search_hits[self.search_index].rect)
        canvas.set_search_hits(rects, current)

    def _refresh_search_overlays(self) -> None:
        for page_index, canvas in self.page_canvases.items():
            self._apply_search_hits(page_index, canvas)

    def _cancel_search(self, *, clear: bool) -> None:
        self._search_timer.stop()
        if self.search is not None:
            self.search.cancel()
        self.search = None
        if clear:
            self.search_hits = []
            self.search_index = -1
            self._refresh_search_overlays()

    def _restart_search_for_document_change(self) -> None:
        """Hits belong to one document: drop them, and re-run the open find bar on the new one."""
        self._cancel_search(clear=True)
        if self.find_bar.is_open() and self.document is not None:
            self.find_bar.emit_search()
        else:
            self.find_bar.set_status("")

    def close_search(self) -> None:
        self._cancel_search(clear=True)
        self.find_bar.set_status("")
        if self.canvas is not None:
            self.scroll_area.setFocus()

    def _create_canvas(self, page_index: int) -> PdfCanvas:
        canvas = PdfCanvas(page_index)
        canvas.set_context_state(continuous_scroll=self.continuous_scroll)
        canvas.set_theme_colors(self._theme_colors())
        canvas.set_marker_radius(self.note_marker_radius)
        canvas.add_note_requested.connect(self.add_note)
        canvas.append_selection_requested.connect(self.append_selected_text_to_current_note_from_canvas)
        canvas.annotation_requested.connect(self.add_text_annotation)
        canvas.bookmark_requested.connect(self.add_bookmark_for_page)
        canvas.fit_requested.connect(self.fit_page)
        canvas.mode_requested.connect(self.set_reading_mode)
        canvas.note_selected.connect(self.select_note)
        canvas.note_color_requested.connect(self.set_note_color)
        canvas.note_style_requested.connect(self.set_note_style)
        canvas.note_delete_requested.connect(self.delete_note_by_id)
        canvas.reset_note_counters_requested.connect(self.reset_note_counters_to_current_notes)
        canvas.settings_requested.connect(self.open_settings)
        canvas.zoom_requested.connect(self.change_zoom)
        return canvas

    def _render_empty_state(self) -> None:
        self._clear_page_widgets()
        self.canvas = self._create_canvas(0)
        self.canvas.set_page(None, [])
        self.pages_layout.addWidget(self.canvas, 0, Qt.AlignHCenter)
        self.page_canvases[0] = self.canvas
        self.page_widgets[0] = self.canvas
        self._lock_pages_container_to_layout()

    def _refresh_page_notes(self, *page_indexes: int) -> bool:
        """Repaint note overlays in place, preserving page widgets and scroll state."""
        refreshed = False
        for page_index in set(page_indexes):
            canvas = self.page_canvases.get(page_index)
            if canvas is None:
                continue
            canvas.set_notes([note for note in self.notes if note.page_index == page_index])
            refreshed = True
        return refreshed

    def _refresh_canvas_appearance(self) -> None:
        colors = self._theme_colors()
        for canvas in self.page_canvases.values():
            canvas.set_theme_colors(colors)
            canvas.set_marker_radius(self.note_marker_radius)

    def _clear_page_widgets(self) -> None:
        while self.pages_layout.count():
            item = self.pages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.page_canvases = {}
        self.page_widgets = {}

    def _lock_pages_container_to_layout(self) -> None:
        self.pages_layout.activate()
        if self.continuous_scroll and self.document is not None:
            viewport_size = self.scroll_area.viewport().size()
            self.pages_container.setFixedSize(
                QSize(
                    max(self.document_content_size.width(), viewport_size.width()),
                    max(self.document_content_size.height(), viewport_size.height()),
                )
            )
            return

        margins = self.pages_layout.contentsMargins()
        widgets = list(self.page_widgets.values())
        if not widgets:
            self.pages_container.setFixedSize(48, 48)
            return

        spacing = self.pages_layout.spacing()
        width = margins.left() + margins.right() + max(widget.width() for widget in widgets)
        height = margins.top() + margins.bottom() + sum(widget.height() for widget in widgets)
        height += max(0, len(widgets) - 1) * spacing
        self.pages_container.setFixedSize(QSize(max(1, width), max(1, height)))

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

        self._auto_save_current_note()
        note_number = self._allocate_note_number(page_index)
        note = Note.create(
            pdf_key=self.pdf_key,
            page_index=page_index,
            x_norm=x_norm,
            y_norm=y_norm,
            markdown=f"# {self._default_note_title(page_index, note_number)}\n",
            note_number=note_number,
        )
        self.page_index = page_index
        self.notes.append(note)
        self.persist_notes()
        if not self._refresh_page_notes(page_index):
            self.render_page_preserving_view()
        self.note_panel.set_note(note)
        self._refresh_note_selector(note.id)

    def add_text_annotation(self, page_index: int, note_type: str, rects_norm: list, selected_text: str, color: str = "") -> None:
        if self.document is None or self.pdf_key is None or not rects_norm:
            return
        self._auto_save_current_note()
        cleaned_rects = []
        for rect in rects_norm:
            if isinstance(rect, list | tuple) and len(rect) == 4:
                cleaned_rects.append([max(0.0, min(1.0, float(value))) for value in rect])
        if not cleaned_rects:
            return

        first_rect = cleaned_rects[0]
        x_norm = (first_rect[0] + first_rect[2]) / 2
        y_norm = (first_rect[1] + first_rect[3]) / 2
        note_number = self._allocate_note_number(page_index)
        note = Note.create(
            pdf_key=self.pdf_key,
            page_index=page_index,
            x_norm=x_norm,
            y_norm=y_norm,
            markdown=f"# {self._default_note_title(page_index, note_number)}\n\n> {selected_text}\n\n",
            note_type=note_type,
            rects_norm=cleaned_rects,
            selected_text=selected_text,
            color=color,
            note_number=note_number,
        )
        self.page_index = page_index
        self.notes.append(note)
        self.persist_notes()
        if not self._refresh_page_notes(page_index):
            self.render_page_preserving_view()
        self.note_panel.set_note(note)
        self._refresh_note_selector(note.id)

    def select_note(self, note_id: str) -> None:
        if note_id != self.note_panel.current_note_id:
            self._auto_save_current_note()
        note = find_note(self.notes, note_id)
        self.note_panel.set_note(note)
        self._refresh_note_selector(note.id if note else None)

    def jump_to_current_note(self) -> None:
        note_id = self.note_panel.current_note_id
        note = find_note(self.notes, note_id) if note_id is not None else None
        if note is None:
            self.statusBar().showMessage("Select a note before jumping to it.", 3000)
            return
        self.jump_to_note(note)

    def jump_to_note(self, note: Note) -> None:
        if self.document is None:
            return
        self._push_reader_return_position()
        self._go_to_page_offset(note.page_index, self._note_page_offset(note))
        self.note_panel.set_note(note)
        self._refresh_note_selector(note.id)

    def _note_page_offset(self, note: Note) -> int:
        if self.document is None:
            return 0
        page_height = self._page_display_size(note.page_index).height()
        rect_tops = [max(0.0, min(1.0, float(rect[1]))) for rect in note.rects_norm if len(rect) >= 4]
        if rect_tops:
            y_norm = min(rect_tops)
        else:
            y_norm = max(0.0, min(1.0, float(note.y_norm)))
        viewport_margin = min(180, max(80, self.scroll_area.viewport().height() // 4))
        return max(0, round(y_norm * page_height) - viewport_margin)

    def _auto_save_current_note(self) -> None:
        if not self.auto_save_current_note:
            return
        note_id = self.note_panel.current_note_id
        if note_id is None:
            return
        note = find_note(self.notes, note_id)
        if note is None:
            self.note_panel.set_note(None)
            return
        markdown = self.note_panel.editor.toPlainText()
        if note.markdown == markdown:
            return
        note.update_markdown(markdown)
        self.persist_notes()
        self._refresh_note_selector(note.id)

    def set_note_color(self, note_id: str, color: str) -> None:
        current_note_id = self.note_panel.current_note_id
        self._auto_save_current_note()
        note = find_note(self.notes, note_id)
        if note is None:
            return
        if not QColor(color).isValid():
            return
        note.color = QColor(color).name()
        note.update_markdown(note.markdown)
        self.persist_notes()
        self._refresh_page_notes(note.page_index)
        self._refresh_note_selector(current_note_id)

    def set_note_style(self, note_id: str, marker_style: str) -> None:
        if marker_style not in EXCERPT_MARKER_STYLES:
            return
        current_note_id = self.note_panel.current_note_id
        self._auto_save_current_note()
        note = find_note(self.notes, note_id)
        if note is None or note.note_type not in {"excerpt", "highlight", "underline"}:
            return
        if note.note_type == "excerpt":
            if note.marker_style == marker_style:
                return
            note.marker_style = marker_style
        else:
            if marker_style not in {"highlight", "underline"} or note.note_type == marker_style:
                return
            note.note_type = marker_style
        note.update_markdown(note.markdown)
        self.persist_notes()
        self._refresh_page_notes(note.page_index)
        self._refresh_note_selector(current_note_id)

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
        self._refresh_note_selector(note.id)

    def save_current_note_from_panel(self) -> None:
        if self.note_panel.current_note_id is not None:
            self.save_current_note(self.note_panel.editor.toPlainText())

    def export_current_note(self, markdown_text: str) -> None:
        note_id = self.note_panel.current_note_id
        if note_id is None:
            return

        note = find_note(self.notes, note_id)
        if note is None:
            self.note_panel.set_note(None)
            return

        note.update_markdown(markdown_text)
        self.persist_notes()
        export_mode = self._choose_export_mode(note)
        if export_mode is None:
            self.note_panel.set_note(note)
            self._refresh_note_selector(note.id)
            return
        path = self.export_markdown_note(note, replace_existing=export_mode == "replace")
        self.note_panel.set_note(note)
        self._refresh_note_selector(note.id)
        if path is not None:
            self.statusBar().showMessage(f"Exported Markdown note: {path}", 5000)
        self._report_export_errors()

    def export_current_note_from_panel(self) -> None:
        if self.note_panel.current_note_id is not None:
            self.export_current_note(self.note_panel.editor.toPlainText())

    def append_selected_text_to_current_note_from_shortcut(self) -> None:
        selected_canvas, text, rects_norm = self._current_text_selection()
        page_index = selected_canvas.page_index if selected_canvas is not None else None
        self.append_selected_text_to_current_note(
            text,
            page_index=page_index,
            rects_norm=rects_norm,
            marker_color=self._selection_color("append_selection_color"),
        )
        self._clear_canvas_selection(selected_canvas)

    def annotate_selected_text_from_shortcut(self, note_type: str) -> None:
        selected_canvas, text, rects_norm = self._current_text_selection()
        if selected_canvas is None or not text or not rects_norm:
            return
        color_key = "highlight_selection_color" if note_type == "highlight" else "underline_selection_color"
        self.add_text_annotation(selected_canvas.page_index, note_type, rects_norm, text, self._selection_color(color_key))
        self._clear_canvas_selection(selected_canvas)

    def append_selected_text_with_style_from_shortcut(self, marker_style: str) -> None:
        selected_canvas, text, rects_norm = self._current_text_selection()
        page_index = selected_canvas.page_index if selected_canvas is not None else None
        color_key = "append_highlight_selection_color" if marker_style == "highlight" else "append_underline_selection_color"
        self.append_selected_text_to_current_note(
            text,
            page_index=page_index,
            rects_norm=rects_norm,
            marker_style=marker_style,
            marker_color=self._selection_color(color_key),
        )
        self._clear_canvas_selection(selected_canvas)

    def _current_text_selection(self) -> tuple[PdfCanvas | None, str, list[list[float]]]:
        text = ""
        selected_canvas: PdfCanvas | None = None
        if self.canvas is not None:
            text = self.canvas.selected_text()
            if text:
                selected_canvas = self.canvas
        if not text:
            for canvas in self.page_canvases.values():
                text = canvas.selected_text()
                if text:
                    selected_canvas = canvas
                    break
        rects_norm = [list(rect) for rect in selected_canvas._selected_rects_norm] if selected_canvas is not None else None
        return selected_canvas, text, rects_norm or []

    @staticmethod
    def _clear_canvas_selection(selected_canvas: PdfCanvas | None) -> None:
        if selected_canvas is not None:
            selected_canvas.clear_selection()
            selected_canvas.update()

    def _selection_color(self, setting_key: str) -> str:
        default_color = SELECTION_COLOR_SETTINGS[setting_key][1]
        color = QColor(str(self.settings.get(setting_key) or default_color))
        return color.name() if color.isValid() else default_color

    def append_selected_text_to_current_note_from_canvas(self, page_index: int, rects_norm: list, selected_text: str) -> None:
        self.append_selected_text_to_current_note(selected_text, page_index=page_index, rects_norm=rects_norm)

    def append_selected_text_to_current_note(
        self,
        selected_text: str,
        *,
        page_index: int | None = None,
        rects_norm: list | None = None,
        marker_style: str = "dashed_underline",
        marker_color: str | None = None,
    ) -> None:
        cleaned = selected_text.strip()
        if not cleaned:
            return
        if self.note_panel.current_note_id is None:
            self.statusBar().showMessage("Select or create a note before appending selected text.", 5000)
            return

        current = self.note_panel.editor.toPlainText().rstrip()
        quote = "\n".join(f"> {line}" if line else ">" for line in cleaned.splitlines())
        updated = f"{current}\n\n{quote}\n" if current else f"{quote}\n"
        self.note_panel.editor.setPlainText(updated)
        self.save_current_note(updated)
        if page_index is not None and rects_norm:
            self._add_excerpt_marker(
                page_index,
                rects_norm,
                cleaned,
                self.note_panel.current_note_id,
                marker_style=marker_style,
                color=marker_color or self._selection_color("append_selection_color"),
            )
        self.statusBar().showMessage("Added selected text to current note.", 3000)

    def _add_excerpt_marker(
        self,
        page_index: int,
        rects_norm: list,
        selected_text: str,
        linked_note_id: str | None,
        *,
        marker_style: str = "dashed_underline",
        color: str = EXCERPT_MARKER_COLOR,
    ) -> None:
        if self.document is None or self.pdf_key is None or not linked_note_id:
            return
        cleaned_rects: list[list[float]] = []
        for rect in rects_norm:
            if isinstance(rect, list | tuple) and len(rect) == 4:
                cleaned_rects.append([max(0.0, min(1.0, float(value))) for value in rect])
        if not cleaned_rects:
            return
        first_rect = cleaned_rects[0]
        marker = Note.create(
            pdf_key=self.pdf_key,
            page_index=max(0, min(int(page_index), self.document.page_count - 1)),
            x_norm=(first_rect[0] + first_rect[2]) / 2,
            y_norm=(first_rect[1] + first_rect[3]) / 2,
            note_type="excerpt",
            rects_norm=cleaned_rects,
            selected_text=selected_text,
            color=color,
            linked_note_id=linked_note_id,
            marker_style=marker_style,
        )
        self.notes.append(marker)
        self.persist_notes()
        if not self._refresh_page_notes(marker.page_index):
            self.render_page_preserving_view()

    def delete_current_note(self) -> None:
        note_id = self.note_panel.current_note_id
        if note_id is None:
            return

        self.delete_note_by_id(note_id, confirm=True)

    def delete_note_by_id(self, note_id: str, *, confirm: bool = False) -> None:
        current_note_id = self.note_panel.current_note_id
        self._auto_save_current_note()
        note = find_note(self.notes, note_id)
        if note is None:
            return

        if confirm:
            title = "Delete annotation" if note.note_type != "point" else "Delete note"
            message = "Delete this annotation?" if note.note_type != "point" else "Delete this note?"
            answer = QMessageBox.question(
                self,
                title,
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        if note.note_type == "excerpt":
            current_note_id = current_note_id or note.linked_note_id
            affected_page = note.page_index
            self.notes = [item for item in self.notes if item.id != note_id]
            self.persist_notes()
            current_note = find_note(self.notes, current_note_id) if current_note_id else None
            self.note_panel.set_note(current_note)
            self._refresh_note_selector(current_note.id if current_note is not None else None)
            self._refresh_page_notes(affected_page)
            return

        affected_pages = {item.page_index for item in self.notes if item.id == note_id or item.linked_note_id == note_id}
        self.notes = [item for item in self.notes if item.id != note_id and item.linked_note_id != note_id]
        self.persist_notes()
        surviving_current = find_note(self.notes, current_note_id) if current_note_id and current_note_id != note_id else None
        self.note_panel.set_note(surviving_current)
        self._refresh_note_selector(surviving_current.id if surviving_current is not None else None)
        self._refresh_page_notes(*affected_pages)

    def reset_note_counters_to_current_notes(self) -> None:
        view = self._current_view_snapshot()
        self._rebuild_note_counters_from_current_note_counts()
        self.persist_notes()
        self.statusBar().showMessage("Reset note numbering to current note counts.", 5000)
        self._restore_view_snapshot(view)

    def _refresh_note_selector(self, current_note_id: str | None = None) -> None:
        current = current_note_id if current_note_id is not None else self.note_panel.current_note_id
        self.note_panel.set_notes([note for note in self.notes if note.note_type != "excerpt"], current)

    def persist_notes(self) -> None:
        if self.pdf_path is None or self.pdf_key is None:
            return
        save_notes(
            pdf_key=self.pdf_key,
            pdf_path=self.pdf_path,
            notes=self.notes,
            note_counters=self.note_counters,
            bookmarks=self.bookmarks,
        )

    def choose_note_export_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose Markdown notes folder", str(self.note_export_dir))
        if not path:
            return
        self.note_export_dir = Path(path)
        self.settings["markdown_export_dir"] = str(self.note_export_dir)
        save_settings(self.settings)

    def add_bookmark(self) -> None:
        self.add_bookmark_for_page(self.page_index)

    def add_bookmark_for_page(self, page_index: int) -> None:
        if self.document is None or self.pdf_key is None:
            return
        view = self._current_view_snapshot()
        page_index = max(0, min(int(page_index), self.document.page_count - 1))
        default_title = self._note_location_label(page_index) or f"Page {page_index + 1}"
        title, accepted = QInputDialog.getText(self, "Add bookmark", "Bookmark title:", text=default_title)
        if not accepted:
            self._restore_view_snapshot(view)
            return
        bookmark = Bookmark.create(pdf_key=self.pdf_key, page_index=page_index, title=title)
        self.bookmarks.append(bookmark)
        self.persist_notes()
        self.outline_panel.set_bookmarks(self.bookmarks)
        self._restore_view_snapshot(view)

    def delete_bookmark(self, bookmark_id: str) -> None:
        view = self._current_view_snapshot()
        before = len(self.bookmarks)
        self.bookmarks = [bookmark for bookmark in self.bookmarks if bookmark.id != bookmark_id]
        if len(self.bookmarks) == before:
            return
        self.persist_notes()
        self.outline_panel.set_bookmarks(self.bookmarks)
        self._restore_view_snapshot(view)

    def add_outline_item(self) -> None:
        self._add_outline_item(as_child=False)

    def add_outline_child_item(self) -> None:
        self._add_outline_item(as_child=True)

    def _add_outline_item(self, *, as_child: bool) -> None:
        if self.document is None:
            return
        page_index = self.outline_panel.selected_outline_page_index()
        if page_index is None or not as_child:
            page_index = self.page_index
        default_title = f"Page {page_index + 1}"
        title, accepted = QInputDialog.getText(self, "New contents item", "Title:", text=default_title)
        if not accepted:
            return
        title = self._single_line_title(title)
        if not title:
            return
        self.outline_panel.add_outline_item(title=title, page_index=page_index, as_child=as_child)
        self.statusBar().showMessage("Contents changed. Save contents to PDF to make note numbering follow it.", 5000)

    def delete_outline_item(self) -> None:
        if self.outline_panel.delete_selected_outline_item():
            self.statusBar().showMessage("Contents changed. Save contents to PDF to make note numbering follow it.", 5000)

    def save_outline_to_pdf(self) -> None:
        if self.document is None or self.pdf_path is None:
            return
        try:
            toc = normalize_toc(self.outline_panel.outline_toc(), self.document.page_count)
        except TocValidationError as exc:
            QMessageBox.warning(self, "Save contents", str(exc))
            return
        reason = refusal_reason(self.document)
        if reason:
            QMessageBox.warning(self, "Save contents", f"PDFNest did not change the PDF.\n\n{reason}")
            return

        backup = backup_path_for(self.pdf_path)
        backup_note = (
            f"The original from before the first save stays at:\n{backup}"
            if backup.exists()
            else f"A copy of the original is kept at:\n{backup}"
        )
        answer = QMessageBox.question(
            self,
            "Save contents to PDF",
            f"PDFNest will rewrite this PDF with the new contents:\n{self.pdf_path}\n\n{backup_note}",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        view = self._current_view_snapshot()
        error: Exception | None = None
        result: TocSaveResult | None = None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = save_toc_safely(self.document, toc, password=self.document_password)
        except Exception as exc:  # The original file is unchanged on every failure path.
            error = exc
        finally:
            QApplication.restoreOverrideCursor()
        if self.document.is_closed:
            self._reopen_active_document(view)
        if error is not None:
            QMessageBox.critical(self, "Save contents failed", f"The PDF was not changed.\n\n{error}")
            return

        self.outline_panel.set_outline(self.document.get_toc())
        self._rebuild_note_counters_from_current_note_counts()
        self.persist_notes()
        message = "Saved contents to PDF and refreshed note numbering counters."
        if result is not None and result.warnings:
            message += " " + " ".join(result.warnings)
        self.statusBar().showMessage(message, 8000)
        self._refresh_actions()

    def restore_pdf_backup(self) -> None:
        if self.document is None or self.pdf_path is None:
            return
        backup = backup_path_for(self.pdf_path)
        if not backup.exists():
            QMessageBox.information(self, "Restore original PDF", "There is no PDFNest backup for this PDF.")
            return
        answer = QMessageBox.question(
            self,
            "Restore original PDF",
            f"Replace the current PDF with the original from before PDFNest first saved contents?\n\n{backup}",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        view = self._current_view_snapshot()
        self.document.close()
        try:
            restore_backup(self.pdf_path)
        except OSError as exc:
            QMessageBox.critical(self, "Restore failed", f"Could not restore the original PDF:\n{exc}")
        self._reopen_active_document(view)
        self.outline_panel.set_outline(self.document.get_toc())
        self.statusBar().showMessage("Restored the original PDF.", 5000)

    def _reopen_active_document(self, view: tuple[int, int] | None) -> None:
        """Re-opens the active PDF after its file was replaced, keeping notes, tab and view."""
        if self.pdf_path is None:
            return
        document = reopen_pdf(self.pdf_path, self.document_password)
        self.document = document
        self.page_text_words_cache = {}
        self.render_cache.clear()
        self.chapter_lookup.invalidate()
        state = self.pdf_tabs.get(self.pdf_key) if self.pdf_key else None
        if state is not None:
            state.document = document
            state.page_text_words_cache = self.page_text_words_cache
        self._cache_page_base_sizes()
        self.render_page(center_current=False)
        self._restore_view_snapshot(view)

    def export_all_notes(self) -> None:
        exportable_notes = [note for note in self.notes if note.note_type != "excerpt"]
        if not exportable_notes:
            self.statusBar().showMessage("No notes to export.", 3000)
            return
        if self.note_panel.current_note_id is not None:
            self.save_current_note_from_panel()

        exported = 0
        for note in sorted(exportable_notes, key=lambda item: (item.page_index, self._note_number(item), item.created_at)):
            path = self.export_markdown_note(note, replace_existing=bool(note.exported_markdown_path))
            if path is not None:
                exported += 1
        self._refresh_note_selector()
        self.statusBar().showMessage(f"Exported {exported} Markdown notes.", 5000)
        self._report_export_errors()

    def _choose_export_mode(self, note: Note) -> str | None:
        if not note.exported_markdown_path:
            return "new"

        existing_path = Path(note.exported_markdown_path)
        if not existing_path.exists():
            return "new"

        message = QMessageBox(self)
        message.setWindowTitle("Export Markdown note")
        message.setText("This note has already been exported. Replace the previous Markdown file or create a new one?")
        replace_button = message.addButton("Replace previous", QMessageBox.AcceptRole)
        new_button = message.addButton("Create new file", QMessageBox.ActionRole)
        message.addButton(QMessageBox.Cancel)
        message.setDefaultButton(replace_button)
        message.exec()
        chosen = message.clickedButton()
        if chosen == replace_button:
            return "replace"
        if chosen == new_button:
            return "new"
        return None

    def export_markdown_note(self, note: Note, *, replace_existing: bool = False) -> Path | None:
        if self.pdf_path is None:
            return None

        path = self.export_markdown_note_for_pdf(
            pdf_path=self.pdf_path,
            note=note,
            document=self.document,
            replace_existing=replace_existing,
        )
        if path is not None:
            self.persist_notes()
        return path

    def export_markdown_note_for_pdf(
        self,
        *,
        pdf_path: Path,
        note: Note,
        document: fitz.Document | None,
        replace_existing: bool = False,
    ) -> Path | None:
        try:
            return export_note_markdown(
                note,
                pdf_path=pdf_path,
                export_root=self.note_export_dir,
                location=self._note_location_label_for_document(document, note.page_index),
                note_number=self._note_number(note),
                replace_existing=replace_existing,
            )
        except ExportError as exc:
            self.export_errors.append(str(exc))
            return None

    def _report_export_errors(self) -> None:
        """One warning per export action, however many notes failed."""
        errors, self.export_errors = self.export_errors, []
        if not errors:
            return
        detail = errors[0] if len(set(errors)) == 1 else "\n".join(sorted(set(errors)))
        QMessageBox.warning(
            self,
            "Export Markdown",
            f"{len(errors)} note(s) could not be exported. Your notes inside PDFNest are unchanged.\n\n{detail}\n\n"
            f"Export folder: {self.note_export_dir}",
        )

    def _default_note_title(self, page_index: int, note_number: int) -> str:
        return f"{self._note_location_label(page_index)}-{note_number}"

    def _note_location_label(self, page_index: int) -> str:
        return location_label(self._chapter_for_page(page_index), page_index)

    def _note_location_label_for_document(self, document: fitz.Document | None, page_index: int) -> str:
        return location_label(self._chapter_for_document(document, page_index), page_index)

    def _counter_key(self, page_index: int) -> str:
        return counter_key(self._chapter_for_page(page_index), page_index)

    def _allocate_note_number(self, page_index: int) -> int:
        key = self._counter_key(page_index)
        next_number = max(1, int(self.note_counters.get(key, 1)))
        self.note_counters[key] = next_number + 1
        return next_number

    def _ensure_note_counters(self, *, force: bool = False) -> None:
        if self.note_counters and not force and not self._note_counters_need_migration():
            return
        max_by_key: dict[str, int] = {}
        for note in self.notes:
            if note.note_type == "excerpt":
                continue
            key = self._counter_key(note.page_index)
            old_page_key = str(max(0, int(note.page_index)))
            for existing_key in (key, old_page_key):
                existing_next = self.note_counters.get(existing_key)
                if existing_next is not None:
                    max_by_key[key] = max(max_by_key.get(key, 0), max(0, int(existing_next) - 1))
            if note.note_number > 0:
                max_by_key[key] = max(max_by_key.get(key, 0), note.note_number)
            else:
                max_by_key[key] = max(max_by_key.get(key, 0), self._legacy_note_number_from_title(note))
        self.note_counters = {key: value + 1 for key, value in max_by_key.items() if value > 0}

    def _note_counters_need_migration(self) -> bool:
        return any(key.isdecimal() for key in self.note_counters)

    def _rebuild_note_counters_from_current_note_counts(self) -> None:
        counts_by_key: dict[str, int] = {}
        for note in self.notes:
            if note.note_type == "excerpt":
                continue
            key = self._counter_key(note.page_index)
            counts_by_key[key] = counts_by_key.get(key, 0) + 1
        self.note_counters = {key: count + 1 for key, count in counts_by_key.items() if count > 0}

    def _legacy_note_number_from_title(self, note: Note) -> int:
        location = self._note_location_label(note.page_index)
        first_line = next((line.strip() for line in note.markdown.splitlines() if line.strip()), "")
        match = re.match(r"^#*\s*" + re.escape(location) + r"-(\d+)\s*$", first_line)
        return int(match.group(1)) if match else 0

    def _note_number(self, note: Note) -> int:
        if note.note_number > 0:
            return note.note_number
        key = self._counter_key(note.page_index)
        page_notes = [item for item in self.notes if item.note_type != "excerpt" and self._counter_key(item.page_index) == key]
        page_notes.sort(key=lambda item: item.created_at)
        for index, item in enumerate(page_notes, start=1):
            if item.id == note.id:
                return index
        return len(page_notes) + 1

    def _chapter_name_for_page(self, page_index: int) -> str | None:
        return self._chapter_name_for_document(self.document, page_index)

    def _chapter_name_for_document(self, document: fitz.Document | None, page_index: int) -> str | None:
        chapter = self._chapter_for_document(document, page_index)
        return chapter[0] if chapter is not None else None

    def _chapter_for_page(self, page_index: int) -> tuple[str, int] | None:
        return self._chapter_for_document(self.document, page_index)

    def _chapter_for_document(self, document: fitz.Document | None, page_index: int) -> tuple[str, int] | None:
        return self.chapter_lookup.chapter_for_page(document, page_index)

    _single_line_title = staticmethod(single_line_title)

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
        self._record_current_pdf()
        self.render_page(center_current=False)
        if self.continuous_scroll:
            self._scroll_to_page(self.page_index, center=False)

    def jump_to_page_from_navigation(self, page_index: int) -> None:
        if self.document is None:
            return
        self._push_reader_return_position()
        self._go_to_page_offset(page_index, 0)

    def return_to_previous_reading_position(self) -> None:
        if self.document is None or not self.reader_return_stack:
            self._refresh_actions()
            return
        page_index, page_offset = self.reader_return_stack.pop()
        self._restore_reader_position(page_index, page_offset)
        self._refresh_actions()

    def _go_to_page_offset(self, page_index: int, page_offset: int) -> None:
        if self.document is None:
            return
        self.page_index = max(0, min(page_index, self.document.page_count - 1))
        self._record_current_pdf()
        if self.continuous_scroll:
            self.render_page(center_current=False)
            self._restore_page_offset(self.page_index, page_offset)
        else:
            self.render_page(center_current=False)
            self._restore_scroll_position(page_offset, self.page_index)

    def go_to_page_number(self, page_number: int) -> None:
        if self.document is None or page_number < 1 or page_number > self.document.page_count:
            return
        self._push_reader_return_position()
        self._go_to_page_offset(page_number - 1, 0)

    def commit_page_number_input(self) -> None:
        if self.document is None:
            self.page_spin.setText("")
            return
        text = self.page_spin.text().strip()
        if not text.isdigit():
            self._refresh_actions()
            return
        page_number = int(text)
        if page_number < 1 or page_number > self.document.page_count:
            self._refresh_actions()
            return
        self.go_to_page_number(page_number)

    def reset_page_number_input(self) -> None:
        self._refresh_actions()

    def _scroll_to_page(self, page_index: int, *, center: bool = False) -> None:
        if not self._has_page_geometry(page_index):
            return

        self._suppress_scroll_sync = True
        self.pages_layout.activate()
        self._set_scroll_value_for_page(page_index, center=center)
        self.page_index = page_index
        if page_index in self.page_canvases:
            self.canvas = self.page_canvases[page_index]
        self._refresh_actions()
        self._suppress_scroll_sync = False
        self._pending_scroll_id += 1
        scroll_id = self._pending_scroll_id
        QTimer.singleShot(0, lambda page=page_index, keep_center=center, token=scroll_id: self._finish_programmatic_scroll(page, center=keep_center, token=token))

    def _finish_programmatic_scroll(self, page_index: int, *, center: bool = False, token: int | None = None) -> None:
        if token is not None and token != self._pending_scroll_id:
            return
        if not self._has_page_geometry(page_index):
            return

        self._suppress_scroll_sync = True
        self._set_scroll_value_for_page(page_index, center=center)
        self.page_index = page_index
        if page_index in self.page_canvases:
            self.canvas = self.page_canvases[page_index]
        self._refresh_actions()
        if token is not None:
            self._pending_scroll_id += 1
        self._suppress_scroll_sync = False

    def _has_page_geometry(self, page_index: int) -> bool:
        return 0 <= page_index < len(self.page_tops) and page_index < len(self.page_heights)

    def _set_scroll_value_for_page(self, page_index: int, *, center: bool) -> None:
        scroll_bar = self.scroll_area.verticalScrollBar()
        scroll_bar.setValue(self._scroll_target_for_page(page_index, center=center))

    def _scroll_target_for_page(self, page_index: int, *, center: bool) -> int:
        scroll_bar = self.scroll_area.verticalScrollBar()
        page_top = self.page_tops[page_index]
        page_height = self.page_heights[page_index]
        if center:
            target = page_top + page_height // 2 - self.scroll_area.viewport().height() // 2
        else:
            target = page_top - self.pages_layout.spacing()
        return max(0, min(scroll_bar.maximum(), target))

    def _sync_current_page_from_scroll(self) -> None:
        if self._suppress_scroll_sync or self.document is None or not self.continuous_scroll or not self.page_tops:
            return

        self._pending_scroll_id += 1
        scroll_bar = self.scroll_area.verticalScrollBar()
        if self._has_page_geometry(self.page_index):
            current_center = self._scroll_target_for_page(self.page_index, center=True)
            if abs(scroll_bar.value() - current_center) <= 2:
                return

        visible_y = scroll_bar.value() + min(80, max(1, self.scroll_area.viewport().height() // 4))
        closest_page = self.page_index
        closest_distance = float("inf")
        for page_index, widget_top in enumerate(self.page_tops):
            widget_bottom = widget_top + self.page_heights[page_index]
            if widget_top <= visible_y <= widget_bottom:
                closest_page = page_index
                break
            distance = abs((widget_top + widget_bottom) / 2 - visible_y)
            if distance < closest_distance:
                closest_distance = distance
                closest_page = page_index

        page_changed = closest_page != self.page_index
        if page_changed:
            self.page_index = closest_page
            if closest_page in self.page_canvases:
                self.canvas = self.page_canvases[closest_page]
            self._refresh_actions()

        rendered_pages = sorted(self.page_canvases)
        needs_render = closest_page not in self.page_canvases
        needs_render = needs_render or any(page_index not in self.page_canvases for page_index in self._visible_page_indexes(margin=24))
        if rendered_pages:
            buffer_edge = max(1, self.render_page_buffer // 2)
            needs_render = needs_render or closest_page <= rendered_pages[0] + buffer_edge
            needs_render = needs_render or closest_page >= rendered_pages[-1] - buffer_edge
        if needs_render:
            self._schedule_page_window_render()

    def _schedule_page_window_render(self) -> None:
        if self.document is None:
            return
        self._page_window_render_token += 1
        token = self._page_window_render_token
        QTimer.singleShot(35, lambda token=token: self._render_scheduled_page_window(token))

    def _render_scheduled_page_window(self, token: int) -> None:
        if token != self._page_window_render_token or self.document is None:
            return
        self.render_page(center_current=False)

    def set_continuous_scroll(self, checked: bool) -> None:
        self.set_reading_mode("continuous" if checked else "single")

    def set_reading_mode(self, mode: str) -> None:
        next_continuous = mode == "continuous"
        if self.continuous_scroll == next_continuous:
            return
        self.continuous_scroll = next_continuous
        self.render_page()

    def change_zoom(self, delta: float, *, clear_fit: bool = True) -> None:
        if self.document is None:
            return
        if clear_fit:
            self.fit_mode = None
        self.zoom = max(0.3, min(4.0, self.zoom + delta))
        self.render_page(render_neighbors=False)

    def set_zoom_percent(self, percent: float) -> None:
        if self.document is None:
            return
        self.fit_mode = None
        self.zoom = max(0.3, min(4.0, percent / 100.0))
        self.render_page(render_neighbors=False)

    def fit_page(self, mode: str) -> None:
        if self.document is None:
            return
        anchor_page = self.page_index
        self.fit_mode = mode
        self._page_window_render_token += 1
        self._apply_fit_mode(anchor_page=anchor_page, force=True)
        self._schedule_fit_refresh(anchor_page=anchor_page)

    def _apply_fit_mode(
        self,
        *,
        anchor_page: int | None = None,
        token: int | None = None,
        force: bool = False,
    ) -> None:
        if token is not None and token != self._fit_refresh_token:
            return
        if self.document is None or self.fit_mode is None:
            return
        if anchor_page is not None:
            self.page_index = max(0, min(anchor_page, self.document.page_count - 1))

        view_anchor = self._fit_view_anchor(self.page_index)
        selection = self._capture_canvas_selection()

        self.reader_splitter.updateGeometry()
        self.reader_area.updateGeometry()
        if self.reader_area.layout() is not None:
            self.reader_area.layout().activate()

        self._update_page_layout_margins()
        page = self.document.load_page(self.page_index)
        rect = page.rect
        margins = self.pages_layout.contentsMargins()
        measured_viewport = self.scroll_area.viewport().size()
        if self.fit_mode == "width":
            widest_page_width = max((size[0] for size in self.page_base_sizes), default=float(rect.width))
            available = measured_viewport.width() - margins.left() - margins.right()
            next_zoom = max(0.3, min(4.0, available / widest_page_width))
        elif self.fit_mode == "height":
            available = measured_viewport.height() - margins.top() - margins.bottom()
            next_zoom = max(0.3, min(4.0, available / rect.height))
        else:
            return
        if not force and self.page_canvases and abs(next_zoom - self.zoom) < 0.0001:
            return

        self.zoom = next_zoom
        self._page_window_render_token += 1
        self.render_page(center_current=False, render_neighbors=True)
        self._restore_fit_view_anchor(view_anchor)
        self._restore_canvas_selection(selection)

    def _fit_view_anchor(self, page_index: int) -> tuple[int, float, int]:
        viewport_offset = min(80, max(1, self.scroll_area.viewport().height() // 4))
        if not self._has_page_geometry(page_index) or self.page_heights[page_index] <= 0:
            return page_index, 0.0, viewport_offset
        content_y = self.scroll_area.verticalScrollBar().value() + viewport_offset
        relative = (content_y - self.page_tops[page_index]) / self.page_heights[page_index]
        return page_index, max(0.0, min(1.0, relative)), viewport_offset

    def _restore_fit_view_anchor(self, anchor: tuple[int, float, int]) -> None:
        page_index, relative, viewport_offset = anchor
        if not self._has_page_geometry(page_index):
            return
        target = self.page_tops[page_index] + round(relative * self.page_heights[page_index]) - viewport_offset
        self._restore_scroll_position(target, page_index)

    def _capture_canvas_selection(self) -> tuple[int, str, list[list[float]]] | None:
        for page_index, canvas in self.page_canvases.items():
            if canvas._selected_text and canvas._selected_rects_norm:
                return page_index, canvas._selected_text, [list(rect) for rect in canvas._selected_rects_norm]
        return None

    def _restore_canvas_selection(self, selection: tuple[int, str, list[list[float]]] | None) -> None:
        if selection is None:
            return
        page_index, selected_text, rects_norm = selection
        canvas = self.page_canvases.get(page_index)
        if canvas is None:
            return
        canvas._selected_text = selected_text
        canvas._selected_rects_norm = [list(rect) for rect in rects_norm]
        canvas.update()

    def _update_page_layout_margins(self) -> None:
        if self.fit_mode == "width":
            margins = (0, self.page_margin, 0, self.page_margin)
        elif self.fit_mode == "height":
            margins = (self.page_margin, 0, self.page_margin, 0)
        else:
            margins = (self.page_margin, self.page_margin, self.page_margin, self.page_margin)

        current = self.pages_layout.contentsMargins()
        if (
            current.left(),
            current.top(),
            current.right(),
            current.bottom(),
        ) != margins:
            self.pages_layout.setContentsMargins(*margins)

    def _handle_reader_splitter_moved(self, _pos: int, _index: int) -> None:
        self._schedule_fit_refresh(anchor_page=self.page_index)

    def _schedule_fit_refresh(self, *, anchor_page: int | None = None) -> None:
        if self.fit_mode is not None and self.document is not None:
            self._fit_refresh_token += 1
            token = self._fit_refresh_token
            page = self.page_index if anchor_page is None else anchor_page
            QTimer.singleShot(120, lambda page=page, token=token: self._apply_fit_mode(anchor_page=page, token=token))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._schedule_fit_refresh(anchor_page=self.page_index)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt override
        if hasattr(self, "page_spin") and watched is self.page_spin and event.type() == QEvent.FocusOut:
            self.reset_page_number_input()
        if hasattr(self, "scroll_area") and watched is self.scroll_area.viewport():
            if event.type() == QEvent.Resize:
                self._schedule_fit_refresh(anchor_page=self.page_index)
            elif event.type() == QEvent.Wheel:
                if event.modifiers() & Qt.ControlModifier:
                    self.change_zoom(0.1 if event.angleDelta().y() > 0 else -0.1)
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

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

        if self.main_stack.currentWidget() is self.history_panel and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            key = self.history_panel.selected_pdf_key
            if key:
                if event.modifiers() & Qt.ShiftModifier:
                    self.remove_history_entry(key)
                else:
                    self.archive_history_entry(key)
                event.accept()
                return

        if event.key() in (Qt.Key_Left, Qt.Key_PageUp):
            self.previous_page()
            event.accept()
            return
        if event.key() in (Qt.Key_Right, Qt.Key_PageDown):
            self.next_page()
            event.accept()
            return
        if event.key() == Qt.Key_Up:
            self.scroll_reader_lines(-1)
            event.accept()
            return
        if event.key() == Qt.Key_Down:
            self.scroll_reader_lines(1)
            event.accept()
            return
        super().keyPressEvent(event)

    def scroll_reader_lines(self, direction: int) -> None:
        if self.document is None:
            return
        scroll_bar = self.scroll_area.verticalScrollBar()
        step = max(16, self.wheel_scroll_lines * 40)
        was_suppressed = self._suppress_scroll_sync
        self._suppress_scroll_sync = True
        try:
            scroll_bar.setValue(max(0, min(scroll_bar.maximum(), scroll_bar.value() + direction * step)))
        finally:
            self._suppress_scroll_sync = was_suppressed

    def _refresh_actions(self) -> None:
        has_document = self.document is not None
        page_count = self.document.page_count if self.document is not None else 0
        self.prev_page_button.setEnabled(has_document and self.page_index > 0)
        self.next_page_button.setEnabled(has_document and self.page_index < page_count - 1)
        can_return = has_document and bool(self.reader_return_stack)
        self.return_position_button.setEnabled(can_return)
        self.return_position_button.setIcon(pic_icon("redo.png" if can_return else "redo-disabled.png"))
        self.outline_action.setEnabled(has_document)
        self.reader_action.setEnabled(has_document)
        self.outline_toggle_button.setEnabled(has_document and self.main_stack.currentWidget() is self.reader_splitter)
        self.page_spin.setEnabled(has_document)
        self.zoom_spin.setEnabled(has_document)
        self._refresh_document_chrome()

        if has_document:
            with QSignalBlocker(self.page_spin):
                self.page_spin.setText(str(self.page_index + 1))
            self.page_count_label.setText(f"/ {page_count}")
        else:
            with QSignalBlocker(self.page_spin):
                self.page_spin.setText("")
            self.page_count_label.setText("/ 0")
        with QSignalBlocker(self.zoom_spin):
            self.zoom_spin.setValue(round(self.zoom * 100))

    def apply_theme(self) -> None:
        colors = self._theme_colors()
        down_arrow_icon = app_resource_path("Pic", "down-arrow.png").as_posix()
        up_arrow_icon = app_resource_path("Pic", "up-arrow.png").as_posix()
        style = build_app_stylesheet(colors, down_arrow_icon=down_arrow_icon, up_arrow_icon=up_arrow_icon)
        self.setStyleSheet(style)
        self._apply_reader_palette()

    def _theme_colors(self) -> dict[str, str]:
        colors = self.themes.get(self.theme_name) or self.themes.get("beige") or {}
        return {str(key): str(value) for key, value in colors.items()}

    def _apply_reader_palette(self) -> None:
        reader_background = QColor(self._theme_colors().get("reader", "#f0ead8"))
        for widget in (self.scroll_area, self.scroll_area.viewport(), self.pages_container, self.reader_area):
            palette = widget.palette()
            palette.setColor(QPalette.Window, reader_background)
            palette.setColor(QPalette.Base, reader_background)
            widget.setPalette(palette)
            widget.setAutoFillBackground(True)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._save_runtime_settings()
        self._close_all_pdf_tabs()
        super().closeEvent(event)
