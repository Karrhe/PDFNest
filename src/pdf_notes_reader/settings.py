from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from pdf_notes_reader.notes import default_data_dir, set_configured_data_dir


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
    "note_marker_radius": 7,
    "append_selection_shortcut": "Ctrl+Shift+C",
    "wheel_scroll_lines": 3,
    "auto_save_current_note": True,
    "window_width": 1180,
    "window_height": 820,
    "window_maximized": False,
    "storage_dir": "",
    "markdown_export_dir": "",
}


def clamp_marker_radius(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 7
    return max(3, min(24, number))


def clamp_wheel_scroll_lines(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 3
    return max(1, min(30, number))


def clamp_window_dimension(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(640, min(4096, number))


def settings_path(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "user_config.json"


def themes_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "themes"


def ensure_default_themes(data_dir: Path | None = None) -> Path:
    directory = themes_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    for name, colors in DEFAULT_THEMES.items():
        path = directory / f"{name}.json"
        if not path.exists():
            with path.open("w", encoding="utf-8") as handle:
                json.dump(colors, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
    return directory


def load_theme_files(data_dir: Path | None = None) -> dict[str, dict[str, str]]:
    directory = ensure_default_themes(data_dir)
    themes: dict[str, dict[str, str]] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        base = DEFAULT_THEMES.get(path.stem, DEFAULT_THEMES["beige"])
        colors = dict(base)
        colors.update({str(key): str(value) for key, value in payload.items()})
        themes[path.stem] = colors
    if not themes:
        themes = deepcopy(DEFAULT_THEMES)
    return themes


def load_settings(data_dir: Path | None = None) -> dict[str, Any]:
    settings = deepcopy(DEFAULT_SETTINGS)
    ensure_default_themes(data_dir)
    path = settings_path(data_dir)
    if not path.exists():
        settings["storage_dir"] = str(data_dir or default_data_dir())
        return settings

    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        return settings

    settings.update({key: value for key, value in loaded.items() if key in DEFAULT_SETTINGS})
    settings["note_marker_radius"] = clamp_marker_radius(settings.get("note_marker_radius"))
    settings["wheel_scroll_lines"] = clamp_wheel_scroll_lines(settings.get("wheel_scroll_lines"))
    settings["auto_save_current_note"] = bool(settings.get("auto_save_current_note"))
    settings["window_width"] = clamp_window_dimension(settings.get("window_width"), 1180)
    settings["window_height"] = clamp_window_dimension(settings.get("window_height"), 820)
    settings["window_maximized"] = bool(settings.get("window_maximized"))
    settings["storage_dir"] = str(settings.get("storage_dir") or data_dir or default_data_dir())
    return settings


def save_settings(settings: dict[str, Any], data_dir: Path | None = None) -> Path:
    storage_dir = Path(data_dir).expanduser() if data_dir is not None else Path(str(settings.get("storage_dir") or default_data_dir())).expanduser()
    if data_dir is None and "storage_dir" in settings and not os.environ.get("PDF_NOTES_READER_DATA_DIR"):
        set_configured_data_dir(storage_dir)
    path = settings_path(storage_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = deepcopy(DEFAULT_SETTINGS)
    payload.update({key: value for key, value in settings.items() if key in DEFAULT_SETTINGS})
    payload["note_marker_radius"] = clamp_marker_radius(payload.get("note_marker_radius"))
    payload["wheel_scroll_lines"] = clamp_wheel_scroll_lines(payload.get("wheel_scroll_lines"))
    payload["auto_save_current_note"] = bool(payload.get("auto_save_current_note"))
    payload["window_width"] = clamp_window_dimension(payload.get("window_width"), 1180)
    payload["window_height"] = clamp_window_dimension(payload.get("window_height"), 820)
    payload["window_maximized"] = bool(payload.get("window_maximized"))
    payload["storage_dir"] = str(storage_dir)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)
    return path
