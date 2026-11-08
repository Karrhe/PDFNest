"""Cross-machine helpers for a data folder shared through iCloud Drive, OneDrive or Dropbox.

Nothing here imports the rest of PDFNest, so ``notes.py`` and ``history.py`` can use it freely.

* A *portable path* is a PDF path relative to the data folder, with ``/`` separators. With the data
  folder and the PDFs both inside the cloud drive, it is the same string on Windows and macOS.
* A *content fingerprint* hashes the file size plus its first and last MiB, so the same file finds
  its notebook wherever it lives.
* Cloud placeholders: iCloud on older macOS replaces an evicted ``a.pdf`` by a ``.a.pdf.icloud``
  stub; newer macOS (and Windows) keep the real name but leave the file "dataless" until it is read.
* Merging: two machines can each save their copy of a JSON file; ``merge_records`` combines them
  record by record instead of letting the later save throw away the other machine's changes.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable


CLOUD_DOWNLOAD_TIMEOUT = 10.0  # seconds to wait for iCloud to download an evicted data file
FINGERPRINT_CHUNK = 1 << 20  # 1 MiB from the start and from the end of the file
_FINGERPRINT_CACHE: dict[tuple[str, int, int], str] = {}

# Windows cloud-file attributes (OneDrive, iCloud for Windows) and the macOS "dataless" flag.
_WIN_FILE_ATTRIBUTE_OFFLINE = 0x1000
_WIN_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
_WIN_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
_MAC_SF_DATALESS = 0x40000000


def pdf_fingerprint(pdf_path: str | Path) -> str | None:
    """A 24-hex-digit hash of the file size and its first and last MiB, or None when unreadable.

    Reading 2 MiB keeps opening a large book fast. Two different PDFs with the same size and the same
    first and last MiB are not a practical concern; the fingerprint is a lookup hint, never the only
    thing that keeps notes apart (see ``notes.resolve_pdf_key``).
    """
    path = Path(pdf_path).expanduser()
    try:
        stat = path.stat()
    except OSError:
        return None
    cache_key = (str(path), stat.st_size, stat.st_mtime_ns)
    cached = _FINGERPRINT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    digest.update(b"pdfnest-fingerprint-1\0")
    digest.update(str(stat.st_size).encode("ascii"))
    try:
        with path.open("rb") as handle:
            digest.update(handle.read(FINGERPRINT_CHUNK))
            if stat.st_size > FINGERPRINT_CHUNK:
                handle.seek(max(FINGERPRINT_CHUNK, stat.st_size - FINGERPRINT_CHUNK))
                digest.update(handle.read(FINGERPRINT_CHUNK))
    except OSError:
        return None
    value = digest.hexdigest()[:24]
    _FINGERPRINT_CACHE[cache_key] = value
    return value


def portable_relpath(path: str | Path, base_dir: str | Path, *, pathmod: Any = os.path) -> str:
    """``path`` relative to ``base_dir`` with ``/`` separators, or "" when there is none (another drive).

    ``pathmod`` (``ntpath`` or ``posixpath``) lets tests compute what the other OS would store.
    """
    try:
        target = pathmod.abspath(pathmod.expanduser(str(path)))
        base = pathmod.abspath(pathmod.expanduser(str(base_dir)))
        relative = pathmod.relpath(target, base)
    except (ValueError, OSError):
        return ""
    return relative.replace("\\", "/")


def normalize_portable(value: str) -> str:
    """Comparable form of a portable path or file name.

    macOS stores names decomposed (NFD) and Windows composed (NFC); both iCloud Drive (APFS default) and
    NTFS ignore case. So ``Café.pdf`` written on one machine still matches on the other.
    """
    text = unicodedata.normalize("NFC", str(value).replace("\\", "/"))
    return text.casefold()


def foreign_basename(path_text: str) -> str:
    """The file name of a path written on either OS (``C:\\a\\b.pdf`` or ``/a/b.pdf``)."""
    return re.split(r"[\\/]", str(path_text))[-1]


def is_native_absolute_path(path_text: str, *, platform: str | None = None) -> bool:
    """Whether a stored absolute path was written for this OS: a Windows path is useless on a Mac."""
    text = str(path_text or "").strip()
    if not text:
        return False
    platform = sys.platform if platform is None else platform
    windows_style = bool(re.match(r"^[A-Za-z]:[\\/]", text)) or text.startswith("\\\\")
    if platform.startswith("win"):
        return windows_style or text.startswith("~")
    return (text.startswith("/") or text.startswith("~")) and not windows_style


def icloud_stub_for(path: str | Path) -> Path:
    path = Path(path)
    return path.with_name(f".{path.name}.icloud")


def is_cloud_placeholder(path: str | Path) -> bool:
    """True for a file the cloud client has not downloaded yet (reading it starts a download)."""
    path = Path(path)
    if not path.exists():
        return icloud_stub_for(path).exists()
    try:
        stat = path.stat()
    except OSError:
        return False
    attributes = getattr(stat, "st_file_attributes", 0)
    if attributes & (_WIN_FILE_ATTRIBUTE_OFFLINE | _WIN_FILE_ATTRIBUTE_RECALL_ON_OPEN | _WIN_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS):
        return True
    return bool(getattr(stat, "st_flags", 0) & _MAC_SF_DATALESS)


def request_cloud_download(path: str | Path) -> bool:
    """Asks iCloud to download an evicted file shown only as a ``.name.icloud`` stub. Returns whether it asked."""
    path = Path(path)
    if path.exists() or not icloud_stub_for(path).exists() or sys.platform != "darwin":
        return False
    try:
        subprocess.Popen(["brctl", "download", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


def ensure_local(path: str | Path, *, timeout: float | None = None) -> bool:
    """Makes sure ``path`` is on disk, downloading an evicted iCloud file first. Returns whether it exists.

    Without this, a notes file evicted to a ``.notes.json.icloud`` stub reads as "no notes", and the
    next save would replace the real one.
    """
    path = Path(path)
    if path.exists():
        return True
    if not icloud_stub_for(path).exists():
        return False
    request_cloud_download(path)
    deadline = time.monotonic() + max(0.0, CLOUD_DOWNLOAD_TIMEOUT if timeout is None else timeout)
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.2)
    return path.exists()


_CONFLICT_SUFFIX = re.compile(r"^(?: \d+| \(.*\)|-[^.]+)$")


def conflict_copies(path: str | Path) -> list[Path]:
    """Copies a sync client made of ``path`` when two machines changed it at once.

    iCloud names them ``notes 2.json``, Dropbox ``notes (Name's conflicted copy 2026-11-08).json`` and
    OneDrive ``notes-PCNAME.json``. Temp files (``notes.json.x.tmp``) and quarantined copies
    (``notes.corrupt-….json``) do not match.
    """
    path = Path(path)
    parent = path.parent
    if not parent.is_dir():
        return []
    copies: list[Path] = []
    try:
        candidates = list(parent.iterdir())
    except OSError:
        return []
    for candidate in candidates:
        if candidate == path or candidate.suffix != path.suffix or not candidate.is_file():
            continue
        if not candidate.stem.startswith(path.stem):
            continue
        if _CONFLICT_SUFFIX.match(candidate.stem[len(path.stem):]):
            copies.append(candidate)
    return sorted(copies)


def merge_records(
    ours: list[dict[str, Any]],
    theirs: list[dict[str, Any]],
    *,
    base: dict[str, str] | None = None,
    key: str = "id",
    stamp: str = "updated_at",
) -> list[dict[str, Any]]:
    """Merges the records this machine is about to save (``ours``) with the copy on disk (``theirs``).

    ``base`` maps record ids to the timestamps this machine last loaded or saved; ``None`` means
    nothing is known, and records are only ever added, never dropped.

    * A record only on disk is kept, unless ``base`` has it with the same stamp (this machine deleted it).
    * A record only in ``ours`` is kept, unless it is in ``base`` unchanged (the other machine deleted it).
    * A record in both: the newer ``stamp`` wins.
    """
    merged: list[dict[str, Any]] = []
    theirs_by_id = {str(item.get(key)): item for item in theirs if isinstance(item, dict) and item.get(key)}
    ours_ids: set[str] = set()
    for item in ours:
        record_id = str(item.get(key))
        ours_ids.add(record_id)
        other = theirs_by_id.get(record_id)
        if other is None:
            if base is not None and record_id in base and base[record_id] == str(item.get(stamp, "")) and theirs_by_id:
                continue  # deleted on the other machine and not changed here
            merged.append(item)
        elif str(other.get(stamp, "")) > str(item.get(stamp, "")):
            merged.append(other)
        else:
            merged.append(item)
    for record_id, other in theirs_by_id.items():
        if record_id in ours_ids:
            continue
        if base is not None and base.get(record_id) == str(other.get(stamp, "")):
            continue  # deleted here, and not changed on the other machine since
        merged.append(other)
    return merged


def record_stamps(records: list[Any], *, key: str = "id", stamp: str = "updated_at") -> dict[str, str]:
    stamps: dict[str, str] = {}
    for item in records:
        data = item if isinstance(item, dict) else getattr(item, "__dict__", {})
        if data.get(key):
            stamps[str(data[key])] = str(data.get(stamp, ""))
    return stamps


def move_aside(path: Path, folder: Path, on_error: Callable[[Exception], None] | None = None) -> Path | None:
    """Moves a merged conflict copy into ``folder`` so it is not merged again, keeping it for safety."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = folder / f"{path.stem}.{stamp}{path.suffix}"
    counter = 1
    while target.exists():
        target = folder / f"{path.stem}.{stamp}-{counter}{path.suffix}"
        counter += 1
    try:
        os.replace(path, target)
    except OSError as exc:
        if on_error is not None:
            on_error(exc)
        return None
    return target
