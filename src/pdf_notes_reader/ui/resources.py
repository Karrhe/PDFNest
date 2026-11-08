"""Locating bundled resources (icons, images) in source and PyInstaller builds."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parents[1]


def app_resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", PROJECT_DIR))
    candidate = base.joinpath(*parts)
    if candidate.exists():
        return candidate
    return PROJECT_DIR.joinpath(*parts)


def pic_icon(name: str) -> QIcon:
    path = app_resource_path("Pic", name)
    return QIcon(str(path)) if path.exists() else QIcon()
