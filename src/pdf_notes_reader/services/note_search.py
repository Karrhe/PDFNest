"""Searching note content: within the open PDF's notes and across all notebooks (Home search)."""

from __future__ import annotations

from pathlib import Path

from pdf_notes_reader.notes import Note, load_notes, notes_path_for_key


def note_search_text(note: Note) -> str:
    return f"{note.markdown}\n{note.selected_text}".casefold()


def note_matches(note: Note, query: str) -> bool:
    """Every whitespace-separated term must appear in the note's Markdown or captured text."""
    terms = query.casefold().split()
    if not terms:
        return True
    haystack = note_search_text(note)
    return all(term in haystack for term in terms)


class NotebookSearchIndex:
    """Caches each notebook's searchable text, re-reading a notes.json only when it changes."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[tuple[str, int], list[str]]] = {}

    def _texts(self, pdf_key: str) -> list[str]:
        path: Path = notes_path_for_key(pdf_key)
        try:
            stat = path.stat()
            stamp = (str(path), stat.st_mtime_ns)
        except OSError:
            self._cache.pop(pdf_key, None)
            return []
        cached = self._cache.get(pdf_key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        texts = [note_search_text(note) for note in load_notes(pdf_key) if note.note_type != "excerpt"]
        self._cache[pdf_key] = (stamp, texts)
        return texts

    def match_counts(self, pdf_keys: list[str], query: str) -> dict[str, int]:
        """Number of matching notes per notebook (only notebooks with at least one match)."""
        terms = query.casefold().split()
        if not terms:
            return {}
        counts: dict[str, int] = {}
        for key in pdf_keys:
            count = sum(1 for text in self._texts(key) if all(term in text for term in terms))
            if count:
                counts[key] = count
        return counts
