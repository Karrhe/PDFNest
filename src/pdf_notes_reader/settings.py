from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from pdf_notes_reader.notes import default_data_dir


DEFAULT_THEMES: dict[str, dict[str, str]] = {
    "beige": {
        "window": "#e8dfc8",
        "reader": "#f0ead8",
        "pdf_tint": "#f3ecd6",
        "panel": "#f5eedc",
        "editor": "#fbf6e8",
        "toolbar": "#bda66a",
        "button": "#d7bf7a",
        "button_hover": "#e3ce91",
        "border": "#cbbd95",
        "text": "#2f2a1f",
        "muted": "#7a705b",
        "selection": "#c2a45d",
        "highlight": "#fde68a",
        "underline": "#2563eb",
        "note_marker": "#e11d48",
    },
    "white": {
        "window": "#f1f5f9",
        "reader": "#e5e7eb",
        "pdf_tint": "#ffffff",
        "panel": "#ffffff",
        "editor": "#ffffff",
        "toolbar": "#e2e8f0",
        "button": "#e5e7eb",
        "button_hover": "#dbeafe",
        "border": "#cbd5e1",
        "text": "#111827",
        "muted": "#64748b",
        "selection": "#93c5fd",
        "highlight": "#fef08a",
        "underline": "#1d4ed8",
        "note_marker": "#dc2626",
    },
}


DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "beige",
    "themes": DEFAULT_THEMES,
}


def settings_path(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "settings.json"


def load_settings(data_dir: Path | None = None) -> dict[str, Any]:
    settings = deepcopy(DEFAULT_SETTINGS)
    path = settings_path(data_dir)
    if not path.exists():
        return settings

    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        return settings

    settings.update({key: value for key, value in loaded.items() if key != "themes"})
    loaded_themes = loaded.get("themes")
    if isinstance(loaded_themes, dict):
        for name, colors in loaded_themes.items():
            if isinstance(colors, dict):
                base = settings["themes"].get(name, {})
                merged = dict(base)
                merged.update({str(key): str(value) for key, value in colors.items()})
                settings["themes"][str(name)] = merged
    return settings


def save_settings(settings: dict[str, Any], data_dir: Path | None = None) -> Path:
    path = settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)
    return path
