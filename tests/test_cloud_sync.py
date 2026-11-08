"""A data folder shared by a Windows PC and a Mac through iCloud Drive (or OneDrive / Dropbox).

The two computers are simulated as two folders, each holding its own copy of the cloud drive:
``pc/iCloudDrive`` and ``mac/Library/Mobile Documents/com~apple~CloudDocs``. "Syncing" copies files
from one to the other, the way the cloud client would.
"""

from __future__ import annotations

import json
import ntpath
import posixpath
import shutil
import unicodedata
from pathlib import Path

import pytest

import pdf_factory
from pdf_notes_reader import notes as notes_module
from pdf_notes_reader import portable
from pdf_notes_reader.history import load_history, save_history, upsert_history_entry
from pdf_notes_reader.notes import (
    Bookmark,
    Note,
    drain_storage_issues,
    load_notes,
    load_notes_data,
    machine_settings_path,
    notebook_index_path,
    notebooks_dir,
    pdf_key_for_path,
    resolve_pdf_key,
    save_notes,
)
from pdf_notes_reader.portable import (
    conflict_copies,
    icloud_stub_for,
    is_native_absolute_path,
    merge_records,
    normalize_portable,
    pdf_fingerprint,
    portable_relpath,
)
from pdf_notes_reader.settings import load_settings, save_settings, settings_path
from pdf_notes_reader.storage_migration import migrate_storage


@pytest.fixture
def machines(tmp_path):
    pc = tmp_path / "pc" / "iCloudDrive"
    mac = tmp_path / "mac" / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    for drive in (pc, mac):
        (drive / "Books").mkdir(parents=True)
    pdf_factory.create_sample_pdf(pc / "Books" / "a.pdf", page_count=3)
    shutil.copy2(pc / "Books" / "a.pdf", mac / "Books" / "a.pdf")
    return pc, mac


def sync(source: Path, target: Path) -> None:
    """Copies the cloud drive from one computer to the other (newest file wins, like iCloud)."""
    shutil.copytree(source, target, dirs_exist_ok=True)


def note(pdf_key: str, text: str, page: int = 0) -> Note:
    return Note.create(pdf_key=pdf_key, page_index=page, x_norm=0.5, y_norm=0.5, markdown=text)


# --- PDF identity -------------------------------------------------------------------------------


def test_relative_path_is_identical_on_windows_and_macos() -> None:
    windows = portable_relpath(r"C:\Users\x\iCloudDrive\Books\a.pdf", r"C:\Users\x\iCloudDrive\PDFNest", pathmod=ntpath)
    mac = portable_relpath(
        "/Users/x/Library/Mobile Documents/com~apple~CloudDocs/Books/a.pdf",
        "/Users/x/Library/Mobile Documents/com~apple~CloudDocs/PDFNest",
        pathmod=posixpath,
    )
    assert windows == mac == "../Books/a.pdf"
    # A PDF on another Windows drive has no relative path; the fingerprint finds it instead.
    assert portable_relpath(r"D:\Books\a.pdf", r"C:\Users\x\iCloudDrive\PDFNest", pathmod=ntpath) == ""


def test_path_keys_differ_between_machines_but_resolved_key_is_shared(machines) -> None:
    pc, mac = machines
    pc_data, mac_data = pc / "PDFNest", mac / "PDFNest"
    pc_pdf, mac_pdf = pc / "Books" / "a.pdf", mac / "Books" / "a.pdf"
    assert pdf_key_for_path(pc_pdf) != pdf_key_for_path(mac_pdf)  # the old bug

    key = resolve_pdf_key(pc_pdf, pc_data)
    save_notes(pdf_key=key, pdf_path=pc_pdf, notes=[note(key, "from the PC")], bookmarks=[Bookmark.create(pdf_key=key, page_index=1, title="Ch 2")], data_dir=pc_data)
    sync(pc, mac)

    assert resolve_pdf_key(mac_pdf, mac_data) == key
    notes, _counters, bookmarks = load_notes_data(key, mac_data)
    assert [item.markdown for item in notes] == ["from the PC"]
    assert [item.title for item in bookmarks] == ["Ch 2"]
    # No second "<name>-<hash>" notebook on the Mac.
    save_notes(pdf_key=key, pdf_path=mac_pdf, notes=notes + [note(key, "from the Mac")], bookmarks=bookmarks, data_dir=mac_data)
    assert sorted(path.name for path in notebooks_dir(mac_data).iterdir() if path.is_dir()) == ["a"]
    manifest = json.loads((notebooks_dir(mac_data) / "a" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["relpath"] == "../Books/a.pdf"
    assert manifest["fingerprint"] == pdf_fingerprint(mac_pdf)


def test_new_pdf_opened_on_both_machines_before_sync_gets_the_same_key(machines) -> None:
    pc, mac = machines
    assert resolve_pdf_key(pc / "Books" / "a.pdf", pc / "PDFNest") != pdf_key_for_path(pc / "Books" / "a.pdf")
    assert resolve_pdf_key(pc / "Books" / "a.pdf", pc / "PDFNest") == resolve_pdf_key(mac / "Books" / "a.pdf", mac / "PDFNest")


def test_moved_pdf_is_found_by_fingerprint(machines, tmp_path) -> None:
    pc, mac = machines
    key = resolve_pdf_key(pc / "Books" / "a.pdf", pc / "PDFNest")
    save_notes(pdf_key=key, pdf_path=pc / "Books" / "a.pdf", notes=[note(key, "kept")], data_dir=pc / "PDFNest")
    sync(pc, mac)
    (pc / "Books" / "a.pdf").unlink()  # the Mac cannot see the PC's disk
    elsewhere = tmp_path / "mac-downloads" / "renamed.pdf"
    elsewhere.parent.mkdir()
    shutil.move(mac / "Books" / "a.pdf", elsewhere)
    assert resolve_pdf_key(elsewhere, mac / "PDFNest") == key


def test_pdf_rewritten_in_place_keeps_its_notes(machines) -> None:
    """Saving the contents (TOC) rewrites the PDF, so its fingerprint changes; the path still finds it."""
    pc, mac = machines
    pdf = pc / "Books" / "a.pdf"
    key = resolve_pdf_key(pdf, pc / "PDFNest")
    save_notes(pdf_key=key, pdf_path=pdf, notes=[note(key, "kept")], data_dir=pc / "PDFNest")
    old_fingerprint = pdf_fingerprint(pdf)
    pdf_factory.create_sample_pdf(pdf, page_count=3, toc=[[1, "Intro", 1]])
    assert pdf_fingerprint(pdf) != old_fingerprint
    sync(pc, mac)
    assert resolve_pdf_key(pdf, pc / "PDFNest") == key
    assert resolve_pdf_key(mac / "Books" / "a.pdf", mac / "PDFNest") == key


def test_unicode_file_names_match_across_nfc_and_nfd() -> None:
    composed = unicodedata.normalize("NFC", "../Books/Café.pdf")
    decomposed = unicodedata.normalize("NFD", "../books/CAFÉ.pdf")
    assert composed != decomposed
    assert normalize_portable(composed) == normalize_portable(decomposed)


# --- Migration of notebooks made before portable lookup ----------------------------------------


def _make_legacy_notebook(data_dir: Path, pdf: Path, text: str) -> str:
    """A notebook as PDFNest 0.3 saved it: keyed by the absolute path, manifest without locators."""
    key = pdf_key_for_path(pdf)
    save_notes(pdf_key=key, pdf_path=pdf, notes=[note(key, text)], data_dir=data_dir)
    manifest_path = notebooks_dir(data_dir) / "a" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("relpath")
    manifest.pop("fingerprint")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (data_dir / "migration_state.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    notes_module._LOCATOR_CACHE.clear()
    return key


def test_migration_backfills_old_notebooks_without_rekeying(machines) -> None:
    pc, mac = machines
    pc_data = pc / "PDFNest"
    key = _make_legacy_notebook(pc_data, pc / "Books" / "a.pdf", "old note")
    notes_before = (notebooks_dir(pc_data) / "a" / "note" / "notes.json").read_bytes()

    assert migrate_storage(pc_data) is True
    manifest = json.loads((notebooks_dir(pc_data) / "a" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["pdf_key"] == key
    assert manifest["relpath"] == "../Books/a.pdf"
    assert manifest["fingerprint"] == pdf_fingerprint(pc / "Books" / "a.pdf")
    assert (notebooks_dir(pc_data) / "a" / "note" / "notes.json").read_bytes() == notes_before
    assert json.loads((pc_data / "migration_state.json").read_text(encoding="utf-8"))["schema_version"] == 2
    assert migrate_storage(pc_data) is False  # runs once per data folder

    # Same machine: the old path key still opens it.
    assert resolve_pdf_key(pc / "Books" / "a.pdf", pc_data) == key
    sync(pc, mac)
    (pc / "Books" / "a.pdf").unlink()  # the Mac cannot see the PC's disk
    # The Mac's copy of the data folder lives elsewhere, so it recomputes locators once.
    migrate_storage(mac / "PDFNest")
    manifest = json.loads((notebooks_dir(mac / "PDFNest") / "a" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["relpath"] == "../Books/a.pdf"
    assert resolve_pdf_key(mac / "Books" / "a.pdf", mac / "PDFNest") == key
    assert [item.markdown for item in load_notes(key, mac / "PDFNest")] == ["old note"]


def test_old_notebook_from_other_machine_found_by_name_before_backfill(machines) -> None:
    pc, mac = machines
    key = _make_legacy_notebook(pc / "PDFNest", pc / "Books" / "a.pdf", "old note")
    (pc / "Books" / "a.pdf").unlink()  # the PC never got to backfill it
    sync(pc, mac)
    assert resolve_pdf_key(mac / "Books" / "a.pdf", mac / "PDFNest") == key


def test_second_local_copy_keeps_its_own_notebook(tmp_path) -> None:
    data = tmp_path / "data"
    one, two = tmp_path / "one" / "a.pdf", tmp_path / "two" / "a.pdf"
    one.parent.mkdir()
    two.parent.mkdir()
    pdf_factory.create_sample_pdf(one, page_count=2)
    shutil.copy2(one, two)
    key_one = resolve_pdf_key(one, data)
    save_notes(pdf_key=key_one, pdf_path=one, notes=[note(key_one, "copy one")], data_dir=data)
    assert pdf_fingerprint(one) == pdf_fingerprint(two)
    assert resolve_pdf_key(two, data) != key_one


def test_name_fallback_ignores_old_notebook_whose_pdf_exists_here(tmp_path) -> None:
    data = tmp_path / "data"
    one, two = tmp_path / "one" / "a.pdf", tmp_path / "two" / "a.pdf"
    one.parent.mkdir()
    two.parent.mkdir()
    pdf_factory.create_sample_pdf(one, page_count=1)
    pdf_factory.create_sample_pdf(two, page_count=4)
    legacy = _make_legacy_notebook(data, one, "lecture one")
    assert resolve_pdf_key(two, data) != legacy


# --- Library / history ----------------------------------------------------------------------------


def as_computer(monkeypatch, name: str) -> None:
    """Both simulated computers run in this one process; give each its own machine id."""
    import pdf_notes_reader.history as history_module

    monkeypatch.setattr(history_module, "machine_id", lambda: name)


def test_history_entry_resolves_on_the_other_machine(machines, monkeypatch) -> None:
    pc, mac = machines
    as_computer(monkeypatch, "pc")
    pc_data, mac_data = pc / "PDFNest", mac / "PDFNest"
    key = resolve_pdf_key(pc / "Books" / "a.pdf", pc_data)
    entries = []
    upsert_history_entry(entries, pdf_key=key, path=pc / "Books" / "a.pdf", page_count=3, last_page_index=2, zoom=1.5)
    save_history(entries, pc_data)
    sync(pc, mac)

    as_computer(monkeypatch, "mac")
    [entry] = load_history(mac_data)
    assert entry.pdf_key == key
    assert entry.rel_path == "../Books/a.pdf"
    assert Path(entry.path) == mac / "Books" / "a.pdf"
    assert entry.exists
    assert entry.last_page_index == 2 and entry.zoom == 1.5


def test_history_save_keeps_books_added_on_the_other_machine(machines, monkeypatch) -> None:
    pc, mac = machines
    as_computer(monkeypatch, "pc")
    pc_data, mac_data = pc / "PDFNest", mac / "PDFNest"
    pdf_factory.create_sample_pdf(pc / "Books" / "b.pdf", page_count=2)
    key_a = resolve_pdf_key(pc / "Books" / "a.pdf", pc_data)
    pc_entries = []
    upsert_history_entry(pc_entries, pdf_key=key_a, path=pc / "Books" / "a.pdf", page_count=3, last_page_index=0)
    save_history(pc_entries, pc_data)
    sync(pc, mac)
    as_computer(monkeypatch, "mac")
    mac_entries = load_history(mac_data)

    # The PC adds b.pdf; then the Mac, still holding its old list, records reading a.pdf.
    key_b = resolve_pdf_key(pc / "Books" / "b.pdf", pc_data)
    as_computer(monkeypatch, "pc")
    upsert_history_entry(pc_entries, pdf_key=key_b, path=pc / "Books" / "b.pdf", page_count=2, last_page_index=1)
    save_history(pc_entries, pc_data)
    sync(pc, mac)
    as_computer(monkeypatch, "mac")
    upsert_history_entry(mac_entries, pdf_key=key_a, path=mac / "Books" / "a.pdf", page_count=3, last_page_index=2)
    save_history(mac_entries, mac_data)

    by_key = {entry.pdf_key: entry for entry in load_history(mac_data)}
    assert set(by_key) == {key_a, key_b}
    assert by_key[key_a].last_page_index == 2
    assert Path(by_key[key_b].path) == mac / "Books" / "b.pdf"
    assert {entry.pdf_key for entry in mac_entries} == {key_a, key_b}  # merged into the open list too


# --- Concurrent edits ---------------------------------------------------------------------------


def test_stale_save_on_one_machine_keeps_the_other_machines_notes(machines) -> None:
    pc, mac = machines
    pc_data, mac_data = pc / "PDFNest", mac / "PDFNest"
    key = resolve_pdf_key(pc / "Books" / "a.pdf", pc_data)
    first = note(key, "first")
    doomed = note(key, "delete me")
    save_notes(pdf_key=key, pdf_path=pc / "Books" / "a.pdf", notes=[first, doomed], data_dir=pc_data)
    sync(pc, mac)

    mac_notes, _counters, _bookmarks = load_notes_data(key, mac_data)  # the Mac opens the PDF
    pc_notes, _c, _b = load_notes_data(key, pc_data)
    pc_notes.append(note(key, "added on the PC"))
    save_notes(pdf_key=key, pdf_path=pc / "Books" / "a.pdf", notes=pc_notes, data_dir=pc_data)
    sync(pc, mac)

    # The Mac, still showing its old list, deletes one note and adds another.
    mac_notes = [item for item in mac_notes if item.id != doomed.id] + [note(key, "added on the Mac")]
    save_notes(pdf_key=key, pdf_path=mac / "Books" / "a.pdf", notes=mac_notes, data_dir=mac_data)

    texts = sorted(item.markdown for item in load_notes(key, mac_data))
    assert texts == ["added on the Mac", "added on the PC", "first"]
    # Saving again (the Mac's list still lacks the PC's note) does not drop it either.
    save_notes(pdf_key=key, pdf_path=mac / "Books" / "a.pdf", notes=mac_notes, data_dir=mac_data)
    assert "added on the PC" in {item.markdown for item in load_notes(key, mac_data)}


def test_note_deleted_on_the_other_machine_stays_deleted(machines) -> None:
    pc, mac = machines
    pc_data, mac_data = pc / "PDFNest", mac / "PDFNest"
    key = resolve_pdf_key(pc / "Books" / "a.pdf", pc_data)
    keep, doomed = note(key, "keep"), note(key, "doomed")
    save_notes(pdf_key=key, pdf_path=pc / "Books" / "a.pdf", notes=[keep, doomed], data_dir=pc_data)
    sync(pc, mac)
    mac_notes, _c, _b = load_notes_data(key, mac_data)
    save_notes(pdf_key=key, pdf_path=pc / "Books" / "a.pdf", notes=[keep], data_dir=pc_data)
    shutil.copy2(notebooks_dir(pc_data) / "a" / "note" / "notes.json", notebooks_dir(mac_data) / "a" / "note" / "notes.json")
    save_notes(pdf_key=key, pdf_path=mac / "Books" / "a.pdf", notes=mac_notes, data_dir=mac_data)
    assert [item.markdown for item in load_notes(key, mac_data)] == ["keep"]


def test_newer_edit_wins_per_note() -> None:
    ours = [{"id": "1", "updated_at": "2026-11-08T10:00:00", "markdown": "old"}]
    theirs = [{"id": "1", "updated_at": "2026-11-08T11:00:00", "markdown": "new"}]
    assert merge_records(ours, theirs, base={"1": "2026-11-08T10:00:00"}) == theirs
    assert merge_records(theirs, ours, base={"1": "2026-11-08T11:00:00"}) == theirs


def test_conflict_copies_are_merged_and_moved_aside(machines) -> None:
    pc, _mac = machines
    data = pc / "PDFNest"
    key = resolve_pdf_key(pc / "Books" / "a.pdf", data)
    save_notes(pdf_key=key, pdf_path=pc / "Books" / "a.pdf", notes=[note(key, "main")], data_dir=data)
    note_dir = notebooks_dir(data) / "a" / "note"
    payload = json.loads((note_dir / "notes.json").read_text(encoding="utf-8"))
    payload["notes"] = [note(key, "from the conflicted copy").to_dict()]
    (note_dir / "notes 2.json").write_text(json.dumps(payload), encoding="utf-8")
    drain_storage_issues()

    texts = sorted(item.markdown for item in load_notes(key, data))
    assert texts == ["from the conflicted copy", "main"]
    assert not (note_dir / "notes 2.json").exists()
    assert list((notebooks_dir(data) / "a" / "conflicts").glob("notes 2.*.json"))
    assert any("conflicting" in issue.message for issue in drain_storage_issues())


@pytest.mark.parametrize(
    "name, is_copy",
    [
        ("notes 2.json", True),
        ("notes (Pat's conflicted copy 2026-11-08).json", True),
        ("notes-DESKTOP-PC.json", True),
        ("notes.corrupt-20261108-101010.json", False),
        ("notes.json.abc123.tmp", False),
        ("notes.json", False),
    ],
)
def test_conflict_copy_names(tmp_path, name, is_copy) -> None:
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    (tmp_path / name).write_text("{}", encoding="utf-8")
    assert (tmp_path / name in conflict_copies(tmp_path / "notes.json")) is is_copy


def test_clobbered_notebook_index_heals(machines) -> None:
    pc, mac = machines
    pc_data = pc / "PDFNest"
    key = resolve_pdf_key(pc / "Books" / "a.pdf", pc_data)
    save_notes(pdf_key=key, pdf_path=pc / "Books" / "a.pdf", notes=[note(key, "indexed")], data_dir=pc_data)
    # The other machine's index.json, written without this notebook, replaced ours.
    notebook_index_path(pc_data).write_text(json.dumps({"schema_version": 1, "notebooks": {"other": "Other"}}), encoding="utf-8")
    assert resolve_pdf_key(pc / "Books" / "a.pdf", pc_data) == key
    assert [item.markdown for item in load_notes(key, pc_data)] == ["indexed"]
    index = json.loads(notebook_index_path(pc_data).read_text(encoding="utf-8"))["notebooks"]
    assert index[key] == "a" and index["other"] == "Other"


# --- iCloud placeholders --------------------------------------------------------------------------


def test_evicted_notes_file_is_downloaded_before_reading(machines, monkeypatch) -> None:
    pc, _mac = machines
    data = pc / "PDFNest"
    key = resolve_pdf_key(pc / "Books" / "a.pdf", data)
    save_notes(pdf_key=key, pdf_path=pc / "Books" / "a.pdf", notes=[note(key, "in the cloud")], data_dir=data)
    notes_file = notebooks_dir(data) / "a" / "note" / "notes.json"
    stash = notes_file.with_name("stash")
    notes_file.rename(stash)
    icloud_stub_for(notes_file).write_text("stub", encoding="utf-8")
    assert portable.is_cloud_placeholder(notes_file)

    def fake_download(path):
        Path(path).write_bytes(stash.read_bytes())
        icloud_stub_for(path).unlink()
        return True

    monkeypatch.setattr(portable, "request_cloud_download", fake_download)
    assert [item.markdown for item in load_notes(key, data)] == ["in the cloud"]


def test_evicted_notes_file_that_does_not_download_is_not_overwritten(machines, monkeypatch) -> None:
    pc, _mac = machines
    data = pc / "PDFNest"
    key = resolve_pdf_key(pc / "Books" / "a.pdf", data)
    save_notes(pdf_key=key, pdf_path=pc / "Books" / "a.pdf", notes=[note(key, "precious")], data_dir=data)
    notes_file = notebooks_dir(data) / "a" / "note" / "notes.json"
    cloud_copy = notes_file.read_bytes()
    notes_file.unlink()
    icloud_stub_for(notes_file).write_text("stub", encoding="utf-8")
    monkeypatch.setattr(portable, "CLOUD_DOWNLOAD_TIMEOUT", 0.0)
    monkeypatch.setattr(portable, "request_cloud_download", lambda path: True)
    drain_storage_issues()

    opened, _counters, _bookmarks = load_notes_data(key, data)  # the reader opens the PDF meanwhile
    assert opened == []
    assert any("downloading from iCloud" in issue.message for issue in drain_storage_issues())
    # The cloud later delivers the file; the next save merges with it instead of replacing it.
    icloud_stub_for(notes_file).unlink()
    notes_file.write_bytes(cloud_copy)
    save_notes(pdf_key=key, pdf_path=pc / "Books" / "a.pdf", notes=[note(key, "new")], data_dir=data)
    assert sorted(item.markdown for item in load_notes(key, data)) == ["new", "precious"]


# --- Per-machine settings -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "path_text, platform, native",
    [
        (r"C:\Users\x\Vault", "win32", True),
        (r"\\server\share", "win32", True),
        ("/Users/x/Vault", "win32", False),
        ("/Users/x/Vault", "darwin", True),
        (r"C:\Users\x\Vault", "darwin", False),
        ("~/Vault", "darwin", True),
        ("", "darwin", False),
    ],
)
def test_native_absolute_path(path_text, platform, native) -> None:
    assert is_native_absolute_path(path_text, platform=platform) is native


def test_machine_settings_stay_on_this_computer(tmp_path) -> None:
    shared = tmp_path / "cloud" / "PDFNest"
    settings = load_settings(shared)
    settings.update({"theme": "white", "window_width": 1500, "obsidian_vault_dir": str(tmp_path / "vault")})
    save_settings(settings, data_dir=shared)
    machine = json.loads(machine_settings_path().read_text(encoding="utf-8"))
    assert machine["window_width"] == 1500
    assert machine["obsidian_vault_dir"] == str(tmp_path / "vault")
    assert "theme" not in machine

    # The other computer saves the shared file with its own window size and a vault path of its OS.
    other_os_vault = "/Users/x/Vault" if is_native_absolute_path(r"C:\x") else r"C:\Users\x\Vault"
    payload = json.loads(settings_path(shared).read_text(encoding="utf-8"))
    payload.update({"theme": "beige", "window_width": 900, "obsidian_vault_dir": other_os_vault, "last_pdf_dir": other_os_vault})
    settings_path(shared).write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_settings(shared)
    assert loaded["theme"] == "beige"  # preferences are shared
    assert loaded["window_width"] == 1500  # this computer's window
    assert loaded["obsidian_vault_dir"] == str(tmp_path / "vault")

    # A computer with no machine file yet ignores folders written for the other OS.
    machine_settings_path().unlink()
    fresh = load_settings(shared)
    assert fresh["obsidian_vault_dir"] == ""
    assert fresh["last_pdf_dir"] == ""
    assert fresh["window_width"] == 900


# --- Each computer keeps its own path to the PDF -------------------------------------------------


def test_each_computer_keeps_its_own_pdf_path(tmp_path, monkeypatch) -> None:
    """The PDF lives in a different, unsynced place on each computer; the user locates it once there."""
    import pdf_notes_reader.history as history_module

    shared = tmp_path / "cloud" / "PDFNest"
    pc_pdf = tmp_path / "pc-disk" / "Books" / "a.pdf"
    mac_pdf = tmp_path / "mac-disk" / "Downloads" / "renamed.pdf"
    for pdf in (pc_pdf, mac_pdf):
        pdf.parent.mkdir(parents=True)
    pdf_factory.create_sample_pdf(pc_pdf, page_count=3)
    shutil.copy2(pc_pdf, mac_pdf)

    monkeypatch.setattr(history_module, "machine_id", lambda: "pc")
    key = resolve_pdf_key(pc_pdf, shared)
    pc_entries = []
    upsert_history_entry(pc_entries, pdf_key=key, path=pc_pdf, page_count=3, last_page_index=1)
    save_history(pc_entries, shared)

    monkeypatch.setattr(history_module, "machine_id", lambda: "mac")
    shutil.move(str(tmp_path / "pc-disk"), str(tmp_path / "pc-disk-hidden"))  # the Mac cannot see the PC's disk
    [entry] = load_history(shared)
    assert not entry.exists and not entry.located_here  # shown as "locate it", with notes and cover
    mac_entries = [entry]
    # The user locates the file; the same book (same key) now has the Mac's path too.
    assert resolve_pdf_key(mac_pdf, shared) == key
    upsert_history_entry(mac_entries, pdf_key=key, path=mac_pdf, page_count=3, last_page_index=2)
    save_history(mac_entries, shared)

    shutil.move(str(tmp_path / "pc-disk-hidden"), str(tmp_path / "pc-disk"))
    monkeypatch.setattr(history_module, "machine_id", lambda: "pc")
    [on_pc] = load_history(shared)
    assert Path(on_pc.path) == pc_pdf.resolve()  # the Mac's relocation did not break the PC
    assert on_pc.last_page_index == 2  # but its reading position came along
    assert set(on_pc.machine_paths) == {"pc", "mac"}

    # The PC saves its stale list again: the Mac's path survives the merge.
    upsert_history_entry(pc_entries, pdf_key=key, path=pc_pdf, page_count=3, last_page_index=2)
    save_history(pc_entries, shared)
    monkeypatch.setattr(history_module, "machine_id", lambda: "mac")
    [on_mac] = load_history(shared)
    assert Path(on_mac.path) == mac_pdf.resolve()
