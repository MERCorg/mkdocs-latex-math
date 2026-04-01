import hashlib
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
from typing import Any, Match, Pattern

from mkdocs.plugins import BasePlugin
from mkdocs.config import config_options


class LatexMathPlugin(BasePlugin):
    """
    MkDocs plugin: render LaTeX math (inline $...$, display $$...$$ and fenced blocks with info 'pdflatex')
    to SVG images using pdflatex + dvisvgm.
    """

    # Maps placeholder token -> HTML span for inline math, populated per page.
    _svg_placeholders: dict[str, str]

    config_scheme = (
        (
            "latex_path",
            config_options.Type(str, default="latex"),
        ),
        ("dvisvgm_path", config_options.Type(str, default="dvisvgm")),
        ("output_dir", config_options.Type(str, default="tmp")),
    )

    def on_page_markdown(
        self, markdown: str, /, *, page: Any, config: Any, files: Any
    ) -> str:
        """
        Override of the BasePlugin method to process the page markdown to replace LaTeX math with SVG images.
        """

        # Reset per-page placeholder map used by on_page_content.
        self._svg_placeholders = {}

        # Create output directory in site_dir for temporary LaTeX build files
        temp_output_dir: str = os.path.join(
            config["site_dir"], self.config["output_dir"]
        )
        os.makedirs(temp_output_dir, exist_ok=True)

        # Extract the preamble (if any) and remove its fenced block from the markdown
        markdown, math_preamble = self._extract_math_preamble(markdown)

        # First replace fenced code blocks with info 'math'.
        markdown = self._replace_fenced_math(markdown, math_preamble, temp_output_dir)

        # Replace $...$ inline math with opaque placeholders.
        # Actual SVG substitution happens in on_page_content, after markdown→HTML
        # conversion, to prevent Python-Markdown from treating <svg> as a block element.
        markdown = self._replace_display_math(markdown, math_preamble, temp_output_dir)

        return markdown

    def on_page_content(
        self, html: str, /, *, page: Any, config: Any, files: Any
    ) -> str:
        """
        Substitute inline-math placeholders with their SVG <span> HTML.
        This runs after markdown→HTML conversion, so <svg> is never seen by
        the markdown block-level HTML parser.
        """
        for placeholder, span_html in self._svg_placeholders.items():
            html = html.replace(placeholder, span_html)
        return html

    def _hash(self, tex: str) -> str:
        h = hashlib.sha1()
        h.update(b"mkdocs-latex-math")
        h.update(tex.encode("utf-8"))
        return h.hexdigest()

    def _render_to_svg(
        self, tex_body: str, pdflatex_preamble: str, basename: str, temp_output_dir: str
    ) -> str:
        build_dir = os.path.join(temp_output_dir, basename)
        svg_path: str = os.path.join(build_dir, basename + ".svg")
        if os.path.exists(svg_path):
            # If SVG already exists, return its contents to allow inline embedding.
            with open(svg_path, "r", encoding="utf-8") as f:
                return f.read()

        # Minimal document using preview to tightly crop the output
        env = r"""\documentclass{article}
\usepackage{amsmath,amssymb}
\usepackage[active,tightpage,align=middle]{preview}
%s
\begin{document}
\fontsize{14pt}{14pt}\selectfont

\begin{preview}
%s
\end{preview}
\end{document}
    """
        tex: str = env % (pdflatex_preamble, tex_body)

        # Use site_dir/output_dir for LaTeX build files
        build_dir = os.path.join(temp_output_dir, basename)
        os.makedirs(build_dir, exist_ok=True)

        tex_file: str = os.path.join(build_dir, basename + ".tex")
        with open(tex_file, "w", encoding="utf-8") as f:
            f.write(tex)

        proc = subprocess.run(
            [
                self.config["latex_path"],
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-output-directory",
                build_dir,
                tex_file,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"latex failed with code {proc.returncode} \n{proc.stdout.decode('utf-8')}"
            )

        dvi_file: str = os.path.join(build_dir, basename + ".dvi")

        # Run dvisvgm to convert DVI to SVG
        proc = subprocess.run(
            [
                self.config["dvisvgm_path"],
                "--no-fonts",
                "--currentcolor",
                dvi_file,
                "-o",
                svg_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"dvisvgm failed with code {proc.returncode} \n {proc.stdout.decode('utf-8')}"
            )

        # Read and return the generated SVG contents for inline embedding.
        with open(svg_path, "r", encoding="utf-8") as f:
            return f.read()

    def _sanitize_alt(self, text: str) -> str:
        """Sanitize alt text for the img alt tag."""
        alt: str = text.replace('"', "'")
        alt = re.sub(r"\s+", " ", alt)
        return (alt[:120] + "…") if len(alt) > 120 else alt

    def _replace_fenced_math(
        self, md: str, pdflatex_preamble: str, temp_output_dir: str
    ) -> str:
        """Replace fenced code blocks: ```math\n...\n```"""
        fence_re: Pattern[str] = re.compile(
            r"(^|\n)(?P<fence>```|~~~)\s*(?P<info>math\b[^\n]*)\n(?P<body>.*?)(?P=fence)\s*(?:\n|$)",
            re.S,
        )

        def repl(m: Match[str]) -> str:
            body: str = m.group("body").rstrip()
            h: str = self._hash(body)
            basename: str = "latex-" + h
            svg_markup: str = self._render_to_svg(
                body, pdflatex_preamble, basename, temp_output_dir
            )
            # Return the SVG markup inline so it can be recolored via CSS.
            return f"\n{svg_markup}\n"

        return fence_re.sub(repl, md)

    def _replace_display_math(
        self, md: str, pdflatex_preamble: str, temp_output_dir: str
    ) -> str:
        """Replace $...$ (inline, same line) with opaque placeholders."""
        disp_re: Pattern[str] = re.compile(r"\$([^\n]+?)\$")

        def repl(m: Match[str]) -> str:
            body: str = m.group(1).strip()

            # Add equation environment
            body = f"${body}$"

            h: str = self._hash(body)
            basename: str = "latex-" + h
            svg_markup: str = self._render_to_svg(
                body, pdflatex_preamble, basename, temp_output_dir
            )
            # Strip the XML declaration so it does not appear in final HTML.
            svg_markup = re.sub(r"<\?xml[^?]*\?>", "", svg_markup).strip()
            # Collapse whitespace so the SVG is a single uninterrupted token.
            svg_markup = svg_markup.replace("\n", "")
            span_html = (
                f'<span style="display: inline-block; vertical-align: middle;">'
                f'{svg_markup}</span>'
            )
            # Store the HTML against a placeholder that Markdown won't
            # interpret as block-level HTML.  The placeholder must not
            # contain < > or & so it is safe inside a paragraph.
            placeholder = f"LATEXSVGINLINE{h}"
            self._svg_placeholders[placeholder] = span_html
            return placeholder

        return disp_re.sub(repl, md)

    def _extract_math_preamble(self, text: str) -> tuple[str, str]:
        """
        Find a fenced code block whose info string starts with 'math_preamble' return (text_without_block, preamble_body).
        """
        fence_re = re.compile(
            r"(^|\n)(?P<fence>```|~~~)\s*(?P<info>math_preamble*\b[^\n]*)\n(?P<body>.*?)(?P=fence)\s*(?:\n|$)",
            re.S,
        )
        m = fence_re.search(text)
        if not m:
            return text, ""
        body = m.group("body").rstrip()
        start, end = m.span()
        new_text = text[:start] + text[end:]
        return new_text, body
