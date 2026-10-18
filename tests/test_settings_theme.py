from gui_helpers import GuiTestCase  # noqa: I001 - sets sys.path and offscreen Qt first

import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import QLabel, QDialog, QToolBar, QToolButton
from pdf_notes_reader.main import MainWindow, SettingsDialog
from pdf_notes_reader.settings import load_settings, load_theme_files, save_settings, themes_dir


class SettingsThemeTest(GuiTestCase):
    def test_reader_blank_area_uses_beige_palette(self) -> None:
        window = MainWindow()
        beige = "#f0ead8"
        self.assertEqual(window.scroll_area.viewport().palette().color(window.scroll_area.viewport().backgroundRole()).name(), beige)
        self.assertEqual(window.pages_container.palette().color(window.pages_container.backgroundRole()).name(), beige)
        window.close()

    def test_app_branding_and_theme_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(Path(tmp) / "data")
            window = MainWindow()
            try:
                self.assertEqual(window.windowTitle(), "PDFNest")
                self.assertFalse(window.windowIcon().isNull())

                window.theme_name = "white"
                window.settings["theme"] = "white"
                window.apply_theme()
                self.assertEqual(
                    window.scroll_area.viewport().palette().color(window.scroll_area.viewport().backgroundRole()).name(),
                    "#e5e7eb",
                )
                self.assertIn("white", window.themes)
                self.assertTrue((themes_dir(Path(tmp) / "data") / "white.json").exists())
            finally:
                window.close()

    def test_settings_store_marker_size_without_embedded_themes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(data_dir)
            window = MainWindow()
            try:
                window.note_marker_radius = 13
                window.settings["note_marker_radius"] = 13
                window.settings["theme"] = "white"
                window.settings["wheel_scroll_lines"] = 9
                window.settings["auto_save_current_note"] = False
                window.settings["window_width"] = 900
                window.settings["window_height"] = 700
                window.settings["window_maximized"] = True
                window.settings["markdown_export_dir"] = str(data_dir / "md")
                save_settings(window.settings)

                settings = load_settings()
                self.assertEqual(settings["note_marker_radius"], 13)
                self.assertEqual(settings["theme"], "white")
                self.assertEqual(settings["wheel_scroll_lines"], 9)
                self.assertFalse(settings["auto_save_current_note"])
                self.assertEqual(settings["window_width"], 900)
                self.assertEqual(settings["window_height"], 700)
                self.assertTrue(settings["window_maximized"])
                self.assertEqual(settings["markdown_export_dir"], str(data_dir / "md"))
                self.assertNotIn("themes", settings)
                self.assertIn("beige", load_theme_files())
                self.assertTrue((data_dir / "themes" / "beige.json").exists())
                custom_theme = data_dir / "themes" / "ocean.json"
                custom_theme.write_text('{"reader": "#ffffff", "window": "#ffffff"}\n', encoding="utf-8")
                self.assertIn("ocean", load_theme_files())
            finally:
                window.close()

    def test_settings_dialog_uses_theme_and_hides_theme_file_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(data_dir)
            window = MainWindow()
            dialog = SettingsDialog(
                settings=window.settings,
                themes=window.themes,
                data_dir=data_dir,
                note_json_path=None,
                markdown_dir=data_dir / "markdown_notes",
                theme_dir=themes_dir(data_dir),
                parent=window,
            )
            try:
                dialog.setStyleSheet(window.styleSheet())
                dialog.append_selection_shortcut_edit.setKeySequence(QKeySequence("Alt+C"))
                dialog.selection_shortcut_edits["highlight_selection_shortcut"].setKeySequence(QKeySequence("Alt+H"))
                color_combo = dialog.selection_color_combos["highlight_selection_color"]
                custom_index = color_combo.count() - 1
                color_combo.setCurrentIndex(custom_index)
                with patch("pdf_notes_reader.ui.settings_dialog.QColorDialog.getColor", return_value=QColor("#123456")):
                    dialog._choose_selection_color("highlight_selection_color", custom_index)
                dialog.wheel_scroll_lines_spin.setValue(11)
                dialog.auto_save_note_checkbox.setChecked(False)
                dialog.markdown_dir_edit.setText(str(data_dir / "custom-md"))
                labels = [label.text() for label in dialog.findChildren(QLabel)]
                categories = [
                    dialog.category_list.topLevelItem(index).text(0)
                    for index in range(dialog.category_list.topLevelItemCount())
                ]
                self.assertIn("QDialog", window.styleSheet())
                self.assertNotIn("Theme files", labels)
                self.assertIn("Theme folder", labels)
                self.assertIn("Page display", categories)
                self.assertIn("Storage", categories)
                self.assertIn("Annotation colors", categories)
                self.assertEqual(dialog.append_selection_shortcut, "Alt+C")
                self.assertEqual(dialog.selection_shortcuts["highlight_selection_shortcut"], "Alt+H")
                self.assertEqual(dialog.selection_colors["highlight_selection_color"], "#123456")
                self.assertEqual(
                    [color_combo.itemText(index).split(" (")[0] for index in range(color_combo.count())],
                    ["Yellow", "Green", "Blue", "Pink", "Red", "Purple", "Custom color..."],
                )
                self.assertEqual(dialog.wheel_scroll_lines, 11)
                self.assertEqual(dialog.markdown_dir, data_dir / "custom-md")
                self.assertLessEqual(dialog.storage_dir_edit.maximumWidth(), 420)
                self.assertEqual(dialog.storage_dir_edit.alignment() & Qt.AlignHorizontal_Mask, Qt.AlignLeft)
                self.assertEqual(dialog.markdown_dir_edit.alignment() & Qt.AlignHorizontal_Mask, Qt.AlignLeft)
                self.assertEqual(dialog.storage_dir_edit.cursorPosition(), 0)
                self.assertTrue(any(button.objectName() == "CopyPathButton" for button in dialog.findChildren(QToolButton)))
                path_labels = dialog.findChildren(QLabel, "SettingsPathLabel")
                self.assertTrue(path_labels)
                self.assertTrue(all(label.minimumWidth() == label.maximumWidth() == 160 for label in path_labels))
                self.assertFalse(dialog.auto_save_current_note)
            finally:
                dialog.close()
                window.close()

    def test_white_theme_keeps_selected_text_readable_and_uses_branch_arrows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            os.environ["PDF_NOTES_READER_DATA_DIR"] = str(data_dir)
            window = MainWindow()
            try:
                window.theme_name = "white"
                window.apply_theme()
                stylesheet = window.styleSheet()
                self.assertIn("selection-color:", stylesheet)
                self.assertIn("#LibraryFolderTree::branch", stylesheet)
                self.assertIn("width: 16px", stylesheet)
                self.assertIn("image: none", stylesheet)
                self.assertNotIn("tree-open.png", stylesheet)
                self.assertNotIn("tree-closed.png", stylesheet)
                self.assertIn("outline: none", stylesheet)
                self.assertIn("down-arrow.png", stylesheet)
                self.assertIn("up-arrow.png", stylesheet)
                self.assertIn("QComboBox::down-arrow", stylesheet)
                self.assertIn("QSpinBox::up-arrow", stylesheet)
            finally:
                window.close()

    def test_toolbar_no_longer_exposes_mode_zoom_or_settings_controls(self) -> None:
        window = MainWindow()
        try:
            action_texts = [action.text() for toolbar in window.findChildren(QToolBar) for action in toolbar.actions()]
            self.assertEqual(window.document_tab_bar.tabText(0), "Home")
            self.assertEqual(window.open_tab_button.text(), "+ Open")
            self.assertFalse(window.document_title_bar.isVisible())
            self.assertEqual(window.outline_toggle_button.text(), "Contents")
            self.assertEqual(window.history_panel.settings_button.text(), "")
            self.assertFalse(window.history_panel.settings_button.icon().isNull())
            self.assertNotIn("Continuous Scroll", action_texts)
            self.assertNotIn("Zoom In", action_texts)
            self.assertNotIn("Zoom Out", action_texts)
            self.assertNotIn("Settings", action_texts)
        finally:
            window.close()

    def test_pdf_file_picker_uses_non_native_dialog(self) -> None:
        calls: dict[str, object] = {}

        class FakeFileDialog:
            ExistingFile = 1
            DontUseNativeDialog = 2

            def __init__(self, parent, title, directory, name_filter) -> None:
                calls["parent"] = parent
                calls["title"] = title
                calls["directory"] = directory
                calls["name_filter"] = name_filter
                self.options: list[tuple[int, bool]] = []

            def setFileMode(self, mode: int) -> None:
                calls["file_mode"] = mode

            def setNameFilter(self, name_filter: str) -> None:
                calls["set_name_filter"] = name_filter

            def setOption(self, option: int, enabled: bool) -> None:
                self.options.append((option, enabled))
                calls["options"] = self.options

            def setWindowModality(self, modality) -> None:
                calls["modality"] = modality

            def exec(self) -> int:
                return QDialog.Accepted

            def selectedFiles(self) -> list[str]:
                return ["chosen.pdf"]

        window = MainWindow()
        try:
            with patch("pdf_notes_reader.ui.main_window.QFileDialog", FakeFileDialog):
                self.assertEqual(window._choose_pdf_file("Open PDF"), "chosen.pdf")
            self.assertEqual(calls["title"], "Open PDF")
            self.assertEqual(calls["file_mode"], FakeFileDialog.ExistingFile)
            self.assertIn((FakeFileDialog.DontUseNativeDialog, True), calls["options"])
            self.assertEqual(calls["modality"], Qt.ApplicationModal)
        finally:
            window.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
