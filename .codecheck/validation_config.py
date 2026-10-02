"""
Configuration constants for codecheck.yml validation, and small helpers shared by the modules
"""

import re
import unicodedata

# Directories (relative to the repository root) that can contain the CODECHECK files and the `outputs/` directory,
# in order of preference: `.codecheck/` (default) or `codecheck/`
TEMPLATE_DIRS = ('.codecheck', 'codecheck')

# Required fields according to CODECHECK spec
MANDATORY_FIELDS = ['manifest', 'codechecker', 'report', 'version', 'paper', 'repository', 'check_time', 'certificate', 'summary']

# Optional but recognized fields
OPTIONAL_FIELDS = ['source']

# Placeholder patterns that indicate incomplete configuration
PLACEHOLDER_PATTERNS = {
    'strings': ['FIXME', 'TODO', 'template', 'example', 'XXXXX', 'placeholder'],
    'certificate_patterns': [
        r'^YYYY-\d{3}$',      # Year placeholder
        r'^(\d{4}|YYYY)-NNN$',  # Number placeholder (e.g. 2026-NNN)
        r'^0000-\d{3}$',      # Zero year
        r'^9999-\d{3}$',      # Invalid year
    ],
    'check_time_patterns': [
        r'YYYY|MM|DD|HH|SS',  # Format hint, e.g. YYYY-MM-DDTHH:MM:SS
    ],
    'doi_patterns': [
        r'XXXXX',
        r'placeholder',
        r'example',
        r'10\.5281/zenodo\.XXXXXX',  # Zenodo placeholder
        r'\bTODO\b',
    ]
}

# Expected formats for validation
CERTIFICATE_ID = r'\d{4}-\d{3}'  # YYYY-NNN (e.g., 2023-001)
CERTIFICATE_FORMAT = rf'^{CERTIFICATE_ID}$'
ORCID_ID = r'\d{4}-\d{4}-\d{4}-\d{3}[0-9X]'  # Standard ORCID format
ORCID_FORMAT = rf'^{ORCID_ID}$'
DOI_ID = r'10\.\d{4,}/[^\s]+'  # Basic DOI format
DOI_FORMAT = rf'^{DOI_ID}$'
ISO_DATE_FORMAT = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$'  # ISO 8601 basic format

# Nested field paths for validation
PAPER_FIELDS = ['title', 'authors', 'reference']
AUTHOR_FIELDS = ['name', 'ORCID']
CODECHECKER_FIELDS = ['name', 'ORCID']
MANIFEST_ENTRY_FIELDS = ['file']  # 'comment' is optional


def as_list(value):
    """A single person (dict) is allowed in `codecheck.yml` in place of a list of people."""
    return [value] if isinstance(value, dict) else value


def is_placeholder_check_time(value) -> bool:
    """Whether a check time is a placeholder such as `YYYY-MM-DDTHH:MM:SS` or `TODO`."""
    return isinstance(value, str) and (
        is_placeholder(value) or any(re.search(p, value) for p in PLACEHOLDER_PATTERNS['check_time_patterns']))


def is_placeholder_certificate(cert) -> bool:
    """Whether a certificate ID is a placeholder such as `YYYY-001` (no ID assigned yet)."""
    return isinstance(cert, str) and any(re.match(p, cert) for p in PLACEHOLDER_PATTERNS['certificate_patterns'])


# letters that have no decomposition into a base letter and a diacritic
LETTERS = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ß": "ss", "æ": "ae", "Æ": "AE",
                         "œ": "oe", "Œ": "OE", "ı": "i"})


def normalise(text) -> str:
    """Lower case text without diacritics, for comparing names (`Nüst` matches `Nust`, `Łukasz` matches `Lukasz`)."""
    decomposed = unicodedata.normalize("NFKD", str(text).translate(LETTERS))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


PLACEHOLDER_WORDS = re.compile(
    r"(?<![^\W_])(" + "|".join("X{5,}" if p == "XXXXX" else re.escape(p) for p in PLACEHOLDER_PATTERNS['strings'])
    + r")(?![^\W_])", re.IGNORECASE)  # any run of at least five X, e.g. `zenodo.XXXXXX`


def is_placeholder(value) -> bool:
    """Whether a text contains a placeholder (FIXME, TODO, example, ...) as a word: `TODO add`, not `Todorov`."""
    return isinstance(value, str) and bool(PLACEHOLDER_WORDS.search(value))
