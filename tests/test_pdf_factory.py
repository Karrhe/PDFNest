"""Guards the fixtures themselves: each problem PDF must really have the problem it claims."""

import fitz

import pdf_factory


def test_sample_pdf_is_clean(tmp_path):
    path = pdf_factory.create_sample_pdf(tmp_path / "a.pdf", page_count=2, toc=[[1, "A", 1]])
    assert pdf_factory.reopen_is_valid(path, expected_pages=2)


def test_encrypted_pdf_needs_password(tmp_path):
    path = pdf_factory.create_encrypted_pdf(tmp_path / "enc.pdf")
    document = fitz.open(path)
    try:
        assert document.needs_pass
        assert document.authenticate(pdf_factory.USER_PASSWORD)
        assert document.page_count == 2
    finally:
        document.close()


def test_owner_only_encrypted_pdf_opens_without_prompt(tmp_path):
    path = pdf_factory.create_encrypted_pdf(tmp_path / "owner.pdf", user_password="")
    document = fitz.open(path)
    try:
        assert not document.needs_pass
        assert document.is_encrypted or document.metadata.get("encryption")
    finally:
        document.close()


def test_broken_xref_pdf_is_repaired_on_open(tmp_path):
    path = pdf_factory.create_broken_xref_pdf(tmp_path / "broken.pdf")
    document = fitz.open(path)
    try:
        assert document.is_repaired
        assert document.page_count == 3
    finally:
        document.close()


def test_object_stream_pdf_opens(tmp_path):
    path = pdf_factory.create_object_stream_pdf(tmp_path / "objstm.pdf")
    assert b"/ObjStm" in path.read_bytes()
    assert pdf_factory.reopen_is_valid(path, expected_pages=3)


def test_mixed_geometry_pdf(tmp_path):
    path = pdf_factory.create_mixed_geometry_pdf(tmp_path / "mixed.pdf")
    document = fitz.open(path)
    try:
        assert document[1].rotation == 90
        assert document[2].cropbox != document[2].mediabox
    finally:
        document.close()


def test_image_only_pdf_has_no_text(tmp_path):
    path = pdf_factory.create_image_only_pdf(tmp_path / "scan.pdf")
    document = fitz.open(path)
    try:
        assert document[0].get_text("words") == []
        assert document[0].get_images()
    finally:
        document.close()


def test_signed_like_pdf_reports_sigflags(tmp_path):
    path = pdf_factory.create_signed_like_pdf(tmp_path / "signed.pdf")
    document = fitz.open(path)
    try:
        assert document.get_sigflags() > 0
    finally:
        document.close()


def test_cjk_pdf_has_text(tmp_path):
    path = pdf_factory.create_cjk_pdf(tmp_path / "cjk.pdf")
    document = fitz.open(path)
    try:
        assert "中文" in document[0].get_text()
    finally:
        document.close()
