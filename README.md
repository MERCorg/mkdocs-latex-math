# Overview

As opposed to `MathJax` or `KaTeX`, this plugin uses a full LaTeX engine to
render math expressions as `SVG` files that are directly linked in the generated
HTML. This is particularly useful for documentation that involves pseudocode and
content that is also used in scientific publications. It is inspired by the 
[MyST](https://myst-parser.readthedocs.io/) project.

## Usage

This plugin requires a [LaTeX](https://www.latex-project.org/) installation with
`pdflatex` and `dvisvgm` available in the system `PATH`, and any packages
included in the math expressions.

This plugin renders inline math, delimited by single dollar signs `$...$`, or
double dollar signs `$$...$$` for block math. Additionally, fenced code blocks with the info
string `math` are also rendered. For example:

```markdown

See the following equation for the area of a circle $A = \pi r^2$.

```

We can use a special fenced `math_preamble` code block to include LaTeX packages or define macros:

```markdown

  ```math_preamble
  \usepackage{tikz}
  ```

  Later on in the tikz we can draw a circle with tikz:

  ```math
  \begin{tikzpicture}
    \draw (0,0) circle (1cm);
  \end{tikzpicture}
  ```

```

The `site_url` configuration option in `mkdocs.yml` is used to determine the correct
URL for the generated SVG images.

The svgs are generated with the `--currentcolor` option to `dvisvgm`, so it is possible to sets
their colors with CSS. For example, to make the math images blue, you can add the following CSS rule:

```css

svg {
    color: blue;
}

```

## Configuration
 
This plugin can be configured via the `mkdocs.yml` configuration file. The following
options are available under the `plugins` section:
 
 - 'dvisvgm_path': Path to the dvisvgm tool. Default: `dvisvgm`
 - 'latex_path': Path to the latex tool. Default: `latex`
 - 'asset_subdir': Subdirectory in the site output directory to store generated images
 - 'temp_dir': Directory to use for temporary files, if enabled will dump files for inspection. Default: system temp directory.
