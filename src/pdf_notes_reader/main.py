from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from pathlib import Path

import fitz
import markdown
from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QSignalBlocker, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
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
    QTabWidget,
    QTextBrowser,
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
from pdf_notes_reader.notes import Note, default_data_dir, find_note, load_notes, notes_path_for_key, pdf_key_for_path, save_notes
from pdf_notes_reader.settings import clamp_marker_radius, load_settings, load_theme_files, save_settings, settings_path, themes_dir


APP_TITLE = "PDFNest"

ANNOTATION_COLORS = [
    ("Yellow", "#fde047"),
    ("Green", "#86efac"),
    ("Blue", "#93c5fd"),
    ("Pink", "#f9a8d4"),
    ("Red", "#fca5a5"),
    ("Purple", "#c4b5fd"),
]


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

    symbol_pattern = re.compile(r"\\(" + "|".join(re.escape(key) for key in sorted(LATEX_SYMBOLS, key=len, reverse=True)) + r")\b")
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
        r"\\(" + "|".join(re.escape(key) for key in sorted(LATEX_SYMBOLS, key=len, reverse=True)) + r")\b"
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
    annotation_requested = Signal(int, str, list, str, str)
    fit_requested = Signal(str)
    mode_requested = Signal(str)
    note_selected = Signal(str)
    note_color_requested = Signal(str, str)
    note_delete_requested = Signal(str)
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
            if note.note_type not in {"highlight", "underline"}:
                continue
            for rect in note.rects_norm:
                page_rect = self._norm_rect_to_page(rect)
                if note.note_type == "highlight":
                    color = QColor(note.color or self._theme_colors.get("highlight", "#fde68a"))
                    color.setAlpha(105)
                    painter.fillRect(page_rect, color)
                else:
                    pen = QPen(QColor(note.color or self._theme_colors.get("underline", "#2563eb")), 2)
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
        copy_action = QAction("Copy selected text", self)
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
        highlight_actions: dict[QAction, str] = {}
        underline_actions: dict[QAction, str] = {}

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
            menu.addAction(delete_note_action)
            menu.addSeparator()

        menu.addAction(add_action)
        if self._selected_text:
            menu.addAction(copy_action)
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
            self.note_selected.emit(target_note.id)
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
        elif chosen == add_action:
            x_norm, y_norm = self._point_to_norm(event.pos())
            self.add_note_requested.emit(self.page_index, x_norm, y_norm)
        elif chosen == copy_action:
            self.copy_selected_text()
        elif chosen in highlight_actions:
            self.annotation_requested.emit(self.page_index, "highlight", self._selected_rects_norm, self._selected_text, highlight_actions[chosen])
        elif chosen in underline_actions:
            self.annotation_requested.emit(self.page_index, "underline", self._selected_rects_norm, self._selected_text, underline_actions[chosen])
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
            self.note_selected.emit(note.id)
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
        selection = self._selection_rect()
        if selection is None:
            return

        ordered_words = sorted(self._text_words, key=self._word_sort_key)
        intersecting_indexes = [
            index
            for index, word in enumerate(ordered_words)
            if self._norm_rect_to_page(word["rect"]).intersects(selection)
        ]
        if not intersecting_indexes:
            self._selected_rects_norm = []
            self._selected_text = ""
            return

        first_index = min(intersecting_indexes)
        last_index = max(intersecting_indexes)
        selected = ordered_words[first_index : last_index + 1]
        self._selected_rects_norm = self._merge_word_rects_by_line(selected)
        self._selected_text = self._join_selected_words(selected)

    @staticmethod
    def _word_sort_key(word: dict[str, object]) -> tuple[int, int, int]:
        return (int(word["block"]), int(word["line"]), int(word["word_no"]))

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
            elif note.note_type in {"highlight", "underline"}:
                for rect in note.rects_norm:
                    if self._norm_rect_to_page(rect).contains(point):
                        return note
        return None


class NotePanel(QWidget):
    choose_folder_requested = Signal()
    save_requested = Signal(str)
    export_requested = Signal(str)
    delete_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._current_note_id: str | None = None

        self.title = QLabel("No note selected")
        self.title.setStyleSheet("font-weight: 600;")

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
        self.folder_button = QPushButton("Notes folder")
        self.folder_label = QLabel("")
        self.folder_label.setObjectName("NoteFolderLabel")
        self.folder_label.setWordWrap(True)
        self.save_button.clicked.connect(self._emit_save)
        self.export_button.clicked.connect(self._emit_export)
        self.delete_button.clicked.connect(self.delete_requested.emit)
        self.folder_button.clicked.connect(self.choose_folder_requested.emit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.folder_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.folder_label)
        layout.addWidget(tabs, 1)
        layout.addLayout(buttons)

        self.set_enabled(False)

    @property
    def current_note_id(self) -> str | None:
        return self._current_note_id

    def set_note(self, note: Note | None) -> None:
        self._current_note_id = note.id if note else None
        self.set_enabled(note is not None)

        if note is None:
            self.title.setText("No note selected")
            self.editor.blockSignals(True)
            self.editor.clear()
            self.editor.blockSignals(False)
            self.preview.clear()
            return

        self.title.setText(f"Page {note.page_index + 1} note")
        self.editor.blockSignals(True)
        self.editor.setPlainText(note.markdown)
        self.editor.blockSignals(False)
        self._update_preview()

    def set_enabled(self, enabled: bool) -> None:
        self.editor.setEnabled(enabled)
        self.preview.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    def set_folder_path(self, path: Path) -> None:
        self.folder_label.setText(f"Markdown folder: {path}")

    def _emit_save(self) -> None:
        if self._current_note_id is not None:
            self.save_requested.emit(self.editor.toPlainText())

    def _emit_export(self) -> None:
        if self._current_note_id is not None:
            self.export_requested.emit(self.editor.toPlainText())

    def _update_preview(self) -> None:
        text = self.editor.toPlainText()
        self.preview.setHtml(render_markdown_preview(text))


class HistoryPanel(QWidget):
    open_requested = Signal(str)
    remove_requested = Signal(str)
    settings_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[PdfHistoryEntry] = []

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidget(self.list_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        title = QLabel("Recent PDFs")
        title.setObjectName("HistoryTitle")
        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self.settings_requested.emit)
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(settings_button)

        hint = QLabel("Open a previous PDF from its absolute path. Missing files can be relocated.")
        hint.setObjectName("HistoryHint")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(hint)
        layout.addWidget(scroll, 1)

    def set_entries(self, entries: list[PdfHistoryEntry]) -> None:
        self.entries = entries
        self._rebuild()

    def _rebuild(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        if not self.entries:
            empty = QLabel("No PDFs opened yet.")
            empty.setObjectName("HistoryEmpty")
            self.list_layout.addWidget(empty)
            return

        for entry in self.entries:
            self.list_layout.addWidget(self._build_row(entry))

    def _build_row(self, entry: PdfHistoryEntry) -> QWidget:
        row = QWidget()
        row.setObjectName("HistoryRowMissing" if not entry.exists else "HistoryRow")

        title = QLabel(entry.title)
        title.setObjectName("HistoryRowTitle")
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)

        path = QLabel(entry.path)
        path.setObjectName("HistoryRowPath")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path.setWordWrap(True)

        page = entry.last_page_index + 1 if entry.page_count else 1
        meta_text = f"Last page: {page}"
        if entry.page_count:
            meta_text += f" / {entry.page_count}"
        meta_text += f"    Updated: {entry.updated_at}"
        if not entry.exists:
            meta_text += "    Missing"
        meta = QLabel(meta_text)
        meta.setObjectName("HistoryRowMeta")

        open_button = QPushButton("Open")
        open_button.clicked.connect(lambda _checked=False, key=entry.pdf_key: self.open_requested.emit(key))

        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(lambda _checked=False, key=entry.pdf_key: self.remove_requested.emit(key))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(open_button)
        buttons.addWidget(remove_button)

        layout = QVBoxLayout(row)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(5)
        layout.addWidget(title)
        layout.addWidget(path)
        layout.addWidget(meta)
        layout.addLayout(buttons)
        return row


class OutlinePanel(QWidget):
    page_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("OutlinePanel")
        self.setMinimumWidth(180)
        self.setMaximumWidth(320)

        title = QLabel("Contents")
        title.setObjectName("OutlineTitle")

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemPressed.connect(self._open_item)
        self.tree.itemActivated.connect(self._open_item)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(self.tree, 1)

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

    def _open_item(self, item: QTreeWidgetItem) -> None:
        page_index = item.data(0, Qt.UserRole)
        if page_index is not None:
            self.page_requested.emit(int(page_index))


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

        data_label = QLabel(str(data_dir))
        data_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        note_label = QLabel(str(note_json_path) if note_json_path is not None else "Open a PDF to see this path.")
        note_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        markdown_label = QLabel(str(markdown_dir))
        markdown_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        settings_label = QLabel(str(settings_path(data_dir)))
        settings_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        theme_dir_label = QLabel(str(theme_dir))
        theme_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        form = QFormLayout()
        form.addRow("Theme", self.theme_combo)
        form.addRow("Note dot size", self.marker_size_spin)
        form.addRow("Data folder", data_label)
        form.addRow("Current note JSON", note_label)
        form.addRow("Markdown export base", markdown_label)
        form.addRow("Settings file", settings_label)
        form.addRow("Theme folder", theme_dir_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @property
    def selected_theme(self) -> str:
        return str(self.theme_combo.currentData())

    @property
    def marker_radius(self) -> int:
        return int(self.marker_size_spin.value())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self._set_app_icon()
        self.resize(1180, 820)

        self.settings = load_settings()
        self.themes = load_theme_files()
        self.theme_name = str(self.settings.get("theme") or "beige")
        if self.theme_name not in self.themes:
            self.theme_name = "beige"
            self.settings["theme"] = self.theme_name
        self.note_marker_radius = clamp_marker_radius(self.settings.get("note_marker_radius"))
        self.document: fitz.Document | None = None
        self.pdf_path: Path | None = None
        self.pdf_key: str | None = None
        self.notes: list[Note] = []
        self.history_entries = load_history()
        self.page_index = 0
        self.zoom = 1.25
        self.fit_mode: str | None = None
        self.render_scale = 2.0
        self.render_page_buffer = 1
        self.page_margin = 24
        self.continuous_scroll = True
        self.note_export_dir = default_data_dir() / "markdown_notes"
        self.page_widgets: dict[int, QWidget] = {}
        self.page_base_sizes: list[tuple[float, float]] = []
        self.page_tops: list[int] = []
        self.page_heights: list[int] = []
        self.page_widths: list[int] = []
        self.document_content_size = QSize(1, 1)
        self._suppress_scroll_sync = False
        self._pending_scroll_id = 0
        self._fit_refresh_token = 0

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
        self.note_panel.choose_folder_requested.connect(self.choose_note_export_dir)
        self.note_panel.save_requested.connect(self.save_current_note)
        self.note_panel.export_requested.connect(self.export_current_note)
        self.note_panel.delete_requested.connect(self.delete_current_note)
        self.note_panel.set_folder_path(self.note_export_dir)

        self.prev_page_button = QPushButton("-")
        self.prev_page_button.setObjectName("PageNavButton")
        self.prev_page_button.clicked.connect(self.previous_page)
        self.next_page_button = QPushButton("+")
        self.next_page_button.setObjectName("PageNavButton")
        self.next_page_button.clicked.connect(self.next_page)
        self.page_spin = QSpinBox()
        self.page_spin.setObjectName("PageSpin")
        self.page_spin.setRange(0, 0)
        self.page_spin.setPrefix("Page ")
        self.page_spin.valueChanged.connect(self.go_to_page_number)
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
        self.outline_panel.page_requested.connect(self.go_to_page)

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
        self.history_panel.remove_requested.connect(self.remove_history_entry)
        self.history_panel.settings_requested.connect(self.open_settings)
        self.history_panel.set_entries(self.history_entries)

        self.main_stack = QStackedWidget()
        self.main_stack.addWidget(self.history_panel)
        self.main_stack.addWidget(self.reader_splitter)
        self.setCentralWidget(self.main_stack)

        self._build_toolbar()
        self._render_empty_state()
        self.apply_theme()
        self.restore_last_session()
        self._refresh_actions()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("PDF controls")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.home_action = QAction("Home", self)
        self.home_action.triggered.connect(self.show_home)
        toolbar.addAction(self.home_action)

        open_action = QAction("Open", self)
        open_action.triggered.connect(self.open_pdf)
        toolbar.addAction(open_action)

        self.reader_action = QAction("Reader", self)
        self.reader_action.triggered.connect(self.show_reader)
        toolbar.addAction(self.reader_action)

        toolbar.addSeparator()

        self.outline_action = QAction("Contents", self)
        self.outline_action.setCheckable(True)
        self.outline_action.setChecked(True)
        self.outline_action.triggered.connect(self.set_outline_visible)
        toolbar.addAction(self.outline_action)

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

    def open_settings(self) -> None:
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
        save_settings(self.settings)
        self.themes = load_theme_files()
        self.apply_theme()
        self.render_page(render_neighbors=False)

    def open_pdf(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF files (*.pdf)")
        if not filename:
            return
        self.load_pdf(Path(filename))

    def load_pdf(self, path: Path, *, pdf_key: str | None = None, restore_last_page: bool = True) -> None:
        try:
            document = fitz.open(path)
        except Exception as exc:  # PyMuPDF raises several exception types.
            QMessageBox.critical(self, "Open failed", f"Could not open PDF:\n{exc}")
            return

        self.close_document()
        key = pdf_key or pdf_key_for_path(path)
        entry = find_history_entry(self.history_entries, key)
        self.document = document
        self.pdf_path = path
        self.pdf_key = key
        self.notes = load_notes(self.pdf_key)
        self._cache_page_base_sizes()
        if restore_last_page and entry is not None:
            self.page_index = min(entry.last_page_index, max(document.page_count - 1, 0))
        else:
            self.page_index = 0
        self.note_panel.set_note(None)
        self._record_current_pdf()
        self.outline_panel.set_outline(document.get_toc())
        self.render_page()
        self.show_reader()

    def close_document(self) -> None:
        self._record_current_pdf()
        if self.document is not None:
            self.document.close()
        self.document = None
        self.page_base_sizes = []
        self.page_tops = []
        self.page_heights = []
        self.page_widths = []
        self.document_content_size = QSize(1, 1)

    def _record_current_pdf(self) -> None:
        if self.document is None or self.pdf_path is None or self.pdf_key is None:
            return
        upsert_history_entry(
            self.history_entries,
            pdf_key=self.pdf_key,
            path=self.pdf_path,
            page_count=self.document.page_count,
            last_page_index=self.page_index,
        )
        save_history(self.history_entries)
        self.history_panel.set_entries(self.history_entries)

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

        filename, _ = QFileDialog.getOpenFileName(self, "Relocate PDF", "", "PDF files (*.pdf)")
        if filename:
            self.load_pdf(Path(filename), pdf_key=entry.pdf_key, restore_last_page=True)

    def remove_history_entry(self, pdf_key: str) -> None:
        self.history_entries = remove_history_entry(self.history_entries, pdf_key)
        save_history(self.history_entries)
        self.history_panel.set_entries(self.history_entries)

    def show_home(self) -> None:
        self._record_current_pdf()
        self.history_panel.set_entries(self.history_entries)
        self.main_stack.setCurrentWidget(self.history_panel)
        self._refresh_actions()

    def show_reader(self) -> None:
        if self.document is not None:
            self.main_stack.setCurrentWidget(self.reader_splitter)
        self._refresh_actions()

    def set_outline_visible(self, visible: bool) -> None:
        anchor_page = self.page_index
        with QSignalBlocker(self.outline_action):
            self.outline_action.setChecked(visible)

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
            rendered_pages = set(self._page_indexes_to_render(render_neighbors=render_neighbors))
            self._recalculate_page_metrics()
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

    def _page_indexes_to_render(self, *, render_neighbors: bool = True) -> range:
        if self.document is None:
            return range(0)
        if not self.continuous_scroll or not render_neighbors:
            return range(self.page_index, self.page_index + 1)
        start = max(0, self.page_index - self.render_page_buffer)
        end = min(self.document.page_count, self.page_index + self.render_page_buffer + 1)
        return range(start, end)

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
        canvas.annotation_requested.connect(self.add_text_annotation)
        canvas.fit_requested.connect(self.fit_page)
        canvas.mode_requested.connect(self.set_reading_mode)
        canvas.note_selected.connect(self.select_note)
        canvas.note_color_requested.connect(self.set_note_color)
        canvas.note_delete_requested.connect(self.delete_note_by_id)
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

        note = Note.create(
            pdf_key=self.pdf_key,
            page_index=page_index,
            x_norm=x_norm,
            y_norm=y_norm,
            markdown="# New note\n",
        )
        self.page_index = page_index
        self.notes.append(note)
        self.persist_notes()
        self.render_page()
        self.note_panel.set_note(note)

    def add_text_annotation(self, page_index: int, note_type: str, rects_norm: list, selected_text: str, color: str = "") -> None:
        if self.document is None or self.pdf_key is None or not rects_norm:
            return
        cleaned_rects = []
        for rect in rects_norm:
            if isinstance(rect, list | tuple) and len(rect) == 4:
                cleaned_rects.append([max(0.0, min(1.0, float(value))) for value in rect])
        if not cleaned_rects:
            return

        first_rect = cleaned_rects[0]
        x_norm = (first_rect[0] + first_rect[2]) / 2
        y_norm = (first_rect[1] + first_rect[3]) / 2
        note = Note.create(
            pdf_key=self.pdf_key,
            page_index=page_index,
            x_norm=x_norm,
            y_norm=y_norm,
            markdown=f"> {selected_text}\n\n",
            note_type=note_type,
            rects_norm=cleaned_rects,
            selected_text=selected_text,
            color=color,
        )
        self.page_index = page_index
        self.notes.append(note)
        self.persist_notes()
        self.render_page()
        self.note_panel.set_note(note)

    def select_note(self, note_id: str) -> None:
        self.note_panel.set_note(find_note(self.notes, note_id))

    def set_note_color(self, note_id: str, color: str) -> None:
        note = find_note(self.notes, note_id)
        if note is None:
            self.note_panel.set_note(None)
            return
        if not QColor(color).isValid():
            return
        note.color = QColor(color).name()
        note.update_markdown(note.markdown)
        self.persist_notes()
        self.render_page(render_neighbors=False)
        self.note_panel.set_note(note)

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
        path = self.export_markdown_note(note)
        self.note_panel.set_note(note)
        if path is not None:
            self.statusBar().showMessage(f"Exported Markdown note: {path}", 5000)

    def delete_current_note(self) -> None:
        note_id = self.note_panel.current_note_id
        if note_id is None:
            return

        self.delete_note_by_id(note_id, confirm=True)

    def delete_note_by_id(self, note_id: str, *, confirm: bool = False) -> None:
        note = find_note(self.notes, note_id)
        if note is None:
            self.note_panel.set_note(None)
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

        self.notes = [item for item in self.notes if item.id != note_id]
        self.persist_notes()
        self.note_panel.set_note(None)
        self.render_page()

    def persist_notes(self) -> None:
        if self.pdf_path is None or self.pdf_key is None:
            return
        save_notes(pdf_key=self.pdf_key, pdf_path=self.pdf_path, notes=self.notes)

    def choose_note_export_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose Markdown notes folder", str(self.note_export_dir))
        if not path:
            return
        self.note_export_dir = Path(path)
        self.note_panel.set_folder_path(self.note_export_dir)

    def export_markdown_note(self, note: Note) -> Path | None:
        if self.pdf_path is None:
            return None

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        pdf_name = self._safe_filename(self.pdf_path.stem)
        export_dir = self.note_export_dir / pdf_name
        export_dir.mkdir(parents=True, exist_ok=True)
        location = self._safe_filename(self._chapter_name_for_page(note.page_index) or f"page-{note.page_index + 1}")
        note_number = self._note_number(note)
        path = export_dir / f"{timestamp}-{pdf_name}-{location}-{note_number}.md"
        path = self._unique_markdown_path(path)
        path.write_text(note.markdown, encoding="utf-8")
        return path

    def _note_number(self, note: Note) -> int:
        page_notes = [item for item in self.notes if item.page_index == note.page_index]
        page_notes.sort(key=lambda item: item.created_at)
        for index, item in enumerate(page_notes, start=1):
            if item.id == note.id:
                return index
        return len(page_notes) + 1

    def _chapter_name_for_page(self, page_index: int) -> str | None:
        if self.document is None:
            return None

        best_title: str | None = None
        for raw in self.document.get_toc():
            if len(raw) < 3:
                continue
            toc_page_index = max(0, int(raw[2]) - 1)
            if toc_page_index <= page_index:
                best_title = str(raw[1])
            else:
                break
        return best_title

    @staticmethod
    def _safe_filename(value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
        return cleaned[:80] or "untitled"

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
        self.note_panel.set_note(None)
        self._record_current_pdf()
        if self.continuous_scroll:
            self.render_page()
        else:
            self.render_page()

    def go_to_page_number(self, page_number: int) -> None:
        if self.document is None or page_number < 1:
            return
        self.go_to_page(page_number - 1)

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

        if closest_page != self.page_index:
            self.page_index = closest_page
            if closest_page in self.page_canvases:
                self.canvas = self.page_canvases[closest_page]
            self._refresh_actions()
            self._record_current_pdf()
            rendered_pages = sorted(self.page_canvases)
            needs_render = closest_page not in self.page_canvases
            if rendered_pages:
                needs_render = needs_render or closest_page in (rendered_pages[0], rendered_pages[-1])
            if needs_render:
                self.render_page(center_current=False)

    def set_continuous_scroll(self, checked: bool) -> None:
        self.set_reading_mode("continuous" if checked else "single")

    def set_reading_mode(self, mode: str) -> None:
        next_continuous = mode == "continuous"
        if self.continuous_scroll == next_continuous:
            return
        self.continuous_scroll = next_continuous
        self.note_panel.set_note(None)
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
        self._apply_fit_mode(anchor_page=anchor_page)
        self._schedule_fit_refresh(anchor_page=anchor_page)

    def _apply_fit_mode(self, *, anchor_page: int | None = None, token: int | None = None) -> None:
        if token is not None and token != self._fit_refresh_token:
            return
        if self.document is None or self.fit_mode is None:
            return
        if anchor_page is not None:
            self.page_index = max(0, min(anchor_page, self.document.page_count - 1))

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
            self.zoom = max(0.3, min(4.0, available / widest_page_width))
        elif self.fit_mode == "height":
            available = measured_viewport.height() - margins.top() - margins.bottom()
            self.zoom = max(0.3, min(4.0, available / rect.height))
        else:
            return
        self.render_page(render_neighbors=False)

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
            for delay in (0, 50, 150, 300):
                QTimer.singleShot(delay, lambda page=page, token=token: self._apply_fit_mode(anchor_page=page, token=token))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._schedule_fit_refresh(anchor_page=self.page_index)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt override
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

        if event.key() in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp):
            self.previous_page()
            event.accept()
            return
        if event.key() in (Qt.Key_Right, Qt.Key_Down, Qt.Key_PageDown):
            self.next_page()
            event.accept()
            return
        super().keyPressEvent(event)

    def _refresh_actions(self) -> None:
        has_document = self.document is not None
        page_count = self.document.page_count if self.document is not None else 0
        self.prev_page_button.setEnabled(has_document and self.page_index > 0)
        self.next_page_button.setEnabled(has_document and self.page_index < page_count - 1)
        self.outline_action.setEnabled(has_document)
        self.reader_action.setEnabled(has_document)
        self.page_spin.setEnabled(has_document)
        self.zoom_spin.setEnabled(has_document)

        if has_document:
            with QSignalBlocker(self.page_spin):
                self.page_spin.setRange(1, page_count)
                self.page_spin.setValue(self.page_index + 1)
            self.page_count_label.setText(f"/ {page_count}")
        else:
            with QSignalBlocker(self.page_spin):
                self.page_spin.setRange(0, 0)
                self.page_spin.setValue(0)
            self.page_count_label.setText("/ 0")
        with QSignalBlocker(self.zoom_spin):
            self.zoom_spin.setValue(round(self.zoom * 100))

    def apply_theme(self) -> None:
        colors = self._theme_colors()
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
                background: {colors["editor"]};
                border-radius: 4px;
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
            }
            QTreeWidget::item {
                min-height: 22px;
                padding: 2px 4px;
            }
            QTreeWidget::item:selected {
                background: {colors["button"]};
            }
            QSplitter::handle {
                background: {colors["border"]};
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
            }
            QPlainTextEdit, QTextBrowser {
                background: {colors["editor"]};
                border: 1px solid {colors["border"]};
                color: {colors["text"]};
                selection-background-color: {colors["selection"]};
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
            QPushButton:disabled {
                background: {colors["border"]};
                color: {colors["muted"]};
            }
            QComboBox, QSpinBox, QDoubleSpinBox {
                background: {colors["editor"]};
                border: 1px solid {colors["border"]};
                border-radius: 4px;
                color: {colors["text"]};
                min-height: 24px;
                padding: 2px 6px;
            }
            QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                background: {colors["button"]};
                border-left: 1px solid {colors["border"]};
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
                font-size: 15px;
                font-weight: 600;
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
        self.close_document()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
