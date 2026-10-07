"""
Plain URLs in Markdown as links, as Jupyter shows them (GitHub's "autolink" extension).

The Markdown renderer of Typst (cmarker) only knows CommonMark links, so `https://example.org` stays plain text in
the PDF while it is a link in the notebook. `link_urls()` writes such URLs as autolinks (`<https://example.org>`),
leaving code, links, images, HTML tags and link reference definitions alone. Run on the executed notebook before the
conversion to Markdown (see `notebook_to_pdf.sh`): `python markdown_links.py codecheck.executed.ipynb`.
"""
import json
import re
import sys

# Parts of the text that are left alone, then the plain URLs; the first alternative that matches wins
_TOKEN = re.compile(
    r"(?P<skip>"
    r"(?P<ticks>`+)(?:(?!\n[ \t]*\n).)*?(?<!`)(?P=ticks)(?!`)"  # inline code (within a paragraph)
    r"|<[A-Za-z/!?][^<>\n]*>"                                    # autolink or HTML tag (not `x < 3`)
    r"|!?\[[^\[\]\n]*\]\([^\n]*?\)"                             # inline link or image
    r"|!?\[[^\[\]\n]*\]\[[^\[\]\n]*\]"                          # reference link or image
    r"|^ {0,3}\[[^\[\]\n]+\]:[^\n]*$"                           # link reference definition
    r"|\\."                                                     # escaped character
    r")"
    r"|(?P<url>(?<![\w/.@-])(?:https?://|www\.)[^\s<>|`]+)",
    re.MULTILINE | re.DOTALL,
)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_INDENTED = re.compile(r"^(?: {4}|\t)")
_TRAILING = ".,:;!?'\"*_~"


def _trim(url):
    """URL without trailing punctuation and unbalanced closing parentheses (as GitHub), and the trimmed rest."""
    end = len(url)
    while end:
        if url[end - 1] in _TRAILING:
            end -= 1
        elif url[end - 1] == ")" and url.count("(", 0, end) < url.count(")", 0, end):
            end -= 1
        else:
            break
    return url[:end], url[end:]


def _link(match):
    if match.group("url") is None:
        return match.group(0)
    url, rest = _trim(match.group("url"))
    if "\\" in url:  # backslash escapes are not processed in autolinks, the link would be wrong
        return match.group(0)
    if "://" not in url:  # `www.example.org`, the link needs a scheme
        return f"[{url}](http://{url}){rest}" if "." in url[4:] else match.group(0)
    return f"<{url}>{rest}" if url.split("://", 1)[1] else match.group(0)


def link_urls(markdown):
    """Markdown with the plain URLs outside of code blocks and code spans written as autolinks."""
    out, text, fence, indented = [], [], None, False
    for line in markdown.splitlines(keepends=True):
        marker = _FENCE.match(line)
        # an indented code block starts after a blank line (in a list this is a nested paragraph, left alone too)
        previous = (text or out or [""])[-1].splitlines() or [""]  # `out` also holds linked chunks of lines
        if _INDENTED.match(line):
            indented = indented or not previous[-1].strip()
        elif line.strip():
            indented = False
        if fence is None and indented:
            out.append(_TOKEN.sub(_link, "".join(text)))
            text = []
        elif fence is None:
            if not marker:
                text.append(line)
                continue
            out.append(_TOKEN.sub(_link, "".join(text)))
            text, fence = [], marker.group(1)
        # a closing fence: only the fence character, at least as often as in the opening fence
        elif marker and len(marker.group(1)) >= len(fence) and not line.strip().lstrip(fence[0]):
            fence = None
        out.append(line)
    out.append(_TOKEN.sub(_link, "".join(text)))
    return "".join(out)


def _linked(source):
    """`link_urls()` for a notebook text field, a string or a list of lines."""
    return link_urls("".join(source) if isinstance(source, list) else source)


def link_notebook(path):
    """
    Write the plain URLs in the Markdown cells and Markdown outputs of the notebook at `path` as links. Only uses the
    standard library (no nbformat): the script may run with another Python than Jupyter (e.g. an activated venv).
    """
    with open(path, encoding="utf-8") as f:
        notebook = json.load(f)
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") == "markdown":
            cell["source"] = _linked(cell["source"])
        for output in cell.get("outputs", []):
            data = output.get("data", {})
            if "text/markdown" in data:
                data["text/markdown"] = _linked(data["text/markdown"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(notebook, f, ensure_ascii=False, indent=1)
        f.write("\n")

if __name__ == "__main__":
    for notebook_path in sys.argv[1:]:
        link_notebook(notebook_path)
