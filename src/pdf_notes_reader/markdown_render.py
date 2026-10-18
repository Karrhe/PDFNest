"""Markdown note preview for Qt rich text (QTextBrowser), with LaTeX-style math.

Pipeline: protect code → protect escaped dollars → math to placeholders → bare symbol commands →
Markdown fixes (nested-list indentation, strikethrough, task lists) → Python-Markdown → restore.
Placeholders are purely alphanumeric so Markdown's ``_``/``*`` emphasis rules never touch them.
"""

from __future__ import annotations

import re

import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import SimpleTagInlineProcessor

from pdf_notes_reader.latex import SYMBOLS as LATEX_SYMBOLS
from pdf_notes_reader.latex import latex_to_html, replace_known_symbols

__all__ = ["LATEX_SYMBOLS", "latex_to_html", "render_markdown_preview"]

MATH_BLOCK_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
# Inline math follows the pandoc rule so prices like "$5 and $10" stay text: the opening $ is not
# followed by a space, the closing $ is not preceded by a space and not followed by a digit.
MATH_INLINE_RE = re.compile(r"(?<![\\$])\$(?![\s$])((?:\\.|[^$\\])+?)(?<![\s\\])\$(?!\d)", re.DOTALL)
CODE_SEGMENT_RE = re.compile(r"(^```.*?^```[ \t]*$|^~~~.*?^~~~[ \t]*$|`[^`\n]+`)", re.DOTALL | re.MULTILINE)
ESCAPED_DOLLAR = "PDFNESTESCAPEDDOLLAR"
LIST_ITEM_RE = re.compile(r"^( +)((?:[-*+]|\d+[.)])[ \t]+)", re.MULTILINE)
TASK_ITEM_RE = re.compile(r"<li>(\s*(?:<p>)?)\[([ xX])\]\s")

MARKDOWN_EXTENSIONS = ["extra", "sane_lists", "nl2br"]


class _StrikethroughExtension(Extension):
    """``~~text~~`` → <s>text</s>; Python-Markdown has no built-in strikethrough."""

    def extendMarkdown(self, md: markdown.Markdown) -> None:  # noqa: N802 - Markdown API name
        md.inlinePatterns.register(SimpleTagInlineProcessor(r"(~{2})(.+?)~{2}", "s"), "strikethrough", 40)


def _token(kind: str, index: int) -> str:
    return f"PDFNEST{kind}{index}X"


def protect_code_segments(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = _token("CODE", len(protected))
        protected[token] = match.group(0)
        return token

    return CODE_SEGMENT_RE.sub(replace, text), protected


def restore_placeholders(text: str, placeholders: dict[str, str]) -> str:
    restored = text
    for token, value in placeholders.items():
        restored = restored.replace(token, value)
    return restored


def normalize_list_indentation(text: str) -> str:
    """Python-Markdown nests lists only at 4-space steps; most editors indent by 2.

    Within each list (a run of lines without a blank-line-separated paragraph), the smallest
    nested indent is taken as one level, and every list item's indent is rescaled to 4 per level.
    """
    lines = text.split("\n")
    out: list[str] = []
    block: list[str] = []

    def flush() -> None:
        indents = [len(m.group(1)) for line in block if (m := LIST_ITEM_RE.match(line))]
        unit = min(indents, default=4)
        if unit >= 4:
            out.extend(block)
        else:
            for line in block:
                match = LIST_ITEM_RE.match(line)
                if match is None:
                    out.append(line)
                    continue
                level = round(len(match.group(1)) / unit)
                out.append(" " * (4 * level) + line[len(match.group(1)) :])
        block.clear()

    for line in lines:
        is_item = bool(re.match(r"^\s*(?:[-*+]|\d+[.)])[ \t]+", line))
        if is_item or (block and line.strip() and line[:1] in " \t"):
            block.append(line)
            continue
        flush()
        out.append(line)
    flush()
    return "\n".join(out)


def _render_task_lists(body: str) -> str:
    return TASK_ITEM_RE.sub(lambda m: f"<li>{m.group(1)}{'☑' if m.group(2) in 'xX' else '☐'} ", body)


def render_markdown_body(text: str) -> str:
    placeholders: dict[str, str] = {}
    block_tokens: set[str] = set()
    prepared, protected_code = protect_code_segments(text)
    prepared = prepared.replace("\\$", ESCAPED_DOLLAR)

    def replace_block(match: re.Match[str]) -> str:
        token = _token("MATHBLOCK", len(placeholders))
        formula = latex_to_html(match.group(1), display=True)
        placeholders[token] = (
            '<table class="math-block" cellspacing="0" cellpadding="0">'
            f'<tr><td align="center">{formula}</td></tr>'
            "</table>"
        )
        block_tokens.add(token)
        return token

    def replace_inline(match: re.Match[str]) -> str:
        token = _token("MATHINLINE", len(placeholders))
        formula = latex_to_html(match.group(1).replace(ESCAPED_DOLLAR, "\\$"))
        placeholders[token] = f'<span class="math-inline">{formula}</span>'
        return token

    prepared = MATH_BLOCK_RE.sub(replace_block, prepared)
    prepared = MATH_INLINE_RE.sub(replace_inline, prepared)
    prepared = replace_known_symbols(prepared)
    prepared = normalize_list_indentation(prepared)
    prepared = restore_placeholders(prepared, protected_code)
    body = markdown.markdown(prepared, extensions=[*MARKDOWN_EXTENSIONS, _StrikethroughExtension()])
    body = _render_task_lists(body)
    for token in block_tokens:
        body = body.replace(f"<p>{token}</p>", placeholders[token])
    body = restore_placeholders(body, placeholders)
    return body.replace(ESCAPED_DOLLAR, "$")


PREVIEW_CSS = """
          body {
            color: #2f2a1f;
            font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            font-size: 14px;
            line-height: 1.55;
          }
          p {
            margin: 0 0 8px 0;
          }
          code {
            background: #eee5cf;
            border: 1px solid #d6c9aa;
            border-radius: 4px;
            font-family: Consolas, "Courier New", monospace;
            padding: 1px 4px;
          }
          pre {
            background: #f4ecd9;
            border: 1px solid #d6c9aa;
            border-radius: 6px;
            padding: 10px;
            white-space: pre-wrap;
          }
          pre code {
            background: transparent;
            border: 0;
            padding: 0;
          }
          blockquote {
            border-left: 4px solid #b89b57;
            color: #5f5644;
            margin: 10px 0;
            padding: 4px 12px;
            background: #f5eedc;
          }
          table {
            border-collapse: collapse;
          }
          th, td {
            border: 1px solid #d6c9aa;
            padding: 4px 8px;
          }
          .math-inline {
            color: #7a4d00;
            font-family: Cambria Math, Times New Roman, serif;
          }
          .latex-frac-num {
            border-bottom: 1px solid #7a4d00;
          }
          .latex-limit {
            font-size: 11px;
          }
          .latex-func, .latex-text {
            font-style: normal;
          }
          .latex-unknown {
            color: #b42318;
            font-family: Consolas, "Courier New", monospace;
          }
          .math-block {
            border-collapse: collapse;
            background: #f8f0dc;
            border: 1px solid #d6c9aa;
            color: #7a4d00;
            font-family: Cambria Math, Times New Roman, serif;
            line-height: 1.2;
            margin: 0 0 4px 0;
            text-align: center;
            width: 100%;
          }
          .math-block td {
            border: 0;
            padding: 1px 6px;
          }
          .math-block .latex-frac td, .math-block .latex-matrix td, .math-block .latex-limits td,
          .math-block .latex-row td, .math-block .latex-delimited td {
            padding: 0 3px;
          }
          .math-block td.latex-frac-num {
            border-bottom: 1px solid #7a4d00;
          }
          .math-block td.latex-cell {
            padding: 1px 8px;
          }
"""


def render_markdown_preview(text: str) -> str:
    return f"""
    <html>
      <head>
        <style>{PREVIEW_CSS}        </style>
      </head>
      <body>{render_markdown_body(text)}</body>
    </html>
    """
