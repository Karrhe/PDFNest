from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

from pdf_notes_reader.portable import (
    conflict_copies,
    ensure_local,
    foreign_basename,
    is_cloud_placeholder,
    merge_records,
    move_aside,
    normalize_portable,
    pdf_fingerprint,
    portable_relpath,
    record_stamps,
)


APP_NAME = "PDFNest"
STORAGE_DIR_NAME = "Note_PDFNest"
# Highlights and underlines: marked text that may carry one optional note of its own.
ANNOTATION_TYPES = frozenset({"highlight", "underline"})


@dataclass
class Note:
    id: str
    pdf_key: str
    page_index: int
    x_norm: float
    y_norm: float
    markdown: str
    created_at: str
    updated_at: str
    note_type: str = "point"
    rects_norm: list[list[float]] = field(default_factory=list)
    selected_text: str = ""
    color: str = ""
    linked_note_id: str = ""
    marker_style: str = "dashed_underline"
    note_number: int = 0
    exported_markdown_path: str = ""
    # Obsidian vault sync: the note's file relative to the vault, and the hash of the file text
    # PDFNest last wrote or read (see services/obsidian.py).
    vault_path: str = ""
    vault_hash: str = ""
    # Highlights and underlines start without a note; the user adds one (at most one) on request.
    # Point notes always are notes.
    has_note: bool = True

    @classmethod
    def create(
        cls,
        *,
        pdf_key: str,
        page_index: int,
        x_norm: float,
        y_norm: float,
        markdown: str = "",
        note_type: str = "point",
        rects_norm: list[list[float]] | None = None,
        selected_text: str = "",
        color: str = "",
        linked_note_id: str = "",
        marker_style: str = "dashed_underline",
        note_number: int = 0,
        exported_markdown_path: str = "",
        has_note: bool = True,
    ) -> "Note":
        now = utc_now()
        return cls(
            id=str(uuid.uuid4()),
            pdf_key=pdf_key,
            page_index=page_index,
            x_norm=clamp01(x_norm),
            y_norm=clamp01(y_norm),
            markdown=markdown,
            created_at=now,
            updated_at=now,
            note_type=note_type,
            rects_norm=rects_norm or [],
            selected_text=selected_text,
            color=str(color),
            linked_note_id=str(linked_note_id),
            marker_style=str(marker_style or "dashed_underline"),
            note_number=max(0, int(note_number)),
            exported_markdown_path=str(exported_markdown_path),
            has_note=bool(has_note),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Note":
        note_type = str(data.get("note_type") or "point")
        markdown = str(data.get("markdown", ""))
        if "has_note" in data:
            has_note = bool(data["has_note"])
        else:
            has_note = note_type not in ANNOTATION_TYPES or _legacy_annotation_has_note(markdown)
        return cls(
            id=str(data["id"]),
            pdf_key=str(data["pdf_key"]),
            page_index=int(data["page_index"]),
            x_norm=clamp01(float(data["x_norm"])),
            y_norm=clamp01(float(data["y_norm"])),
            markdown=markdown,
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            note_type=note_type,
            rects_norm=normalize_rects(data.get("rects_norm", [])),
            selected_text=str(data.get("selected_text", "")),
            color=str(data.get("color", "")),
            linked_note_id=str(data.get("linked_note_id", "")),
            marker_style=str(data.get("marker_style") or "dashed_underline"),
            note_number=normalize_nonnegative_int(data.get("note_number"), default=0),
            exported_markdown_path=str(data.get("exported_markdown_path", "")),
            vault_path=str(data.get("vault_path", "")),
            vault_hash=str(data.get("vault_hash", "")),
            has_note=has_note,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def update_markdown(self, markdown: str) -> None:
        self.markdown = markdown
        self.updated_at = utc_now()


@dataclass
class Bookmark:
    id: str
    pdf_key: str
    page_index: int
    title: str
    created_at: str

    @classmethod
    def create(cls, *, pdf_key: str, page_index: int, title: str) -> "Bookmark":
        return cls(
            id=str(uuid.uuid4()),
            pdf_key=pdf_key,
            page_index=max(0, int(page_index)),
            title=str(title).strip() or f"Page {page_index + 1}",
            created_at=utc_now(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Bookmark":
        return cls(
            id=str(data["id"]),
            pdf_key=str(data["pdf_key"]),
            page_index=max(0, int(data["page_index"])),
            title=str(data.get("title") or f"Page {int(data['page_index']) + 1}"),
            created_at=str(data.get("created_at") or utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _legacy_annotation_has_note(markdown: str) -> bool:
    """Older highlights were always given a note holding only a title and the quoted text. Those
    count as having no note; any line the user wrote beyond the title and quote makes it a note."""
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", ">")):
            return True
    return False


def is_annotation(note: Note) -> bool:
    return note.note_type in ANNOTATION_TYPES


def shows_as_note(note: Note) -> bool:
    """Whether the note is a note the user writes in: a point note, or an annotation's added note."""
    if note.note_type == "point":
        return True
    return is_annotation(note) and note.has_note


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalize_rects(value: Any) -> list[list[float]]:
    if not isinstance(value, list):
        return []

    rects: list[list[float]] = []
    for item in value:
        if not isinstance(item, list | tuple) or len(item) != 4:
            continue
        rects.append([clamp01(float(coord)) for coord in item])
    return rects


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def macos_app_support_dir(home: Path | None = None) -> Path:
    """``~/Library/Application Support/PDFNest``: where a Mac app keeps its data."""
    return (home or Path.home()) / "Library" / "Application Support" / APP_NAME


def app_data_root(*, platform: str | None = None, frozen: bool | None = None, home: Path | None = None) -> Path:
    """The folder holding ``.local-data`` and the default note store.

    Windows builds and source checkouts keep data next to the program (portable). A frozen macOS
    ``PDFNest.app`` cannot: ``sys.executable`` lives in the signed, often read-only
    ``PDFNest.app/Contents/MacOS``, and replacing the app would delete the notes. It uses
    Application Support instead.
    """
    platform = sys.platform if platform is None else platform
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if frozen and platform == "darwin":
        return macos_app_support_dir(home)
    return app_base_dir()


def app_local_data_dir() -> Path:
    return app_data_root() / ".local-data"


def storage_pointer_path() -> Path:
    return app_local_data_dir() / "storage_location.json"


def machine_settings_path() -> Path:
    """Settings that belong to this computer (window size, folders on this disk). Never synced."""
    return storage_pointer_path().parent / "machine_settings.json"


_MACHINE_IDS: dict[str, str] = {}


def machine_id() -> str:
    """A random id for this computer, kept beside the data-folder pointer (never in the synced data).

    Library entries remember the PDF's path per computer under this id, so a Mac and a PC sharing a
    data folder can each keep the book wherever they like.
    """
    path = storage_pointer_path().parent / "machine_id.txt"
    cached = _MACHINE_IDS.get(str(path))
    if cached:
        return cached
    value = ""
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        value = uuid.uuid4().hex
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value + "\n", encoding="utf-8")
        except OSError:
            pass  # still unique for this run
    _MACHINE_IDS[str(path)] = value
    return value


def _read_storage_pointer() -> Path | None:
    path = storage_pointer_path()
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = str(payload.get("data_dir") or "").strip()
    return Path(value).expanduser() if value else None


def set_configured_data_dir(data_dir: str | Path) -> Path:
    path = Path(data_dir).expanduser()
    _atomic_write_json(storage_pointer_path(), {"data_dir": str(path)})
    return path


def default_data_dir() -> Path:
    override = os.environ.get("PDF_NOTES_READER_DATA_DIR")
    if override:
        return Path(override).expanduser()

    local = app_data_root() / STORAGE_DIR_NAME
    configured = _read_storage_pointer()
    if configured is not None:
        if configured.exists():
            return configured
        # The configured folder is gone (drive unplugged, folder moved or deleted). Silently creating
        # an empty store there would look like all notes were lost, so prefer the local store when it
        # exists or when the configured drive is missing, and tell the user once.
        if local.exists() or not Path(configured.anchor or os.sep).exists():
            _report_missing_configured_dir(configured, local)
            return local
        return configured

    return local


_reported_missing_dirs: set[str] = set()


def _report_missing_configured_dir(configured: Path, fallback: Path) -> None:
    key = str(configured)
    if key in _reported_missing_dirs:
        return
    _reported_missing_dirs.add(key)
    record_storage_issue(
        f"The configured PDFNest data folder was not found, so the local folder {fallback} is used. "
        "Choose the data folder again in Settings if it moved.",
        configured,
    )


def notes_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "notes"


def notebooks_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "notebooks"


def notebook_index_path(data_dir: Path | None = None) -> Path:
    return notebooks_dir(data_dir) / "index.json"


def bookmarks_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "bookmarks"


def root_sync_lock_path(data_dir: Path | None = None) -> Path:
    return bookmarks_dir(data_dir) / "sync.lock"


def _write_sync_lock(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PDFNest sync lock\n", encoding="utf-8")


def safe_folder_name(value: str, *, max_length: int = 96) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    cleaned = re.sub(r"\s+", " ", cleaned) or "Untitled PDF"
    if len(cleaned) <= max_length:
        return cleaned
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[: max_length - 9].rstrip()}-{digest}"


def pdf_key_for_path(pdf_path: str | Path) -> str:
    path = Path(pdf_path).expanduser()
    try:
        canonical = path.resolve(strict=False)
    except OSError:
        canonical = path.absolute()

    normalized = os.path.normcase(str(canonical))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


@dataclass
class NotebookLocator:
    """What a notebook's manifest says about its PDF, for finding it from another machine."""

    pdf_key: str
    folder: Path
    relpath: str  # normalized, relative to the data folder
    fingerprint: str
    name: str  # normalized file name
    refpath: str


_LOCATOR_CACHE: dict[str, tuple[tuple[int, int], list[NotebookLocator]]] = {}


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def notebook_locators(data_dir: Path | None = None) -> list[NotebookLocator]:
    """Reads every notebook manifest once; cached until a notebook is added (here or by sync)."""
    root = notebooks_dir(data_dir)
    stamp = (_mtime_ns(root), _mtime_ns(root / "index.json"))
    cached = _LOCATOR_CACHE.get(str(root))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    locators: list[NotebookLocator] = []
    if root.exists():
        for manifest_path in sorted(root.glob("*/manifest.json")):
            try:
                payload = _read_json_path(manifest_path)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(payload, dict) or not payload.get("pdf_key"):
                continue
            refpath = ""
            resources = payload.get("res")
            if isinstance(resources, list) and resources and isinstance(resources[0], dict):
                refpath = str(resources[0].get("refpath") or "")
            locators.append(
                NotebookLocator(
                    pdf_key=str(payload["pdf_key"]),
                    folder=manifest_path.parent,
                    relpath=normalize_portable(str(payload.get("relpath") or "")),
                    fingerprint=str(payload.get("fingerprint") or ""),
                    name=normalize_portable(foreign_basename(refpath)) if refpath else "",
                    refpath=refpath,
                )
            )
    _LOCATOR_CACHE[str(root)] = (stamp, locators)
    return locators


def resolve_pdf_key(pdf_path: str | Path, data_dir: Path | None = None) -> str:
    """The key of the notebook that belongs to ``pdf_path``, on this machine or any other.

    A key is an opaque ID chosen when a PDF is first seen and kept forever, so notes never move. It
    is found again by, in order:

    1. this machine's old path key (notebooks made before portable lookup, and same-path reopens);
    2. the path relative to the data folder: identical on Windows and macOS when both the data folder
       and the PDFs live in the cloud drive;
    3. the content fingerprint: the PDF was moved, or lives outside the data folder's drive;
    4. for an old notebook made on another machine (no fingerprint yet), a unique file-name match.

    Steps 3 and 4 skip a notebook whose recorded PDF still exists here at another path: that is a
    second copy on this computer, and each copy keeps its own notes.

    A PDF seen for the first time gets a key derived from its relative path, so two computers that open
    a new PDF in the cloud drive before the cloud has synced still pick the same notebook. A PDF on
    another drive than the data folder gets the path key.
    """
    data_dir = data_dir or default_data_dir()
    path = Path(pdf_path).expanduser()
    legacy = pdf_key_for_path(path)
    index = _load_notebook_index(data_dir)
    root = notebooks_dir(data_dir)
    if legacy in index and (root / index[legacy]).exists():
        return legacy
    locators = notebook_locators(data_dir)
    if any(locator.pdf_key == legacy for locator in locators):
        return legacy

    relpath = normalize_portable(portable_relpath(path, data_dir))
    if relpath:
        for locator in locators:
            if locator.relpath == relpath:
                return locator.pdf_key

    fingerprint = pdf_fingerprint(path)
    if fingerprint:
        for locator in locators:
            if locator.fingerprint == fingerprint and not _is_other_local_file(locator.refpath, path):
                return locator.pdf_key

    name = normalize_portable(path.name)
    candidates = [
        locator
        for locator in locators
        if not locator.fingerprint and locator.name == name and not _is_other_local_file(locator.refpath, path)
    ]
    if len(candidates) == 1:
        return candidates[0].pdf_key
    return new_pdf_key(path, data_dir)


def new_pdf_key(pdf_path: str | Path, data_dir: Path | None = None) -> str:
    """The key for a PDF without a notebook: a hash of its path relative to the data folder.

    The relative path is the same on every computer sharing the data folder, unlike the absolute path
    behind ``pdf_key_for_path``, which is still used for a PDF on another drive (no relative path).
    """
    relpath = normalize_portable(portable_relpath(pdf_path, data_dir or default_data_dir()))
    if not relpath:
        return pdf_key_for_path(pdf_path)
    return hashlib.sha256(f"pdfnest-relpath\0{relpath}".encode("utf-8")).hexdigest()[:24]


def _is_other_local_file(refpath: str, path: Path) -> bool:
    """Whether ``refpath`` is a file on this computer other than ``path`` (a second copy of the PDF)."""
    try:
        if not refpath or not Path(refpath).exists():
            return False
        return os.path.normcase(str(Path(refpath).resolve(strict=False))) != os.path.normcase(str(path.resolve(strict=False)))
    except (OSError, ValueError):
        return False


@dataclass
class StorageIssue:
    message: str
    path: Path
    quarantined_path: Path | None = None


_STORAGE_ISSUES: list[StorageIssue] = []


def record_storage_issue(message: str, path: Path, quarantined_path: Path | None = None) -> StorageIssue:
    issue = StorageIssue(message=message, path=path, quarantined_path=quarantined_path)
    _STORAGE_ISSUES.append(issue)
    return issue


def drain_storage_issues() -> list[StorageIssue]:
    """Returns and clears storage problems found since the last call, for the UI to report once."""
    issues = list(_STORAGE_ISSUES)
    _STORAGE_ISSUES.clear()
    return issues


def quarantine_file(path: Path) -> Path:
    """Moves an unreadable file aside so later saves cannot overwrite the only copy of the data."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.corrupt-{stamp}-{counter}{path.suffix}")
        counter += 1
    os.replace(path, candidate)
    return candidate


def read_json_checked(path: Path) -> Any | None:
    """Reads JSON, or returns None. Corrupt files are quarantined and reported instead of raising.

    A file iCloud evicted to a ``.name.icloud`` stub is downloaded first; if that does not finish in
    time it is reported, because "no file" would otherwise read as "no data".
    """
    if not ensure_local(path):
        if is_cloud_placeholder(path):
            record_storage_issue(f"{path.name} is still downloading from iCloud; reopen the PDF in a moment.", path)
        return None
    try:
        return _read_json_path(path)
    except (json.JSONDecodeError, UnicodeDecodeError):
        try:
            quarantined = quarantine_file(path)
        except OSError:
            quarantined = None
        record_storage_issue(f"{path.name} was unreadable and has been set aside.", path, quarantined)
        return None
    except OSError as exc:
        record_storage_issue(f"{path.name} could not be read: {exc}", path)
        return None


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Writes to a unique temp file, flushes it to disk, then atomically replaces the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def legacy_notes_path_for_key(pdf_key: str, data_dir: Path | None = None) -> Path:
    return notes_dir(data_dir) / f"{pdf_key}.json"


def _read_json_path(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_notebook_index(data_dir: Path | None = None) -> dict[str, str]:
    path = notebook_index_path(data_dir)
    if not path.exists():
        return {}
    payload = read_json_checked(path)
    if not isinstance(payload, dict):
        return rebuild_notebook_index(data_dir)
    notebooks = payload.get("notebooks", payload)
    if not isinstance(notebooks, dict):
        return {}
    return {str(key): str(value) for key, value in notebooks.items() if str(key) and str(value)}


def _save_notebook_index(index: dict[str, str], data_dir: Path | None = None) -> None:
    payload = {
        "schema_version": 1,
        "app": APP_NAME,
        "notebooks": dict(sorted(index.items())),
    }
    _atomic_write_json(notebook_index_path(data_dir), payload)
    _LOCATOR_CACHE.clear()


def register_notebook_dir(pdf_key: str, notebook_dir: Path, data_dir: Path | None = None) -> None:
    index = _load_notebook_index(data_dir)
    index[str(pdf_key)] = notebook_dir.name
    _save_notebook_index(index, data_dir)


def rebuild_notebook_index(data_dir: Path | None = None) -> dict[str, str]:
    root = notebooks_dir(data_dir)
    index: dict[str, str] = {}
    if not root.exists():
        _save_notebook_index(index, data_dir)
        return index
    for manifest_path in root.glob("*/manifest.json"):
        try:
            payload = _read_json_path(manifest_path)
        except (OSError, json.JSONDecodeError):
            continue
        manifest_key = str(payload.get("pdf_key") or "") if isinstance(payload, dict) else ""
        if manifest_key:
            index[manifest_key] = manifest_path.parent.name
            continue
        resources = payload.get("res") if isinstance(payload, dict) else None
        if isinstance(resources, list):
            for item in resources:
                key = str(item.get("pdf_key") or item.get("uuid") or "") if isinstance(item, dict) else ""
                if key:
                    index[key] = manifest_path.parent.name
                    break
    _save_notebook_index(index, data_dir)
    return index


def notebook_dir_for_key(pdf_key: str, data_dir: Path | None = None) -> Path | None:
    root = notebooks_dir(data_dir)
    index = _load_notebook_index(data_dir)
    if not index and not notebook_index_path(data_dir).exists():
        index = rebuild_notebook_index(data_dir)
    folder_name = index.get(pdf_key)
    candidate = root / folder_name if folder_name else None
    if candidate is not None and candidate.exists():
        return candidate
    # Stale index: the notebook may exist on disk without an index entry.
    found = _find_notebook_by_manifest(pdf_key, data_dir)
    if found is not None:
        register_notebook_dir(pdf_key, found, data_dir)
    return found


def _find_notebook_by_manifest(pdf_key: str, data_dir: Path | None = None) -> Path | None:
    root = notebooks_dir(data_dir)
    if not root.exists():
        return None
    for manifest_path in root.glob("*/manifest.json"):
        try:
            payload = _read_json_path(manifest_path)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict) and str(payload.get("pdf_key") or "") == pdf_key:
            return manifest_path.parent
    return None


def notebook_dir_for_pdf(pdf_path: str | Path, pdf_key: str, data_dir: Path | None = None) -> Path:
    existing = notebook_dir_for_key(pdf_key, data_dir)
    if existing is not None:
        return existing

    root = notebooks_dir(data_dir)
    base_name = safe_folder_name(Path(pdf_path).stem)
    candidate = root / base_name
    if not candidate.exists():
        register_notebook_dir(pdf_key, candidate, data_dir)
        return candidate

    manifest_path = candidate / "manifest.json"
    try:
        payload = _read_json_path(manifest_path)
    except (OSError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict) and str(payload.get("pdf_key") or "") in {"", pdf_key}:
        register_notebook_dir(pdf_key, candidate, data_dir)
        return candidate
    candidate = root / f"{base_name}-{pdf_key[:8]}"
    register_notebook_dir(pdf_key, candidate, data_dir)
    return candidate


def notes_path_for_key(pdf_key: str, data_dir: Path | None = None) -> Path:
    notebook_dir = notebook_dir_for_key(pdf_key, data_dir)
    if notebook_dir is not None:
        return notebook_dir / "note" / "notes.json"
    return notebooks_dir(data_dir) / pdf_key / "note" / "notes.json"


def legacy_notebook_note_file_for_key(pdf_key: str, data_dir: Path | None = None) -> Path | None:
    notebook_dir = notebook_dir_for_key(pdf_key, data_dir)
    if notebook_dir is None:
        candidate = notebooks_dir(data_dir) / pdf_key / "note"
        return candidate if candidate.exists() and candidate.is_file() else None
    candidate = notebook_dir / "note"
    return candidate if candidate.exists() and candidate.is_file() else None


def bookmark_path_for_key(pdf_key: str, data_dir: Path | None = None) -> Path:
    return bookmarks_dir(data_dir) / f"{pdf_key}_bookmark.json"


def load_notes(pdf_key: str, data_dir: Path | None = None) -> list[Note]:
    """Read-only view (search, summaries): does not change what the next save merges against."""
    notes, _counters, _bookmarks = load_notes_data(pdf_key, data_dir, track=False)
    return notes


def load_notes_with_counters(pdf_key: str, data_dir: Path | None = None) -> tuple[list[Note], dict[str, int]]:
    notes, counters, _bookmarks = load_notes_data(pdf_key, data_dir)
    return notes, counters


def load_notes_data(
    pdf_key: str, data_dir: Path | None = None, *, track: bool = True
) -> tuple[list[Note], dict[str, int], list[Bookmark]]:
    """Loads a notebook for editing. With ``track`` the next ``save_notes`` treats records missing
    from the saved list as deleted here; records another machine adds meanwhile are kept."""
    payload = load_notes_payload(pdf_key, data_dir, track=track)
    raw_notes = payload.get("notes", [])
    if not isinstance(raw_notes, list):
        raw_notes = []

    notes: list[Note] = []
    for item in raw_notes:
        if isinstance(item, dict):
            notes.append(Note.from_dict(item))

    bookmark_payload = load_bookmarks_payload(pdf_key, data_dir, track=track)
    raw_bookmarks = bookmark_payload.get("bookmarks", payload.get("bookmarks", []))
    if not isinstance(raw_bookmarks, list):
        raw_bookmarks = []

    bookmarks: list[Bookmark] = []
    for item in raw_bookmarks:
        if isinstance(item, dict):
            try:
                bookmarks.append(Bookmark.from_dict(item))
            except (KeyError, TypeError, ValueError):
                continue
    return notes, normalize_note_counters(payload.get("note_counters", {})), bookmarks


# The records this process last loaded per notebook file, or the caller's list it last saved: a
# record that differs changed here, one missing was deleted here (see sync_store.save_records).
_SYNC_BASES: dict[str, dict[str, Any]] = {}


def _sync_base_key(path: Path) -> str:
    return os.path.normcase(str(path))


def _note_records(payload: dict[str, Any]) -> dict[str, Any]:
    records: dict[str, Any] = {f"note:{item['id']}": item for item in _dict_list(payload.get("notes")) if item.get("id")}
    for page, counter in normalize_note_counters(payload.get("note_counters", {})).items():
        records[f"counter:{page}"] = counter
    return records


def _bookmark_records(payload: dict[str, Any]) -> dict[str, Any]:
    return {f"bookmark:{item['id']}": item for item in _dict_list(payload.get("bookmarks")) if item.get("id")}


def _keep_highest_counter(winner: Any, versions: list[tuple[str, Any]]) -> Any:
    """Note counters only grow; keep the highest any computer reached so numbers are never reused."""
    if isinstance(winner, int) and not isinstance(winner, bool):
        return max([winner] + [data for _stamp, data in versions if isinstance(data, int) and not isinstance(data, bool)])
    return winner


def _payload_from_records(records: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    payload = dict(template)
    # Records keep the order the notes were saved in; notes from another computer follow.
    payload["notes"] = [data for key, data in records.items() if key.startswith("note:") and isinstance(data, dict)]
    payload["note_counters"] = {key[len("counter:"):]: data for key, data in records.items() if key.startswith("counter:")}
    return payload


def _bookmarks_from_records(records: dict[str, Any]) -> list[dict[str, Any]]:
    return [data for key, data in records.items() if key.startswith("bookmark:") and isinstance(data, dict)]


def load_notes_payload(pdf_key: str, data_dir: Path | None = None, *, track: bool = True) -> dict[str, Any]:
    """The notebook as every computer sharing the data folder saved it (see ``sync_store``)."""
    from pdf_notes_reader import sync_store

    notes_path = notes_path_for_key(pdf_key, data_dir)
    payload = _legacy_notes_payload(pdf_key, data_dir)
    records = sync_store.load_records(notes_path, _note_records(payload), combine=_keep_highest_counter)
    payload = _payload_from_records(records, payload)
    if track:
        _SYNC_BASES[_sync_base_key(notes_path)] = records
    return payload


def _legacy_notes_payload(pdf_key: str, data_dir: Path | None) -> dict[str, Any]:
    """The plain notes.json (or an older notes file): data from before per-computer replicas."""
    path = notes_path_for_key(pdf_key, data_dir)
    if ensure_local(path):
        _absorb_notes_conflicts(path)
    elif is_cloud_placeholder(path):
        pass  # read_json_checked reports it; never fall back to an older copy meanwhile
    else:
        legacy_notebook_path = legacy_notebook_note_file_for_key(pdf_key, data_dir)
        path = legacy_notebook_path or legacy_notes_path_for_key(pdf_key, data_dir)
    payload = read_json_checked(path)
    return payload if isinstance(payload, dict) else {}


def load_bookmarks_payload(pdf_key: str, data_dir: Path | None = None, *, track: bool = True) -> dict[str, Any]:
    from pdf_notes_reader import sync_store

    path = bookmark_path_for_key(pdf_key, data_dir)
    records = sync_store.load_records(path, _bookmark_records(_legacy_bookmarks_payload(path)))
    if track:
        _SYNC_BASES[_sync_base_key(path)] = records
    return {"schema_version": 1, "app": APP_NAME, "bookmarks": _bookmarks_from_records(records)}


def _legacy_bookmarks_payload(path: Path) -> dict[str, Any]:
    if ensure_local(path):
        _absorb_conflicts(path, _merge_bookmark_payloads, path.parent / "conflicts")
    payload = read_json_checked(path)
    return payload if isinstance(payload, dict) else {}


def _merge_notes_payloads(ours: dict[str, Any], theirs: dict[str, Any], base: dict[str, str] | None = None) -> dict[str, Any]:
    merged = dict(theirs)
    merged.update(ours)
    merged["notes"] = merge_records(_dict_list(ours.get("notes")), _dict_list(theirs.get("notes")), base=base)
    merged["bookmarks"] = merge_records(
        _dict_list(ours.get("bookmarks")), _dict_list(theirs.get("bookmarks")), base=None, stamp="created_at"
    )
    counters = normalize_note_counters(theirs.get("note_counters", {}))
    for key, value in normalize_note_counters(ours.get("note_counters", {})).items():
        counters[key] = max(value, counters.get(key, 0))
    merged["note_counters"] = counters
    return merged


def _merge_bookmark_payloads(ours: dict[str, Any], theirs: dict[str, Any], base: dict[str, str] | None = None) -> dict[str, Any]:
    merged = dict(theirs)
    merged.update(ours)
    merged["bookmarks"] = merge_records(
        _dict_list(ours.get("bookmarks")), _dict_list(theirs.get("bookmarks")), base=base, stamp="created_at"
    )
    return merged


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _absorb_notes_conflicts(path: Path) -> None:
    _absorb_conflicts(path, _merge_notes_payloads, path.parent.parent / "conflicts")


def _absorb_conflicts(path: Path, merge, conflicts_dir: Path) -> None:
    """Merges sync-client conflict copies (``notes 2.json``...) into ``path`` and moves them aside.

    Records are combined, never dropped, so a note written on either machine survives; the copies are
    kept in ``conflicts/`` in case something needs to be recovered by hand.
    """
    copies = conflict_copies(path)
    if not copies:
        return
    current = read_json_checked(path)
    merged = current if isinstance(current, dict) else {}
    absorbed: list[Path] = []
    for copy in copies:
        try:
            other = _read_json_path(copy)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(other, dict):
            merged = merge(merged, other, None)
            absorbed.append(copy)
    if not absorbed:
        return
    _atomic_write_json(path, merged)
    for copy in absorbed:
        move_aside(copy, conflicts_dir)
    record_storage_issue(
        f"{path.name} had {len(absorbed)} conflicting cop{'y' if len(absorbed) == 1 else 'ies'} from cloud sync; "
        f"they were merged and kept in {conflicts_dir}.",
        path,
    )


def normalize_note_counters(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counters: dict[str, int] = {}
    for key, counter in value.items():
        try:
            counters[str(key)] = max(1, int(counter))
        except (TypeError, ValueError):
            continue
    return counters


def normalize_nonnegative_int(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def portable_locators(pdf_path: str | Path, data_dir: Path | None = None, previous: dict[str, Any] | None = None) -> dict[str, str]:
    """The ``relpath`` and ``fingerprint`` a manifest records so other machines find the notebook.

    A PDF that is not readable here (missing, or a cloud placeholder that would start a download)
    keeps what the manifest recorded before.
    """
    previous = previous or {}
    locators = {
        "relpath": str(previous.get("relpath") or ""),
        "fingerprint": str(previous.get("fingerprint") or ""),
    }
    path = Path(pdf_path).expanduser()
    try:
        available = path.is_file() and not is_cloud_placeholder(path)
    except OSError:
        available = False
    if not available:
        return locators
    locators["relpath"] = portable_relpath(path, data_dir or default_data_dir())
    locators["fingerprint"] = pdf_fingerprint(path) or locators["fingerprint"]
    return locators


def read_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        payload = _read_json_path(manifest_path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _manifest_payload(
    *,
    pdf_key: str,
    pdf_path: str | Path,
    page_count: int = 0,
    data_dir: Path | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(pdf_path).expanduser()
    return {
        "schema_version": 1,
        "app": APP_NAME,
        "pdf_key": pdf_key,
        **portable_locators(path, data_dir, previous),
        "resid": 1,
        "res": [
            {
                "id": 0,
                "name": path.name,
                "refpath": str(path),
                "refhash": pdf_key,
                "uuid": pdf_key,
                "ftype": 0,
                "autoopen": False,
                "page_count": max(0, int(page_count)),
            }
        ],
    }


def _manifest_page_count(manifest_path: Path) -> int:
    try:
        payload = _read_json_path(manifest_path)
        return normalize_nonnegative_int(payload["res"][0].get("page_count", 0))
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return 0


def _markups_payload(notes: list[Note]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "app": APP_NAME,
        "markups": [note.to_dict() for note in notes if note.note_type != "point"],
    }


def _recent_file_payload(*, page_index: int, zoom: float = 1.25) -> list[dict[str, Any]]:
    return [
        {
            "~docid": 0,
            "~entry": "",
            "~mod": utc_now(),
            "~view": [max(0, int(page_index)), -1, round(max(0.3, min(4.0, zoom)) * 100, 4)],
        }
    ]


def _ensure_cover(pdf_path: str | Path, notebook_dir: Path) -> None:
    cover_path = notebook_dir / "cover.png"
    if cover_path.exists() or is_cloud_placeholder(pdf_path):
        return  # A cover is not worth downloading a whole book from the cloud.
    try:
        document = fitz.open(pdf_path)
    except Exception:
        return
    try:
        # Password-protected PDFs get no cover: the thumbnail would need the password again.
        if document.needs_pass or document.page_count <= 0:
            return
        page = document.load_page(0)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(0.45, 0.45), alpha=False)
        notebook_dir.mkdir(parents=True, exist_ok=True)
        pixmap.save(cover_path)
    except Exception:  # A cover is cosmetic; it must never break saving notes or history.
        return
    finally:
        document.close()


def save_notes(
    *,
    pdf_key: str,
    pdf_path: str | Path,
    notes: list[Note],
    note_counters: dict[str, int] | None = None,
    bookmarks: list[Bookmark] | None = None,
    data_dir: Path | None = None,
) -> Path:
    notebook_dir = notebook_dir_for_pdf(pdf_path, pdf_key, data_dir)
    path = notebook_dir / "note" / "notes.json"
    bookmark_path = bookmark_path_for_key(pdf_key, data_dir)
    current_bookmarks = bookmarks or []

    payload = {
        "pdf_key": pdf_key,
        "pdf_path": str(Path(pdf_path).expanduser()),
        "schema_version": 1,
        "app": APP_NAME,
        "note_counters": normalize_note_counters(note_counters or {}),
        "bookmarks": [bookmark.to_dict() for bookmark in current_bookmarks],
        "notes": [note.to_dict() for note in notes],
    }
    notebook_dir.mkdir(parents=True, exist_ok=True)
    # Each computer sharing the data folder records only its own changes, in its own replica (see
    # sync_store): a note added on the other computer is never overwritten by a stale save here,
    # and a note disappears only when it was deleted, never because a copy lacked it.
    from pdf_notes_reader import sync_store

    current = _note_records(payload)
    current_bookmarks_records = _bookmark_records(payload)
    try:
        merged = sync_store.save_records(
            path,
            current,
            _SYNC_BASES.get(_sync_base_key(path)),
            legacy=_note_records(_legacy_notes_payload(pdf_key, data_dir)) if path.exists() else None,
            combine=_keep_highest_counter,
        )
        merged_bookmarks = sync_store.save_records(
            bookmark_path,
            current_bookmarks_records,
            _SYNC_BASES.get(_sync_base_key(bookmark_path)),
            legacy=_bookmark_records(_legacy_bookmarks_payload(bookmark_path)) if bookmark_path.exists() else None,
        )
    except sync_store.ReplicaUnavailable as exc:
        record_storage_issue(f"Notes were not saved: {exc}. Save again once it has downloaded.", path)
        return path
    written = _payload_from_records(merged, payload)
    written["bookmarks"] = _bookmarks_from_records(merged_bookmarks)
    _atomic_write_json(path, written)  # plain readable copy of the merged notebook
    _atomic_write_json(bookmark_path, {"schema_version": 1, "app": APP_NAME, "bookmarks": written["bookmarks"]})
    # The base is what this computer's caller holds, not the merged result: a note merged in from the
    # other computer but missing from the caller's list is not one deleted here.
    _SYNC_BASES[_sync_base_key(path)] = current
    _SYNC_BASES[_sync_base_key(bookmark_path)] = current_bookmarks_records
    manifest_path = notebook_dir / "manifest.json"
    _atomic_write_json(
        manifest_path,
        _manifest_payload(
            pdf_key=pdf_key,
            pdf_path=pdf_path,
            page_count=_manifest_page_count(manifest_path),
            data_dir=data_dir,
            previous=read_manifest(manifest_path),
        ),
    )
    _LOCATOR_CACHE.clear()
    _atomic_write_json(notebook_dir / "markups.json", _markups_payload(notes))
    recent_path = notebook_dir / "recentfile.json"
    if not recent_path.exists():  # History owns the last-read page; only seed it here.
        _atomic_write_json(recent_path, _recent_file_payload(page_index=0))
    _write_sync_lock(root_sync_lock_path(data_dir))
    _write_sync_lock(notebook_dir / "sync.lock")
    _ensure_cover(pdf_path, notebook_dir)
    return path


def find_note(notes: list[Note], note_id: str) -> Note | None:
    return next((note for note in notes if note.id == note_id), None)
