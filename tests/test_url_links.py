"""pdfnest:// links: opening them in the reader, the Windows handler registration (against a fake
registry) and handing a link to an already running PDFNest."""

from __future__ import annotations

import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtTest import QTest

import pdf_factory
from pdf_notes_reader import app
from pdf_notes_reader.services import url_scheme
from pdf_notes_reader.services.obsidian import pdfnest_url

SRC_DIR = Path(__file__).resolve().parents[1] / "src"


# --- reader ----------------------------------------------------------------------------------------


def test_open_url_opens_pdf_at_page(tmp_path, window, qapp) -> None:
    window.resize(900, 600)
    window.show()
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "book.pdf", page_count=8)
    assert window.open_url(pdfnest_url(pdf_path, 6))
    assert window.pdf_path == pdf_path
    assert window.page_index == 5


def test_open_url_jumps_to_note_and_excerpt_selects_parent(tmp_path, window, qapp) -> None:
    window.resize(900, 600)
    window.show()
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "book.pdf", page_count=8)
    window.load_pdf(pdf_path)
    window.add_note(3, 0.5, 0.5)
    parent = window.notes[0]
    window.append_selected_text_to_current_note("words", page_index=6, rects_norm=[[0.1, 0.1, 0.3, 0.2]])
    excerpt = next(note for note in window.notes if note.note_type == "excerpt")
    window.go_to_page(0)

    assert window.open_url(pdfnest_url(pdf_path, 4, parent.id))
    assert window.page_index == 3
    assert window.note_panel.current_note_id == parent.id

    window.note_panel.set_note(None)
    assert window.open_url(pdfnest_url(pdf_path, 7, excerpt.id))
    assert window.page_index == 6
    assert window.note_panel.current_note_id == parent.id  # the excerpt's note, not the marker


def test_open_url_ignores_missing_files_and_other_links(tmp_path, window) -> None:
    assert not window.open_url(pdfnest_url(tmp_path / "missing.pdf", 1))
    assert not window.open_url("https://example.com")
    assert window.document is None


def test_preview_pdfnest_links_open_in_place(tmp_path, window) -> None:
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "book.pdf", page_count=3)
    window.note_panel.pdfnest_link_requested.emit(pdfnest_url(pdf_path, 2))
    assert window.pdf_path == pdf_path


def test_command_line_requests() -> None:
    argv = ["PDFNest.exe", "pdfnest://open?path=x.pdf&page=2", "--flag", r"C:\b.PDF", "notes.txt"]
    assert app.open_requests(argv) == ["pdfnest://open?path=x.pdf&page=2", r"C:\b.PDF"]


# --- registry --------------------------------------------------------------------------------------


class FakeKey:
    def __init__(self, registry: "FakeRegistry", path: str) -> None:
        self.registry, self.path = registry, path

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class FakeRegistry(SimpleNamespace):
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self) -> None:
        super().__init__()
        self.keys: dict[str, dict[str, str]] = {}

    def CreateKey(self, root, path):  # noqa: N802 - winreg API
        self.keys.setdefault(path, {})
        return FakeKey(self, path)

    def OpenKey(self, root, path):  # noqa: N802
        if path not in self.keys:
            raise FileNotFoundError(path)
        return FakeKey(self, path)

    def SetValueEx(self, key, name, _reserved, _kind, value):  # noqa: N802
        self.keys[key.path][name] = value

    def QueryValueEx(self, key, name):  # noqa: N802
        if name not in self.keys[key.path]:
            raise FileNotFoundError(name)
        return self.keys[key.path][name], self.REG_SZ

    def DeleteKey(self, root, path):  # noqa: N802
        if any(other.startswith(path + "\\") for other in self.keys):
            raise PermissionError("has subkeys")
        if path not in self.keys:
            raise FileNotFoundError(path)
        del self.keys[path]


def test_register_and_unregister_link_handler() -> None:
    registry = FakeRegistry()
    command = url_scheme.register(registry)
    assert registry.keys[r"Software\Classes\pdfnest"] == {"": "URL:PDFNest link", "URL Protocol": ""}
    assert registry.keys[r"Software\Classes\pdfnest\shell\open\command"][""] == command
    assert command.endswith('"%1"')
    assert url_scheme.registered_command(registry) == command

    url_scheme.unregister(registry)
    assert registry.keys == {}
    assert url_scheme.registered_command(registry) == ""


def test_set_registered_follows_the_setting() -> None:
    registry = FakeRegistry()
    url_scheme.set_registered(True, registry)
    assert url_scheme.registered_command(registry) == url_scheme.handler_command()
    registry.keys[r"Software\Classes\pdfnest\shell\open\command"][""] = '"old.exe" "%1"'  # app moved
    url_scheme.set_registered(True, registry)
    assert url_scheme.registered_command(registry) == url_scheme.handler_command()
    url_scheme.set_registered(False, registry)
    assert registry.keys == {}


def test_dev_handler_command_starts_the_app_from_source(monkeypatch) -> None:
    monkeypatch.delattr("sys.frozen", raising=False)
    command = url_scheme.handler_command()
    assert "from pdf_notes_reader.app import main" in command
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", r"D:\apps\PDFNest\PDFNest.exe")
    assert url_scheme.handler_command() == r'"D:\apps\PDFNest\PDFNest.exe" "%1"'


# --- single instance -----------------------------------------------------------------------------


def test_second_launch_hands_links_to_the_running_instance(qapp) -> None:
    name = f"PDFNest-test-{uuid.uuid4().hex[:8]}"
    assert not app.send_to_running_instance(["x"], name, timeout_ms=200)  # nobody running yet

    server = app.InstanceServer(name)
    received: list[list[str]] = []
    server.requests_received.connect(received.append)
    try:
        assert server.is_listening()
        link = "pdfnest://open?path=C%3A%5Cb.pdf&page=2"
        # A second PDFNest launch is another process, as when Windows runs the link handler.
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]); "
            "from pdf_notes_reader.app import send_to_running_instance; "
            "sys.exit(0 if send_to_running_instance([sys.argv[3]], sys.argv[2]) else 3)"
        )
        sender = subprocess.Popen([sys.executable, "-c", code, str(SRC_DIR), name, link])
        deadline = time.monotonic() + 30
        while (not received or sender.poll() is None) and time.monotonic() < deadline:
            QTest.qWait(20)
        assert sender.wait(timeout=30) == 0
        assert received == [[link]]
    finally:
        server.close()
