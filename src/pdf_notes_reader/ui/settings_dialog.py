"""Settings dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdf_notes_reader.notes import app_local_data_dir, default_data_dir
from pdf_notes_reader.services.backup import create_backup, default_backup_name, verify_backup
from pdf_notes_reader.settings import clamp_marker_radius, clamp_wheel_scroll_lines, settings_path
from pdf_notes_reader.ui.constants import ANNOTATION_COLORS, SELECTION_COLOR_SETTINGS, SELECTION_SHORTCUTS


class SettingsDialog(QDialog):
    def __init__(
        self,
        *,
        settings: dict,
        themes: dict[str, dict[str, str]],
        data_dir: Path,
        note_json_path: Path | None,
        markdown_dir: Path,
        theme_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.data_dir = data_dir
        self.setWindowTitle("PDFNest Settings")
        self.resize(760, 560)
        self.setMinimumWidth(720)

        self.theme_combo = QComboBox()
        for theme_name in sorted(themes):
            self.theme_combo.addItem(theme_name, theme_name)
        current_theme = str(settings.get("theme") or "beige")
        index = self.theme_combo.findData(current_theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

        self.marker_size_spin = QSpinBox()
        self.marker_size_spin.setRange(3, 24)
        self.marker_size_spin.setValue(clamp_marker_radius(settings.get("note_marker_radius")))

        self.auto_save_note_checkbox = QCheckBox("Save current note when switching notes or closing")
        self.auto_save_note_checkbox.setChecked(bool(settings.get("auto_save_current_note", True)))

        self.wheel_scroll_lines_spin = QSpinBox()
        self.wheel_scroll_lines_spin.setRange(1, 30)
        self.wheel_scroll_lines_spin.setValue(clamp_wheel_scroll_lines(settings.get("wheel_scroll_lines")))

        self.append_selection_shortcut_edit = QKeySequenceEdit()
        shortcut_text = str(settings.get("append_selection_shortcut") or "Ctrl+Shift+C")
        self.append_selection_shortcut_edit.setKeySequence(QKeySequence(shortcut_text))
        self.selection_shortcut_edits: dict[str, QKeySequenceEdit] = {}
        for setting_key, (_label, default_shortcut) in SELECTION_SHORTCUTS.items():
            edit = QKeySequenceEdit()
            edit.setKeySequence(QKeySequence(str(settings.get(setting_key) or default_shortcut)))
            self.selection_shortcut_edits[setting_key] = edit

        self.selection_color_combos: dict[str, QComboBox] = {}
        for setting_key, (_label, default_color) in SELECTION_COLOR_SETTINGS.items():
            color = QColor(str(settings.get(setting_key) or default_color))
            if not color.isValid():
                color = QColor(default_color)
            combo = QComboBox()
            combo.setMinimumWidth(180)
            for label, preset_color in ANNOTATION_COLORS:
                combo.addItem(label, preset_color)
            combo.addItem("Custom color...", "")
            normalized = color.name()
            index = combo.findData(normalized)
            if index < 0:
                index = combo.count() - 1
                combo.setItemText(index, f"Custom color... ({normalized})")
                combo.setItemData(index, normalized)
            combo.setCurrentIndex(index)
            combo.setProperty("selectedColor", normalized)
            combo.currentIndexChanged.connect(lambda selected, key=setting_key: self._selection_color_changed(key, selected))
            combo.activated.connect(lambda selected, key=setting_key: self._choose_selection_color(key, selected))
            self.selection_color_combos[setting_key] = combo

        self.storage_dir_edit = QLineEdit(str(settings.get("storage_dir") or data_dir))
        self.storage_dir_edit.setAlignment(Qt.AlignLeft)
        self.storage_dir_edit.setCursorPosition(0)
        self.storage_dir_edit.setMinimumWidth(260)
        self.storage_dir_edit.setMaximumWidth(420)
        storage_browse_button = QPushButton("Browse")
        storage_browse_button.clicked.connect(self._choose_storage_dir)
        storage_copy_button = self._copy_button(lambda: self.storage_dir_edit.text())
        storage_row = QWidget()
        storage_row_layout = QHBoxLayout(storage_row)
        storage_row_layout.setContentsMargins(0, 0, 0, 0)
        storage_row_layout.setSpacing(8)
        storage_row_layout.addWidget(self.storage_dir_edit, 1)
        storage_row_layout.addWidget(storage_browse_button, 0)
        storage_row_layout.addWidget(storage_copy_button, 0)

        self.markdown_dir_edit = QLineEdit(str(settings.get("markdown_export_dir") or markdown_dir))
        self.markdown_dir_edit.setAlignment(Qt.AlignLeft)
        self.markdown_dir_edit.setCursorPosition(0)
        self.markdown_dir_edit.setMinimumWidth(260)
        self.markdown_dir_edit.setMaximumWidth(420)
        markdown_browse_button = QPushButton("Browse")
        markdown_browse_button.clicked.connect(self._choose_markdown_dir)
        markdown_copy_button = self._copy_button(lambda: self.markdown_dir_edit.text())
        markdown_row = QWidget()
        markdown_row_layout = QHBoxLayout(markdown_row)
        markdown_row_layout.setContentsMargins(0, 0, 0, 0)
        markdown_row_layout.setSpacing(8)
        markdown_row_layout.addWidget(self.markdown_dir_edit, 1)
        markdown_row_layout.addWidget(markdown_browse_button, 0)
        markdown_row_layout.addWidget(markdown_copy_button, 0)

        data_label = self._path_row(str(data_dir))
        note_label = self._path_row(str(note_json_path) if note_json_path is not None else "Open a PDF to see this path.")
        settings_label = self._path_row(str(settings_path(data_dir)))
        theme_dir_label = self._path_row(str(theme_dir))

        self.category_list = QTreeWidget()
        self.category_list.setHeaderHidden(True)
        self.category_list.setRootIsDecorated(False)
        self.category_list.setFixedWidth(140)
        self.category_list.itemSelectionChanged.connect(self._sync_category_page)

        self.pages = QStackedWidget()

        basic_form = QFormLayout()
        basic_form.addRow("Theme", self.theme_combo)

        note_form = QFormLayout()
        note_form.addRow("Note dot size", self.marker_size_spin)
        note_form.addRow("Auto save", self.auto_save_note_checkbox)

        display_form = QFormLayout()
        display_form.addRow("Mouse wheel scroll lines", self.wheel_scroll_lines_spin)

        shortcuts_form = QFormLayout()
        shortcuts_form.addRow("Add selection to current note", self.append_selection_shortcut_edit)
        for setting_key, (label, _default_shortcut) in SELECTION_SHORTCUTS.items():
            shortcuts_form.addRow(label, self.selection_shortcut_edits[setting_key])

        annotation_colors_form = QFormLayout()
        for setting_key, (label, _default_color) in SELECTION_COLOR_SETTINGS.items():
            annotation_colors_form.addRow(label, self.selection_color_combos[setting_key])

        storage_form = QGridLayout()
        self._add_storage_row(storage_form, 0, "PDFNest data folder", storage_row)
        self._add_storage_row(storage_form, 1, "Data folder", data_label)
        self._add_storage_row(storage_form, 2, "Current note data", note_label)
        self._add_storage_row(storage_form, 3, "Markdown export base", markdown_row)
        self._add_storage_row(storage_form, 4, "Settings file", settings_label)
        self._add_storage_row(storage_form, 5, "Theme folder", theme_dir_label)
        self.backup_button = QPushButton("Back up all data...")
        self.backup_button.setToolTip("Save notes, anchors, highlights, bookmarks, library and settings into one .zip file")
        self.backup_button.clicked.connect(self.create_backup)
        self._add_storage_row(storage_form, 6, "Backup", self.backup_button)
        storage_form.setColumnStretch(0, 0)
        storage_form.setColumnStretch(1, 1)

        self._add_settings_page("Basic", basic_form)
        self._add_settings_page("Notes", note_form)
        self._add_settings_page("Annotation colors", annotation_colors_form)
        self._add_settings_page("Page display", display_form)
        self._add_settings_page("Storage", storage_form)
        self._add_settings_page("Shortcuts", shortcuts_form)
        self._add_settings_page("Other", QFormLayout())
        self.category_list.setCurrentItem(self.category_list.topLevelItem(0))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        body = QHBoxLayout()
        body.addWidget(self.category_list)
        body.addWidget(self.pages, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)

    def _add_settings_page(self, title: str, form) -> None:
        page = QWidget()
        form.setContentsMargins(18, 18, 18, 18)
        form.setSpacing(12)
        page.setLayout(form)
        index = self.pages.addWidget(page)
        item = QTreeWidgetItem([title])
        item.setData(0, Qt.UserRole, index)
        self.category_list.addTopLevelItem(item)

    @staticmethod
    def _path_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setWordWrap(False)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        label.setMinimumWidth(0)
        label.setToolTip(text)
        return label

    @staticmethod
    def _copy_button(text_getter) -> QToolButton:
        button = QToolButton()
        button.setObjectName("CopyPathButton")
        button.setText("⧉")
        button.setToolTip("Copy path")
        button.setFixedSize(26, 24)
        button.clicked.connect(lambda: QApplication.clipboard().setText(str(text_getter())))
        return button

    @staticmethod
    def _add_storage_row(layout: QGridLayout, row: int, label_text: str, value_widget: QWidget) -> None:
        label = QLabel(label_text)
        label.setObjectName("SettingsPathLabel")
        label.setFixedWidth(160)
        label.setMinimumHeight(28)
        layout.addWidget(label, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(value_widget, row, 1)

    @staticmethod
    def _path_row(text: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = SettingsDialog._path_label(text)
        copy_button = SettingsDialog._copy_button(lambda: text)
        layout.addWidget(label, 1)
        layout.addWidget(copy_button, 0)
        return row

    def _sync_category_page(self) -> None:
        item = self.category_list.currentItem()
        if item is None:
            return
        index = item.data(0, Qt.UserRole)
        if index is not None:
            self.pages.setCurrentIndex(int(index))

    def _choose_storage_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose PDFNest data folder", self.storage_dir_edit.text())
        if path:
            self.storage_dir_edit.setText(path)
            self.storage_dir_edit.setCursorPosition(0)

    def create_backup(self) -> Path | None:
        source = Path(self.storage_dir_edit.text().strip() or str(self.data_dir))
        suggested = Path.home() / default_backup_name()
        target, _filter = QFileDialog.getSaveFileName(self, "Back up PDFNest data", str(suggested), "Zip archive (*.zip)")
        if not target:
            return None
        try:
            path, count = create_backup(source, Path(target))
            broken = verify_backup(path)
        except OSError as exc:
            QMessageBox.critical(self, "Backup failed", f"The backup could not be written:\n{exc}")
            return None
        if broken:
            QMessageBox.warning(self, "Backup created with problems", "These files could not be read:\n" + "\n".join(broken))
        else:
            QMessageBox.information(self, "Backup created", f"Backed up {count} files to:\n{path}")
        return path

    def _choose_markdown_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose Markdown export folder", self.markdown_dir_edit.text())
        if path:
            self.markdown_dir_edit.setText(path)
            self.markdown_dir_edit.setCursorPosition(0)

    def _selection_color_changed(self, setting_key: str, index: int) -> None:
        combo = self.selection_color_combos[setting_key]
        if index == combo.count() - 1:
            return
        color = QColor(str(combo.itemData(index) or ""))
        if color.isValid():
            combo.setProperty("selectedColor", color.name())

    def _choose_selection_color(self, setting_key: str, index: int) -> None:
        combo = self.selection_color_combos[setting_key]
        if index != combo.count() - 1:
            return
        current = QColor(str(combo.property("selectedColor") or SELECTION_COLOR_SETTINGS[setting_key][1]))
        color = QColorDialog.getColor(current, self, "Choose default annotation color")
        if color.isValid():
            normalized = color.name()
            combo.setItemText(index, f"Custom color... ({normalized})")
            combo.setItemData(index, normalized)
            combo.setProperty("selectedColor", normalized)
            return
        previous = str(combo.property("selectedColor") or SELECTION_COLOR_SETTINGS[setting_key][1])
        previous_index = combo.findData(previous)
        if previous_index >= 0:
            with QSignalBlocker(combo):
                combo.setCurrentIndex(previous_index)

    @property
    def selected_theme(self) -> str:
        return str(self.theme_combo.currentData())

    @property
    def marker_radius(self) -> int:
        return int(self.marker_size_spin.value())

    @property
    def append_selection_shortcut(self) -> str:
        sequence = self.append_selection_shortcut_edit.keySequence().toString(QKeySequence.PortableText)
        return sequence or "Ctrl+Shift+C"

    @property
    def selection_shortcuts(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for setting_key, (_label, default_shortcut) in SELECTION_SHORTCUTS.items():
            sequence = self.selection_shortcut_edits[setting_key].keySequence().toString(QKeySequence.PortableText)
            values[setting_key] = sequence or default_shortcut
        return values

    @property
    def selection_colors(self) -> dict[str, str]:
        return {
            setting_key: str(combo.property("selectedColor"))
            for setting_key, combo in self.selection_color_combos.items()
        }

    @property
    def storage_dir(self) -> Path:
        value = self.storage_dir_edit.text().strip()
        return Path(value).expanduser() if value else default_data_dir()

    @property
    def markdown_dir(self) -> Path:
        value = self.markdown_dir_edit.text().strip()
        return Path(value).expanduser() if value else app_local_data_dir() / "markdown_notes"

    @property
    def wheel_scroll_lines(self) -> int:
        return int(self.wheel_scroll_lines_spin.value())

    @property
    def auto_save_current_note(self) -> bool:
        return self.auto_save_note_checkbox.isChecked()
