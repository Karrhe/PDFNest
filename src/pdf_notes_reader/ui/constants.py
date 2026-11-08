"""UI-wide constants: app title, annotation colors, selection shortcuts."""

from __future__ import annotations


APP_TITLE = "PDFNest"


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
