"""A small LaTeX math renderer producing HTML that Qt's rich-text engine (QTextBrowser) can display.

Qt rich text supports a CSS subset only: no flexbox or inline-block, but tables (also nested),
<sup>/<sub>, and text-decoration overline/underline/line-through. So:

* inline math stays on one line: fractions become ``a⁄b`` with raised/lowered parts;
* display math ($$...$$) uses nested tables for stacked fractions, binomials, matrices, cases,
  aligned environments and limits above/below big operators.

Unknown commands are kept visibly as ``\\name`` (class ``latex-unknown``) instead of disappearing.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------------
# Symbol tables
# --------------------------------------------------------------------------------------------

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "varkappa": "ϰ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π",
    "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ",
    "upsilon": "υ", "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "digamma": "ϝ",
}

RELATIONS = {
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "leqslant": "⩽", "geqslant": "⩾", "neq": "≠", "ne": "≠",
    "approx": "≈", "equiv": "≡", "sim": "∼", "simeq": "≃", "cong": "≅", "propto": "∝",
    "ll": "≪", "gg": "≫", "prec": "≺", "succ": "≻", "preceq": "⪯", "succeq": "⪰",
    "subset": "⊂", "supset": "⊃", "subseteq": "⊆", "supseteq": "⊇", "subsetneq": "⊊", "supsetneq": "⊋",
    "in": "∈", "notin": "∉", "ni": "∋", "perp": "⊥", "parallel": "∥", "mid": "∣", "nmid": "∤",
    "models": "⊨", "vdash": "⊢", "dashv": "⊣", "asymp": "≍", "doteq": "≐", "coloneqq": "≔",
    "lesssim": "≲", "gtrsim": "≳", "triangleq": "≜", "nsim": "≁", "ncong": "≇",
}

OPERATORS = {
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓", "ast": "∗", "star": "⋆",
    "circ": "∘", "bullet": "•", "oplus": "⊕", "ominus": "⊖", "otimes": "⊗", "oslash": "⊘",
    "odot": "⊙", "cup": "∪", "cap": "∩", "setminus": "∖", "wedge": "∧", "vee": "∨",
    "land": "∧", "lor": "∨", "neg": "¬", "lnot": "¬", "dagger": "†", "ddagger": "‡",
    "sqcup": "⊔", "sqcap": "⊓", "uplus": "⊎", "amalg": "⨿", "wr": "≀",
}

ARROWS = {
    "to": "→", "rightarrow": "→", "leftarrow": "←", "gets": "←", "leftrightarrow": "↔",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔", "iff": "⟺", "implies": "⟹",
    "impliedby": "⟸", "mapsto": "↦", "longmapsto": "⟼", "longrightarrow": "⟶", "longleftarrow": "⟵",
    "longleftrightarrow": "⟷", "Longrightarrow": "⟹", "Longleftarrow": "⟸", "Longleftrightarrow": "⟺",
    "uparrow": "↑", "downarrow": "↓", "updownarrow": "↕", "Uparrow": "⇑", "Downarrow": "⇓",
    "nearrow": "↗", "searrow": "↘", "swarrow": "↙", "nwarrow": "↖", "hookrightarrow": "↪",
    "hookleftarrow": "↩", "rightharpoonup": "⇀", "leftharpoonup": "↼", "rightleftharpoons": "⇌",
    "leadsto": "⇝",
}

BIG_OPERATORS = {
    "sum": "∑", "prod": "∏", "coprod": "∐", "int": "∫", "iint": "∬", "iiint": "∭", "oint": "∮",
    "bigcup": "⋃", "bigcap": "⋂", "bigoplus": "⨁", "bigotimes": "⨂", "bigodot": "⨀",
    "bigvee": "⋁", "bigwedge": "⋀", "bigsqcup": "⨆",
}

MISC = {
    "infty": "∞", "partial": "∂", "nabla": "∇", "forall": "∀", "exists": "∃", "nexists": "∄",
    "emptyset": "∅", "varnothing": "∅", "aleph": "ℵ", "beth": "ℶ", "hbar": "ℏ", "ell": "ℓ",
    "Re": "ℜ", "Im": "ℑ", "wp": "℘", "angle": "∠", "measuredangle": "∡", "triangle": "△",
    "square": "□", "Box": "□", "Diamond": "◇", "prime": "′", "therefore": "∴", "because": "∵",
    "dots": "…", "ldots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱",
    "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    "lbrace": "{", "rbrace": "}", "vert": "|", "Vert": "‖", "lvert": "|", "rvert": "|",
    "lVert": "‖", "rVert": "‖", "backslash": "\\", "top": "⊤", "bot": "⊥", "flat": "♭",
    "sharp": "♯", "natural": "♮", "clubsuit": "♣", "diamondsuit": "♢", "heartsuit": "♡",
    "spadesuit": "♠", "checkmark": "✓", "degree": "°", "S": "§", "P": "¶", "copyright": "©",
    "imath": "ı", "jmath": "ȷ", "complement": "∁", "surd": "√",
}

SYMBOLS: dict[str, str] = {**GREEK, **RELATIONS, **OPERATORS, **ARROWS, **BIG_OPERATORS, **MISC}

FUNCTIONS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "sinh", "cosh",
    "tanh", "coth", "log", "ln", "lg", "exp", "lim", "limsup", "liminf", "max", "min", "sup",
    "inf", "det", "dim", "ker", "deg", "gcd", "lcm", "arg", "Pr", "hom", "mod", "argmax", "argmin",
}
LIMIT_FUNCTIONS = {"lim", "limsup", "liminf", "max", "min", "sup", "inf", "argmax", "argmin", "Pr", "det", "gcd"}
FUNCTION_LABELS = {"limsup": "lim sup", "liminf": "lim inf", "argmax": "arg max", "argmin": "arg min"}

SPACES = {",": "\u2009", ":": "\u205f", ";": "\u2004", "!": "", " ": " ", "quad": "\u2003", "qquad": "\u2003\u2003"}
ESCAPED_CHARACTERS = {"$", "%", "&", "_", "#", "{", "}", "|"}
SIZE_COMMANDS = {"big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr", "Biggl", "Biggr",
                 "displaystyle", "textstyle", "scriptstyle", "limits", "nolimits", "middle"}
FRACTIONS = {"frac", "dfrac", "tfrac", "cfrac"}
BINOMIALS = {"binom", "dbinom", "tbinom"}

COMBINING_ACCENTS = {"hat": "\u0302", "widehat": "\u0302", "bar": "\u0304", "vec": "\u20d7", "dot": "\u0307",
                     "ddot": "\u0308", "tilde": "\u0303", "widetilde": "\u0303", "acute": "\u0301",
                     "grave": "\u0300", "breve": "\u0306", "check": "\u030c"}
LINE_DECORATIONS = {"overline": "overline", "underline": "underline", "bar": "overline", "widehat": "overline",
                    "widetilde": "overline", "overrightarrow": "overline", "cancel": "line-through"}

ENV_DELIMITERS = {"matrix": ("", ""), "pmatrix": ("(", ")"), "bmatrix": ("[", "]"), "Bmatrix": ("{", "}"),
                  "vmatrix": ("|", "|"), "Vmatrix": ("‖", "‖"), "smallmatrix": ("", ""),
                  "cases": ("{", ""), "rcases": ("", "}"), "dcases": ("{", ""),
                  "aligned": ("", ""), "align": ("", ""), "align*": ("", ""), "gathered": ("", ""),
                  "gather": ("", ""), "gather*": ("", ""), "split": ("", ""), "eqnarray": ("", ""),
                  "array": ("", ""), "equation": ("", ""), "equation*": ("", "")}

_DOUBLE_STRUCK_EXCEPTIONS = {"C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ", "R": "ℝ", "Z": "ℤ"}
_SCRIPT_EXCEPTIONS = {"B": "ℬ", "E": "ℰ", "F": "ℱ", "H": "ℋ", "I": "ℐ", "L": "ℒ", "M": "ℳ", "R": "ℛ",
                      "e": "ℯ", "g": "ℊ", "o": "ℴ"}
_FRAKTUR_EXCEPTIONS = {"C": "ℭ", "H": "ℌ", "I": "ℑ", "R": "ℜ", "Z": "ℨ"}


def _alphabet(text: str, upper_base: int, lower_base: int | None, exceptions: dict[str, str], digit_base: int | None = None) -> str:
    out = []
    for char in text:
        if char in exceptions:
            out.append(exceptions[char])
        elif "A" <= char <= "Z":
            out.append(chr(upper_base + ord(char) - ord("A")))
        elif lower_base is not None and "a" <= char <= "z":
            out.append(chr(lower_base + ord(char) - ord("a")))
        elif digit_base is not None and "0" <= char <= "9":
            out.append(chr(digit_base + ord(char) - ord("0")))
        else:
            out.append(char)
    return "".join(out)


ALPHABETS = {
    "mathbb": lambda t: _alphabet(t, 0x1D538, 0x1D552, _DOUBLE_STRUCK_EXCEPTIONS, 0x1D7D8),
    "mathcal": lambda t: _alphabet(t, 0x1D49C, 0x1D4B6, _SCRIPT_EXCEPTIONS),
    "mathscr": lambda t: _alphabet(t, 0x1D49C, 0x1D4B6, _SCRIPT_EXCEPTIONS),
    "mathfrak": lambda t: _alphabet(t, 0x1D504, 0x1D51E, _FRAKTUR_EXCEPTIONS),
}
TEXT_STYLES = {"mathrm": "", "text": "", "textrm": "", "operatorname": "", "mathsf": "", "textsf": "",
               "mathtt": "font-family: Consolas, monospace;", "texttt": "font-family: Consolas, monospace;",
               "mathbf": "font-weight: bold;", "textbf": "font-weight: bold;", "boldsymbol": "font-weight: bold;",
               "bm": "font-weight: bold;", "mathit": "font-style: italic;", "textit": "font-style: italic;",
               "emph": "font-style: italic;"}

# --------------------------------------------------------------------------------------------
# Tokenizer and parser
# --------------------------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\\([A-Za-z]+\*?|.)|(\s+)|(.)", re.DOTALL)


@dataclass
class Token:
    kind: str  # "cmd", "space", "char"
    value: str


def tokenize(source: str) -> list[Token]:
    tokens = []
    for match in _TOKEN_RE.finditer(source):
        if match.group(1) is not None:
            tokens.append(Token("cmd", match.group(1)))
        elif match.group(2) is not None:
            tokens.append(Token("space", match.group(2)))
        else:
            tokens.append(Token("char", match.group(3)))
    return tokens


@dataclass
class Node:
    kind: str
    text: str = ""
    children: list["Node"] = field(default_factory=list)
    sup: "Node | None" = None
    sub: "Node | None" = None
    rows: list[list["Node"]] = field(default_factory=list)
    style: str = ""


def _seq(children: list[Node]) -> Node:
    return Node("seq", children=children)


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> Token | None:
        token = self.peek()
        if token is not None:
            self.pos += 1
        return token

    def skip_spaces(self) -> None:
        while (token := self.peek()) is not None and token.kind == "space":
            self.pos += 1

    def parse_sequence(self, stop: set[str]) -> Node:
        """Parses until a stop token: '}' / '&' / '\\\\' / 'end' / 'right' (as char or cmd value)."""
        children: list[Node] = []
        while (token := self.peek()) is not None:
            if token.kind == "char" and token.value in stop:
                break
            if token.kind == "cmd" and token.value in stop:
                break
            if token.kind == "char" and token.value in "^_":
                self.take()
                script = self.parse_argument()
                base = children.pop() if children and children[-1].kind not in {"space"} else Node("text", "")
                if base.kind != "scripts":
                    base = Node("scripts", children=[base])
                if token.value == "^":
                    base.sup = script if base.sup is None else _seq([base.sup, script])
                else:
                    base.sub = script if base.sub is None else _seq([base.sub, script])
                children.append(base)
                continue
            if token.kind == "char" and token.value == "'":
                self.take()
                primes = "′"
                while (nxt := self.peek()) is not None and nxt.kind == "char" and nxt.value == "'":
                    self.take()
                    primes += "′"
                base = children.pop() if children else Node("text", "")
                if base.kind != "scripts":
                    base = Node("scripts", children=[base])
                prime_node = Node("text", primes.replace("′′′", "‴").replace("′′", "″"))
                base.sup = prime_node if base.sup is None else _seq([prime_node, base.sup])
                children.append(base)
                continue
            node = self.parse_atom()
            if node is not None:
                children.append(node)
        return _seq(children)

    def parse_argument(self) -> Node:
        """A {group} or a single token, as for ^ _ \\frac etc."""
        self.skip_spaces()
        token = self.peek()
        if token is None:
            return Node("text", "")
        if token.kind == "char" and token.value == "{":
            self.take()
            group = self.parse_sequence({"}"})
            self.take()  # the closing brace, if present
            return group
        if token.kind == "cmd":
            atom = self.parse_atom()
            return atom if atom is not None else Node("text", "")
        self.take()
        return Node("text", token.value)

    def parse_optional(self) -> Node | None:
        self.skip_spaces()
        token = self.peek()
        if token is None or not (token.kind == "char" and token.value == "["):
            return None
        self.take()
        node = self.parse_sequence({"]"})
        self.take()
        return node

    def read_raw_group(self) -> str:
        """Raw text of a {group} (for \\text and \\begin names)."""
        self.skip_spaces()
        token = self.peek()
        if token is None or not (token.kind == "char" and token.value == "{"):
            token = self.take()
            return "" if token is None else token.value
        self.take()
        depth, out = 1, []
        while (token := self.take()) is not None:
            if token.kind == "char" and token.value == "{":
                depth += 1
            elif token.kind == "char" and token.value == "}":
                depth -= 1
                if depth == 0:
                    break
            out.append("\\" + token.value if token.kind == "cmd" else token.value)
        return "".join(out)

    def parse_atom(self) -> Node | None:
        token = self.take()
        if token is None:
            return None
        if token.kind == "space":
            return Node("space")
        if token.kind == "char":
            if token.value == "{":
                group = self.parse_sequence({"}"})
                self.take()
                return group
            if token.value == "}":
                return None  # stray closing brace
            if token.value == "~":
                return Node("text", "\u00a0")
            return Node("text", token.value)
        return self.parse_command(token.value)

    def parse_command(self, name: str) -> Node | None:
        if name in SPACES:
            return Node("text", SPACES[name])
        if name in ESCAPED_CHARACTERS:
            return Node("text", name)
        if name in SIZE_COMMANDS:
            return None
        if name in {"left", "right"}:
            self.skip_spaces()
            delimiter = self.take()
            if delimiter is None:
                return None
            if delimiter.kind == "cmd":
                value = SYMBOLS.get(delimiter.value) or (delimiter.value if delimiter.value in "{}|" else "")
                if delimiter.value == "|":
                    value = "‖"
            else:
                value = "" if delimiter.value == "." else delimiter.value
            return Node("text", value)
        if name in FRACTIONS:
            return Node("frac", children=[self.parse_argument(), self.parse_argument()])
        if name in BINOMIALS:
            return Node("binom", children=[self.parse_argument(), self.parse_argument()])
        if name == "sqrt":
            index = self.parse_optional()
            return Node("sqrt", children=[self.parse_argument()], sup=index)
        if name in ALPHABETS:
            return Node("text", ALPHABETS[name](self.read_raw_group()))
        if name in {"text", "textrm", "textbf", "textit", "texttt", "textsf", "mbox", "emph"}:
            return Node("styled", text=self.read_raw_group(), style=TEXT_STYLES.get(name, ""))
        if name in TEXT_STYLES:
            return Node("group_style", children=[self.parse_argument()], style=TEXT_STYLES[name])
        if name in COMBINING_ACCENTS or name in LINE_DECORATIONS:
            return Node("accent", text=name, children=[self.parse_argument()])
        if name in {"overbrace", "underbrace"}:
            return Node("accent", text="overline" if name == "overbrace" else "underline", children=[self.parse_argument()])
        if name in {"stackrel", "overset"}:
            above, base = self.parse_argument(), self.parse_argument()
            return Node("scripts", children=[base], sup=above)
        if name == "underset":
            below, base = self.parse_argument(), self.parse_argument()
            return Node("scripts", children=[base], sub=below)
        if name == "begin":
            return self.parse_environment(self.read_raw_group())
        if name in {"end", "\\"}:
            return None
        if name == "not":
            nxt = self.parse_argument()
            return _seq([nxt, Node("text", "\u0338")])
        if name in FUNCTIONS:
            return Node("func", text=FUNCTION_LABELS.get(name, name))
        if name in BIG_OPERATORS:
            return Node("bigop", text=SYMBOLS[name])
        if name in SYMBOLS:
            return Node("text", SYMBOLS[name])
        unknown = name
        if (nxt := self.peek()) is not None and nxt.kind == "char" and nxt.value == "{":
            unknown += "{" + self.read_raw_group() + "}"  # keep the argument visible with the command
        return Node("unknown", text=unknown)

    def parse_environment(self, env: str) -> Node:
        if env == "array":
            self.read_raw_group()  # column spec
        rows: list[list[Node]] = [[]]
        while self.peek() is not None:
            cell = self.parse_sequence({"&", "\\", "end"})
            rows[-1].append(cell)
            token = self.take()
            if token is None:
                break
            if token.kind == "char" and token.value == "&":
                continue
            if token.kind == "cmd" and token.value == "\\":
                rows.append([])
                continue
            if token.kind == "cmd" and token.value == "end":
                self.read_raw_group()
                break
        rows = [row for row in rows if any(cell.children for cell in row)] or [[_seq([])]]
        return Node("env", text=env, rows=rows)


def parse(source: str) -> Node:
    parser = _Parser(tokenize(source))
    nodes = []
    while parser.peek() is not None:
        nodes.append(parser.parse_sequence(set()))
        parser.take()  # unreachable stop tokens at top level are skipped
    return _seq(nodes)


# --------------------------------------------------------------------------------------------
# HTML rendering
# --------------------------------------------------------------------------------------------

_BLOCK_KINDS = {"frac", "binom", "env"}
_INTEGRALS = {"∫", "∬", "∭", "∮"}


def _has_stacked_limits(node: Node) -> bool:
    """Big operators (except integrals) and lim/max/... carry limits above/below in display math."""
    if node.kind != "scripts" or not node.children:
        return False
    base = node.children[0]
    if base.kind == "bigop":
        return base.text not in _INTEGRALS
    if base.kind == "func":
        words = base.text.split()
        return bool(words) and words[0] in LIMIT_FUNCTIONS
    return False


def _contains_block(node: Node) -> bool:
    if node.kind in _BLOCK_KINDS or _has_stacked_limits(node):
        return True
    return any(_contains_block(child) for child in node.children) or any(
        _contains_block(n) for n in (node.sup, node.sub) if n is not None
    )


BASE_FONT_PX = 14


FRACTION_RULE = "border-bottom: 1px solid #7a4d00;"
_CELL_STYLES = {"latex-frac-num": FRACTION_RULE}


def _td(content: str, *, align: str | None = None, valign: str | None = None, cls: str | None = None) -> str:
    """A math table cell.

    ``white-space: nowrap`` is the only way to stop Qt wrapping inside a cell. Once a cell has an
    inline style, Qt ignores class-based rules for it, so per-class styles are inlined here too.
    """
    attributes = ""
    if align:
        attributes += f' align="{align}"'
    if valign:
        attributes += f' valign="{valign}"'
    if cls:
        attributes += f' class="{cls}"'
    return f'<td{attributes} style="white-space: nowrap; {_CELL_STYLES.get(cls or "", "")}">{content}</td>'


class _Renderer:
    def __init__(self, display: bool) -> None:
        self.display = display

    def render(self, node: Node) -> str:
        method = getattr(self, f"_render_{node.kind}")
        return method(node)

    def _render_seq(self, node: Node) -> str:
        if self.display and any(_contains_block(child) for child in node.children):
            return self._row([self.render(child) for child in node.children])
        return "".join(self.render(child) for child in node.children)

    def _row(self, cells: list[str]) -> str:
        # Group consecutive inline pieces into one cell; block pieces get their own cell.
        merged: list[str] = []
        buffer = ""
        for cell in cells:
            if cell.startswith("<table"):
                if buffer:
                    merged.append(buffer)
                    buffer = ""
                merged.append(cell)
            else:
                buffer += cell
        if buffer:
            merged.append(buffer)
        if len(merged) == 1:
            return merged[0]
        tds = "".join(_td(cell, valign="middle") for cell in merged)
        return f'<table class="latex-row" cellspacing="0" cellpadding="0"><tr>{tds}</tr></table>'

    def _render_text(self, node: Node) -> str:
        return html.escape(node.text)

    def _render_space(self, node: Node) -> str:
        # TeX ignores source spaces, but notes are typed by hand: "f(x) dx" should keep its gap.
        return " "

    def _render_unknown(self, node: Node) -> str:
        return f'<span class="latex-unknown">\\{html.escape(node.text)}</span>'

    def _render_func(self, node: Node) -> str:
        return f'<span class="latex-func">{html.escape(node.text)}</span>\u2009'

    def _render_bigop(self, node: Node) -> str:
        if not self.display:
            return html.escape(node.text)
        return f'<span class="latex-bigop" style="font-size: {round(BASE_FONT_PX * 1.4)}px">{html.escape(node.text)}</span>'

    def _render_styled(self, node: Node) -> str:
        style = f' style="{node.style}"' if node.style else ""
        return f'<span class="latex-text"{style}>{html.escape(node.text)}</span>'

    def _render_group_style(self, node: Node) -> str:
        inner = "".join(self.render(child) for child in node.children)
        return f'<span style="{node.style}">{inner}</span>' if node.style else inner

    def _render_accent(self, node: Node) -> str:
        body_node = node.children[0]
        plain = _plain_text(body_node)
        if node.text in COMBINING_ACCENTS and plain is not None and len(plain) == 1:
            return html.escape(plain + COMBINING_ACCENTS[node.text])
        body = self.render(body_node)
        decoration = LINE_DECORATIONS.get(node.text, "overline")
        if node.text in {"vec", "overrightarrow"}:
            return f'<span style="text-decoration: overline">{body}</span><sup>→</sup>'
        if node.text in {"hat", "widehat"}:
            return f'{body}<sup>^</sup>'
        if node.text in {"tilde", "widetilde"}:
            return f'{body}<sup>~</sup>'
        if node.text in {"dot", "ddot"}:
            return f'{body}<sup>{"·" if node.text == "dot" else "··"}</sup>'
        return f'<span style="text-decoration: {decoration}">{body}</span>'

    def _render_scripts(self, node: Node) -> str:
        base_node = node.children[0]
        base = self.render(base_node)
        if self.display and _has_stacked_limits(node):
            upper = self.render(node.sup) if node.sup is not None else ""
            lower = self.render(node.sub) if node.sub is not None else ""
            rows = ""
            if upper:
                rows += f"<tr>{_td(upper, align='center', cls='latex-limit')}</tr>"
            rows += f"<tr>{_td(base, align='center')}</tr>"
            if lower:
                rows += f"<tr>{_td(lower, align='center', cls='latex-limit')}</tr>"
            return f'<table class="latex-limits" cellspacing="0" cellpadding="0">{rows}</table>'
        out = base
        if node.sub is not None:
            out += f"<sub>{self._inline(node.sub)}</sub>"
        if node.sup is not None:
            out += f"<sup>{self._inline(node.sup)}</sup>"
        return out

    def _inline(self, node: Node) -> str:
        return _Renderer(display=False).render(node)

    def _render_frac(self, node: Node) -> str:
        numerator, denominator = node.children
        if not self.display:
            return (
                f'<span class="latex-frac"><sup>{self._wrap(numerator)}</sup>\u2044'
                f"<sub>{self._wrap(denominator)}</sub></span>"
            )
        return (
            '<table class="latex-frac" cellspacing="0" cellpadding="0">'
            f"<tr>{_td(self.render(numerator), align='center', cls='latex-frac-num')}</tr>"
            f"<tr>{_td(self.render(denominator), align='center')}</tr></table>"
        )

    def _wrap(self, node: Node) -> str:
        """Inline fraction parts are parenthesized when they contain an operator: (a+b)⁄2."""
        rendered = self._inline(node)
        flat = _flat_text(node)
        return f"({rendered})" if len(flat) > 1 and any(op in flat for op in "+-−=±<>,") else rendered

    def _render_binom(self, node: Node) -> str:
        top, bottom = node.children
        if not self.display:
            return f"(<sup>{self._inline(top)}</sup><sub>{self._inline(bottom)}</sub>)"
        inner = (
            '<table cellspacing="0" cellpadding="0">'
            f"<tr>{_td(self.render(top), align='center')}</tr>"
            f"<tr>{_td(self.render(bottom), align='center')}</tr></table>"
        )
        return self._delimited("(", inner, ")", 2)

    def _render_sqrt(self, node: Node) -> str:
        radicand = self._inline(node.children[0]) if not self.display else self.render(node.children[0])
        index = f"<sup>{self._inline(node.sup)}</sup>" if node.sup is not None else ""
        return f'<span class="latex-sqrt">{index}√<span style="text-decoration: overline">{radicand}</span></span>'

    def _render_env(self, node: Node) -> str:
        left, right = ENV_DELIMITERS.get(node.text, ("", ""))
        if not self.display:
            rows = "; ".join(", ".join(self._inline(cell).strip() for cell in row) for row in node.rows)
            return f"{left}{rows}{right}"
        aligned = node.text in {"aligned", "align", "align*", "split", "eqnarray"}
        cases = node.text in {"cases", "dcases", "rcases"}
        body_rows = []
        for row in node.rows:
            cells = []
            for index, cell in enumerate(row):
                if aligned:
                    alignment = "right" if index % 2 == 0 else "left"
                elif cases:
                    alignment = "left"
                else:
                    alignment = "center"
                cells.append(_td(self.render(cell), align=alignment, cls="latex-cell"))
            body_rows.append(f"<tr>{''.join(cells)}</tr>")
        grid = f'<table class="latex-matrix" cellspacing="0" cellpadding="0">{"".join(body_rows)}</table>'
        if not left and not right:
            return grid
        return self._delimited(left, grid, right, len(node.rows))

    def _delimited(self, left: str, inner: str, right: str, rows: int) -> str:
        # Qt rich text ignores em/% font sizes; px works.
        delimiter = f'<span style="font-size: {round(BASE_FONT_PX * max(1.0, 1.15 * rows))}px">{{}}</span>'
        cells = ""
        if left:
            cells += _td(delimiter.format(html.escape(left)), valign="middle", cls="latex-delim")
        cells += _td(inner, valign="middle")
        if right:
            cells += _td(delimiter.format(html.escape(right)), valign="middle", cls="latex-delim")
        return f'<table class="latex-delimited" cellspacing="0" cellpadding="0"><tr>{cells}</tr></table>'


def _plain_text(node: Node) -> str | None:
    """The node's text when it is plain characters only, else None."""
    if node.kind == "text":
        return node.text
    if node.kind == "seq":
        parts = [_plain_text(child) for child in node.children if child.kind != "space"]
        if all(part is not None for part in parts):
            return "".join(parts)  # type: ignore[arg-type]
    return None


def _flat_text(node: Node) -> str:
    """All text in the node at its own level (not inside scripts), for operator detection."""
    if node.kind == "text":
        return node.text
    if node.kind == "seq":
        return "".join(_flat_text(child) for child in node.children)
    if node.kind == "scripts" and node.children:
        return _flat_text(node.children[0])
    return node.text


def latex_to_html(expression: str, *, display: bool = False) -> str:
    """Renders a LaTeX math expression (without the $ delimiters) to Qt-compatible HTML."""
    return _Renderer(display=display).render(parse(expression.strip()))


def replace_known_symbols(text: str) -> str:
    """Replaces bare known symbol commands (e.g. ``\\beta`` in prose) outside math."""
    return _BARE_SYMBOL_RE.sub(lambda match: SYMBOLS[match.group(1)], text)


_BARE_SYMBOL_RE = re.compile(r"(?<!\\)\\(" + "|".join(re.escape(key) for key in sorted(SYMBOLS, key=len, reverse=True)) + r")(?![A-Za-z])")
