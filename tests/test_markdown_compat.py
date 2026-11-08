"""#6: the Markdown/LaTeX compatibility matrix (docs/markdown-compat.md) is enforced here."""

from __future__ import annotations

import pytest

from markdown_cases import CASES
from pdf_notes_reader.markdown_render import render_markdown_body


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_compat_case(case):
    body = render_markdown_body(case.source)
    missing = [item for item in case.expect if item not in body]
    present = [item for item in case.reject if item in body]
    assert not missing and not present, f"{case.feature}\nmissing: {missing}\nunexpected: {present}\nbody: {body}"


def test_case_ids_are_unique():
    ids = [case.id for case in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    "source",
    ["$", "$$", "$\\frac{a}$", "$x^$", "$\\begin{pmatrix} 1 & 2$", "$\\left($", "$}{$", "$\\sqrt[$", "$$\\end{cases}$$"],
)
def test_malformed_latex_never_raises(source):
    assert render_markdown_body(source)
