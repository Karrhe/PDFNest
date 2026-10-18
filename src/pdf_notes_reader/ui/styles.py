"""Application stylesheet. Colors come from the selected theme JSON file."""

from __future__ import annotations

APP_STYLESHEET_TEMPLATE = """
            QMainWindow {
                background: {colors["window"]};
                color: {colors["text"]};
            }
            QDialog {
                background: {colors["panel"]};
                color: {colors["text"]};
            }
            QToolBar {
                background: {colors["toolbar"]};
                border: 0;
                spacing: 8px;
                padding: 4px 8px;
            }
            QToolButton {
                background: transparent;
                border: 0;
                color: {colors["text"]};
                padding: 7px 10px;
            }
            QToolButton:hover {
                background: {colors["button_hover"]};
            }
            QToolButton:checked {
                background: {colors["button_hover"]};
                color: {colors["text"]};
                border-radius: 4px;
            }
            #DocumentTabStrip {
                background: {colors["toolbar"]};
                border-bottom: 1px solid {colors["border"]};
            }
            #DocumentTabBar {
                background: {colors["toolbar"]};
            }
            #DocumentTabBar::tab {
                background: transparent;
                border: 0;
                border-right: 1px solid {colors["border"]};
                color: {colors["text"]};
                min-width: 108px;
                max-width: 250px;
                padding: 8px 34px 8px 12px;
            }
            #DocumentTabBar::tab:selected {
                background: {colors["editor"]};
                border-bottom: 1px solid {colors["border"]};
            }
            #DocumentTabCloseButton {
                background: transparent;
                border: 0;
                min-width: 18px;
                max-width: 18px;
                min-height: 18px;
                max-height: 18px;
                padding: 0px;
            }
            #DocumentTabCloseButton:hover {
                background: {colors["button_hover"]};
                border: 1px solid {colors["border"]};
                border-radius: 9px;
            }
            #DocumentTabCloseButton:focus {
                background: {colors["button_hover"]};
                border: 1px solid {colors["selection"]};
                border-radius: 9px;
            }
            #OpenTabButton {
                background: transparent;
                border: 0;
                border-left: 1px solid {colors["border"]};
                border-radius: 0;
                min-height: 34px;
                padding: 0 14px;
                font-weight: 600;
            }
            #OpenTabButton:hover {
                background: {colors["button_hover"]};
            }
            #DocumentTitleBar {
                background: {colors["panel"]};
                border-bottom: 1px solid {colors["border"]};
            }
            #DocumentTitleCombo {
                background: {colors["editor"]};
                border: 1px solid {colors["border"]};
                border-radius: 3px;
                color: {colors["text"]};
                font-size: 12px;
                min-height: 22px;
                padding: 0 8px;
            }
            #DocumentTitleCombo::drop-down {
                background: {colors["button"]};
                border-left: 1px solid {colors["border"]};
                width: 24px;
            }
            #DocumentTitleCombo::down-arrow {
                image: url("{down_arrow_icon}");
                width: 9px;
                height: 9px;
            }
            #OutlineToggleButton {
                padding: 3px 8px;
            }
            #LibraryLeftPanel, #LibraryRightPanel {
                background: {colors["window"]};
            }
            #LibrarySidebarTitle {
                font-weight: 700;
            }
            #LibraryFolderTree {
                background: {colors["window"]};
                border: 0;
                outline: none;
            }
            #LibraryFolderTree::branch {
                width: 16px;
                height: 16px;
            }
            #LibraryFolderTree::branch:closed:has-children {
                image: none;
            }
            #LibraryFolderTree::branch:open:has-children {
                image: none;
            }
            #LibrarySearch {
                background: {colors["editor"]};
                border: 1px solid {colors["border"]};
                border-radius: 12px;
                min-height: 24px;
                padding: 2px 12px;
                color: {colors["text"]};
            }
            #HomeSettingsButton, #LibraryListModeButton, #LibraryIconModeButton {
                padding: 4px;
            }
            #LibraryListHeader {
                background: {colors["panel"]};
                border-top: 1px solid {colors["border"]};
                border-bottom: 1px solid {colors["border"]};
                min-height: 32px;
            }
            #LibraryListHeaderLabel {
                color: {colors["text"]};
                font-weight: 600;
            }
            #LibraryRow, #LibraryRowMissing {
                border-bottom: 1px solid {colors["border"]};
                min-height: 58px;
            }
            #LibraryRow:hover, #LibraryGridCard:hover {
                background: {colors["panel"]};
            }
            #LibraryRowMissing, #LibraryGridCardMissing {
                color: {colors["muted"]};
            }
            #LibraryRowCover {
                background: {colors["editor"]};
                border: 1px solid {colors["border"]};
            }
            #LibraryGridCard, #LibraryGridCardMissing {
                background: transparent;
                border: 1px solid {colors["border"]};
                border-radius: 4px;
            }
            #LibraryGridCover {
                background: {colors["editor"]};
                border: 1px solid {colors["border"]};
            }
            #LibraryGridTitle {
                font-family: "Segoe UI", "Microsoft YaHei UI";
                font-size: 13px;
                font-weight: 500;
            }
            #OutlineMoreButton::menu-indicator {
                image: none;
                width: 0px;
                height: 0px;
            }
            QLabel {
                color: {colors["text"]};
            }
            QScrollArea {
                background: {colors["window"]};
                border: 0;
            }
            QScrollArea > QWidget > QWidget {
                background: {colors["reader"]};
            }
            #ReaderViewport, #PagesContainer {
                background: {colors["reader"]};
            }
            #ReaderArea, #PageFooter, #OutlinePanel {
                background: {colors["reader"]};
            }
            #BottomPageLabel {
                font-weight: 600;
                padding: 0 4px;
            }
            #PageNavButton {
                min-width: 30px;
                max-width: 30px;
                min-height: 24px;
                padding: 0;
                font-weight: 700;
            }
            #OutlineTitle {
                font-size: 15px;
                font-weight: 700;
            }
            QTreeWidget {
                background: {colors["panel"]};
                border: 1px solid {colors["border"]};
                color: {colors["text"]};
                outline: none;
            }
            QTreeWidget::item {
                min-height: 22px;
                padding: 2px 4px;
                outline: none;
            }
            QTreeWidget::item:selected {
                background: {colors["button_hover"]};
                color: {colors["text"]};
                border: 1px solid {colors["selection"]};
            }
            QTreeWidget::item:focus {
                outline: none;
            }
            QSplitter::handle {
                background: {colors["border"]};
            }
            QSplitter::handle:horizontal {
                width: 1px;
            }
            QTabWidget::pane {
                border: 1px solid {colors["border"]};
                background: {colors["panel"]};
            }
            QTabBar::tab {
                background: {colors["button"]};
                padding: 7px 12px;
            }
            QTabBar::tab:selected {
                background: {colors["editor"]};
                color: {colors["text"]};
            }
            QPlainTextEdit, QTextBrowser {
                background: {colors["editor"]};
                border: 1px solid {colors["border"]};
                color: {colors["text"]};
                selection-background-color: {colors["selection"]};
                selection-color: {colors["text"]};
            }
            QPushButton {
                background: {colors["button"]};
                border: 1px solid {colors["border"]};
                border-radius: 4px;
                color: {colors["text"]};
                padding: 5px 10px;
            }
            QPushButton:hover {
                background: {colors["button_hover"]};
            }
            #CopyPathButton {
                background: {colors["editor"]};
                border: 1px solid {colors["border"]};
                border-radius: 3px;
                color: {colors["text"]};
                padding: 0px;
            }
            #CopyPathButton:hover {
                background: {colors["button_hover"]};
            }
            QPushButton:disabled {
                background: {colors["border"]};
                color: {colors["muted"]};
            }
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
                background: {colors["editor"]};
                border: 1px solid {colors["border"]};
                border-radius: 4px;
                color: {colors["text"]};
                min-height: 24px;
                padding: 2px 6px;
                selection-background-color: {colors["selection"]};
                selection-color: {colors["text"]};
            }
            QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                background: {colors["button"]};
                border-left: 1px solid {colors["border"]};
            }
            QComboBox::down-arrow {
                image: url("{down_arrow_icon}");
                width: 9px;
                height: 9px;
            }
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
                image: url("{up_arrow_icon}");
                width: 9px;
                height: 9px;
            }
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
                image: url("{down_arrow_icon}");
                width: 9px;
                height: 9px;
            }
            #HistoryTitle {
                font-size: 18px;
                font-weight: 700;
            }
            #HistoryHint, #HistoryRowMeta {
                color: {colors["muted"]};
            }
            #HistoryRow, #HistoryRowMissing {
                background: {colors["panel"]};
                border: 1px solid {colors["border"]};
                border-radius: 6px;
            }
            #HistoryRowMissing {
                background: {colors["panel"]};
                border-color: {colors["underline"]};
            }
            #HistoryRowTitle {
                font-family: "Segoe UI", "Microsoft YaHei UI";
                font-size: 14px;
                font-weight: 500;
            }
            #HistoryRowPath {
                color: {colors["text"]};
            }
            #HistoryEmpty {
                background: {colors["panel"]};
                border: 1px solid {colors["border"]};
                border-radius: 6px;
                padding: 20px;
            }
            """


def build_app_stylesheet(colors: dict[str, str], *, down_arrow_icon: str, up_arrow_icon: str) -> str:
    style = APP_STYLESHEET_TEMPLATE
    for key, value in colors.items():
        style = style.replace(f'{{colors["{key}"]}}', value)
    style = style.replace("{down_arrow_icon}", down_arrow_icon)
    return style.replace("{up_arrow_icon}", up_arrow_icon)
