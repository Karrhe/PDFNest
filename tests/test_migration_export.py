"""#9: data migration, Markdown export failures, full backups and a missing configured data folder."""

from __future__ import annotations

import json
import zipfile
from unittest.mock import patch

import pytest

import pdf_factory
from pdf_notes_reader import notes as notes_module
from pdf_notes_reader import storage_migration
from pdf_notes_reader.history import load_history
from pdf_notes_reader.notes import Note, default_data_dir, drain_storage_issues, load_notes_data, pdf_key_for_path, save_notes
from pdf_notes_reader.services.backup import create_backup, verify_backup
from pdf_notes_reader.storage_migration import migrate_storage


@pytest.fixture(autouse=True)
def _issues():
    drain_storage_issues()
    yield
    drain_storage_issues()


def _legacy_note(key: str, text: str) -> dict:
    return Note.create(pdf_key=key, page_index=1, x_norm=0.3, y_norm=0.4, markdown=text, note_number=1).to_dict()


def _legacy_root(tmp_path, *, entries: dict[str, dict]) -> object:
    root = tmp_path / "legacy"
    (root / "notes").mkdir(parents=True)
    for name, payload in entries.items():
        path = root / "notes" / name
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return root


# --- migration ---------------------------------------------------------------------------------


def test_migration_is_idempotent(tmp_path):
    key = pdf_key_for_path(tmp_path / "a.pdf")
    root = _legacy_root(tmp_path, entries={f"{key}.json": {"pdf_key": key, "pdf_path": str(tmp_path / "a.pdf"), "notes": [_legacy_note(key, "one")]}})
    target = tmp_path / "store"
    assert migrate_storage(target, legacy_roots=[root]) is True
    first = load_notes_data(key, target)[0]
    assert migrate_storage(target, legacy_roots=[root]) is False
    assert [n.to_dict() for n in load_notes_data(key, target)[0]] == [n.to_dict() for n in first]


def test_migration_resumes_after_a_crash(tmp_path, monkeypatch):
    key = pdf_key_for_path(tmp_path / "a.pdf")
    root = _legacy_root(tmp_path, entries={f"{key}.json": {"pdf_key": key, "pdf_path": str(tmp_path / "a.pdf"), "notes": [_legacy_note(key, "kept")]}})
    target = tmp_path / "store"
    real = storage_migration._migrate_notes

    def crash(*args, **kwargs):
        raise OSError("power loss")

    monkeypatch.setattr(storage_migration, "_migrate_notes", crash)
    with pytest.raises(OSError):
        migrate_storage(target, legacy_roots=[root])
    assert not (target / "migration_state.json").exists()

    monkeypatch.setattr(storage_migration, "_migrate_notes", real)
    assert migrate_storage(target, legacy_roots=[root]) is True
    assert [n.markdown for n in load_notes_data(key, target)[0]] == ["kept"]


def test_corrupt_legacy_files_are_reported_left_untouched_and_others_migrate(tmp_path):
    good_key = pdf_key_for_path(tmp_path / "good.pdf")
    root = _legacy_root(
        tmp_path,
        entries={
            "broken.json": '{"notes": [',
            f"{good_key}.json": {"pdf_key": good_key, "pdf_path": str(tmp_path / "good.pdf"), "notes": [_legacy_note(good_key, "fine")]},
        },
    )
    (root / "pdf_history.json").write_text("[{oops", encoding="utf-8")
    broken_before = (root / "notes" / "broken.json").read_bytes()
    target = tmp_path / "store"

    migrate_storage(target, legacy_roots=[root])

    assert [n.markdown for n in load_notes_data(good_key, target)[0]] == ["fine"]
    assert (root / "notes" / "broken.json").read_bytes() == broken_before
    assert (root / "pdf_history.json").exists()  # not renamed/quarantined
    messages = " ".join(issue.message for issue in drain_storage_issues())
    assert "broken.json" in messages and "pdf_history.json" in messages


def test_legacy_notes_without_pdf_path_are_still_migrated(tmp_path):
    key = "a" * 24
    root = _legacy_root(tmp_path, entries={f"{key}.json": {"pdf_key": key, "notes": [_legacy_note(key, "orphan")]}})
    target = tmp_path / "store"
    migrate_storage(target, legacy_roots=[root])
    assert [n.markdown for n in load_notes_data(key, target)[0]] == ["orphan"]
    assert any("did not record its PDF" in issue.message for issue in drain_storage_issues())


def test_legacy_history_is_migrated(tmp_path):
    root = _legacy_root(tmp_path, entries={})
    entry = {"pdf_key": "k" * 24, "path": str(tmp_path / "x.pdf"), "title": "x.pdf", "last_page_index": 4, "page_count": 9,
             "opened_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-02T00:00:00+00:00"}
    (root / "pdf_history.json").write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    target = tmp_path / "store"
    migrate_storage(target, legacy_roots=[root])
    assert [(e.pdf_key, e.last_page_index) for e in load_history(target)] == [("k" * 24, 4)]


# --- configured data folder --------------------------------------------------------------------


def _point_to(monkeypatch, tmp_path, configured):
    monkeypatch.delenv("PDF_NOTES_READER_DATA_DIR", raising=False)
    monkeypatch.setattr(notes_module, "app_base_dir", lambda: tmp_path / "app")
    monkeypatch.setattr(notes_module, "_read_storage_pointer", lambda: configured)
    notes_module._reported_missing_dirs.clear()


def test_existing_configured_folder_is_used(tmp_path, monkeypatch):
    configured = tmp_path / "elsewhere" / "Note_PDFNest"
    configured.mkdir(parents=True)
    (tmp_path / "app" / "Note_PDFNest").mkdir(parents=True)
    _point_to(monkeypatch, tmp_path, configured)
    assert default_data_dir() == configured
    assert drain_storage_issues() == []


def test_missing_configured_folder_falls_back_to_local_store_once(tmp_path, monkeypatch):
    local = tmp_path / "app" / "Note_PDFNest"
    local.mkdir(parents=True)
    _point_to(monkeypatch, tmp_path, tmp_path / "moved-away" / "Note_PDFNest")
    assert default_data_dir() == local
    assert default_data_dir() == local
    issues = drain_storage_issues()
    assert len(issues) == 1 and "was not found" in issues[0].message


def test_missing_configured_folder_is_created_when_no_local_store_exists(tmp_path, monkeypatch):
    configured = tmp_path / "new-place" / "Note_PDFNest"
    _point_to(monkeypatch, tmp_path, configured)
    assert default_data_dir() == configured  # a fresh setup on a drive that exists


# --- export ------------------------------------------------------------------------------------


@pytest.mark.gui
def test_export_failure_shows_one_warning_and_keeps_notes(tmp_path, window):
    pdf_path = pdf_factory.create_sample_pdf(tmp_path / "doc.pdf", page_count=2)
    window.load_pdf(pdf_path)
    window.add_note(0, 0.2, 0.2)
    window.save_current_note("# one")
    window.add_note(1, 0.2, 0.2)
    window.save_current_note("# two")
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    window.note_export_dir = blocker

    with patch("pdf_notes_reader.ui.main_window.QMessageBox.warning") as warning:
        window.export_all_notes()
    assert warning.call_count == 1
    assert "2 note(s) could not be exported" in warning.call_args.args[2]
    assert [n.markdown for n in load_notes_data(window.pdf_key)[0]] == ["# one", "# two"]
    assert all(not n.exported_markdown_path for n in window.notes)


# --- backup ------------------------------------------------------------------------------------


def test_backup_contains_data_and_skips_temp_files(tmp_path, isolated_storage):
    pdf_path = tmp_path / "b.pdf"
    key = pdf_key_for_path(pdf_path)
    save_notes(pdf_key=key, pdf_path=pdf_path, notes=[Note.create(pdf_key=key, page_index=0, x_norm=0.1, y_norm=0.1, markdown="m")])
    (isolated_storage / "leftover.json.abc.tmp").write_text("partial", encoding="utf-8")

    path, count = create_backup(isolated_storage, tmp_path / "out" / "backup.zip")
    names = zipfile.ZipFile(path).namelist()
    assert any(name.endswith("note/notes.json") for name in names)
    assert "Note_PDFNest/backup_info.json" in names
    assert not any(name.endswith((".tmp", ".lock")) for name in names)
    assert count == len(names) - 1
    assert verify_backup(path) == []


def test_verify_backup_reports_broken_json(tmp_path):
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("Note_PDFNest/library.json", "{broken")
    assert verify_backup(archive_path) == ["Note_PDFNest/library.json"]


@pytest.mark.gui
def test_settings_backup_button(tmp_path, qapp, isolated_storage):
    from pdf_notes_reader.ui.settings_dialog import SettingsDialog

    isolated_storage.mkdir(parents=True, exist_ok=True)
    (isolated_storage / "library.json").write_text("{}", encoding="utf-8")
    dialog = SettingsDialog(settings={}, themes={"beige": {}}, data_dir=isolated_storage, note_json_path=None,
                            markdown_dir=tmp_path / "md", theme_dir=tmp_path / "themes")
    target = tmp_path / "chosen.zip"
    with patch("pdf_notes_reader.ui.settings_dialog.QFileDialog.getSaveFileName", return_value=(str(target), "")), patch(
        "pdf_notes_reader.ui.settings_dialog.QMessageBox.information"
    ) as info:
        assert dialog.create_backup() == target
    assert target.exists() and "Backed up" in info.call_args.args[2]
