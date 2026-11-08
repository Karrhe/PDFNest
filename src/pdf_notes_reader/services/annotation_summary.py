"""Summary of a PDF's highlights and underlines, grouped by outline section (or by page)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pdf_notes_reader.notes import Note, is_annotation
from pdf_notes_reader.services.chapters import counter_key


ChapterResolver = Callable[[int], "tuple[str, int] | None"]


@dataclass
class SummaryGroup:
    """One section of the summary: an outline section, or a page that has no section."""

    key: str
    title: str
    first_page_index: int  # Where the section starts, or the page itself.
    is_section: bool
    annotations: list[Note] = field(default_factory=list)


def group_annotations(notes: list[Note], chapter_for_page: ChapterResolver) -> list[SummaryGroup]:
    """Groups highlights/underlines by the outline section they are in. A page with no section
    (no outline, or before the first section) gets a group of its own."""
    groups: dict[str, SummaryGroup] = {}
    annotations = sorted(
        (note for note in notes if is_annotation(note)),
        key=lambda item: (item.page_index, _top(item), item.created_at),
    )
    for note in annotations:
        chapter = chapter_for_page(note.page_index)
        key = counter_key(chapter, note.page_index)
        group = groups.get(key)
        if group is None:
            if chapter is not None:
                group = SummaryGroup(key, chapter[0], chapter[1], True)
            else:
                group = SummaryGroup(key, f"Page {note.page_index + 1}", note.page_index, False)
            groups[key] = group
        group.annotations.append(note)
    return sorted(groups.values(), key=lambda group: group.first_page_index)


def _top(note: Note) -> float:
    tops = [float(rect[1]) for rect in note.rects_norm if len(rect) >= 4]
    return min(tops) if tops else float(note.y_norm)


def annotation_note_body(note: Note) -> str:
    """The note the user wrote on an annotation, without the generated title and quoted text."""
    if not note.has_note:
        return ""
    lines = note.markdown.splitlines()
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is not None and lines[first].lstrip().startswith("#"):
        lines = lines[first + 1 :]
    body = [line for line in lines if not line.lstrip().startswith(">")]
    return "\n".join(body).strip()


def single_line(text: str) -> str:
    return " ".join(text.split())


def summary_markdown(title: str, groups: list[SummaryGroup]) -> str:
    lines = [f"# {title} — highlights", ""]
    if not groups:
        lines.append("No highlights or underlines yet.")
        return "\n".join(lines) + "\n"
    for group in groups:
        heading = group.title if not group.is_section else f"{group.title} (p.{group.first_page_index + 1})"
        lines.extend([f"## {heading}", ""])
        for note in group.annotations:
            text = single_line(note.selected_text) or "(no text)"
            marked = f"=={text}==" if note.note_type == "highlight" else f"<u>{text}</u>"
            suffix = f" (p.{note.page_index + 1})" if group.is_section else ""
            lines.append(f"- {marked}{suffix}")
            body = annotation_note_body(note)
            if body:
                for body_line in body.splitlines():
                    lines.append(f"    {body_line}" if body_line.strip() else "")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
