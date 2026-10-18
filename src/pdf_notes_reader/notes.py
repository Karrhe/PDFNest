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


APP_NAME = "PDFNest"
STORAGE_DIR_NAME = "Note_PDFNest"


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
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Note":
        return cls(
            id=str(data["id"]),
            pdf_key=str(data["pdf_key"]),
            page_index=int(data["page_index"]),
            x_norm=clamp01(float(data["x_norm"])),
            y_norm=clamp01(float(data["y_norm"])),
            markdown=str(data.get("markdown", "")),
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            note_type=str(data.get("note_type") or "point"),
            rects_norm=normalize_rects(data.get("rects_norm", [])),
            selected_text=str(data.get("selected_text", "")),
            color=str(data.get("color", "")),
            linked_note_id=str(data.get("linked_note_id", "")),
            marker_style=str(data.get("marker_style") or "dashed_underline"),
            note_number=normalize_nonnegative_int(data.get("note_number"), default=0),
            exported_markdown_path=str(data.get("exported_markdown_path", "")),
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


def app_local_data_dir() -> Path:
    return app_base_dir() / ".local-data"


def storage_pointer_path() -> Path:
    return app_local_data_dir() / "storage_location.json"


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

    local = app_base_dir() / STORAGE_DIR_NAME
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
    """Reads JSON, or returns None. Corrupt files are quarantined and reported instead of raising."""
    if not path.exists():
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
    notes, _counters, _bookmarks = load_notes_data(pdf_key, data_dir)
    return notes


def load_notes_with_counters(pdf_key: str, data_dir: Path | None = None) -> tuple[list[Note], dict[str, int]]:
    notes, counters, _bookmarks = load_notes_data(pdf_key, data_dir)
    return notes, counters


def load_notes_data(pdf_key: str, data_dir: Path | None = None) -> tuple[list[Note], dict[str, int], list[Bookmark]]:
    payload = load_notes_payload(pdf_key, data_dir)
    raw_notes = payload.get("notes", [])
    if not isinstance(raw_notes, list):
        raw_notes = []

    notes: list[Note] = []
    for item in raw_notes:
        if isinstance(item, dict):
            notes.append(Note.from_dict(item))

    bookmark_payload = load_bookmarks_payload(pdf_key, data_dir)
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


def load_notes_payload(pdf_key: str, data_dir: Path | None = None) -> dict[str, Any]:
    path = notes_path_for_key(pdf_key, data_dir)
    if not path.exists():
        legacy_notebook_path = legacy_notebook_note_file_for_key(pdf_key, data_dir)
        path = legacy_notebook_path or legacy_notes_path_for_key(pdf_key, data_dir)
    payload = read_json_checked(path)
    return payload if isinstance(payload, dict) else {}


def load_bookmarks_payload(pdf_key: str, data_dir: Path | None = None) -> dict[str, Any]:
    payload = read_json_checked(bookmark_path_for_key(pdf_key, data_dir))
    return payload if isinstance(payload, dict) else {}


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


def _manifest_payload(*, pdf_key: str, pdf_path: str | Path, page_count: int = 0) -> dict[str, Any]:
    path = Path(pdf_path).expanduser()
    return {
        "schema_version": 1,
        "app": APP_NAME,
        "pdf_key": pdf_key,
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
    if cover_path.exists():
        return
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
    _atomic_write_json(path, payload)
    _atomic_write_json(bookmark_path, {"schema_version": 1, "app": APP_NAME, "bookmarks": [bookmark.to_dict() for bookmark in current_bookmarks]})
    manifest_path = notebook_dir / "manifest.json"
    _atomic_write_json(
        manifest_path,
        _manifest_payload(pdf_key=pdf_key, pdf_path=pdf_path, page_count=_manifest_page_count(manifest_path)),
    )
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
