from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from pdf_notes_reader.notes import (
    _atomic_write_json,
    default_data_dir,
    machine_settings_path,
    read_json_checked,
    record_storage_issue,
    set_configured_data_dir,
)
from pdf_notes_reader.portable import conflict_copies, is_native_absolute_path, move_aside


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
    "highlight_selection_shortcut": "Ctrl+H",
    "underline_selection_shortcut": "Ctrl+U",
    "append_highlight_selection_shortcut": "Ctrl+Shift+H",
    "append_underline_selection_shortcut": "Ctrl+Shift+U",
    "append_selection_color": "#93c5fd",
    "highlight_selection_color": "#fca5a5",
    "underline_selection_color": "#fca5a5",
    "append_highlight_selection_color": "#93c5fd",
    "append_underline_selection_color": "#93c5fd",
    "wheel_scroll_lines": 3,
    "auto_save_current_note": True,
    "window_width": 1180,
    "window_height": 820,
    "window_maximized": False,
    "storage_dir": "",
    "markdown_export_dir": "",
    "last_pdf_dir": "",  # where the Open / Add PDF dialogs start
    # Obsidian integration: off while the vault folder is empty.
    "obsidian_vault_dir": "",
    "obsidian_subfolder": "PDFNest",
    "register_pdfnest_links": False,
}


# Settings that describe this computer, not the user's preferences. The data folder (with
# user_config.json) may be shared by a Windows PC and a Mac through a cloud drive, so these live in
# .local-data/machine_settings.json beside the data-folder pointer, which is never synced.
MACHINE_SETTINGS: frozenset[str] = frozenset(
    {
        "window_width",
        "window_height",
        "window_maximized",
        "storage_dir",
        "markdown_export_dir",
        "last_pdf_dir",
        "obsidian_vault_dir",
        "register_pdfnest_links",
    }
)
# Machine settings holding a folder: a value read from the shared file is only used when it is an
# absolute path of this OS (a Mac ignores ``C:\...`` written by the PC, and the other way around).
MACHINE_PATH_SETTINGS: frozenset[str] = frozenset({"storage_dir", "markdown_export_dir", "last_pdf_dir", "obsidian_vault_dir"})


def load_machine_settings() -> dict[str, Any]:
    payload = read_json_checked(machine_settings_path())
    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items() if key in MACHINE_SETTINGS}


def _apply_machine_settings(settings: dict[str, Any]) -> None:
    machine = load_machine_settings()
    for key in MACHINE_SETTINGS:
        if key in machine:
            settings[key] = machine[key]
        elif key in MACHINE_PATH_SETTINGS and settings.get(key) and not is_native_absolute_path(str(settings[key])):
            settings[key] = DEFAULT_SETTINGS[key]


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
            _atomic_write_json(path, colors)
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


# The shared preferences as this process last loaded or saved them, per user_config.json: a
# preference that differs from it was changed here. See save_settings.
_SHARED_BASES: dict[str, dict[str, Any]] = {}


def _shared_values(settings: dict[str, Any]) -> dict[str, Any]:
    return {key: settings.get(key) for key in DEFAULT_SETTINGS if key not in MACHINE_SETTINGS}


def _base_key(path: Path) -> str:
    return os.path.normcase(str(path))


def _set_aside_conflict_copies(path: Path) -> None:
    """Moves cloud-sync conflict copies of ``path`` (``user_config 2.json``...) into ``conflicts/``.

    The main file wins: settings are preferences, not data, and the copies are kept for recovery.
    """
    copies = conflict_copies(path)
    if not copies:
        return
    folder = path.parent / "conflicts"
    moved = [copy for copy in copies if move_aside(copy, folder) is not None]
    if moved:
        record_storage_issue(
            f"{path.name} had {len(moved)} conflicting cop{'y' if len(moved) == 1 else 'ies'} from cloud sync; "
            f"they were moved to {folder}.",
            path,
        )


def load_settings(data_dir: Path | None = None) -> dict[str, Any]:
    settings = _load_settings(data_dir)
    _SHARED_BASES[_base_key(settings_path(data_dir))] = _shared_values(settings)
    return settings


def _load_settings(data_dir: Path | None = None) -> dict[str, Any]:
    settings = deepcopy(DEFAULT_SETTINGS)
    ensure_default_themes(data_dir)
    path = settings_path(data_dir)
    if path.parent.is_dir():
        _set_aside_conflict_copies(path)
    loaded = read_json_checked(path) if path.exists() else None
    if not isinstance(loaded, dict):
        # A new (for example freshly synced, still empty) data folder: this computer's own settings
        # still apply.
        _apply_machine_settings(settings)
        settings["storage_dir"] = str(data_dir or default_data_dir())
        settings["window_width"] = clamp_window_dimension(settings.get("window_width"), 1180)
        settings["window_height"] = clamp_window_dimension(settings.get("window_height"), 820)
        return settings

    settings.update({key: value for key, value in loaded.items() if key in DEFAULT_SETTINGS})
    _apply_machine_settings(settings)
    settings["note_marker_radius"] = clamp_marker_radius(settings.get("note_marker_radius"))
    settings["wheel_scroll_lines"] = clamp_wheel_scroll_lines(settings.get("wheel_scroll_lines"))
    settings["auto_save_current_note"] = bool(settings.get("auto_save_current_note"))
    settings["window_width"] = clamp_window_dimension(settings.get("window_width"), 1180)
    settings["window_height"] = clamp_window_dimension(settings.get("window_height"), 820)
    settings["window_maximized"] = bool(settings.get("window_maximized"))
    settings["storage_dir"] = str(settings.get("storage_dir") or data_dir or default_data_dir())
    settings["last_pdf_dir"] = str(settings.get("last_pdf_dir") or "")
    _clean_obsidian_settings(settings)
    return settings


def _clean_obsidian_settings(settings: dict[str, Any]) -> None:
    settings["obsidian_vault_dir"] = str(settings.get("obsidian_vault_dir") or "").strip()
    subfolder = settings.get("obsidian_subfolder")
    settings["obsidian_subfolder"] = "PDFNest" if subfolder is None else str(subfolder).strip()
    settings["register_pdfnest_links"] = bool(settings.get("register_pdfnest_links"))


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
    _clean_obsidian_settings(payload)
    _write_shared_settings(path, payload)
    machine = {key: payload[key] for key in sorted(MACHINE_SETTINGS)}
    try:
        _atomic_write_json(machine_settings_path(), {"schema_version": 1, "app": "PDFNest", **machine})
    except OSError:
        pass  # The shared file still holds them; only the per-computer override is missing.
    return path


def _write_shared_settings(path: Path, payload: dict[str, Any]) -> None:
    """Writes ``user_config.json`` only when a shared preference changed here.

    The file may be shared by several computers through a cloud drive, which keeps a conflict copy
    (``user_config 2.json``) whenever two of them write it between syncs. So closing the window, or
    any save that changes nothing shared, writes nothing. A write takes the file as it is now and
    applies only the preferences changed here since loading, so a stale copy never undoes a change
    made on the other computer.
    """
    key = _base_key(path)
    base = _SHARED_BASES.get(key)
    ours = _shared_values(payload)
    on_disk = read_json_checked(path) if path.exists() else None
    if isinstance(on_disk, dict):
        merged = _shared_values({**DEFAULT_SETTINGS, **{k: v for k, v in on_disk.items() if k in DEFAULT_SETTINGS}})
        for name, value in ours.items():
            if base is None or base.get(name) != value:
                merged[name] = value
        unchanged = all(name in on_disk and on_disk[name] == value for name, value in merged.items())
    else:
        merged = ours
        unchanged = False
    _SHARED_BASES[key] = dict(merged)
    if unchanged:
        return
    # Machine settings are written too, only as defaults for a computer without a machine file yet.
    _atomic_write_json(path, {**payload, **merged})
