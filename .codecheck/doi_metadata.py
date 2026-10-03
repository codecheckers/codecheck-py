"""
Metadata of the checked paper (title, authors with ORCID, reference, publication date) from its DOI, via Crossref
(https://api.crossref.org) with OpenAlex (https://api.openalex.org) for missing ORCIDs and as fallback, and updating
the `paper` section of `codecheck.yml` with it
"""

import copy
import html
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from config_io import write_config_fields
from orcid_records import check_digit_ok, words
from validation_config import DOI_ID, ORCID_ID, as_list, is_placeholder

CROSSREF_URL = "https://api.crossref.org/works/{doi}"
OPENALEX_URL = "https://api.openalex.org/works/https://doi.org/{doi}"
DOI_IN_TEXT = re.compile(f"({DOI_ID})")
ORCID_IN_URL = re.compile(f"({ORCID_ID})$")
PAPER_FIELDS = ("title", "authors", "reference")  # fields of `paper` that are filled from the DOI

_cache: Dict[str, Dict] = {}  # DOI metadata does not change during a session


class DoiNotFound(Exception):
    """Neither Crossref nor OpenAlex know the DOI."""


def doi_from(text) -> Optional[str]:
    """The DOI in a DOI or DOI URL (`https://doi.org/10.1234/abc` -> `10.1234/abc`), or None."""
    match = DOI_IN_TEXT.search(str(text or ""))
    if not match:
        return None
    doi = match.group(1).rstrip(".,;'\">]")
    while doi.endswith(")") and doi.count(")") > doi.count("("):  # `(https://doi.org/...)`, but not `...(1997)`
        doi = doi[:-1].rstrip(".,;")
    return doi


def _get(url: str, params: Dict[str, str], timeout: int) -> Optional[Dict]:
    """JSON of a response, None for 404; raises `requests.exceptions.RequestException` otherwise."""
    response = requests.get(url, params=params, timeout=timeout)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _orcid(value) -> Optional[str]:
    """ORCID from an ORCID URL (`https://orcid.org/0000-...`), or None."""
    match = ORCID_IN_URL.search(str(value or ""))
    return match.group(1) if match else None


def _person(name: str, orcid: Optional[str]) -> Dict[str, str]:
    """Author entry as in `codecheck.yml`."""
    return {"name": name, "ORCID": orcid} if orcid else {"name": name}


def _text(value) -> str:
    """Plain text from a title with markup (Crossref titles may contain JATS/HTML tags such as `<i>`)."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).split())


def _metadata(title, authors, date, source) -> Dict:
    return {"title": _text(title), "authors": authors, "date": date, "source": source}


def parse_crossref(message: Dict) -> Dict:
    """Metadata from the `message` of a Crossref works response."""
    authors = []
    for a in message.get("author") or []:
        name = " ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name") or ""
        if name:
            authors.append(_person(name, _orcid(a.get("ORCID"))))
    parts = ((message.get("published") or message.get("issued") or {}).get("date-parts") or [[]])[0]
    date = "-".join(f"{p:02d}" for p in parts) if parts and parts[0] else None
    title = _text((message.get("title") or [""])[0])
    subtitle = _text((message.get("subtitle") or [""])[0])
    if subtitle and subtitle.lower() not in title.lower():
        title = f"{title}: {subtitle}"
    return _metadata(title, authors, date, "Crossref")


def parse_openalex(work: Dict) -> Dict:
    """Metadata from an OpenAlex work."""
    authors = [_person(a["author"]["display_name"], _orcid(a["author"].get("orcid")))
               for a in work.get("authorships") or [] if (a.get("author") or {}).get("display_name")]
    return _metadata(work.get("display_name") or work.get("title"), authors, work.get("publication_date"), "OpenAlex")


def _same_person(a: Dict, b: Dict) -> bool:
    """Whether two author entries of the same position name the same person (last word of `a` in the name `b`)."""
    words_a = words(a["name"])
    return bool(words_a) and words_a[-1] in words(b["name"])


def add_missing_orcids(authors: List[Dict], other: List[Dict]) -> List[Dict]:
    """Authors with the ORCIDs from `other` (same position, same family name) where they have none."""
    result = []
    for i, author in enumerate(authors):
        o = other[i] if i < len(other) else None
        orcid = author.get("ORCID") or (o.get("ORCID") if o and _same_person(author, o) else None)
        result.append(_person(author["name"], orcid))
    return result


def fetch_paper_metadata(doi: str, mailto: Optional[str] = None, timeout: int = 10) -> Dict:
    """
    Title, authors (name and ORCID if known), reference (DOI URL), publication date and source of a paper.

    Crossref is used first and OpenAlex adds missing ORCIDs; if Crossref does not know the DOI (e.g. some preprints),
    OpenAlex alone. `mailto` (or the `CODECHECK_MAILTO` environment variable) is sent to the polite pools of the APIs.
    Results are cached for the session. Raises `DoiNotFound` if neither knows the DOI and
    `requests.exceptions.RequestException` on network errors.
    """
    doi = doi_from(doi) or str(doi)
    if doi.lower() not in _cache:
        _cache[doi.lower()] = _fetch(doi, mailto, timeout)
    return copy.deepcopy(_cache[doi.lower()])  # callers may change the result


def _fetch(doi: str, mailto: Optional[str], timeout: int) -> Dict:
    mailto = mailto or os.environ.get("CODECHECK_MAILTO")
    params = {"mailto": mailto} if mailto else {}
    url_doi = quote(doi, safe="/")  # DOIs may contain `#`, `?`, `<`, ...

    crossref_error = None
    try:
        crossref = _get(CROSSREF_URL.format(doi=url_doi), params, timeout)
    except requests.exceptions.RequestException as e:  # OpenAlex may still answer
        crossref, crossref_error = None, e
    metadata = parse_crossref(crossref.get("message") or {}) if crossref else None
    if metadata is None or not all(a.get("ORCID") for a in metadata["authors"]):
        try:
            openalex = _get(OPENALEX_URL.format(doi=url_doi), params, timeout)
        except requests.exceptions.RequestException as e:
            if metadata is None:
                raise crossref_error or e  # both failed: the Crossref error first
            openalex = None  # only needed for missing ORCIDs
        if metadata and openalex:
            metadata["authors"] = add_missing_orcids(metadata["authors"], parse_openalex(openalex)["authors"])
        elif openalex:
            metadata = parse_openalex(openalex)
    if metadata is None:
        if crossref_error:
            raise crossref_error
        raise DoiNotFound(doi)
    metadata["reference"] = f"https://doi.org/{doi}"
    return metadata


def _replaceable(key: str, value, overwrite: bool) -> bool:
    """
    Whether a value of `paper` may be replaced: `overwrite`, missing or a placeholder; authors also if a name is a
    placeholder or an ORCID is invalid (e.g. the template's `0123-4567-8910-1112`).
    """
    if overwrite or not value or is_placeholder(value):
        return True
    if key == "authors":
        authors = as_list(value)  # a single author may be a mapping
        return not isinstance(authors, list) or any(
            not isinstance(a, dict) or not a.get("name") or is_placeholder(a.get("name"))
            or (a.get("ORCID") and not check_digit_ok(a["ORCID"])) for a in authors)
    return False


def plan_paper_updates(config, metadata: Dict, overwrite: bool = False) -> List[Tuple[str, object, object, bool]]:
    """
    (key, current value, new value, replace) for the `paper` fields whose value differs from the metadata. ORCIDs of
    the current authors are kept where the metadata has none.
    """
    paper = config.get("paper") if isinstance(config, dict) and isinstance(config.get("paper"), dict) else {}
    plan = []
    for key in PAPER_FIELDS:
        current, new = paper.get(key), metadata.get(key)
        current_authors = as_list(current) if key == "authors" else None
        if new and isinstance(current_authors, list) and all(isinstance(a, dict) and a.get("name")
                                                             for a in current_authors):
            valid = [a if not a.get("ORCID") or check_digit_ok(a["ORCID"]) else {"name": a["name"]}
                     for a in current_authors]
            new = add_missing_orcids(new, valid)
        if new and new != current:
            plan.append((key, current, new, _replaceable(key, current, overwrite)))
    return plan


def write_paper_fields(path, updates: Dict) -> Dict:
    """Set `paper.<key>` in a `codecheck.yml` for the updates, see `write_config_fields()`."""
    return write_config_fields(path, updates, section="paper")
