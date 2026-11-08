"""Platform-specific behaviour: where data lives on each OS, and macOS file-open events."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pdf_notes_reader import app
from pdf_notes_reader import notes as notes_module
from pdf_notes_reader.services import url_scheme


# --- data folder ---------------------------------------------------------------------------------


def test_frozen_mac_app_keeps_data_in_application_support(tmp_path) -> None:
    root = notes_module.app_data_root(platform="darwin", frozen=True, home=tmp_path)
    assert root == tmp_path / "Library" / "Application Support" / "PDFNest"


@pytest.mark.parametrize(("platform", "frozen"), [("darwin", False), ("win32", True), ("win32", False), ("linux", True)])
def test_other_builds_keep_data_next_to_the_program(platform, frozen, tmp_path) -> None:
    assert notes_module.app_data_root(platform=platform, frozen=frozen, home=tmp_path) == notes_module.app_base_dir()


def test_frozen_windows_exe_is_portable(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "PDFNest" / "PDFNest.exe"
    exe.parent.mkdir()
    exe.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "platform", "win32")
    assert notes_module.app_local_data_dir() == exe.parent / ".local-data"


def test_frozen_mac_app_defaults_outside_the_bundle(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "PDFNest.app" / "Contents" / "MacOS" / "PDFNest"
    exe.parent.mkdir(parents=True)
    exe.touch()
    home = tmp_path / "home"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("PDF_NOTES_READER_DATA_DIR", raising=False)
    support = home / "Library" / "Application Support" / "PDFNest"

    assert notes_module.app_local_data_dir() == support / ".local-data"
    assert notes_module.default_data_dir() == support / notes_module.STORAGE_DIR_NAME
    assert "PDFNest.app" not in str(notes_module.default_data_dir())


def test_data_dir_override_still_wins_on_mac(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PDF_NOTES_READER_DATA_DIR", str(tmp_path / "custom"))
    assert notes_module.default_data_dir() == tmp_path / "custom"


# --- pdfnest:// link registration ----------------------------------------------------------------


def test_only_windows_registers_links_itself() -> None:
    assert url_scheme.can_register("win32")
    assert not url_scheme.can_register("darwin")
    assert url_scheme.registration_hint("win32") == ""
    assert "macOS" in url_scheme.registration_hint("darwin")
    assert url_scheme.registration_hint("linux")


def test_set_registered_is_a_no_op_on_mac(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")

    def fail(*_args, **_kwargs):
        raise AssertionError("the registry must not be touched on macOS")

    monkeypatch.setattr(url_scheme, "register", fail)
    monkeypatch.setattr(url_scheme, "registered_command", fail)
    url_scheme.set_registered(True)
    url_scheme.set_registered(False)


# --- macOS QFileOpenEvent ------------------------------------------------------------------------


def test_file_open_request_picks_pdfs_and_links() -> None:
    link = "pdfnest://open?path=%2FUsers%2Fme%2Fa%2Bb.pdf&page=3"
    assert app.file_open_request("pdfnest", link, "") == link
    assert app.file_open_request("file", "file:///Users/me/book.PDF", "/Users/me/book.PDF") == "/Users/me/book.PDF"
    assert app.file_open_request("file", "file:///Users/me/notes.txt", "/Users/me/notes.txt") is None
    assert app.file_open_request("https", "https://example.com/x.pdf", "") is None


def test_file_open_events_are_held_until_the_window_is_ready(qapp) -> None:
    from PySide6.QtCore import QCoreApplication, QUrl
    from PySide6.QtGui import QFileOpenEvent

    receiver = app.FileOpenReceiver()
    received: list[list[str]] = []
    receiver.requests_received.connect(received.append)
    qapp.installEventFilter(receiver)
    try:
        link = "pdfnest://open?path=%2Ftmp%2Fa%2Bb.pdf&page=2"
        QCoreApplication.sendEvent(qapp, QFileOpenEvent(QUrl(link)))
        QCoreApplication.sendEvent(qapp, QFileOpenEvent(QUrl.fromLocalFile("/tmp/book.pdf")))
        QCoreApplication.sendEvent(qapp, QFileOpenEvent(QUrl.fromLocalFile("/tmp/notes.txt")))
        assert received == []  # the window does not exist yet

        receiver.set_ready()
        assert len(received) == 1
        assert received[0][0] == link  # "+" stays encoded, so the path survives parse_qs
        assert Path(received[0][1]) == Path("/tmp/book.pdf")

        QCoreApplication.sendEvent(qapp, QFileOpenEvent(QUrl.fromLocalFile("/tmp/later.pdf")))
        assert len(received) == 2
        assert Path(received[1][0]) == Path("/tmp/later.pdf")
    finally:
        qapp.removeEventFilter(receiver)
