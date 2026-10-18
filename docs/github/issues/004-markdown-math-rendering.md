---
title: "Note preview: fractions not stacked, $ amounts become math, many LaTeX and Markdown features missing"
labels: [bug, enhancement, markdown]
status: fixed in 0.3.0
register: I-18, I-19, I-20, I-21, I-22
---

## Summary
- `\frac{a}{b}` never displayed as a stacked fraction: the CSS used `display: inline-flex`, which Qt's
  rich-text engine (`QTextBrowser`) doesn't support.
- "costs $5 and $10" was rendered as math.
- Only ~55 symbols. Nested braces (`\frac{1}{1+\frac{1}{x}}`, `x^{a^{b}}`), `\sqrt[3]{x}`, `\mathbb{R}`,
  accents, matrices, `cases`, `aligned` and limits under `\sum` did not work. Unknown commands silently lost their backslash.
- No strikethrough, task lists, footnotes, definition lists or abbreviations. Lists indented by 2 spaces didn't
  nest. Math inside `~~~` code blocks was converted.

## Fix
- New `latex.py`: tokenizer + brace-aware parser + renderer that targets what Qt rich text actually supports.
  - **Display math:** nested tables for stacked fractions, matrices, cases, aligned and limits.
  - **Inline math:** `a⁄b` with raised/lowered parts.
  - `px` font sizes (Qt ignores `em`/`%`) and `white-space: nowrap` on cells (the only thing that stops Qt
    wrapping inside them), both verified with a probe.
  - 228 symbols and 36 functions.
- `markdown_render.py`: pandoc-style `$` rules, `\$` escape, `~~~` protection, `extra` extension,
  strikethrough, task lists, 2→4-space list normalization, emphasis-safe placeholders.

## Tests
`tests/test_markdown_compat.py`: 66 cases, also published as `docs/markdown-compat.md` with a before/after
column generated against 0.2.5. Malformed LaTeX never raises.

## Known limitations
Inline fractions stay on one line (Qt limitation). Bare URLs aren't auto-linked. Relative image paths aren't resolved.
