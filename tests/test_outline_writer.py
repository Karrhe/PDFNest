"""#8: saving contents must never leave a PDF that other readers cannot open."""

from __future__ import annotations

import io
import warnings

import fitz
import pytest

import pdf_factory
from pdf_notes_reader.pdf.outline_writer import (
    TocSaveRefused,
    TocValidationError,
    backup_path_for,
    normalize_toc,
    restore_backup,
    save_toc_safely,
)

pikepdf = pytest.importorskip("pikepdf")
pypdf = pytest.importorskip("pypdf")

NEW_TOC = [[1, "One", 1], [2, "Child", 2], [1, "Two", 3]]


def _strict_readers_accept(path, *, password: str = "") -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pikepdf.open(path, password=password) as pdf:
            assert pdf.check_pdf_syntax() == []
    reader = pypdf.PdfReader(io.BytesIO(path.read_bytes()), strict=True)
    if reader.is_encrypted:
        reader.decrypt(password)
    assert len(reader.pages) >= 1


def _with_prefix(path, prefix: bytes):
    pdf_factory.create_sample_pdf(path, page_count=3, toc=[[1, "Old", 1]])
    path.write_bytes(prefix + path.read_bytes())
    return path


def _legacy_save(path, toc):
    document = fitz.open(path)
    document.set_toc(toc)
    document.saveIncr()
    document.close()


@pytest.mark.parametrize("prefix", [b"\xef\xbb\xbf", b"\r\n\r\n", b"HTTP/1.1 200 OK\r\n\r\n"])
def test_legacy_incremental_save_damages_prefixed_pdf(tmp_path, prefix):
    """Documents the bug: the old code path turns a tolerated file into a damaged one."""
    path = _with_prefix(tmp_path / "prefixed.pdf", prefix)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pikepdf.open(path) as pdf:
            assert pdf.check_pdf_syntax() == []

    _legacy_save(path, NEW_TOC)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pikepdf.open(path) as pdf:
            assert any("damaged" in str(problem) for problem in pdf.check_pdf_syntax())
    document = fitz.open(path)
    try:
        assert document.is_repaired
    finally:
        document.close()


@pytest.mark.parametrize(
    "build",
    [
        lambda p: pdf_factory.create_sample_pdf(p, page_count=3),
        lambda p: pdf_factory.create_object_stream_pdf(p),
        lambda p: pdf_factory.create_broken_xref_pdf(p),
        lambda p: pdf_factory.create_mixed_geometry_pdf(p),
        lambda p: _with_prefix(p, b"\xef\xbb\xbf"),
        lambda p: _with_prefix(p, b"HTTP/1.1 200 OK\r\n\r\n"),
    ],
    ids=["plain", "object-streams", "broken-xref", "mixed-geometry", "bom-prefix", "http-prefix"],
)
def test_safe_save_produces_file_strict_readers_accept(tmp_path, build):
    path = tmp_path / "doc.pdf"
    build(path)
    original_bytes = path.read_bytes()
    document = fitz.open(path)
    pages = document.page_count
    toc = [[1, "One", 1], [2, "Child", 2], [1, "Two", pages]]

    result = save_toc_safely(document, toc)

    assert document.is_closed
    _strict_readers_accept(path)
    reopened = fitz.open(path)
    try:
        assert not reopened.is_repaired
        assert reopened.page_count == pages
        assert reopened.get_toc() == toc
    finally:
        reopened.close()
    assert result.backup_created and result.backup_path.read_bytes() == original_bytes
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp.pdf")]


def test_repeated_saves_keep_pristine_backup_and_stay_valid(tmp_path):
    path = _with_prefix(tmp_path / "twice.pdf", b"\xef\xbb\xbf")
    original_bytes = path.read_bytes()
    for round_number in range(3):
        save_toc_safely(fitz.open(path), [[1, f"Round {round_number}", 1], [1, "End", 3]])
        _strict_readers_accept(path)
    assert backup_path_for(path).read_bytes() == original_bytes

    restore_backup(path)
    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize(
    ("build", "reason"),
    [
        (pdf_factory.create_signed_like_pdf, "signed"),
        (lambda p: pdf_factory.create_encrypted_pdf(p, user_password=""), "security settings"),
    ],
    ids=["signed", "owner-restricted"],
)
def test_unsafe_documents_are_refused_and_left_untouched(tmp_path, build, reason):
    path = tmp_path / "refused.pdf"
    build(path)
    before = path.read_bytes()
    document = fitz.open(path)
    try:
        with pytest.raises(TocSaveRefused, match=reason):
            save_toc_safely(document, [[1, "One", 1]])
    finally:
        if not document.is_closed:
            document.close()
    assert path.read_bytes() == before
    assert not backup_path_for(path).exists()


def test_locked_document_is_refused(tmp_path):
    path = pdf_factory.create_encrypted_pdf(tmp_path / "locked.pdf")
    document = fitz.open(path)
    try:
        with pytest.raises(TocSaveRefused, match="locked"):
            save_toc_safely(document, [[1, "One", 1]])
    finally:
        document.close()


def test_failed_verification_leaves_original_and_no_temp(tmp_path, monkeypatch):
    path = pdf_factory.create_sample_pdf(tmp_path / "verify.pdf", page_count=3)
    before = path.read_bytes()

    def broken_verify(*args, **kwargs):
        raise RuntimeError("simulated verification failure")

    monkeypatch.setattr("pdf_notes_reader.pdf.outline_writer.verify_saved_pdf", broken_verify)
    with pytest.raises(RuntimeError, match="simulated"):
        save_toc_safely(fitz.open(path), [[1, "One", 1]])
    assert path.read_bytes() == before
    assert not backup_path_for(path).exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["verify.pdf"]


@pytest.mark.parametrize(
    ("toc", "message"),
    [
        ([[2, "Starts deep", 1]], "level 1"),
        ([[1, "A", 1], [3, "Jump", 1]], "nested"),
        ([[1, "Past end", 9]], "has 3 pages"),
        ([[1, "   ", 1]], "no title"),
        ([[1, "A"]], "incomplete"),
    ],
)
def test_invalid_toc_is_rejected(toc, message):
    with pytest.raises(TocValidationError, match=message):
        normalize_toc(toc, page_count=3)


def test_titles_are_collapsed_to_one_line():
    assert normalize_toc([[1, "  Multi\nline\ttitle ", 2]], page_count=3) == [[1, "Multi line title", 2]]
