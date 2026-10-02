# codecheck-py

[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/codecheckers/codecheck-py/main?labpath=.codecheck/codecheck.ipynb)

Python-based template for writing [CODECHECK](https://codecheck.org.uk)
certificates.

Note that this is an **alpha version**, please report any issues in the
[issue tracker](https://github.com/codecheckers/codecheck-py/issues).

## Try it Online

**🚀 Launch on Binder**: Click the badge above to try this template in your browser without installing anything! The Binder environment includes all dependencies and opens an interactive notebook to explore the template.

### What You Can Do on Binder

- **Explore the template**: Run the certificate generation notebook
- **Test validation**: Try the validation system with example data
- **Experiment**: Modify code and see results immediately
- **Learn**: Follow the workflow without local setup

**Note**: Binder environments are temporary and reset when idle. For actual CODECHECK work, clone the repository locally.

## Quick Start

> The template files live in the `.codecheck/` directory, both in this repository and
> in the repository you are checking. `codecheck.yml` stays in the root of the checked
> repository.

### 1. Prerequisites

Install the dependencies (Python, Jupyter, pandas, and the [Typst](https://typst.app)
command line tool used to create the PDF) with [conda](https://docs.conda.io):

```bash
git clone https://github.com/codecheckers/codecheck-py.git
cd codecheck-py
conda env create -f environment.yml
conda activate codecheck-env
typst --version   # should print a version number
```

### 2. Add the template to the repository you are checking

Fork or clone the repository you want to check, then copy **only the template
files** (not `tests/`, `CLAUDE.md`, `.github/`, etc.) and the example config:

```bash
cd /path/to/repository-to-check
mkdir -p .codecheck/outputs
cp /path/to/codecheck-py/.codecheck/*.{py,ipynb,typ,svg,sh} .codecheck/
cp /path/to/codecheck-py/codecheck.yml .      # then edit it, see step 3
```

### 3. Fill in `codecheck.yml`

Edit `codecheck.yml` in the repository root according to the
[configuration file specification](https://codecheck.org.uk/spec/config/1.0/).
Replace all `TODO`/`FIXME` placeholders (see [Validation](#validation-features)).

### 4. Reproduce the results and copy them to `.codecheck/outputs/`

Run the authors' code. Every file listed in the `manifest` of `codecheck.yml` must
be copied to `.codecheck/outputs/`, **keeping the path from the manifest**. The
manifest paths are relative to the repository root, so a manifest entry
`figures/image.png` has to be placed at `.codecheck/outputs/figures/image.png`.

You don't have to do this by hand: the notebook copies the manifest files from
the repository into `outputs/` every time it runs (`check.copy_manifest_files(update=True)`),
so a rebuilt certificate never uses old copies. `update=True` keeps a file in `outputs/` that is
newer than the one in the repository. Files that git tracks and that have not changed since the
last commit are marked in the report ("was it reproduced?"), because then the copy is
probably the authors' original rather than your result. This report is only shown in
the notebook, not in the certificate. If your results are not in the repository
(e.g. computed on another machine or in a container), copy them into `outputs/` yourself and set
`COPY_OUTPUTS = False` in the notebook.

Why a separate `outputs/` directory? Typst can only read files inside `.codecheck/`, so
the figures in the certificate must be there; and `outputs/` keeps the files you
reproduced apart from the authors' files, as the record that goes with the certificate.

### 5. Fill in the notebook and create the certificate

Open `.codecheck/codecheck.ipynb` (e.g. `jupyter lab .codecheck/codecheck.ipynb`), fill in
the `TODO` sections (notes, recommendations), and then build the PDF:

```bash
cd .codecheck
sh notebook_to_pdf.sh
```

The script runs the notebook (hiding the code cells, and the output of cells tagged
`remove-output`) into `codecheck.md` with `jupyter nbconvert`, and then compiles `codecheck.typ` with `typst` into
`codecheck.pdf`. It stops with an error if `codecheck.md` is larger than 5 MB
(set `MAX_MD_BYTES` to change that limit), which usually means that very large
output (e.g. big tables) ended up in the report.

### Output files

`check.manifest_files()` shows every file of the manifest according to its type. Each
section starts with the author's comment and a table with the file size, modification
time and SHA-256 checksum:

| File type | What is shown |
| --- | --- |
| `.csv`, `.tsv`, `.xlsx` | number of lines and columns, summary statistics (`describe`) of the first `max_rows` rows (default 15) and first `max_cols` columns (default 50), optionally the first rows (`head=5`) |
| `.txt`, `.log`, `.out`, `.Rout`, `.md`, `.json` | the first `max_lines` lines (default 50), JSON is pretty-printed |
| `.png`, `.jpg`, `.gif`, `.svg`, `.pdf` | the image itself (the first page of PDFs) |
| anything else | only the file information |

The report stays small even for huge files, and a missing or broken file is reported in
its section instead of stopping the build. Additional arguments are passed to
`pandas.read_csv()`/`read_excel()`:

```python
check.manifest_files(max_rows=50, max_cols=20, index_col=False, header=None)
check.manifest_files(describe=False, head=5)   # first 5 rows instead of statistics
check.csv_files()                              # only the CSV files
check.git_info()                               # the git commit the check is based on
```

EPS figures cannot be included by Typst, convert them to PDF or PNG.

### Assumptions of this template

* The root directory has a `codecheck.yml` (i.e. `../codecheck.yml` from the
  point of view of the notebook, which is run from within `.codecheck/`).
* Files referenced in the *manifest* are reproduced in `.codecheck/outputs/`, using
  the same relative paths as in the manifest.

For an example use of this template in a CODECHECK, see
<https://github.com/codecheckers/causality-review/>

## Repository Structure

When using this template for a CODECHECK, your repository should look like this:

```
repository-root/
├── codecheck.yml                    # Configuration file (at root level)
├── figures/                         # Original figures from paper
│   ├── plot1.png
│   └── plot2.pdf
├── data/                            # Original data files
│   └── results.csv
├── code/                            # Original code to reproduce results
│   ├── analysis.py
│   └── generate_figures.R
└── .codecheck/                      # CODECHECK materials (this template)
    ├── codecheck.py                 # Helper module
    ├── codecheck.ipynb              # Certificate notebook
    ├── codecheck.typ                # Typst template (PDF styling)
    ├── codecheck_logo.svg           # CODECHECK logo
    ├── notebook_to_pdf.sh           # Notebook -> Markdown -> PDF script
    ├── validation.py                # Validation module
    ├── validation_config.py         # Validation configuration
    ├── manifest.py                  # Manifest processing
    ├── register.py                  # CODECHECK register issues (GitHub API)
    ├── codecheck.md                 # Generated Markdown (intermediate output)
    ├── codecheck.pdf                # Generated certificate (output)
    └── outputs/                     # Reproduced files from manifest
        ├── figures/
        │   ├── plot1.png            # Reproduced version
        │   └── plot2.pdf            # Reproduced version
        └── data/
            └── results.csv          # Reproduced version
```

### Key Points

1. **`codecheck.yml`** is at the repository root, not inside the `.codecheck/` directory
2. **Original files** (from the paper) live in the main repository structure
3. **Reproduced files** (regenerated by the codechecker) go in `.codecheck/outputs/`
4. The **directory structure** within `outputs/` mirrors the paths specified in the manifest
5. File paths in the `codecheck.yml` manifest are relative to the repository root

## Validation Features

This template includes validation features to check your `codecheck.yml` configuration before generating the certificate. Validation helps catch errors early and ensures your CODECHECK meets the specification.

### Quick Start with Validation

```python
from codecheck import Codecheck

# Initialize with validation enabled
check = Codecheck(validate=True, strict=False)

# Or validate manually
check = Codecheck()
passed, issues = check.validate(
    check_manifest=True,
    check_register=True,  # Check GitHub register (default: True)
    strict=False,
    check_orcid_online=False  # Check ORCIDs at orcid.org (default: False)
)
check.validation_report()
```

### Validation Checks Performed

The validation system performs the following checks on your `codecheck.yml` file:

#### 1. **YAML Syntax Validation**

- ✓ Valid YAML structure
- ✓ Proper indentation
- ✓ No syntax errors
- ✓ File is readable and parseable

#### 2. **Field Completeness**

- **Mandatory fields** (errors if missing):
  - `version` - Config specification version
  - `certificate` - Certificate ID (YYYY-NNN format)
  - `report` - DOI or URL of certificate report
  - `paper` - Paper metadata (title, authors, reference)
  - `repository` - Code repository URL
  - `codechecker` - Name and ORCID of checker
  - `check_time` - When the check was performed
  - `summary` - Summary of findings
  - `manifest` - List of reproduced files

- **Optional fields**: `source` - Additional source information

#### 3. **Placeholder Detection**

- ✓ Detects common placeholder patterns:
  - "FIXME", "TODO", "template", "example"
  - "XXXXX", "placeholder"
- ✓ Flags incomplete configuration values
- ✓ Helps ensure all fields are filled in

#### 4. **Certificate ID Format**

- ✓ Format: `YYYY-NNN` (e.g., `2023-001`)
- ✓ Year must be 4 digits
- ✓ Number must be 3 digits
- ✓ Detects placeholder certificates:
  - `YYYY-001`, `0000-001`, `9999-001`

#### 5. **Report DOI/URL Validation**

- ✓ Must be a valid URL or DOI
- ✓ Detects placeholder DOIs:
  - `10.5281/zenodo.XXXXXX`
  - URLs containing "placeholder" or "example"

#### 6. **ORCID Validation**

- ✓ Format: `0000-0000-0000-0000` (or ending in X)
- ✓ Check digit (last character, ISO 7064 mod 11-2): catches typos and placeholders such as `0123-4567-8910-1112`
- ✓ Validates for all authors
- ✓ Validates for codechecker(s)
- ✓ Online (opt-in, `check_orcid_online=True`): one request per ORCID to the public API at
  [pub.orcid.org](https://pub.orcid.org), no token needed
  - **ERROR** if the ORCID does not exist or is locked/deactivated
  - **WARNING** if the name in `codecheck.yml` does not match the ORCID record (case, diacritics, punctuation and
    name order are ignored; the family name and a given name or its initial must be in the name, or it is the published
    name)
  - **INFO** if the ORCID record has no public name
  - Network errors only warn, the remaining ORCIDs are then skipped
- ✓ Also available as `Codecheck(validate=True, check_orcid_online=True)`

#### 7. **Date/Time Format Validation**

- ✓ `check_time` must be ISO 8601 format
- ✓ Format: `YYYY-MM-DDTHH:MM:SS`
- ✓ Example: `2023-11-15T14:30:00`

#### 8. **Paper Structure Validation**

- ✓ Paper section must be a dictionary
- ✓ Must contain: `title`, `authors`, `reference`
- ✓ Authors must be a list
- ✓ Each author must have `name` field
- ✓ ORCID recommended for each author

#### 9. **Codechecker Structure Validation**

- ✓ Must be a dictionary
- ✓ Must contain `name` field
- ✓ ORCID strongly recommended

#### 10. **Manifest Structure Validation**

- ✓ Must be a list (not empty)
- ✓ Each entry must be a dictionary
- ✓ Each entry must have `file` field
- ✓ `comment` field is optional but recommended

#### 11. **Manifest File Existence**

- ✓ Checks all files exist in `.codecheck/outputs/`
- ✓ Reports missing files
- ✓ Validates paths are safe (no path traversal)

#### 12. **GitHub Register Issue Verification**

- ✓ Checks if a GitHub issue exists in [codecheckers/register](https://github.com/codecheckers/register)
- ✓ Searches all open and closed issues (all pages) for the certificate ID in the title
- **ERROR** if no matching issue found
- **WARNING** if issue is closed
- **WARNING** if issue is unassigned
- **INFO** if the certificate ID is still a placeholder (`YYYY-001`, ...): lists the register issues with the surname of
  the first author in the title and their certificate IDs (never written to `codecheck.yml`)
- ✓ Can be disabled with `check_register=False`
- ✓ Gracefully handles network errors (warns but doesn't fail)
- ✓ Uses a `GITHUB_TOKEN` or `GITHUB_PAT` environment variable if set (the GitHub API allows 60 requests per hour without
  a token)

To look up the certificate ID in the notebook, `check.find_certificate_id()` shows the matching register issues as a
table (`check.find_certificate_id(name="Surname")` searches for another name).

### Validation Modes

**Non-strict mode** (default):

- Reports errors and warnings
- Only fails on errors
- Allows generation with warnings

**Strict mode**:

- Treats warnings as failures
- Ensures complete configuration
- Use for final validation

### Example Validation Output

```txt
## ❌ Errors (2)

- **manifest**: Missing 2 file(s) in outputs/: figures/plot1.png, data/results.csv
  - *Suggestion*: Copy all manifest files to the .codecheck/outputs/ directory, e.g. with `check.copy_manifest_files()`

- **codechecker.name**: Codechecker name is missing
  - *Suggestion*: Add name field for codechecker

## ⚠️  Warnings (2)

- **certificate**: Certificate ID 'YYYY-001' appears to be a placeholder
  - *Suggestion*: Replace with actual certificate ID (format: YYYY-NNN)

- **paper.authors[0].ORCID**: Author 1 ORCID is missing
  - *Suggestion*: Add ORCID for complete author information
```

### Disabling Register Checks

If you need to validate without checking the GitHub register (e.g., for offline work or testing):

```python
# Disable register check
passed, issues = check.validate(
    check_manifest=True,
    check_register=False,  # Skip GitHub API call
    strict=False
)
```

## Testing

This template includes a comprehensive test suite. To run tests:

```bash
# Install test dependencies
conda env create -f environment.yml
conda activate codecheck-env

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=. --cov-report=term-missing
```

The test suite includes:

- 50+ unit tests for validation functions
- Tests for the GitHub register issue verification and the certificate ID lookup (mocked API, incl. pagination)
- Integration tests for the complete workflow
- Tests with various invalid configurations
- Fixture-based testing with example configurations
- Mock-based testing for GitHub API interactions

## Continuous Integration

Tests run automatically on GitHub Actions for every push to the main branch. See `.github/workflows/test.yml` for the CI configuration.

## License

This repository is licensed under MIT License, see the LICENSE file for details.
