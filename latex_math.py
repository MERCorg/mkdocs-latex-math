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

    config_scheme = (
        ("asset_subdir", config_options.Type(str, default="assets/latex")),
        (
            "latex_path",
            config_options.Type(str, default="latex"),
        ),
        ("dvisvgm_path", config_options.Type(str, default="dvisvgm")),
        ("temp_dir", config_options.Type(str, default="")),
    )

    def on_page_markdown(
        self, markdown: str, /, *, page: Any, config: Any, files: Any
    ) -> str:
        """
        Override of the BasePlugin method to process the page markdown to replace LaTeX math with SVG images.
        """

        site_assets_dir: str = os.path.join(
            config["site_dir"], self.config["asset_subdir"]
        )
        os.makedirs(site_assets_dir, exist_ok=True)

        site_url: str = os.path.join(
            config.get("site_url", ""), self.config["asset_subdir"]
        )

        if self.config["temp_dir"]:
            os.makedirs(self.config["temp_dir"], exist_ok=True)

        # Extract the preamble (if any) and remove its fenced block from the markdown
        markdown, math_preamble = self._extract_math_preamble(markdown)

        # First replace fenced code blocks with info 'math'.
        markdown = self._replace_fenced_math(
            markdown, site_assets_dir, site_url, math_preamble
        )

        # Then handle $$...$$ display math
        markdown = self._replace_display_math(
            markdown, site_assets_dir, site_url, math_preamble
        )

        return markdown

    def _hash(self, tex: str) -> str:
        h = hashlib.sha1()
        h.update(b"pdflatex_v1")
        h.update(tex.encode("utf-8"))
        return h.hexdigest()

    def _render_to_svg(
        self, tex_body: str, pdflatex_preamble: str, out_dir: str, basename: str
    ) -> str:
        svg_path: str = os.path.join(out_dir, basename + ".svg")
        if os.path.exists(svg_path):
            # Skip rendering if SVG already exists, since we hash the input.
            return svg_path

        # Minimal document using preview to tightly crop the output
        env = r"""\documentclass{article}
\usepackage[active,tightpage]{preview}
\usepackage{amsmath,amssymb}
%s
\begin{document}
\begin{preview}
%s
\end{preview}
\end{document}
"""
        tex: str = env % (pdflatex_preamble, tex_body)

        with tempfile.TemporaryDirectory(
            dir=self.config["temp_dir"] or None, delete="temp_dir" not in self.config
        ) as td:
            tex_file: str = os.path.join(td, basename + ".tex")
            with open(tex_file, "w", encoding="utf-8") as f:
                f.write(tex)

            proc = subprocess.run(
                [
                    self.config["latex_path"],
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-output-directory",
                    td,
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

            dvi_file: str = os.path.join(td, basename + ".dvi")

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

            return svg_path

    def _sanitize_alt(self, text: str) -> str:
        """Sanitize alt text for the img alt tag."""
        alt: str = text.replace('"', "'")
        alt = re.sub(r"\s+", " ", alt)
        return (alt[:120] + "…") if len(alt) > 120 else alt

    def _url_path(self, site_url: str, path: str) -> str:
        """Convert a full file path to a site-relative path for use in the img src attribute."""
        return site_url + "/" + os.path.basename(path)

    def _replace_fenced_math(
        self, md: str, out_dir: str, site_url: str, pdflatex_preamble: str
    ) -> str:
        """Replace fenced code blocks: ```math\n...\n```"""
        fence_re: Pattern[str] = re.compile(
            r"(^|\n)(?P<fence>```|~~~)\s*(?P<info>math\b[^\n]*)\n(?P<body>.*?)(?P=fence)\s*(?:\n|$)",
            re.S,
        )

        def repl(m: Match[str]) -> str:
            try:
                body: str = m.group("body").rstrip()
                h: str = self._hash(body)
                basename: str = "latex-" + h
                svg: str = self._render_to_svg(
                    body, pdflatex_preamble, out_dir, basename
                )
                alt: str = self._sanitize_alt(body)
                return f'\n<img src="{self._url_path(site_url, svg)}">\n'
            except Exception as e:
                print(f"Error processing fenced pdflatex: {e}")
                return m.group(0)  # return original on error

        return fence_re.sub(repl, md)

    def _replace_display_math(
        self, md: str, out_dir: str, site_url: str, pdflatex_preamble: str
    ) -> str:
        """Replace $...$ (inline, same line)"""
        disp_re: Pattern[str] = re.compile(r'\$([^\n]+?)\$')

        def repl(m: Match[str]) -> str:
            try:
                body: str = m.group(1).strip()

                # Add equation environment
                body = f"${body}$"

                h: str = self._hash(body)
                basename: str = "latex-" + h
                svg: str = self._render_to_svg(
                    body, pdflatex_preamble, out_dir, basename
                )
                alt: str = self._sanitize_alt(body)
                return f'<img src="{self._url_path(site_url, svg)}">'
            except Exception as e:
                print(f"Error processing display math: {e}")
                return m.group(0)  # return original on error

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
