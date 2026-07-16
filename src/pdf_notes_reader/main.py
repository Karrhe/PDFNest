from __future__ import annotations

import hashlib
import html
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import fitz
import markdown
from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QSignalBlocker, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPalette, QPen, QPixmap, QShortcut
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
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QDoubleSpinBox,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdf_notes_reader.history import (
    PdfHistoryEntry,
    find_history_entry,
    load_history,
    remove_history_entry,
    save_history,
    upsert_history_entry,
)
from pdf_notes_reader.library import (
    LibraryFolder,
    LibraryState,
    UNFILED_FOLDER_ID,
    load_library,
    save_library,
)
from pdf_notes_reader.notes import (
    Bookmark,
    Note,
    app_local_data_dir,
    default_data_dir,
    find_note,
    load_notes_data,
    notebook_dir_for_key,
    notes_path_for_key,
    pdf_key_for_path,
    save_notes,
    utc_now,
)
from pdf_notes_reader.settings import (
    clamp_marker_radius,
    clamp_window_dimension,
    clamp_wheel_scroll_lines,
    load_settings,
    load_theme_files,
    save_settings,
    settings_path,
    themes_dir,
)
from pdf_notes_reader.storage_migration import migrate_storage


APP_TITLE = "PDFNest"


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


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", *, mode: Qt.TextElideMode = Qt.ElideRight) -> None:
        super().__init__()
        self._full_text = ""
        self._elide_mode = mode
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        self._full_text = text
        self.setToolTip(text)
        self._refresh_elided_text()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._refresh_elided_text()

    def _refresh_elided_text(self) -> None:
        available_width = max(0, self.width() - 2)
        if available_width <= 0:
            super().setText(self._full_text)
            return
        super().setText(self.fontMetrics().elidedText(self._full_text, self._elide_mode, available_width))


class LibraryFolderTree(QTreeWidget):
    folder_drop_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(QPen(QColor(58, 58, 58), 1, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
        item = self.topLevelItem(0)
        while item is not None:
            if item.childCount():
                rect = self.visualItemRect(item)
                if rect.isValid() and rect.intersects(event.rect()):
                    x = max(3, rect.left() - 14)
                    cy = rect.center().y()
                    if item.isExpanded():
                        painter.drawLine(x, cy - 2, x + 4, cy + 2)
                        painter.drawLine(x + 4, cy + 2, x + 8, cy - 2)
                    else:
                        painter.drawLine(x + 2, cy - 4, x + 6, cy)
                        painter.drawLine(x + 6, cy, x + 2, cy + 4)
            item = self.itemBelow(item)
        painter.end()

ANNOTATION_COLORS = [
    ("Yellow", "#fde047"),
    ("Green", "#86efac"),
    ("Blue", "#93c5fd"),
    ("Pink", "#f9a8d4"),
    ("Red", "#fca5a5"),
    ("Purple", "#c4b5fd"),
]
EXCERPT_MARKER_COLOR = "#2563eb"
EXCERPT_MARKER_STYLES = {
    "dashed_underline": "Dashed underline",
    "highlight": "Highlight",
    "underline": "Underline",
}
SELECTION_SHORTCUTS = {
    "highlight_selection_shortcut": ("Highlight selection", "Ctrl+H"),
    "underline_selection_shortcut": ("Underline selection", "Ctrl+U"),
    "append_highlight_selection_shortcut": ("Add selection to note as highlight", "Ctrl+Shift+H"),
    "append_underline_selection_shortcut": ("Add selection to note as underline", "Ctrl+Shift+U"),
}
SELECTION_COLOR_SETTINGS = {
    "append_selection_color": ("Add selection to current note", "#93c5fd"),
    "highlight_selection_color": ("Highlight selection", "#fca5a5"),
    "underline_selection_color": ("Underline selection", "#fca5a5"),
    "append_highlight_selection_color": ("Add to note as highlight", "#93c5fd"),
    "append_underline_selection_color": ("Add to note as underline", "#93c5fd"),
}


def app_resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    candidate = base.joinpath(*parts)
    if candidate.exists():
        return candidate
    return Path(__file__).resolve().parents[2].joinpath(*parts)


def pic_icon(name: str) -> QIcon:
    path = app_resource_path("Pic", name)
    return QIcon(str(path)) if path.exists() else QIcon()


MATH_BLOCK_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
MATH_INLINE_RE = re.compile(r"(?<!\\)\$(?!\$)(.+?)(?<!\\)\$", re.DOTALL)
CODE_SEGMENT_RE = re.compile(r"(```.*?```|`[^`\n]+`)", re.DOTALL)

LATEX_SYMBOLS = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "varepsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "vartheta": "θ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "phi": "φ",
    "varphi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
    "times": "×",
    "cdot": "·",
    "pm": "±",
    "le": "≤",
    "leq": "≤",
    "ge": "≥",
    "geq": "≥",
    "neq": "≠",
    "approx": "≈",
    "infty": "∞",
    "sum": "∑",
    "prod": "∏",
    "int": "∫",
    "partial": "∂",
    "nabla": "∇",
    "rightarrow": "→",
    "to": "→",
    "leftarrow": "←",
    "Rightarrow": "⇒",
    "Leftarrow": "⇐",
}


LATEX_SYMBOLS = {
    "alpha": "\u03b1",
    "beta": "\u03b2",
    "gamma": "\u03b3",
    "delta": "\u03b4",
    "epsilon": "\u03b5",
    "varepsilon": "\u03b5",
    "zeta": "\u03b6",
    "eta": "\u03b7",
    "theta": "\u03b8",
    "vartheta": "\u03b8",
    "lambda": "\u03bb",
    "mu": "\u03bc",
    "nu": "\u03bd",
    "xi": "\u03be",
    "pi": "\u03c0",
    "rho": "\u03c1",
    "sigma": "\u03c3",
    "tau": "\u03c4",
    "phi": "\u03c6",
    "varphi": "\u03c6",
    "chi": "\u03c7",
    "psi": "\u03c8",
    "omega": "\u03c9",
    "Gamma": "\u0393",
    "Delta": "\u0394",
    "Theta": "\u0398",
    "Lambda": "\u039b",
    "Xi": "\u039e",
    "Pi": "\u03a0",
    "Sigma": "\u03a3",
    "Phi": "\u03a6",
    "Psi": "\u03a8",
    "Omega": "\u03a9",
    "times": "\u00d7",
    "cdot": "\u00b7",
    "pm": "\u00b1",
    "le": "\u2264",
    "leq": "\u2264",
    "ge": "\u2265",
    "geq": "\u2265",
    "neq": "\u2260",
    "approx": "\u2248",
    "infty": "\u221e",
    "sum": "\u2211",
    "prod": "\u220f",
    "int": "\u222b",
    "partial": "\u2202",
    "nabla": "\u2207",
    "rightarrow": "\u2192",
    "to": "\u2192",
    "leftarrow": "\u2190",
    "Rightarrow": "\u21d2",
    "Leftarrow": "\u21d0",
}


def latex_to_html(expression: str) -> str:
    compiled = html.escape(expression.strip())
    compiled = compiled.replace(r"\left", "").replace(r"\right", "")

    frac_re = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
    sqrt_re = re.compile(r"\\sqrt\{([^{}]+)\}")
    for _ in range(10):
        next_compiled = frac_re.sub(r'<span class="latex-frac"><span>\1</span><span>\2</span></span>', compiled)
        next_compiled = sqrt_re.sub(r'<span class="latex-sqrt">√<span>\1</span></span>', next_compiled)
        if next_compiled == compiled:
            break
        compiled = next_compiled

    symbol_pattern = re.compile(
        r"\\(" + "|".join(re.escape(key) for key in sorted(LATEX_SYMBOLS, key=len, reverse=True)) + r")(?=$|[^A-Za-z])"
    )
    compiled = symbol_pattern.sub(lambda match: LATEX_SYMBOLS[match.group(1)], compiled)
    compiled = re.sub(r"\^\{([^{}]+)\}", r"<sup>\1</sup>", compiled)
    compiled = re.sub(r"_\{([^{}]+)\}", r"<sub>\1</sub>", compiled)
    compiled = re.sub(r"\^([A-Za-z0-9+\-=])", r"<sup>\1</sup>", compiled)
    compiled = re.sub(r"_([A-Za-z0-9+\-=])", r"<sub>\1</sub>", compiled)
    compiled = compiled.replace("\u0104\u0116", "\u221a")
    compiled = compiled.replace(r"\,", " ").replace(r"\;", " ").replace(r"\ ", " ")
    return compiled


def protect_code_segments(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = f"@@PDF_NOTES_CODE_{len(protected)}@@"
        protected[token] = match.group(0)
        return token

    return CODE_SEGMENT_RE.sub(replace, text), protected


def restore_placeholders(text: str, placeholders: dict[str, str]) -> str:
    restored = text
    for token, value in placeholders.items():
        restored = restored.replace(token, value)
    return restored


def render_markdown_preview(text: str) -> str:
    placeholders: dict[str, str] = {}
    block_tokens: set[str] = set()
    prepared, protected_code = protect_code_segments(text)

    def replace_block(match: re.Match[str]) -> str:
        token = f"@@PDF_NOTES_MATH_BLOCK_{len(placeholders)}@@"
        formula = latex_to_html(match.group(1))
        placeholders[token] = (
            '<table class="math-block" cellspacing="0" cellpadding="0">'
            f"<tr><td>{formula}</td></tr>"
            "</table>"
        )
        block_tokens.add(token)
        return token

    def replace_inline(match: re.Match[str]) -> str:
        token = f"@@PDF_NOTES_MATH_INLINE_{len(placeholders)}@@"
        formula = latex_to_html(match.group(1))
        placeholders[token] = f'<span class="math-inline">{formula}</span>'
        return token

    prepared = MATH_BLOCK_RE.sub(replace_block, prepared)
    prepared = MATH_INLINE_RE.sub(replace_inline, prepared)
    standalone_symbol_re = re.compile(
        r"\\(" + "|".join(re.escape(key) for key in sorted(LATEX_SYMBOLS, key=len, reverse=True)) + r")(?=$|[^A-Za-z])"
    )
    prepared = standalone_symbol_re.sub(lambda match: LATEX_SYMBOLS[match.group(1)], prepared)
    prepared = restore_placeholders(prepared, protected_code)
    body = markdown.markdown(
        prepared,
        extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
    )
    for token in block_tokens:
        body = body.replace(f"<p>{token}</p>", placeholders[token])
    for token, rendered in placeholders.items():
        body = body.replace(token, rendered)

    return f"""
    <html>
      <head>
        <style>
          body {{
            color: #2f2a1f;
            font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            font-size: 14px;
            line-height: 1.55;
          }}
          p {{
            margin: 0 0 8px 0;
          }}
          code {{
            background: #eee5cf;
            border: 1px solid #d6c9aa;
            border-radius: 4px;
            font-family: Consolas, "Courier New", monospace;
            padding: 1px 4px;
          }}
          pre {{
            background: #f4ecd9;
            border: 1px solid #d6c9aa;
            border-radius: 6px;
            padding: 10px;
            white-space: pre-wrap;
          }}
          pre code {{
            background: transparent;
            border: 0;
            padding: 0;
          }}
          blockquote {{
            border-left: 4px solid #b89b57;
            color: #5f5644;
            margin: 10px 0;
            padding: 4px 12px;
            background: #f5eedc;
          }}
          table {{
            border-collapse: collapse;
          }}
          th, td {{
            border: 1px solid #d6c9aa;
            padding: 4px 8px;
          }}
          .math-inline {{
            color: #7a4d00;
            font-family: Cambria Math, Times New Roman, serif;
          }}
          .latex-frac {{
            display: inline-flex;
            flex-direction: column;
            font-size: 0.9em;
            line-height: 1.05;
            margin: 0 2px;
            text-align: center;
            vertical-align: middle;
          }}
          .latex-frac span:first-child {{
            border-bottom: 1px solid #7a4d00;
            padding: 0 3px;
          }}
          .latex-frac span:last-child {{
            padding: 0 3px;
          }}
          .latex-sqrt span {{
            border-top: 1px solid #7a4d00;
            padding-left: 2px;
          }}
          .math-block {{
            border-collapse: collapse;
            background: #f8f0dc;
            border: 1px solid #d6c9aa;
            color: #7a4d00;
            font-family: Cambria Math, Times New Roman, serif;
            line-height: 1.2;
            margin: 0 0 4px 0;
            text-align: center;
            width: 100%;
          }}
          .math-block td {{
            border: 0;
            padding: 1px 6px;
          }}
        </style>
      </head>
      <body>{body}</body>
    </html>
    """


class PdfCanvas(QWidget):
    add_note_requested = Signal(int, float, float)
    append_selection_requested = Signal(int, list, str)
    annotation_requested = Signal(int, str, list, str, str)
    bookmark_requested = Signal(int)
    fit_requested = Signal(str)
    mode_requested = Signal(str)
    note_selected = Signal(str)
    note_color_requested = Signal(str, str)
    note_style_requested = Signal(str, str)
    note_delete_requested = Signal(str)
    reset_note_counters_requested = Signal()
    settings_requested = Signal()
    zoom_requested = Signal(float)

    def __init__(self, page_index: int = 0) -> None:
        super().__init__()
        self.page_index = page_index
        self._pixmap: QPixmap | None = None
        self._page_size = QSize(640, 480)
        self._notes: list[Note] = []
        self._text_words: list[dict[str, object]] = []
        self._selection_start: QPoint | None = None
        self._selection_end: QPoint | None = None
        self._selected_rects_norm: list[list[float]] = []
        self._selected_text = ""
        self._marker_radius = 7
        self._continuous_scroll = True
        self._theme_colors: dict[str, str] = {
            "pdf_tint": "#f3ecd6",
            "note_marker": "#e11d48",
            "highlight": "#fde68a",
            "underline": "#2563eb",
            "text_selection": "#bfdbfe",
        }
        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_page(
        self,
        pixmap: QPixmap | None,
        notes: list[Note],
        display_size: QSize | None = None,
        text_words: list[dict[str, object]] | None = None,
    ) -> None:
        self._pixmap = pixmap
        self._notes = notes
        self._text_words = text_words or []
        self.clear_selection()
        if pixmap is None:
            self._page_size = QSize(640, 480)
        else:
            self._page_size = display_size or pixmap.deviceIndependentSize().toSize()
        self.setFixedSize(self._page_size)
        self.update()

    def set_notes(self, notes: list[Note]) -> None:
        """Refresh annotation overlays without recreating or rerasterizing the page."""
        self._notes = notes
        self.update()

    def clear_selection(self) -> None:
        self._selection_start = None
        self._selection_end = None
        self._selected_rects_norm = []
        self._selected_text = ""

    def set_context_state(self, *, continuous_scroll: bool) -> None:
        self._continuous_scroll = continuous_scroll

    def set_theme_colors(self, colors: dict[str, str]) -> None:
        self._theme_colors.update(colors)
        self.update()

    def set_marker_radius(self, radius: int) -> None:
        self._marker_radius = max(3, min(24, int(radius)))
        self.update()

    def render_device_pixel_ratio(self) -> float:
        if self._pixmap is None:
            return 1.0
        return self._pixmap.devicePixelRatio()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._theme_colors.get("pdf_tint", "#f3ecd6")))

        if self._pixmap is None:
            painter.setPen(QColor("#6f6653"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Open a PDF to begin")
            return

        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(self.rect(), self._pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_Multiply)
        painter.fillRect(self.rect(), QColor(self._theme_colors.get("pdf_tint", "#f3ecd6")))
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.Antialiasing, True)

        for note in self._notes:
            if note.note_type not in {"highlight", "underline", "excerpt"}:
                continue
            for rect in note.rects_norm:
                page_rect = self._norm_rect_to_page(rect)
                if note.note_type == "highlight":
                    color = QColor(note.color or self._theme_colors.get("highlight", "#fde68a"))
                    self._fill_highlight(painter, page_rect, color)
                elif note.note_type == "underline":
                    pen = QPen(QColor(note.color or self._theme_colors.get("underline", "#2563eb")), 2)
                    painter.setPen(pen)
                    y = page_rect.bottom() - 1
                    painter.drawLine(page_rect.left(), y, page_rect.right(), y)
                elif note.marker_style == "highlight":
                    color = QColor(note.color or EXCERPT_MARKER_COLOR)
                    self._fill_highlight(painter, page_rect, color)
                elif note.marker_style == "underline":
                    pen = QPen(QColor(note.color or EXCERPT_MARKER_COLOR), 2)
                    painter.setPen(pen)
                    y = page_rect.bottom() - 1
                    painter.drawLine(page_rect.left(), y, page_rect.right(), y)
                else:
                    # A dashed underline identifies text copied into the current note.
                    pen = QPen(QColor(note.color or EXCERPT_MARKER_COLOR), 2, Qt.DashLine)
                    painter.setPen(pen)
                    y = page_rect.bottom() - 1
                    painter.drawLine(page_rect.left(), y, page_rect.right(), y)

        for rect in self._selection_rects():
            color = QColor(self._theme_colors.get("text_selection", "#bfdbfe"))
            color.setAlpha(120)
            painter.fillRect(rect, color)

        for note in self._notes:
            if note.note_type != "point":
                continue
            center = self._note_center(note)
            painter.setBrush(QColor(note.color or self._theme_colors.get("note_marker", "#e11d48")))
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawEllipse(center, self._marker_radius, self._marker_radius)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._pixmap is None or not self._inside_page(event.pos()):
            return

        target_note = self._note_at(event.pos())
        menu = QMenu(self)
        add_action = QAction("Add note", self)
        add_bookmark_action = QAction("Add bookmark", self)
        reset_note_numbers_action = QAction("Reset note numbering", self)
        copy_action = QAction("Copy selected text", self)
        append_selection_action = QAction("Add selected text to current note", self)
        open_note_action = QAction("Open note", self)
        delete_note_action = QAction("Delete annotation" if target_note and target_note.note_type != "point" else "Delete note", self)
        fit_width_action = QAction("Fit width", self)
        fit_height_action = QAction("Fit height", self)
        continuous_action = QAction("Continuous scroll", self)
        single_page_action = QAction("Single page", self)
        settings_action = QAction("Settings", self)
        continuous_action.setCheckable(True)
        single_page_action.setCheckable(True)
        continuous_action.setChecked(self._continuous_scroll)
        single_page_action.setChecked(not self._continuous_scroll)

        note_color_actions: dict[QAction, str] = {}
        note_style_actions: dict[QAction, str] = {}
        highlight_actions: dict[QAction, str] = {}
        underline_actions: dict[QAction, str] = {}

        if self._selected_text:
            highlight_menu = menu.addMenu("Highlight selection")
            underline_menu = menu.addMenu("Underline selection")
            for label, color in ANNOTATION_COLORS:
                highlight_action = QAction(label, self)
                underline_action = QAction(label, self)
                highlight_menu.addAction(highlight_action)
                underline_menu.addAction(underline_action)
                highlight_actions[highlight_action] = color
                underline_actions[underline_action] = color
            menu.addSeparator()
            menu.addAction(copy_action)
            menu.addAction(append_selection_action)
            menu.addSeparator()

        if target_note is not None:
            menu.addAction(open_note_action)
            color_menu = menu.addMenu("Change color")
            for label, color in ANNOTATION_COLORS:
                action = QAction(label, self)
                color_menu.addAction(action)
                note_color_actions[action] = color
            custom_action = QAction("Custom color...", self)
            color_menu.addAction(custom_action)
            note_color_actions[custom_action] = ""
            if target_note.note_type in {"excerpt", "highlight", "underline"}:
                style_menu = menu.addMenu("Change marker style" if target_note.note_type == "excerpt" else "Change annotation style")
                available_styles = EXCERPT_MARKER_STYLES if target_note.note_type == "excerpt" else {
                    "highlight": "Highlight",
                    "underline": "Underline",
                }
                current_style = target_note.marker_style if target_note.note_type == "excerpt" else target_note.note_type
                for style, label in available_styles.items():
                    action = QAction(label, self)
                    action.setCheckable(True)
                    action.setChecked(current_style == style)
                    style_menu.addAction(action)
                    note_style_actions[action] = style
            menu.addAction(delete_note_action)
            menu.addSeparator()

        menu.addAction(add_action)
        menu.addAction(add_bookmark_action)
        menu.addAction(reset_note_numbers_action)
        menu.addSeparator()
        menu.addAction(fit_width_action)
        menu.addAction(fit_height_action)
        menu.addSeparator()
        menu.addAction(continuous_action)
        menu.addAction(single_page_action)
        menu.addSeparator()
        menu.addAction(settings_action)
        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        if chosen == open_note_action and target_note is not None:
            self.note_selected.emit(target_note.linked_note_id or target_note.id)
        elif chosen == delete_note_action and target_note is not None:
            self.note_delete_requested.emit(target_note.id)
        elif chosen in note_color_actions and target_note is not None:
            color = note_color_actions[chosen]
            if not color:
                picked = QColorDialog.getColor(QColor(target_note.color or self._theme_colors.get("note_marker", "#e11d48")), self, "Choose annotation color")
                if not picked.isValid():
                    return
                color = picked.name()
            self.note_color_requested.emit(target_note.id, color)
        elif chosen in note_style_actions and target_note is not None:
            self.note_style_requested.emit(target_note.id, note_style_actions[chosen])
        elif chosen == add_action:
            x_norm, y_norm = self._point_to_norm(event.pos())
            self.add_note_requested.emit(self.page_index, x_norm, y_norm)
        elif chosen == add_bookmark_action:
            self.bookmark_requested.emit(self.page_index)
        elif chosen == reset_note_numbers_action:
            self.reset_note_counters_requested.emit()
        elif chosen == copy_action:
            self.copy_selected_text()
        elif chosen == append_selection_action:
            selected_rects = [list(rect) for rect in self._selected_rects_norm]
            selected_text = self._selected_text
            self.append_selection_requested.emit(self.page_index, selected_rects, selected_text)
            self.clear_selection()
            self.update()
        elif chosen in highlight_actions:
            selected_rects = [list(rect) for rect in self._selected_rects_norm]
            selected_text = self._selected_text
            self.annotation_requested.emit(self.page_index, "highlight", selected_rects, selected_text, highlight_actions[chosen])
            self.clear_selection()
            self.update()
        elif chosen in underline_actions:
            selected_rects = [list(rect) for rect in self._selected_rects_norm]
            selected_text = self._selected_text
            self.annotation_requested.emit(self.page_index, "underline", selected_rects, selected_text, underline_actions[chosen])
            self.clear_selection()
            self.update()
        elif chosen == fit_width_action:
            self.fit_requested.emit("width")
        elif chosen == fit_height_action:
            self.fit_requested.emit("height")
        elif chosen == continuous_action:
            self.mode_requested.emit("continuous")
        elif chosen == single_page_action:
            self.mode_requested.emit("single")
        elif chosen == settings_action:
            self.settings_requested.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() != Qt.LeftButton or self._pixmap is None:
            return

        note = self._note_at(event.pos())
        if note is not None:
            self.note_selected.emit(note.linked_note_id or note.id)
            event.accept()
            return

        if self._inside_page(event.pos()):
            self.setFocus(Qt.MouseFocusReason)
            self._selection_start = event.pos()
            self._selection_end = event.pos()
            self._selected_rects_norm = []
            self._selected_text = ""
            self.update()
            event.accept()
            return

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._selection_start is None or self._pixmap is None:
            return
        self._selection_end = self._clamp_point_to_page(event.pos())
        self._update_text_selection()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() != Qt.LeftButton or self._selection_start is None:
            return
        self._selection_end = self._clamp_point_to_page(event.pos())
        self._update_text_selection()
        if not self._selected_text:
            self.clear_selection()
        self.update()
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.modifiers() & Qt.ControlModifier and event.key() in (Qt.Key_C, Qt.Key_V):
            self.copy_selected_text()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_selected_text(self) -> None:
        if self._selected_text:
            QApplication.clipboard().setText(self._selected_text)
            self.clear_selection()
            self.update()

    def selected_text(self) -> str:
        return self._selected_text

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_requested.emit(0.1 if event.angleDelta().y() > 0 else -0.1)
            event.accept()
            return
        super().wheelEvent(event)

    def _inside_page(self, point: QPoint) -> bool:
        if self._pixmap is None:
            return False
        return 0 <= point.x() < self._page_size.width() and 0 <= point.y() < self._page_size.height()

    @staticmethod
    def _fill_highlight(painter: QPainter, rect, color: QColor) -> None:
        """Tint the page while preserving dark glyph contrast beneath the fill."""
        fill = QColor(color)
        fill.setAlpha(105)
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_Multiply)
        painter.fillRect(rect, fill)
        painter.restore()

    def _point_to_norm(self, point: QPoint) -> tuple[float, float]:
        if self._pixmap is None or self._page_size.width() == 0 or self._page_size.height() == 0:
            return 0.0, 0.0
        return point.x() / self._page_size.width(), point.y() / self._page_size.height()

    def _norm_rect_to_page(self, rect: list[float]) -> QRectF:
        return QRectF(
            rect[0] * self._page_size.width(),
            rect[1] * self._page_size.height(),
            (rect[2] - rect[0]) * self._page_size.width(),
            (rect[3] - rect[1]) * self._page_size.height(),
        )

    def _page_rect_to_norm(self, rect: QRectF) -> list[float]:
        if self._page_size.width() == 0 or self._page_size.height() == 0:
            return [0.0, 0.0, 0.0, 0.0]
        return [
            rect.left() / self._page_size.width(),
            rect.top() / self._page_size.height(),
            rect.right() / self._page_size.width(),
            rect.bottom() / self._page_size.height(),
        ]

    def _clamp_point_to_page(self, point: QPoint) -> QPoint:
        return QPoint(
            max(0, min(point.x(), max(0, self._page_size.width() - 1))),
            max(0, min(point.y(), max(0, self._page_size.height() - 1))),
        )

    def _selection_rect(self) -> QRectF | None:
        if self._selection_start is None or self._selection_end is None:
            return None
        return QRectF(self._selection_start, self._selection_end).normalized()

    def _selection_rects(self) -> list[QRectF]:
        return [self._norm_rect_to_page(rect) for rect in self._selected_rects_norm]

    def _update_text_selection(self) -> None:
        if self._selection_start is None or self._selection_end is None:
            return

        ordered_words = sorted(self._text_words, key=self._word_sort_key)
        if not ordered_words:
            self._selected_rects_norm = []
            self._selected_text = ""
            return

        line_groups = self._word_line_groups(ordered_words)
        start_endpoint = self._selection_endpoint(self._selection_start, line_groups)
        end_endpoint = self._selection_endpoint(self._selection_end, line_groups)
        first_index, last_index = self._selection_word_bounds(start_endpoint, end_endpoint)
        if first_index >= last_index:
            self._selected_rects_norm = []
            self._selected_text = ""
            return

        selected = ordered_words[first_index:last_index]
        self._selected_rects_norm = self._merge_word_rects_by_line(selected)
        self._selected_text = self._join_selected_words(selected)

    @staticmethod
    def _word_sort_key(word: dict[str, object]) -> tuple[int, int, int]:
        return (int(word["block"]), int(word["line"]), int(word["word_no"]))

    @staticmethod
    def _word_line_groups(words: list[dict[str, object]]) -> list[tuple[int, list[dict[str, object]]]]:
        groups: list[tuple[int, list[dict[str, object]]]] = []
        current_key: tuple[int, int] | None = None
        current_start = 0
        current_words: list[dict[str, object]] = []
        for index, word in enumerate(words):
            key = (int(word["block"]), int(word["line"]))
            if current_key is None:
                current_key = key
                current_start = index
            elif key != current_key:
                groups.append((current_start, current_words))
                current_key = key
                current_start = index
                current_words = []
            current_words.append(word)
        if current_words:
            groups.append((current_start, current_words))
        return groups

    def _selection_endpoint(
        self,
        point: QPoint,
        line_groups: list[tuple[int, list[dict[str, object]]]],
    ) -> tuple[int, int | None]:
        line_start, line_words = self._closest_word_line(point, line_groups)
        hit_index: int | None = None
        boundary = line_start + len(line_words)
        for local_index, word in enumerate(line_words):
            word_rect = self._norm_rect_to_page(word["rect"])
            if hit_index is None and word_rect.contains(point):
                hit_index = line_start + local_index
            if point.x() < word_rect.center().x():
                boundary = line_start + local_index
                break
        return boundary, hit_index

    def _closest_word_line(
        self,
        point: QPoint,
        line_groups: list[tuple[int, list[dict[str, object]]]],
    ) -> tuple[int, list[dict[str, object]]]:
        best_group = line_groups[0]
        best_distance = float("inf")
        for line_start, line_words in line_groups:
            rects = [self._norm_rect_to_page(word["rect"]) for word in line_words]
            top = min(rect.top() for rect in rects)
            bottom = max(rect.bottom() for rect in rects)
            if top <= point.y() <= bottom:
                return line_start, line_words
            distance = min(abs(point.y() - top), abs(point.y() - bottom))
            if distance < best_distance:
                best_distance = distance
                best_group = (line_start, line_words)
        return best_group

    @staticmethod
    def _selection_word_bounds(
        start_endpoint: tuple[int, int | None],
        end_endpoint: tuple[int, int | None],
    ) -> tuple[int, int]:
        start_boundary, start_hit = start_endpoint
        end_boundary, end_hit = end_endpoint
        if start_boundary <= end_boundary:
            lower_boundary, lower_hit = start_boundary, start_hit
            upper_boundary, upper_hit = end_boundary, end_hit
        else:
            lower_boundary, lower_hit = end_boundary, end_hit
            upper_boundary, upper_hit = start_boundary, start_hit

        first_index = min(lower_boundary, lower_hit) if lower_hit is not None else lower_boundary
        last_index = max(upper_boundary, upper_hit + 1) if upper_hit is not None else upper_boundary
        return first_index, last_index

    @staticmethod
    def _join_selected_words(words: list[dict[str, object]]) -> str:
        lines: dict[tuple[int, int], list[dict[str, object]]] = {}
        for word in words:
            key = (int(word["block"]), int(word["line"]))
            lines.setdefault(key, []).append(word)

        text_lines: list[str] = []
        for key in sorted(lines):
            ordered = sorted(lines[key], key=lambda item: int(item["word_no"]))
            text_lines.append(" ".join(str(item["text"]) for item in ordered))
        return "\n".join(text_lines)

    def _merge_word_rects_by_line(self, words: list[dict[str, object]]) -> list[list[float]]:
        lines: dict[tuple[int, int], list[list[float]]] = {}
        for word in words:
            key = (int(word["block"]), int(word["line"]))
            lines.setdefault(key, []).append([float(value) for value in word["rect"]])

        rects: list[list[float]] = []
        for key in sorted(lines):
            line_rects = lines[key]
            rects.append(
                [
                    min(rect[0] for rect in line_rects),
                    min(rect[1] for rect in line_rects),
                    max(rect[2] for rect in line_rects),
                    max(rect[3] for rect in line_rects),
                ]
            )
        return rects

    def _note_center(self, note: Note) -> QPoint:
        if self._pixmap is None:
            return QPoint()
        return QPoint(round(note.x_norm * self._page_size.width()), round(note.y_norm * self._page_size.height()))

    def _note_at(self, point: QPoint) -> Note | None:
        for note in reversed(self._notes):
            if note.note_type == "point":
                center = self._note_center(note)
                delta = center - point
                if delta.x() * delta.x() + delta.y() * delta.y() <= (self._marker_radius + 5) ** 2:
                    return note
            elif note.note_type in {"highlight", "underline", "excerpt"}:
                for rect in note.rects_norm:
                    if self._norm_rect_to_page(rect).contains(point):
                        return note
        return None


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

        with QSignalBlocker(self.note_selector):
            self.note_selector.clear()
            if self._notes:
                for note in self._notes:
                    self.note_selector.addItem(self.note_label(note), note.id)
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
        self.search_edit.setPlaceholderText("Search notebooks")
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
        if query:
            entries = [
                entry
                for entry in entries
                if query in self._entry_title(entry).casefold() or query in entry.path.casefold()
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

        title = ElidedLabel(self._entry_title(entry))
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


class OutlinePanel(QWidget):
    page_requested = Signal(int)
    bookmark_add_requested = Signal()
    bookmark_delete_requested = Signal(str)
    outline_new_requested = Signal()
    outline_new_child_requested = Signal()
    outline_delete_requested = Signal()
    outline_save_requested = Signal()
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
        menu.addSeparator()
        menu.addAction(export_action)
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
        frozen_base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        candidates = [
            frozen_base / "pdf_notes_reader" / "assets" / "Icon.png",
            Path(__file__).resolve().parent / "assets" / "Icon.png",
            Path.cwd() / "Icon.png",
            Path(__file__).resolve().parents[2] / "Icon.png",
            Path(sys.executable).resolve().parent / "Icon.png",
            Path.cwd() / "PDFNest-Icon.png",
            Path(__file__).resolve().parents[2] / "PDFNest-Icon.png",
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
            document = fitz.open(path)
        except Exception as exc:  # PyMuPDF raises several exception types.
            QMessageBox.critical(self, "Open failed", f"Could not open PDF:\n{exc}")
            return

        self._save_active_pdf_tab_state()
        entry = find_history_entry(self.history_entries, key)
        self.document = document
        self.pdf_path = path
        self.pdf_key = key
        self.active_pdf_key = key
        self.notes, self.note_counters, self.bookmarks = load_notes_data(self.pdf_key)
        self.page_text_words_cache = {}
        self.reader_return_stack = []
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

        page = self.document.load_page(page_index)
        render_zoom = self.zoom * self.render_scale
        pix = page.get_pixmap(matrix=fitz.Matrix(render_zoom, render_zoom), alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(self.render_scale)
        display_size = QSize(round(pix.width / self.render_scale), round(pix.height / self.render_scale))
        return pixmap, display_size

    def _page_text_words(self, page_index: int) -> list[dict[str, object]]:
        if self.document is None:
            return []
        cached_words = self.page_text_words_cache.get(page_index)
        if cached_words is not None:
            return cached_words

        page = self.document.load_page(page_index)
        rect = page.rect
        if rect.width == 0 or rect.height == 0:
            return []

        words: list[dict[str, object]] = []
        for raw in page.get_text("words"):
            if len(raw) < 8:
                continue
            x0, y0, x1, y1, text, block_no, line_no, word_no = raw[:8]
            words.append(
                {
                    "rect": [
                        max(0.0, min(1.0, float(x0) / rect.width)),
                        max(0.0, min(1.0, float(y0) / rect.height)),
                        max(0.0, min(1.0, float(x1) / rect.width)),
                        max(0.0, min(1.0, float(y1) / rect.height)),
                    ],
                    "text": str(text),
                    "block": int(block_no),
                    "line": int(line_no),
                    "word_no": int(word_no),
                }
            )
        self.page_text_words_cache[page_index] = words
        return words

    def _cache_page_base_sizes(self) -> None:
        self.page_base_sizes = []
        if self.document is None:
            return

        for page_index in range(self.document.page_count):
            rect = self.document.load_page(page_index).rect
            self.page_base_sizes.append((float(rect.width), float(rect.height)))

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
        if 0 <= page_index < len(self.page_base_sizes):
            width, height = self.page_base_sizes[page_index]
        else:
            rect = self.document.load_page(page_index).rect
            width, height = float(rect.width), float(rect.height)
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
        self.pages_layout.addWidget(widget, 0, Qt.AlignHCenter)
        self.page_canvases[page_index] = widget
        self.page_widgets[page_index] = widget

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
        toc = self.outline_panel.outline_toc()
        try:
            self.document.set_toc(toc)
            self.document.saveIncr()
        except Exception as exc:  # PyMuPDF has version-specific save failures.
            QMessageBox.critical(self, "Save contents failed", f"Could not save contents to PDF:\n{exc}")
            return

        self.outline_panel.set_outline(self.document.get_toc())
        self._rebuild_note_counters_from_current_note_counts()
        self.persist_notes()
        self.statusBar().showMessage("Saved contents to PDF and refreshed note numbering counters.", 5000)

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
        if replace_existing and note.exported_markdown_path:
            path = Path(note.exported_markdown_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(note.markdown, encoding="utf-8")
            note.exported_markdown_path = str(path)
            return path

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        pdf_name = self._safe_filename(pdf_path.stem, max_length=48)
        export_dir = self.note_export_dir / pdf_name
        export_dir.mkdir(parents=True, exist_ok=True)
        location = self._safe_filename(self._note_location_label_for_document(document, note.page_index), max_length=48)
        note_number = self._note_number(note)
        filename_stem = self._safe_filename(f"{timestamp}-{location}-{note_number}", max_length=150)
        path = export_dir / f"{filename_stem}.md"
        path = self._unique_markdown_path(path)
        path.write_text(note.markdown, encoding="utf-8")
        note.exported_markdown_path = str(path)
        return path

    def _default_note_title(self, page_index: int, note_number: int) -> str:
        return f"{self._note_location_label(page_index)}-{note_number}"

    def _note_location_label(self, page_index: int) -> str:
        return self._chapter_name_for_page(page_index) or f"page-{page_index + 1}"

    def _note_location_label_for_document(self, document: fitz.Document | None, page_index: int) -> str:
        return self._chapter_name_for_document(document, page_index) or f"page-{page_index + 1}"

    def _counter_key(self, page_index: int) -> str:
        chapter = self._chapter_for_page(page_index)
        if chapter is None:
            return f"page:{max(0, int(page_index))}"
        title, start_page_index = chapter
        return f"toc:{start_page_index}:{title}"

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
        if document is None:
            return None

        best: tuple[str, int] | None = None
        for raw in document.get_toc():
            if len(raw) < 3:
                continue
            toc_page_index = max(0, int(raw[2]) - 1)
            if toc_page_index <= page_index:
                title = self._single_line_title(str(raw[1]))
                if title:
                    best = (title, toc_page_index)
            else:
                break
        return best

    @staticmethod
    def _single_line_title(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _safe_filename(value: str, *, max_length: int = 80) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
        cleaned = cleaned or "untitled"
        if len(cleaned) <= max_length:
            return cleaned
        digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]
        prefix_length = max(1, max_length - len(digest) - 1)
        prefix = cleaned[:prefix_length].rstrip(" ._-") or "untitled"
        return f"{prefix}-{digest}"

    @staticmethod
    def _unique_markdown_path(path: Path) -> Path:
        if not path.exists():
            return path

        for index in range(2, 1000):
            candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
            if not candidate.exists():
                return candidate
        return path.with_name(f"{path.stem}-{datetime.now().strftime('%f')}{path.suffix}")

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
        style = """
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
        for key, value in colors.items():
            style = style.replace(f'{{colors["{key}"]}}', value)
        style = style.replace("{down_arrow_icon}", down_arrow_icon)
        style = style.replace("{up_arrow_icon}", up_arrow_icon)
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


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    if window.restore_window_maximized:
        window.showMaximized()
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
