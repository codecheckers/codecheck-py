"""
Helper module to prepare a CODECHECK report
https://codecheck.org.uk
"""
import hashlib
import itertools
import json
import os
import os.path as op
import pandas as pd
import re
import session_info2 as si
import subprocess
import warnings
import yaml
from IPython.display import Markdown
from datetime import datetime
from pathlib import Path

from manifest import ManifestProcessor
from validation import CodecheckValidator
from validation_config import TEMPLATE_DIRS, as_list


def name_orcid(entry):
    """Helper function for Name + ORCID"""
    if 'ORCID' in entry:
        return f"{entry['name']} (ORCID: {entry['ORCID']})"
    else:
        return entry['name']

def multiple_name_orcid(entries):
    """Helper function for multiple people to return their Name + ORCID"""
    entries = as_list(entries)
    return f"{', '.join([name_orcid(a) for a in entries])}"

def multiple_name(entries):
    """Helper function for multiple people to return their names"""
    entries = as_list(entries)
    return f"{', '.join([a['name'] for a in entries])}"

def url_link(url):
    """Helper function to create Markdown links for the full URL with the protocol in front."""
    return f"[{url}]({url})"

def short_link(url):
    """Helper function to create Markdown links for the short URL without the protocol in front."""
    return f"[{url.split('://')[1]}]({url})"

# File types of manifest files and how they are shown in `Codecheck.manifest_files()`
TABULAR_SEPARATORS = {".csv": ",", ".tsv": "\t"}
EXCEL_EXTENSIONS = (".xlsx", ".xlsm")
TEXT_EXTENSIONS = (".txt", ".log", ".rout", ".out", ".md", ".json")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf")  # supported natively by Typst
# number formats of the `describe()` table: index and `count` without, the 7 other statistics with decimals
DESCRIBE_FLOATFMT = (".0f", ".0f") + (".4f",) * 7
VECTOR_EXTENSIONS = (".svg", ".pdf")  # images without a pixel size
NO_PREVIEW_DEFAULT = "*No preview available for this file type.*"
NO_PREVIEW = {  # hints for figure types that Typst cannot include
    **{ext: "*No preview available: Typst cannot include EPS files, convert the figure to PDF or PNG.*"
       for ext in (".eps",)},
    **{ext: f"*No preview available: Typst cannot include {ext[1:].upper()} images, convert the figure to PNG or JPG.*"
       for ext in (".tif", ".tiff", ".webp", ".bmp")},
}
MAX_JSON_BYTES = 1024 * 1024  # larger JSON files are not parsed for pretty-printing
MAX_LINE_WIDTH = 200  # longer lines of text files are cut

class Codecheck:
    """
    Object that generates automatic Markdown/LaTeX output for inclusion in a jupyter notebook,
    based on a `codecheck.yml` file.
    """

    def __init__(self, manifest_file=op.join("..", "codecheck.yml"),
                 validate=False, strict=False):
        """
        Create new `Codecheck` object with optional validation.

        Parameters
        ----------
        manifest_file : str, optional
            The path/name of the `codecheck.yml` file. Defaults to `../codecheck.yml`.
        validate : bool, optional
            Whether to run validation on initialization. Defaults to False.
            Set to True to validate configuration before processing.
        strict : bool, optional
            If True, raises error on validation failure (when validate=True).
            If False, only warnings are issued. Defaults to False.
        """
        self.manifest_file = manifest_file
        self.validator = CodecheckValidator(manifest_file)
        self.manifest_processor = None

        # Optionally validate on initialization
        if validate:
            passed, issues = self.validator.validate_all(
                check_manifest=False,  # Don't check files until explicitly requested
                strict=strict
            )
            if not passed and strict:
                raise ValueError(
                    f"Validation failed for {manifest_file}:\n{self.validator.format_report(markdown=False)}"
                )

        with open(manifest_file) as f:
            self.conf = yaml.safe_load(f)

        # Initialize manifest processor if manifest exists
        if self.conf and 'manifest' in self.conf:
            base_dir = Path(manifest_file).parent
            self.manifest_processor = ManifestProcessor(
                self.conf['manifest'],
                base_dir
            )

    def get_formatted_summary(self):
        """Remove additional whitespaces and newline characters from the summary."""
        return self.conf['summary'].strip().replace("\n", " ")

    def title(self):
        """
        Markdown title with the certificate number, the doi of the report, and the CODECHECK
        logo. The logo is expected to be stored as `codecheck_logo.png` in the current
        directory.
        """
        return Markdown(
            f"""# CODECHECK certificate {self.conf['certificate']}
## {url_link(self.conf['report'])}
[![CODECHECK logo](codecheck_logo.svg)](https://codecheck.org.uk)"""
        )

    def summary_table(self):
        """
        Markdown table with the general information (title, authors, etc.) from the `codecheck.yml`
        file.
        """
        summary_header = """
Item | Value
:--- | :----
"""
        summary_rows = [
            f"Title | *{self.conf['paper']['title']}*",
            f"Author(s) | {multiple_name_orcid(self.conf['paper']['authors'])}",
            f"Reference | {url_link(self.conf['paper']['reference'])}",
            f"Repository | {url_link(self.conf['repository'])}",
            f"Codechecker(s) | {multiple_name_orcid(self.conf['codechecker'])}",
            f"Date of check | {datetime.fromisoformat(self.conf['check_time']).date()}",
            f"Summary | {self.get_formatted_summary()}",
        ]
        return Markdown(summary_header + "\n".join(summary_rows))

    def files(self, remove_dirname=True):
        """
        Markdown table with the name, comment and file size of all files in the manifest.
        Only shows the file name without the directory by default.
        
        Parameters
        ----------
        remove_dirname: bool
            Whether to remove the directory names from the file names in the `file` column.
            Defaults to `True`.
        """
        # Note that the &nbsp; below are used to work around the fact that pandoc seems to
        # calculate the column width for the LaTeX output based on the length of the headers
        files_header = """
File | Comment | Size (b)
:--------------------- | :----------------------------------- | -------:
"""
        files_rows = [
            (
                "`"
                + (op.basename(entry["file"]) if remove_dirname else entry["file"])
                + "` | "
                + str(entry.get("comment") or "")
                + " | "
                + (
                    str(op.getsize(op.join("outputs", entry["file"])))
                    if op.isfile(op.join("outputs", entry["file"]))
                    else "**missing**"
                )
            )
            for entry in self.conf["manifest"]
            if isinstance(entry, dict) and entry.get("file")
        ]
        return Markdown(files_header + "\n".join(files_rows))

    def summary(self):
        """
        Markdown rendering of the `summary` field in `codecheck.yml`.
        """
        return Markdown(self.get_formatted_summary())

    def citation(self):
        """
        Markdown citation for this CODECHECK.
        """
        return Markdown(
            f"{multiple_name(self.conf['codechecker'])} "
            f"({datetime.fromisoformat(self.conf['check_time']).year}). "
            f"CODECHECK Certificate {self.conf['certificate']}. "
            f"Zenodo. {url_link(self.conf['report'])}"
        )

    def about_codecheck(self):
        """
        Markdown boilerplate text about what a CODECHECK is.
        """
        return Markdown(
            """
This certificate confirms that the codechecker could independently reproduce the results of a computational analysis given the data and code from a third party. A CODECHECK does not check whether the original computation analysis is correct. However, as all materials required for the reproduction are freely availableby following the links in this document, the reader can then study for themselves the code and data."""
        )
    
    def session_info(self):
        """
        Markdown formatted session info
        """
        return Markdown(f"""```bash
{si.session_info(os=True, cpu=True, gpu=True, dependencies=True)}
```
"""
)

    @staticmethod
    def _file_info(path):
        """Size, modification time, SHA-256 checksum and number of lines of a file (read in chunks)."""
        sha256 = hashlib.sha256()
        lines = 0
        last = b""
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                sha256.update(chunk)
                lines += chunk.count(b"\n")
                last = chunk
        if last and not last.endswith(b"\n"):
            lines += 1  # last line without trailing newline
        stat = os.stat(path)
        return {
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "sha256": sha256.hexdigest(),
            "lines": lines,
        }

    @staticmethod
    def _info_table(rows):
        """Markdown table with `Item | Value` rows."""
        return "Item | Value\n:--- | :----\n" + "\n".join(f"{k} | {v}" for k, v in rows) + "\n"

    @staticmethod
    def _info_rows(info):
        """Table rows for the output of `_file_info()`."""
        return [
            ("Size (b)", f"{info['size']:,}"),
            ("Modified", info["modified"]),
            ("SHA-256", f"`{info['sha256']}`"),
        ]

    @staticmethod
    def _fenced(text):
        """Fenced code block that cannot be closed by the text itself."""
        longest = max((len(m) for m in re.findall(r"~+", text)), default=0)
        fence = "~" * max(3, longest + 1)
        return f"{fence}\n{text}\n{fence}\n"

    def _tabular(self, path, ext, info, max_rows, max_cols, describe, head, **kwds):
        """Extra info rows and Markdown (first rows, statistics) of a CSV/TSV/Excel file, bounded by max_rows/max_cols."""
        rows = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", pd.errors.DtypeWarning)
            if ext in EXCEL_EXTENSIONS:
                with pd.ExcelFile(path) as workbook:
                    sheets = workbook.sheet_names
                    df = workbook.parse(**{"nrows": max_rows, **kwds})
                shown = ", ".join(f"`{name}`" for name in sheets[:10])
                rows.append(("Sheets", shown + (f", ... ({len(sheets)} in total)" if len(sheets) > 10 else "")))
                rows.append(("Columns (first sheet)", f"{df.shape[1]:,}"))
            else:
                read_kwds = {"nrows": max_rows, **kwds}
                if "delimiter" not in read_kwds:  # `delimiter` is an alias of `sep` in pandas
                    read_kwds.setdefault("sep", TABULAR_SEPARATORS[ext])
                n_cols = None
                if "usecols" not in read_kwds:
                    # Only parse the first `max_cols` columns, wide files are otherwise very slow
                    n_cols = pd.read_csv(path, **{**read_kwds, "nrows": 1}).shape[1]
                    read_kwds["usecols"] = list(range(min(n_cols, max_cols)))
                df = pd.read_csv(path, **read_kwds)
                rows.append(("Lines", f"{info['lines']:,}"))
                rows.append(("Columns", f"{n_cols if n_cols is not None else df.shape[1]:,}"))
        df = df.iloc[:, :max_cols]

        body = ""
        if head:
            body += f"""**First {min(head, len(df))} rows** (up to {max_cols} columns):

{df.head(head).to_markdown(index=False)}

"""
        if describe and len(df.columns) > 0:
            body += f"""**Column summary statistics** (first {len(df)} rows, up to {max_cols} columns):

{df.describe().transpose().to_markdown(floatfmt=DESCRIBE_FLOATFMT)}
"""
        return rows, body

    @staticmethod
    def _json_lines(path, info):
        """Pretty-printed lines of a JSON file, or `None` if it is too large or invalid (then shown as plain text)."""
        if info["size"] > MAX_JSON_BYTES:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.dumps(json.load(f), indent=2, ensure_ascii=False).splitlines()
        except ValueError:
            return None

    def _text(self, path, ext, info, max_lines):
        """Extra info rows and Markdown (first `max_lines` lines) of a text or JSON file."""
        lines = self._json_lines(path, info) if ext == ".json" else None
        if lines is not None:
            total = len(lines)
        else:
            total = info["lines"]
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = [line.rstrip("\r\n") for line in itertools.islice(f, max_lines)]
        lines = [line if len(line) <= MAX_LINE_WIDTH else line[:MAX_LINE_WIDTH] + " [...]" for line in lines[:max_lines]]
        body = self._fenced("\n".join(lines))
        if total > max_lines:
            body += f"\n*... {total - max_lines:,} more lines omitted*\n"
        return [("Lines", f"{total:,}")], body

    @staticmethod
    def _image(fname, comment, path, ext):
        """Extra info rows and Markdown of an image (embedded by Typst, so only formats supported by Typst)."""
        rows = []
        if ext not in VECTOR_EXTENSIONS:
            try:
                from PIL import Image
                with Image.open(path) as img:
                    rows.append(("Dimensions", f"{img.width} x {img.height} px"))
            except (ImportError, OSError):  # Pillow is optional, the dimensions are not essential
                pass
        if ext == ".pdf":
            rows.append(("Preview", "first page"))
        alt = re.sub(r"[\[\]\n]", " ", comment or fname)
        return rows, f"![{alt}](<outputs/{fname}>)\n"

    def _render_manifest_entry(self, entry, max_rows, max_cols, max_lines, describe, head, **kwds):
        """Markdown section for one manifest entry; problems are reported in the section, they never raise."""
        fname = str(entry["file"])
        comment = str(entry["comment"]) if entry.get("comment") else None
        path = op.join("outputs", fname)
        ext = op.splitext(fname)[1].lower()
        section = f"""### `{fname}`
{('Author comment: *' + comment + '*') if comment else ' '}

"""
        outputs = Path("outputs").resolve()
        if not (outputs / fname).resolve().is_relative_to(outputs):
            return section + "> **Not shown:** the path is not inside the `outputs/` directory.\n"
        if not op.isfile(path):
            return section + f"> **File missing:** `outputs/{fname}` does not exist.\n"
        try:
            info = self._file_info(path)  # read the file once for size, checksum and line count
            if ext in TABULAR_SEPARATORS or ext in EXCEL_EXTENSIONS:
                rows, body = self._tabular(path, ext, info, max_rows, max_cols, describe, head, **kwds)
            elif ext in TEXT_EXTENSIONS:
                rows, body = self._text(path, ext, info, max_lines)
            elif ext in IMAGE_EXTENSIONS:
                rows, body = self._image(fname, comment, path, ext)
            else:
                rows, body = [], NO_PREVIEW.get(ext, NO_PREVIEW_DEFAULT) + "\n"
            return section + self._info_table(self._info_rows(info) + rows) + "\n" + body
        except Exception as e:  # one broken file must not break the whole certificate
            message = re.sub(r"\s+", " ", f"{type(e).__name__}: {e}")[:300]
            return section + f"> **Could not display this file:** {message}\n"

    def manifest_files(self, max_rows=15, max_cols=50, max_lines=50, describe=True, head=0, extensions=None, **kwds):
        """
        Markdown section for every file in the manifest, shown according to the file type. Each section starts with
        the author comment and a table with file size, modification time and SHA-256 checksum.

        - `.csv`, `.tsv`, `.xlsx`: number of lines/columns, optionally the first rows and summary statistics
        - `.txt`, `.log`, `.out`, `.Rout`, `.md`, `.json`: the first lines (JSON is pretty-printed)
        - `.png`, `.jpg`, `.gif`, `.svg`, `.pdf`: the image (first page for PDFs)
        - anything else: only the file information

        Missing or broken files are reported in the section instead of raising an error. The size of the output does
        not depend on the size of the files.

        Parameters
        ----------
        max_rows: int
            Number of rows to read from tables for the statistics. Defaults to `15`.
        max_cols: int
            Limit of table columns to display. Defaults to `50`.
        max_lines: int
            Limit of lines to display of text and JSON files. Defaults to `50`.
        describe: bool
            Whether to show summary statistics of tables. Defaults to `True`.
        head: int
            Number of first rows of tables to show (at most `max_rows`). Defaults to `0` (not shown).
        extensions: sequence, optional
            Only show files with these extensions (in lower case, e.g. `('.csv',)`). Defaults to all files.
        **kwds
            Additional arguments (e.g. index_col=False) that will be handed over to Panda's `read_csv`/`read_excel`
            function. Arguments given here (e.g. `nrows`, `usecols`) take precedence over `max_rows` and `max_cols`.
            They have to be valid for all table types in the manifest, use `extensions` to handle e.g. CSV and Excel
            files with different arguments.
        """
        sections = [
            self._render_manifest_entry(entry, max_rows, max_cols, max_lines, describe, head, **kwds)
            for entry in self.conf["manifest"]
            # malformed entries are reported by the validation, they are skipped here
            if isinstance(entry, dict) and entry.get("file")
            and (extensions is None or op.splitext(str(entry["file"]))[1].lower() in extensions)
        ]
        return Markdown("\n\n".join(sections))

    def csv_files(self, max_rows=15, max_cols=50, describe=True, head=0, **kwds):
        """Like `manifest_files()`, but only for the `.csv` files in the manifest (see there for the arguments)."""
        return self.manifest_files(max_rows=max_rows, max_cols=max_cols, describe=describe, head=head,
                                   extensions=(".csv",), **kwds)

    def git_info(self):
        """
        Markdown sentence with the git commit that this check is based on (the repository that contains
        `codecheck.yml`). Reports if the information is not available (e.g. no git repository).
        """
        repo_dir = Path(self.manifest_file).resolve().parent

        def git(*args):
            return subprocess.run(["git", "-C", str(repo_dir), *args], capture_output=True, text=True, timeout=10)

        try:
            commit = git("rev-parse", "HEAD")
            # the codechecker's own files (template, certificate config) are changed by definition, ignore them
            ignore = [f":(exclude){name}" for name in (*TEMPLATE_DIRS, "codecheck.yml")]
            status = git("status", "--porcelain", "--untracked-files=no", "--", ".", *ignore)
            dirty = commit.returncode == 0 and bool(status.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            commit = None
        if commit is None or commit.returncode != 0:
            return Markdown("*Git commit information is not available (not a git repository, or git is not installed).*")
        text = f"This check is based on the commit `{commit.stdout.strip()}`"
        if dirty:
            text += " (the working tree had uncommitted changes to tracked files outside of the CODECHECK files)"
        return Markdown(text + ".")

    def latex_figures(self, extensions=(".pdf", ".eps")):
        """
        LaTeX output (therefore only useful for the LaTeX/PDF version of the notebook) of all the figures in the
        manifest.
        
        Parameters
        ----------
        extensions : sequence
            A list/tuple of extensions (in lower case) that should be handled by this function.
            Defaults to `('.pdf', '.eps')`.
        """
        full_text = []
        # Figures (only PDF versions)
        for entry in self.conf["manifest"]:
            fname = entry["file"]
            if not op.splitext(fname)[1].lower() in extensions:
                continue
            comment = entry["comment"]
            heading = f"""### `{fname}`
{('Author comment: *' + comment + '*') if comment else ' '}"""
            full_text.extend(
                [
                    heading + r"![" + r"Author comment: " + comment + r"]" + r"(outputs/" + fname + r")",
                    "",
                ]
            )
        return Markdown("\n".join(full_text))

    def validate(self, check_manifest=True, check_register=True, strict=False):
        """
        Run validation checks on the codecheck.yml file.

        Parameters
        ----------
        check_manifest : bool, optional
            Whether to check if manifest files exist in outputs/. Defaults to True.
        check_register : bool, optional
            Whether to check for GitHub register issue. Defaults to True.
        strict : bool, optional
            If True, warnings are treated as failures. Defaults to False.

        Returns
        -------
        tuple
            (passed: bool, issues: List[ValidationIssue])
        """
        return self.validator.validate_all(
            check_manifest=check_manifest,
            check_register=check_register,
            strict=strict
        )

    def validation_report(self, markdown=True):
        """
        Display validation report.

        Parameters
        ----------
        markdown : bool, optional
            If True, return Markdown formatted report. Otherwise plain text.
            Defaults to True.

        Returns
        -------
        Markdown or str
            Formatted validation report
        """
        report = self.validator.format_report(markdown=markdown)
        if markdown:
            return Markdown(report)
        else:
            return report

    def validate_manifest_files(self):
        """
        Validate that all manifest files exist in outputs/ directory.

        Returns
        -------
        tuple
            (all_exist: bool, missing_files: List[str])
        """
        if not self.manifest_processor:
            return False, []
        return self.manifest_processor.validate_output_files_exist()

    def manifest_summary(self):
        """
        Get summary statistics about the manifest.

        Returns
        -------
        Markdown
            Formatted manifest summary with file counts, sizes, and types
        """
        if not self.manifest_processor:
            return Markdown("*No manifest found*")

        summary = self.manifest_processor.get_manifest_summary()

        markdown = f"""### Manifest Summary

- **Total files**: {summary['total_files']}
- **Total size**: {summary['total_size']:,} bytes ({summary['total_size_mb']} MB)
- **Files with comments**: {summary['has_comments']}

**File types:**
"""
        for ext, count in sorted(summary['file_types'].items()):
            ext_display = ext if ext else "(no extension)"
            markdown += f"- `{ext_display}`: {count} file(s)\n"

        return Markdown(markdown)

    def copy_manifest_files(self, source_dir=None, keep_full_path=True,
                          overwrite=True, dry_run=False):
        """
        Copy manifest files from source to outputs directory.

        Parameters
        ----------
        source_dir : str or Path, optional
            Source directory containing files. Defaults to parent of config file.
        keep_full_path : bool, optional
            If True, maintain directory structure. If False, flatten. Defaults to True.
        overwrite : bool, optional
            If True, overwrite existing files. Defaults to True.
        dry_run : bool, optional
            If True, don't actually copy files. Defaults to False.

        Returns
        -------
        Markdown
            Report of copied files
        """
        if not self.manifest_processor:
            return Markdown("*No manifest found*")

        if source_dir is None:
            source_dir = Path(self.manifest_file).parent

        copied = self.manifest_processor.copy_manifest_files(
            source_dir=source_dir,
            keep_full_path=keep_full_path,
            overwrite=overwrite,
            dry_run=dry_run
        )

        if not copied:
            return Markdown("*No files copied*")

        markdown = f"### Copied {len(copied)} file(s)\n\n"
        for entry in copied:
            size_kb = entry['size'] / 1024
            markdown += f"- `{entry['file']}` ({size_kb:.1f} KB)\n"

        return Markdown(markdown)
    
    def acknowledge_sponsors(self):
        """The sponsoring acknowledgement."""
        return Markdown("CODECHECK is financially supported by the Mozilla foundation.")
