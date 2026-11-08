"""Registers PDFNest as the handler of pdfnest:// links for the current Windows user.

Clicking ``pdfnest://open?path=...&page=N&note=ID`` in Obsidian (or anywhere) then starts PDFNest,
or hands the link to the running PDFNest (see ``app.py``). Only the per-user key
``HKCU\\Software\\Classes\\pdfnest`` is written; unregistering removes exactly that key.

``winreg`` is passed in so tests can use a fake registry and never touch the real one.

macOS has no registry: ``PDFNest.app`` declares the scheme in its ``Info.plist``
(``CFBundleURLTypes``, see ``scripts/build_macos_app.sh``) and LaunchServices delivers the link as
a ``QFileOpenEvent``. :func:`set_registered` is therefore a no-op everywhere but Windows.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from pdf_notes_reader.services.obsidian import URL_SCHEME

KEY_PATH = rf"Software\Classes\{URL_SCHEME}"


def can_register(platform: str | None = None) -> bool:
    """True where PDFNest registers the link handler itself (Windows)."""
    return (sys.platform if platform is None else platform) == "win32"


def registration_hint(platform: str | None = None) -> str:
    """Why the setting is unavailable on this system, or "" where it applies."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return ""
    if platform == "darwin":
        return "On macOS, PDFNest.app handles pdfnest:// links itself once it is in Applications."
    return "Registering pdfnest:// links is only supported on Windows."


def handler_command() -> str:
    """The command Windows runs for a link; ``%1`` is the link."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    if pythonw.exists():
        python = pythonw
    src_dir = Path(__file__).resolve().parents[2]
    code = f"import sys; sys.path.insert(0, r'{src_dir}'); from pdf_notes_reader.app import main; sys.exit(main())"
    return f'"{python}" -c "{code}" "%1"'


def _winreg(module: ModuleType | None) -> ModuleType:
    if module is not None:
        return module
    import winreg  # noqa: PLC0415 - Windows only

    return winreg


def register(winreg_module: ModuleType | None = None) -> str:
    """Creates or updates the handler; returns the registered command."""
    reg = _winreg(winreg_module)
    command = handler_command()
    icon_source = sys.executable if getattr(sys, "frozen", False) else ""
    with reg.CreateKey(reg.HKEY_CURRENT_USER, KEY_PATH) as key:
        reg.SetValueEx(key, "", 0, reg.REG_SZ, "URL:PDFNest link")
        reg.SetValueEx(key, "URL Protocol", 0, reg.REG_SZ, "")
    if icon_source:
        with reg.CreateKey(reg.HKEY_CURRENT_USER, KEY_PATH + r"\DefaultIcon") as key:
            reg.SetValueEx(key, "", 0, reg.REG_SZ, f'"{icon_source}",0')
    with reg.CreateKey(reg.HKEY_CURRENT_USER, KEY_PATH + r"\shell\open\command") as key:
        reg.SetValueEx(key, "", 0, reg.REG_SZ, command)
    return command


def registered_command(winreg_module: ModuleType | None = None) -> str:
    reg = _winreg(winreg_module)
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, KEY_PATH + r"\shell\open\command") as key:
            value, _kind = reg.QueryValueEx(key, "")
            return str(value)
    except OSError:
        return ""


def unregister(winreg_module: ModuleType | None = None) -> None:
    reg = _winreg(winreg_module)
    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", r"\DefaultIcon", ""):
        try:
            reg.DeleteKey(reg.HKEY_CURRENT_USER, KEY_PATH + sub)
        except OSError:
            pass


def set_registered(enabled: bool, winreg_module: ModuleType | None = None) -> None:
    """Brings the registry in line with the setting. Re-registers when the app moved."""
    if not can_register() and winreg_module is None:
        return
    if enabled:
        if registered_command(winreg_module) != handler_command():
            register(winreg_module)
    elif registered_command(winreg_module):
        unregister(winreg_module)
