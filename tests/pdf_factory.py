"""Builders for sample PDFs used across the test suite, including PDFs with known problems."""

from __future__ import annotations

from pathlib import Path

import fitz

USER_PASSWORD = "user-pass"
OWNER_PASSWORD = "owner-pass"


def create_sample_pdf(
    path: Path,
    page_count: int = 1,
    toc: list[list] | None = None,
    page_size: tuple[int, int] = (300, 200),
) -> Path:
    document = fitz.open()
    for page_number in range(page_count):
        page = document.new_page(width=page_size[0], height=page_size[1])
        page.insert_text((40, 80), f"PDF smoke test {page_number + 1}")
    if toc:
        document.set_toc(toc)
    document.save(path)
    document.close()
    return path


def create_encrypted_pdf(path: Path, *, page_count: int = 2, user_password: str = USER_PASSWORD) -> Path:
    """Encrypted PDF. With an empty user password it opens without a prompt but stays encrypted."""
    document = fitz.open()
    for page_number in range(page_count):
        document.new_page(width=300, height=200).insert_text((40, 80), f"Encrypted page {page_number + 1}")
    permissions = fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY
    document.save(
        path,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw=OWNER_PASSWORD,
        user_pw=user_password,
        permissions=permissions,
    )
    document.close()
    return path


def create_object_stream_pdf(path: Path, *, page_count: int = 3) -> Path:
    """PDF 1.5+ layout: compressed object streams and a cross-reference stream."""
    document = fitz.open()
    for page_number in range(page_count):
        document.new_page(width=300, height=200).insert_text((40, 80), f"Object stream page {page_number + 1}")
    document.save(path, garbage=4, deflate=True, use_objstms=1)
    document.close()
    return path


def create_broken_xref_pdf(path: Path, *, page_count: int = 3) -> Path:
    """Valid content whose cross-reference offsets are wrong, so MuPDF has to repair it on open."""
    create_sample_pdf(path, page_count=page_count, toc=[[1, "Start", 1]])
    data = bytearray(path.read_bytes())
    marker = data.rfind(b"startxref")
    if marker < 0:
        raise RuntimeError("sample PDF has no startxref")
    # Point startxref at a bogus offset; every reader must fall back to scanning objects.
    tail = b"startxref\n9\n%%EOF\n"
    path.write_bytes(bytes(data[:marker]) + tail)
    return path


def create_mixed_geometry_pdf(path: Path) -> Path:
    """Pages with /Rotate, a CropBox smaller than the MediaBox, and different sizes."""
    document = fitz.open()
    plain = document.new_page(width=300, height=200)
    plain.insert_text((40, 80), "Plain page")
    rotated = document.new_page(width=300, height=200)
    rotated.insert_text((40, 80), "Rotated page")
    rotated.set_rotation(90)
    cropped = document.new_page(width=600, height=400)
    cropped.insert_text((100, 150), "Cropped page")
    cropped.set_cropbox(fitz.Rect(50, 50, 450, 350))
    document.new_page(width=200, height=500).insert_text((20, 60), "Tall page")
    document.save(path)
    document.close()
    return path


def create_image_only_pdf(path: Path) -> Path:
    """A 'scanned' page: one embedded image, no text layer."""
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 80), False)
    pixmap.set_rect(pixmap.irect, (200, 180, 150))
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_image(page.rect, pixmap=pixmap)
    document.save(path)
    document.close()
    return path


def create_poster_pdf(path: Path, *, width: int = 14400, height: int = 14400) -> Path:
    """A single very large page (the PDF maximum is 14400pt), which is expensive to render at 2x."""
    document = fitz.open()
    document.new_page(width=width, height=height).insert_text((100, 200), "Poster", fontsize=72)
    document.save(path)
    document.close()
    return path


def create_cjk_pdf(path: Path, text: str = "中文检索测试 数学公式") -> Path:
    document = fitz.open()
    page = document.new_page(width=400, height=200)
    page.insert_text((40, 80), text, fontname="china-s")
    document.save(path)
    document.close()
    return path


def create_signed_like_pdf(path: Path) -> Path:
    """PDF whose AcroForm declares signatures exist (SigFlags=3), without a real signature."""
    create_sample_pdf(path, page_count=1)
    document = fitz.open(path)
    catalog = document.pdf_catalog()
    form = document.get_new_xref()
    document.update_object(form, "<< /Fields [] /SigFlags 3 >>")
    document.xref_set_key(catalog, "AcroForm", f"{form} 0 R")
    document.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    document.close()
    return path


def create_not_a_pdf(path: Path) -> Path:
    path.write_bytes(b"this is not a pdf file\n")
    return path


def create_empty_file(path: Path) -> Path:
    path.write_bytes(b"")
    return path


def reopen_is_valid(path: Path, *, expected_pages: int | None = None) -> bool:
    """True when a fresh MuPDF instance can open the file and load every page."""
    fitz.TOOLS.mupdf_warnings()  # clear
    try:
        document = fitz.open(path)
    except Exception:
        return False
    try:
        if document.is_repaired:
            return False
        if expected_pages is not None and document.page_count != expected_pages:
            return False
        for page in document:
            page.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
        return True
    except Exception:
        return False
    finally:
        document.close()
