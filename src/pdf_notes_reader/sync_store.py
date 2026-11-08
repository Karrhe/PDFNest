"""Records shared between computers through a cloud-synced data folder, without lost updates.

A cloud drive (iCloud Drive, OneDrive, Dropbox) syncs whole files and keeps the last one written.
When two computers both rewrite ``library.json``, the one that saves while its copy is out of date
silently throws away the other's changes: a folder made on the Mac disappears when the PC adds a
book. Guessing "missing over there, so deleted over there" makes it worse.

So no file here is written by two computers. For a logical file ``X.json`` each computer writes
only its own replica, ``X.json.sync/<machine id>.json``, holding every record it knows with the
time it last changed, and an explicit tombstone for a record it deleted. Reading merges all
replicas: per record, the newest change wins. A stale computer can at worst re-save old knowledge
under old timestamps, which loses to the newer change. ``X.json`` itself is still written, as a
plain readable copy of the merged result for backups and older PDFNest versions, but it is only
read for records no replica knows (data from before this scheme).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pdf_notes_reader import notes as _notes
from pdf_notes_reader.portable import ensure_local, is_cloud_placeholder

Record = dict[str, Any]
Combine = Callable[[Any, list[tuple[str, Any]]], Any]

LEGACY_STAMP = ""  # older than any real change


class ReplicaUnavailable(OSError):
    """This computer's own replica exists only in the cloud and did not download in time.

    Saving now would replace it with a copy missing everything it held, so nothing is written.
    """


def replica_dir(path: Path) -> Path:
    return path.with_name(path.name + ".sync")


def own_replica_path(path: Path) -> Path:
    return replica_dir(path) / f"{_notes.machine_id()}.json"


def change_stamp() -> str:
    """Microsecond UTC time: two changes in the same second still order."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _read_replica(path: Path) -> dict[str, Record]:
    if not ensure_local(path):
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}  # half-synced or damaged: the other computer rewrites it on its next save
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, dict):
        return {}
    clean: dict[str, Record] = {}
    for key, value in records.items():
        if isinstance(value, dict) and "stamp" in value:
            clean[str(key)] = {"stamp": str(value.get("stamp") or ""), "data": value.get("data")}
    return clean


def _replica_files(path: Path) -> list[Path]:
    folder = replica_dir(path)
    if not folder.is_dir():
        return []
    files = set(folder.glob("*.json"))
    # Evicted replicas (``.<id>.json.icloud``) are downloaded by _read_replica.
    for stub in folder.glob(".*.json.icloud"):
        files.add(stub.with_name(stub.name[1 : -len(".icloud")]))
    return sorted(files)


def _merge(sets: list[dict[str, Record]], combine: Combine | None) -> dict[str, Record]:
    merged: dict[str, Record] = {}
    versions: dict[str, list[tuple[str, Any]]] = {}
    for records in sets:
        for key, record in records.items():
            versions.setdefault(key, []).append((record["stamp"], record["data"]))
            current = merged.get(key)
            if current is None or (record["stamp"], _order(record["data"])) > (current["stamp"], _order(current["data"])):
                merged[key] = record
    if combine is not None:
        for key, record in merged.items():
            if record["data"] is not None and len(versions.get(key, ())) > 1:
                merged[key] = {"stamp": record["stamp"], "data": combine(record["data"], versions[key])}
    return merged


def _order(data: Any) -> str:
    """Tie-break for equal stamps, the same on every computer."""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)


def load_records(path: Path, legacy: dict[str, Any] | None = None, *, combine: Combine | None = None) -> dict[str, Any]:
    """The merged live records (tombstones removed) of all computers' replicas of ``path``."""
    return _live(_load_stamped(path, legacy, combine))


def _load_stamped(path: Path, legacy: dict[str, Any] | None, combine: Combine | None) -> dict[str, Record]:
    sets = [_read_replica(replica) for replica in _replica_files(path)]
    if legacy:
        sets.insert(0, {key: {"stamp": LEGACY_STAMP, "data": data} for key, data in legacy.items()})
    return _merge(sets, combine)


def _live(stamped: dict[str, Record]) -> dict[str, Any]:
    return {key: record["data"] for key, record in stamped.items() if record["data"] is not None}


def save_records(
    path: Path,
    current: dict[str, Any],
    base: dict[str, Any] | None,
    *,
    legacy: dict[str, Any] | None = None,
    combine: Combine | None = None,
    materialize: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Records this computer's changes and returns the merged live records of all computers.

    ``current`` is what this computer holds now and ``base`` what it held when it last loaded or
    saved: a record that differs from ``base`` changed here, and one in ``base`` but missing from
    ``current`` was deleted here. Every other record keeps whatever the replicas say, so a stale
    ``current`` never undoes another computer's change. Without a ``base`` nothing is deleted and
    only records that differ from the merged state count as changes.
    """
    own = own_replica_path(path)
    if not own.exists() and is_cloud_placeholder(own) and not ensure_local(own):
        raise ReplicaUnavailable(f"{own.name} for {path.name} is still downloading from the cloud")
    stamped = _load_stamped(path, legacy, combine)
    live = _live(stamped)
    stamp = change_stamp()
    reference = base if base is not None else live
    # Keep the caller's order (notes, folders): sets would shuffle records saved in the same second.
    for key in list(current) + [key for key in (base or {}) if key not in current]:
        if key in current:
            if reference.get(key) != current[key] or (base is not None and key not in live):
                if base is not None and key in base and base[key] == current[key]:
                    continue  # unchanged here; another computer deleted or changed it
                stamped[key] = {"stamp": stamp, "data": current[key]}
        elif base is not None and key in base:
            stamped[key] = {"stamp": stamp, "data": None}  # deleted here: a tombstone, not an absence
    _notes._atomic_write_json(own, {"schema_version": 1, "app": _notes.APP_NAME, "machine": _notes.machine_id(), "records": stamped})
    merged = _live(stamped)
    if materialize is not None:
        _notes._atomic_write_json(path, materialize(merged))
    return merged


def has_replicas(path: Path) -> bool:
    return bool(_replica_files(path))


def remove_replicas(path: Path) -> None:
    """Testing and maintenance helper: forget the replicas of ``path``."""
    folder = replica_dir(path)
    for replica in folder.glob("*.json") if folder.is_dir() else []:
        try:
            os.remove(replica)
        except OSError:
            pass
