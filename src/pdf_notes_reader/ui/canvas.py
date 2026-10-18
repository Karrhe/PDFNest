"""One rendered PDF page with note markers, text selection and annotation overlays."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QColorDialog, QMenu, QSizePolicy, QWidget

from pdf_notes_reader.notes import Note
from pdf_notes_reader.ui.constants import ANNOTATION_COLORS, EXCERPT_MARKER_COLOR, EXCERPT_MARKER_STYLES


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
        self._search_hits: list[tuple[float, float, float, float]] = []
        self._current_search_hit = -1
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

    def set_search_hits(self, rects: list[tuple[float, float, float, float]], current: int = -1) -> None:
        """Overlay-only, like set_notes: search highlights never re-rasterize the page."""
        self._search_hits = list(rects)
        self._current_search_hit = current
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

        for index, rect in enumerate(self._search_hits):
            page_rect = self._norm_rect_to_page(list(rect))
            current = index == self._current_search_hit
            painter.fillRect(page_rect, QColor(255, 140, 0, 150 if current else 70))
            if current:
                painter.setPen(QPen(QColor("#c2410c"), 1.5))
                painter.drawRect(page_rect.adjusted(-1, -1, 1, 1))

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
