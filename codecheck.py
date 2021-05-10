"""
Helper module to prepare a CODECHECK report
https://codecheck.org.uk
"""
from datetime import datetime
import os.path as op
import yaml
from IPython.display import Markdown, Latex
import pandas as pd


def name_orcid(entry):
    """Helper function for Name + ORCID"""
    return f"{entry['name']} (ORCID: [{entry['ORCID']}](https://orcid.org/{entry['ORCID']}))"


class Codecheck:
    """
    Object that generates automatic Markdown/LaTeX output for inclusion in a jupyter notebook,
    based on a `codecheck.yml` file.
    """

    def __init__(self, manifest_file=op.join("..", "codecheck.yml")):
        """
        Create new `Codecheck` object.
        
        Parameters
        ----------
        manifest_file : str, optional
            The path/name of the `codecheck.yml` file. Defaults to `../codecheck.yml`.
        """
        with open(manifest_file) as f:
            self.conf = yaml.safe_load(f)

    def title(self):
        """
        Markdown title with the certificate number, the doi of the report, and the CODECHECK
        logo. The logo is expected to be stored as `codecheck_logo.png` in the current
        directory.
        """
        return Markdown(
            f"""# CODECHECK certificate {self.conf['certificate']}{{-}}
## [{self.conf['report'].split('://')[1]}]({self.conf['report']}) {{-}}
[![CODECHECK logo](codecheck_logo.png)](https://codecheck.org.uk)"""
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
            f"Authors | {', '.join([name_orcid(a) for a in self.conf['paper']['authors']])}",
            f"Reference | [{self.conf['paper']['reference'].split('://')[1]}]({self.conf['paper']['reference']})",
            f"Repository | [{self.conf['repository'].split('://')[1]}]({self.conf['repository']})",
            f"Codechecker | {name_orcid(self.conf['codechecker'])}",
            f"Date of check | {datetime.fromisoformat(self.conf['check_time']).date()}",
            f"Summary | {self.conf['summary'].strip()}",
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
File&nbsp;&nbsp;&nbsp; | Comment&nbsp;&nbsp;&nbsp;&nbsp;&nbsp | Size (b)
:--------------------- | :----------------------------------- | -------:
"""
        files_rows = [
            (
                "`"
                + (op.basename(entry["file"]) if remove_dirname else entry["file"])
                + "` | "
                + entry.get("comment", "")
                + " | "
                + str(op.getsize(op.join("outputs", entry["file"])))
            )
            for entry in self.conf["manifest"]
        ]
        return Markdown(files_header + "\n".join(files_rows))

    def summary(self):
        """
        Markdown rendering of the `summary` field in `codecheck.yml`.
        """
        return Markdown(self.conf["summary"].strip())

    def citation(self):
        """
        Markdown citation for this CODECHECK.
        """
        return Markdown(
            f"{self.conf['codechecker']['name']} "
            f"({datetime.fromisoformat(self.conf['check_time']).year}). "
            f"CODECHECK Certificate {self.conf['certificate']}. "
            f"Zenodo. [{self.conf['report'].split('://')[1]}]({self.conf['report']})"
        )

    def about_codecheck(self):
        """
        Markdown boilerplate text about what a CODECHECK is.
        """
        return Markdown(
            """
This certificate confirms that the codechecker could independently reproduce the results of a computational analysis given the data and code from a third party. A CODECHECK does not check whether the original computation analysis is correct. However, as all materials required for the reproduction are freely availableby following the links in this document, the reader can then study for themselves the code and data."""
        )

    def csv_files(self, **kwds):
        """
        Markdown summary of all `.csv` files in the manifest. Prints the output of Panda's `describe` function (number of entries, mean, quantiles, etc.)
        for each column.
        
        Parameters
        ----------
        **kwds
            Additional arguments (e.g. index_col=False) that will be handed over to Panda's `read_csv` function.
        """
        full_markdown = []
        for entry in self.conf["manifest"]:
            fname = entry["file"]
            if not fname.endswith(".csv"):
                continue
            comment = entry.get("comment", None)
            df = pd.read_csv(op.join("outputs", fname), **kwds)
            markdown = f"""### `{fname}` {{-}}
{('Author comment: *' + comment + '*') if comment else ' '}

**Column summary statistics:**

{df.describe().transpose().to_markdown(tablefmt="grid",
                                               floatfmt=('.0f', '.0f', '.4f', '.4f', '.4f', '.4f', '.4f', '.4f', '.4f'))}
"""
            full_markdown.append(markdown)

        return Markdown("\n\n".join(full_markdown))

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
            full_text.extend(
                [
                    r"\begin{figure}" r"\texttt{" + fname.replace("_", r"\_") + r"}.\\",
                    r"Author comment: \emph{" + comment + r"}\\",
                    r"\includegraphics{outputs/" + fname + r"}",
                    r"\end{figure}",
                    "",
                ]
            )
        return Latex("\n".join(full_text))
