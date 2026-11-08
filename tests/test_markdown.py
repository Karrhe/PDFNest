from gui_helpers import GuiTestCase  # noqa: I001 - sets sys.path and offscreen Qt first

from pdf_notes_reader.main import render_markdown_preview


class MarkdownPreviewTest(GuiTestCase):
    def test_markdown_preview_supports_math_code_and_quotes(self) -> None:
        html = render_markdown_preview(
            "> quoted\n\n"
            "Inline code `\\beta` and bare latex \\beta plus math $a^2+b^2=c^2$.\n\n"
            "```python\nprint('hello')\n```\n\n"
            "$$E = mc^2 + \\frac{1}{2}\\sqrt{x}$$\n\n"
            "| A | B |\n| - | - |\n| 1 | 2 |"
        )

        self.assertIn("<blockquote>", html)
        self.assertIn("<code>", html)
        code_html = render_markdown_preview("`\\beta`")
        self.assertIn("\\beta", code_html)
        self.assertNotIn("β", code_html)
        self.assertIn("β", html)
        self.assertNotIn("\\beta plus", html)
        self.assertIn("math-inline", html)
        self.assertIn("math-block", html)
        int_html = render_markdown_preview("$\\int_K f(x) dx$")
        self.assertIn("∫<sub>K</sub>", int_html)
        self.assertIn("<sup>2</sup>", html)
        self.assertIn("latex-frac", html)
        self.assertIn("latex-sqrt", html)
        self.assertIn("<table>", html)
        self.assertNotIn("<p><table class=\"math-block\"", html)
        self.assertIn("margin: 0 0 4px 0", html)
        self.assertIn("padding: 1px 6px", html)


if __name__ == "__main__":
    import unittest

    unittest.main()
