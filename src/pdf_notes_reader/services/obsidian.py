"""Obsidian vault sync: one Markdown file per note, plus a generated index note per book.

Layout::

    <vault>/<subfolder>/<pdf stem>/_Index.md        generated; PDFNest overwrites it
    <vault>/<subfolder>/<pdf stem>/p25 Title.md     one per point / highlight / underline note

Each note file starts with front matter. The keys in ``MANAGED_KEYS`` belong to PDFNest and are
rewritten on every write; any other property the user adds in Obsidian (tags, aliases, ...) is kept.
Everything below the front matter is the note's Markdown and may be edited in either app.

Sync rules (the reason for ``Note.vault_hash``, the hash of the file text PDFNest last wrote or read):

* pull: the file's hash differs from ``vault_hash`` -> Obsidian edited it; its body becomes the note.
* push: the note changed and the file is still what PDFNest last saw -> rewrite the file.
* both changed -> Obsidian's text wins and PDFNest's text is saved beside it as
  ``<name>.pdfnest-conflict.md``. Nothing is overwritten silently.
* a deleted note's file is moved to the vault's ``.trash`` folder (Obsidian's own trash), never deleted.

This module has no Qt dependency.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from pdf_notes_reader.notes import Note
from pdf_notes_reader.services.export import safe_filename, unique_markdown_path

URL_SCHEME = "pdfnest"
INDEX_NAME = "_Index.md"
CONFLICT_SUFFIX = ".pdfnest-conflict"
MANAGED_KEYS = ("pdfnest_id", "pdf", "page", "type", "created", "link")
NOTE_TYPES_WITH_FILES = {"point", "highlight", "underline"}


# --- configuration ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VaultConfig:
    vault_dir: Path
    subfolder: str = "PDFNest"

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> "VaultConfig | None":
        """The configured vault, or None while the integration is off (no folder set)."""
        raw = str(settings.get("obsidian_vault_dir") or "").strip()
        if not raw:
            return None
        return cls(Path(raw).expanduser(), clean_subfolder(str(settings.get("obsidian_subfolder") or "")))

    @property
    def root(self) -> Path:
        return self.vault_dir / self.subfolder if self.subfolder else self.vault_dir

    def book_dir(self, pdf_path: Path) -> Path:
        return self.root / obsidian_safe_name(Path(pdf_path).stem, max_length=80)

    def is_obsidian_vault(self) -> bool:
        return (self.vault_dir / ".obsidian").is_dir()


def obsidian_safe_name(value: str, *, max_length: int = 80) -> str:
    """A file or folder name that also works inside an Obsidian [[wiki link]]: no [ ] # ^ |."""
    value = value.replace("[", "(").replace("]", ")")
    value = value.translate(str.maketrans({"#": "-", "^": "-", "|": "-"}))
    return safe_filename(value, max_length=max_length)


def clean_subfolder(value: str) -> str:
    parts = [obsidian_safe_name(part, max_length=60) for part in value.replace("\\", "/").split("/") if part.strip(" .")]
    return "/".join(parts)


# --- URLs --------------------------------------------------------------------------------------


def pdfnest_url(pdf_path: Path | str, page_number: int, note_id: str = "", pdf_key: str = "") -> str:
    """``pdfnest://open?path=...&page=N[&note=ID][&key=KEY]``; fully percent-encoded so it is a
    valid Markdown link target even for paths with spaces or brackets.

    ``path`` is where the computer that wrote the link keeps the PDF; ``key`` is the book's id, the
    same on every computer sharing the data folder, so a link written on Windows still opens the
    book on a Mac (see ``history.local_pdf_for_link``).
    """
    url = f"{URL_SCHEME}://open?path={quote(str(pdf_path), safe='')}&page={max(1, int(page_number))}"
    if note_id:
        url += f"&note={quote(note_id, safe='')}"
    if pdf_key:
        url += f"&key={quote(pdf_key, safe='')}"
    return url


@dataclass(frozen=True)
class OpenRequest:
    path: Path
    page_number: int = 0  # 1-based; 0 = not given
    note_id: str = ""
    pdf_key: str = ""  # the book's id; empty in links written before PDFNest 0.3.6


def parse_pdfnest_url(url: str) -> OpenRequest | None:
    """Parses a pdfnest:// link, or a plain .pdf path (as passed on a command line)."""
    text = url.strip().strip('"')
    if not text.lower().startswith(f"{URL_SCHEME}:"):
        return OpenRequest(Path(text)) if text.lower().endswith(".pdf") else None
    parts = urlsplit(text)
    query = parse_qs(parts.query)
    path = (query.get("path") or [""])[0]
    if not path:
        return None
    try:
        page = max(0, int((query.get("page") or ["0"])[0]))
    except ValueError:
        page = 0
    return OpenRequest(Path(path), page, (query.get("note") or [""])[0], (query.get("key") or [""])[0])


def obsidian_open_url(file_path: Path) -> str:
    return f"obsidian://open?path={quote(str(file_path), safe='')}"


# --- note files --------------------------------------------------------------------------------


FrontMatterBlock = tuple[str, list[str]]  # (key, its lines including continuation lines)


def parse_note_file(text: str) -> tuple[list[FrontMatterBlock], str]:
    """Splits a note file into front-matter blocks and the body. Files without front matter have
    no blocks. Only top-level ``key:`` lines start a block; indented lines and list items belong
    to the block above, so Obsidian list properties survive a rewrite."""
    text = normalize_newlines(text)
    if not text.startswith("---\n"):
        return [], text
    end = text.find("\n---\n", 3)
    if end == -1:
        if text.endswith("\n---"):
            end = len(text) - 4
        else:
            return [], text
    header = text[4:end]
    body = text[end + 5 :]
    blocks: list[FrontMatterBlock] = []
    for line in header.split("\n") if header else []:
        if line and not line[0].isspace() and not line.startswith("-") and ":" in line:
            blocks.append((line.split(":", 1)[0].strip(), [line]))
        elif blocks:
            blocks[-1][1].append(line)
        elif line.strip():
            blocks.append(("", [line]))
    return blocks, body


def front_matter_value(blocks: list[FrontMatterBlock], key: str) -> str:
    for block_key, lines in blocks:
        if block_key == key:
            return _unquote(lines[0].split(":", 1)[1].strip())
    return ""


def shown_pdf_path(blocks: list[FrontMatterBlock], pdf_key: str, pdf_path: Path | str) -> str:
    """The PDF path to write into a vault file that already exists.

    A vault shared by several computers would otherwise flip between each computer's path to the
    PDF on every save, rewriting every note file. A file whose link already names this book keeps
    the path it has: the link opens the book on any computer through its key.
    """
    if pdf_key:
        request = parse_pdfnest_url(front_matter_value(blocks, "link"))
        shown = front_matter_value(blocks, "pdf")
        if request is not None and request.pdf_key == pdf_key and shown:
            return shown
    return str(pdf_path)


def render_note_file(note: Note, pdf_path: Path | str, preserved: list[FrontMatterBlock] | None = None) -> str:
    pdf_text = shown_pdf_path(preserved or [], note.pdf_key, pdf_path)
    managed = {
        "pdfnest_id": note.id,
        "pdf": _quote(pdf_text),
        "page": str(note.page_index + 1),
        "type": note.note_type,
        "created": note.created_at,
        "link": _quote(pdfnest_url(pdf_text, note.page_index + 1, note.id, note.pdf_key)),
    }
    lines = ["---"] + [f"{key}: {managed[key]}" for key in MANAGED_KEYS]
    for key, block_lines in preserved or []:
        if key not in MANAGED_KEYS:
            lines.extend(block_lines)
    lines.append("---")
    return "\n".join(lines) + "\n" + normalize_newlines(note.markdown)


def render_index(
    config: VaultConfig,
    pdf_path: Path,
    notes: Iterable[Note],
    files: dict[str, Path],
    *,
    pdf_key: str = "",
    existing: str = "",
) -> str:
    notes = list(notes)
    pdf_key = pdf_key or next((note.pdf_key for note in notes if note.pdf_key), "")
    pdf_text = shown_pdf_path(parse_note_file(existing)[0] if existing else [], pdf_key, pdf_path)
    lines = [
        "---",
        "pdfnest_index: true",
        f"pdf: {_quote(pdf_text)}",
        f"link: {_quote(pdfnest_url(pdf_text, 1, pdf_key=pdf_key))}",
        "---",
        f"# {Path(pdf_path).stem}",
        "",
        f"[Open in PDFNest]({pdfnest_url(pdf_text, 1, pdf_key=pdf_key)})",
        "",
        "*This index is generated by PDFNest and rewritten whenever notes change.*",
        "",
    ]
    ordered = sorted((note for note in notes if note.id in files), key=lambda item: (item.page_index, item.y_norm, item.created_at))
    for note in ordered:
        path = files[note.id]
        try:
            target = path.relative_to(config.vault_dir).with_suffix("").as_posix()
        except ValueError:
            target = path.stem
        label = note_title(note) or path.stem
        lines.append(f"- p.{note.page_index + 1} · [[{target}|{label.replace('|', '/').replace(']', ')')}]]")
    if not ordered:
        lines.append("No notes yet.")
    return "\n".join(lines) + "\n"


def note_title(note: Note) -> str:
    for line in normalize_newlines(note.markdown).split("\n"):
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:120]
    return ""


def note_file_name(note: Note, fallback_title: str) -> str:
    title = note_title(note) or fallback_title or "note"
    if title.startswith(">"):
        title = fallback_title or "note"
    return obsidian_safe_name(f"p{note.page_index + 1} {title}", max_length=90) + ".md"


# --- sync --------------------------------------------------------------------------------------


@dataclass
class SyncReport:
    written: list[Path] = field(default_factory=list)
    pulled: list[str] = field(default_factory=list)  # note ids updated from Obsidian
    conflicts: list[Path] = field(default_factory=list)  # conflict copies written
    trashed: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def changed_notes(self) -> bool:
        return bool(self.pulled)


def has_file(note: Note) -> bool:
    """Point notes, and highlights/underlines only once the user has added a note to them."""
    return note.note_type in NOTE_TYPES_WITH_FILES and (note.note_type == "point" or note.has_note)


def resolve_note_file(config: VaultConfig, pdf_path: Path, note: Note, id_index: dict[str, Path] | None = None) -> Path | None:
    """The note's file: its recorded path, else (renamed or moved in Obsidian) a file anywhere in
    the vault subfolder whose front matter carries the note's id."""
    if note.vault_path:
        path = config.vault_dir / note.vault_path
        if path.is_file():
            return path
    if id_index is None:
        id_index = scan_note_ids(config.root)
    return id_index.get(note.id)


def scan_note_ids(directory: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    if not directory.is_dir():
        return found
    for path in directory.rglob("*.md"):
        if path.name == INDEX_NAME or path.stem.endswith(CONFLICT_SUFFIX):
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                head = handle.read(2048)
        except (OSError, UnicodeDecodeError):
            continue
        note_id = front_matter_value(parse_note_file(head)[0], "pdfnest_id")
        if note_id:
            found.setdefault(note_id, path)
    return found


def pull_notes(config: VaultConfig, pdf_path: Path, notes: list[Note]) -> SyncReport:
    """Takes edits made in Obsidian into ``notes`` (in place)."""
    report = SyncReport()
    id_index: dict[str, Path] | None = None
    for note in notes:
        if not has_file(note) or not note.vault_hash:
            continue
        path = config.vault_dir / note.vault_path if note.vault_path else None
        if path is None or not path.is_file():
            if id_index is None:
                id_index = scan_note_ids(config.root)
            path = id_index.get(note.id)
            if path is None:
                # Gone from the vault: written again on the next push. PDFNest never loses the note.
                note.vault_path = ""
                note.vault_hash = ""
                continue
            note.vault_path = _relative(config, path)
        try:
            text = read_text(path)
        except OSError as exc:
            report.errors.append(f"{path}: {exc}")
            continue
        current_hash = text_hash(text)
        if current_hash == note.vault_hash:
            continue
        _blocks, body = parse_note_file(text)
        note.vault_hash = current_hash
        if body != normalize_newlines(note.markdown):
            note.update_markdown(body)
            report.pulled.append(note.id)
    return report


def push_notes(
    config: VaultConfig,
    pdf_path: Path,
    notes: list[Note],
    fallback_title: Callable[[Note], str],
    *,
    write_index_file: bool = True,
) -> SyncReport:
    """Writes notes whose file is missing or out of date, then the book's index."""
    report = SyncReport()
    book_dir = config.book_dir(pdf_path)
    id_index: dict[str, Path] | None = None
    files: dict[str, Path] = {}
    for note in notes:
        if not has_file(note):
            continue
        path = config.vault_dir / note.vault_path if note.vault_path else None
        if path is None or not path.is_file():
            if id_index is None:
                id_index = scan_note_ids(config.root)
            path = id_index.get(note.id)
        try:
            if path is None:
                path = unique_markdown_path(book_dir / note_file_name(note, fallback_title(note)))
                text = render_note_file(note, pdf_path)
                write_text_atomic(path, text)
                report.written.append(path)
            else:
                existing = read_text(path)
                blocks, body = parse_note_file(existing)
                text = render_note_file(note, pdf_path, blocks)
                if text != existing:
                    edited_elsewhere = bool(note.vault_hash) and text_hash(existing) != note.vault_hash
                    if edited_elsewhere and body != normalize_newlines(note.markdown):
                        conflict = unique_markdown_path(path.with_name(f"{path.stem}{CONFLICT_SUFFIX}.md"))
                        write_text_atomic(conflict, render_note_file(note, pdf_path, blocks))
                        report.conflicts.append(conflict)
                        note.update_markdown(body)
                        report.pulled.append(note.id)
                        text = existing
                    else:
                        write_text_atomic(path, text)
                        report.written.append(path)
            note.vault_path = _relative(config, path)
            note.vault_hash = text_hash(text)
            files[note.id] = path
        except OSError as exc:
            report.errors.append(f"{note.id}: {exc}")
    if write_index_file:
        try:
            index_path = book_dir / INDEX_NAME
            existing_index = read_text(index_path) if index_path.is_file() else ""
            index_text = render_index(config, pdf_path, notes, files, existing=existing_index)
            if not index_path.is_file() or existing_index != index_text:
                write_text_atomic(index_path, index_text)
                report.written.append(index_path)
        except OSError as exc:
            report.errors.append(f"{INDEX_NAME}: {exc}")
    return report


def write_conflict_copy(config: VaultConfig, pdf_path: Path, note: Note, markdown: str) -> Path:
    """Saves ``markdown`` (PDFNest's competing version of ``note``) beside the note's file."""
    path = note_file_for_opening(config, note)
    base = path if path is not None else config.book_dir(pdf_path) / note_file_name(note, "note")
    conflict = unique_markdown_path(base.with_name(f"{base.stem}{CONFLICT_SUFFIX}.md"))
    copy = Note.from_dict({**note.to_dict(), "markdown": markdown})
    write_text_atomic(conflict, render_note_file(copy, pdf_path))
    return conflict


def trash_note_file(config: VaultConfig, note: Note) -> Path | None:
    """Moves a deleted note's file into ``<vault>/.trash`` (restorable from Obsidian)."""
    if not has_file(note) and not note.vault_path:
        return None
    path = config.vault_dir / note.vault_path if note.vault_path else None
    if path is None or not path.is_file():
        path = scan_note_ids(config.root).get(note.id)
    if path is None:
        return None
    trash = config.vault_dir / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    target = unique_markdown_path(trash / path.name)
    shutil.move(str(path), str(target))
    note.vault_path = ""
    note.vault_hash = ""
    return target


def note_file_for_opening(config: VaultConfig, note: Note) -> Path | None:
    if note.vault_path and (config.vault_dir / note.vault_path).is_file():
        return config.vault_dir / note.vault_path
    return scan_note_ids(config.root).get(note.id)


# --- helpers -----------------------------------------------------------------------------------


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def text_hash(text: str) -> str:
    return hashlib.sha1(normalize_newlines(text).encode("utf-8")).hexdigest()


def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return normalize_newlines(handle.read())


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _relative(config: VaultConfig, path: Path) -> str:
    try:
        return path.relative_to(config.vault_dir).as_posix()
    except ValueError:
        return str(path)


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value
