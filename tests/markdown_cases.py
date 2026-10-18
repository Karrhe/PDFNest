"""Markdown/LaTeX compatibility cases, shared by tests/test_markdown_compat.py and the doc generator.

Each case renders ``source`` and checks the HTML body: every ``expect`` string present, every
``reject`` string absent. ``supported=False`` documents a known gap: the check describes the
current (unsupported) behavior, so closing the gap shows up as a test failure to update.
"""

from __future__ import annotations

from dataclasses import dataclass

from pdf_notes_reader import latex


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    feature: str
    source: str
    expect: tuple[str, ...] = ()
    reject: tuple[str, ...] = ()
    supported: bool = True
    note: str = ""


def _symbol_case(case_id: str, feature: str, table: dict[str, str]) -> Case:
    source = " ".join(f"$\\{name}$" for name in table)
    return Case(case_id, "LaTeX symbols", f"{feature} ({len(table)})", source, expect=tuple(sorted(set(table.values()))), reject=tuple(f"\\{name}<" for name in table))


CASES: list[Case] = [
    # --- Markdown blocks and inlines ------------------------------------------------------
    Case("heading", "Markdown", "Headings", "# Title\n\n### Sub", expect=("<h1>Title</h1>", "<h3>Sub</h3>")),
    Case("emphasis", "Markdown", "Emphasis / strong", "*it* **bold** ***both***", expect=("<em>it</em>", "<strong>bold</strong>")),
    Case("strike", "Markdown", "Strikethrough ~~x~~", "~~gone~~ kept", expect=("<s>gone</s>",)),
    Case("ul", "Markdown", "Bullet list", "- a\n- b", expect=("<ul>", "<li>a</li>")),
    Case("ol", "Markdown", "Numbered list", "1. a\n2. b", expect=("<ol>", "<li>a</li>")),
    Case("ol-start", "Markdown", "Numbered list starting at 3", "3. c\n4. d", expect=('<ol start="3">',)),
    Case("nested-4", "Markdown", "Nested list (4-space indent)", "- a\n    - b", expect=("<ul>\n<li>b</li>",)),
    Case("nested-2", "Markdown", "Nested list (2-space indent)", "- a\n  - b\n    - c", expect=("<ul>\n<li>b", "<ul>\n<li>c</li>")),
    Case("tasks", "Markdown", "Task list - [ ] / - [x]", "- [ ] todo\n- [x] done", expect=("☐ todo", "☑ done")),
    Case("link", "Markdown", "Link [text](url)", "[site](https://example.com)", expect=('<a href="https://example.com">site</a>',)),
    Case("autolink", "Markdown", "Autolink <url>", "<https://example.com>", expect=('<a href="https://example.com">',)),
    Case("bare-url", "Markdown", "Bare URL auto-linking", "see https://example.com now", reject=("<a ",), supported=False,
         note="Write <https://...> or [text](url)."),
    Case("image", "Markdown", "Image ![alt](path)", "![fig](figure.png)", expect=('<img alt="fig" src="figure.png"',),
         note="Relative paths are not resolved against the PDF; use absolute paths."),
    Case("table", "Markdown", "Table", "| A | B |\n|---|:-:|\n| 1 | 2 |", expect=("<table>", "<th>A</th>", "<td>1</td>")),
    Case("fence-backtick", "Markdown", "Fenced code ```", "```python\nx = 1\n```", expect=('<code class="language-python">x = 1',)),
    Case("fence-tilde", "Markdown", "Fenced code ~~~", "~~~\ny = $a$\n~~~", expect=("<pre><code>y = $a$",), reject=("math-inline",)),
    Case("inline-code", "Markdown", "Inline code", "use `a_b` here", expect=("<code>a_b</code>",)),
    Case("quote", "Markdown", "Block quote", "> quoted", expect=("<blockquote>",)),
    Case("footnote", "Markdown", "Footnotes [^1]", "text[^1]\n\n[^1]: note", expect=('class="footnote"', 'class="footnote-ref"')),
    Case("deflist", "Markdown", "Definition list", "Term\n: Definition", expect=("<dl>", "<dt>Term</dt>")),
    Case("abbr", "Markdown", "Abbreviations", "HTML here\n\n*[HTML]: Hyper Text", expect=('<abbr title="Hyper Text">HTML</abbr>',)),
    Case("hr", "Markdown", "Horizontal rule", "a\n\n---\n\nb", expect=("<hr",)),
    Case("br", "Markdown", "Single newline = line break", "line one\nline two", expect=("line one<br />",)),
    Case("raw-html", "Markdown", "Inline HTML", "<b>raw</b>", expect=("<b>raw</b>",)),
    Case("attr", "Markdown", "Heading id {#id}", "## Part {#part}", expect=('id="part"',)),
    Case("escape-html", "Markdown", "< > & in text are escaped", "a < b & c", expect=("a &lt; b &amp; c",)),
    # --- Math delimiters ------------------------------------------------------------------
    Case("inline-math", "Math delimiters", "Inline $...$", "Euler $e^{i\\pi}$", expect=("math-inline", "e<sup>iπ</sup>")),
    Case("block-math", "Math delimiters", "Display $$...$$", "$$a+b$$", expect=('class="math-block"',)),
    Case("block-multiline", "Math delimiters", "Display math over several lines", "$$\na\n+ b\n$$", expect=('class="math-block"',)),
    Case("prices", "Math delimiters", "Dollar amounts stay text ($5 and $10)", "costs $5 and $10 today", expect=("$5 and $10",), reject=("math-inline",)),
    Case("escaped-dollar", "Math delimiters", "Escaped \\$ is a literal dollar", "price \\$x\\$ here", expect=("price $x$ here",), reject=("math-inline",)),
    Case("code-protects", "Math delimiters", "No math inside inline code", "`$x^2$`", expect=("<code>$x^2$</code>",), reject=("math-inline",)),
    Case("math-in-table", "Math delimiters", "Math with | inside a table cell", "| f |\n|---|\n| $\\{a | b\\}$ |", expect=("<td><span class=\"math-inline\">",)),
    Case("bare-symbol", "Math delimiters", "Bare \\alpha in prose becomes α", "angle \\alpha here", expect=("angle α here",)),
    # --- LaTeX symbols ------------------------------------------------------------------
    _symbol_case("greek", "Greek letters incl. variants", latex.GREEK),
    _symbol_case("relations", "Relations", latex.RELATIONS),
    _symbol_case("operators", "Binary operators", latex.OPERATORS),
    _symbol_case("arrows", "Arrows", latex.ARROWS),
    _symbol_case("bigops", "Big operators", latex.BIG_OPERATORS),
    _symbol_case("misc", "Misc symbols, dots, delimiters", latex.MISC),
    # --- LaTeX structures ---------------------------------------------------------------
    Case("scripts", "LaTeX structures", "Superscript / subscript", "$x_i^2$", expect=("x<sub>i</sub><sup>2</sup>",)),
    Case("nested-scripts", "LaTeX structures", "Nested braces in scripts", "$e^{x^{2}}$", expect=("e<sup>x<sup>2</sup></sup>",)),
    Case("primes", "LaTeX structures", "Primes f' f''", "$f'(x) + f''(x)$", expect=("f<sup>′</sup>", "f<sup>″</sup>")),
    Case("frac-inline", "LaTeX structures", "\\frac inline", "$\\frac{a+b}{2}$", expect=("<sup>(a+b)</sup>⁄<sub>2</sub>",)),
    Case("frac-display", "LaTeX structures", "\\frac display (stacked, nested)", "$$\\frac{1}{1+\\frac{1}{x}}$$", expect=('class="latex-frac"', "border-bottom")),
    Case("dfrac", "LaTeX structures", "\\dfrac \\tfrac \\cfrac", "$\\dfrac{1}{2} \\tfrac{3}{4}$", expect=("<sup>1</sup>⁄<sub>2</sub>", "<sup>3</sup>⁄<sub>4</sub>")),
    Case("sqrt", "LaTeX structures", "\\sqrt and \\sqrt[n]", "$\\sqrt{x} \\sqrt[3]{y}$", expect=("√<span style=\"text-decoration: overline\">x", "<sup>3</sup>√")),
    Case("binom", "LaTeX structures", "\\binom", "$\\binom{n}{k}$", expect=("(<sup>n</sup><sub>k</sub>)",)),
    Case("functions", "LaTeX structures", "\\sin \\log \\lim ... upright", "$\\sin x + \\log y$", expect=('class="latex-func">sin', 'class="latex-func">log')),
    Case("limits-display", "LaTeX structures", "Limits under \\sum / \\lim in display", "$$\\sum_{i=1}^{n} \\lim_{x \\to 0}$$", expect=('class="latex-limits"', "i=1")),
    Case("integral", "LaTeX structures", "Integral bounds as scripts", "$$\\int_0^1 x$$", expect=("∫</span><sub>0</sub><sup>1</sup>",)),
    Case("accents", "LaTeX structures", "\\hat \\bar \\vec \\dot \\ddot \\tilde", "$\\hat{x} \\bar{y} \\vec{v} \\dot{a} \\ddot{b} \\tilde{n}$", expect=("x̂", "ȳ", "v⃗", "ȧ", "b̈", "ñ")),
    Case("overline", "LaTeX structures", "\\overline \\underline", "$\\overline{AB} \\underline{c}$", expect=("text-decoration: overline", "text-decoration: underline")),
    Case("mathbb", "LaTeX structures", "\\mathbb \\mathcal \\mathfrak", "$\\mathbb{R} \\mathbb{N} \\mathcal{L} \\mathfrak{g}$", expect=("ℝ", "ℕ", "ℒ", "𝔤")),
    Case("fonts", "LaTeX structures", "\\mathbf \\mathrm \\text \\operatorname", "$\\mathbf{v} \\text{if } x \\operatorname{rank} A$", expect=("font-weight: bold", ">if </span>", "rank")),
    Case("left-right", "LaTeX structures", "\\left( \\right) \\big", "$\\left( x \\right) \\big[ y \\big]$", expect=("( x )", "[ y ]"), reject=("latex-unknown",)),
    Case("spacing", "LaTeX structures", "Spacing \\, \\; \\quad \\qquad", "$a\\,b\\;c\\quad d\\qquad e$", reject=("latex-unknown",)),
    Case("matrix", "LaTeX structures", "matrix pmatrix bmatrix vmatrix", "$$\\begin{pmatrix} 1 & 2 \\\\ 3 & 4 \\end{pmatrix} \\begin{bmatrix} a \\end{bmatrix}$$", expect=('class="latex-matrix"', ">(</span>", ">[</span>")),
    Case("cases", "LaTeX structures", "cases", "$$f = \\begin{cases} 1 & x>0 \\\\ 0 & x \\le 0 \\end{cases}$$", expect=(">{</span>", "x&gt;0")),
    Case("aligned", "LaTeX structures", "aligned / align", "$$\\begin{aligned} a &= b \\\\ c &= d \\end{aligned}$$", expect=('align="right"', 'align="left"')),
    Case("array", "LaTeX structures", "array with column spec", "$$\\begin{array}{cc} 1 & 2 \\end{array}$$", expect=('class="latex-matrix"',), reject=("cc",)),
    Case("matrix-inline", "LaTeX structures", "Matrix in inline math (flattened)", "$\\begin{pmatrix} 1 & 2 \\\\ 3 & 4 \\end{pmatrix}$", expect=("(1, 2; 3, 4)",)),
    Case("overset", "LaTeX structures", "\\overset \\stackrel \\underset", "$\\overset{def}{=}$", expect=("=<sup>def</sup>",)),
    Case("not", "LaTeX structures", "\\not \\notin", "$a \\notin B, a \\not= b$", expect=("∉", "≠")),
    Case("escapes", "LaTeX structures", "\\{ \\} \\% \\& \\_ \\#", "$\\{1\\} \\% \\& \\_ \\#$", expect=("{1}", "%", "&amp;", "_", "#")),
    Case("unknown", "LaTeX structures", "Unknown commands stay visible", "$\\foo{x}$", expect=('class="latex-unknown">\\foo{x}',)),
]
