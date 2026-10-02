"""
ORCID checks: check digit (offline) and the public ORCID record of a person (https://pub.orcid.org)
"""

import re
from typing import Dict, List, Optional, Tuple

import requests

from validation_config import ORCID_FORMAT, normalise

ORCID_API_URL = "https://pub.orcid.org/v3.0/{orcid}/person"


def check_digit_ok(orcid: str) -> bool:
    """Whether the last character of an ORCID (`0000-0002-1825-0097`) is its ISO 7064 mod 11-2 check digit."""
    if not re.match(ORCID_FORMAT, str(orcid)):
        return False
    digits = str(orcid).replace("-", "")
    total = 0
    for d in digits[:-1]:
        total = (total + int(d)) * 2
    result = (12 - total % 11) % 11
    return digits[-1] == ("X" if result == 10 else str(result))


class OrcidNotFound(Exception):
    """The ORCID does not exist."""


class OrcidDeactivated(Exception):
    """The ORCID record is locked or deactivated."""


DEACTIVATED_NAMES = {"given": "Given Names Deactivated", "family": "Family Name Deactivated"}


def fetch_orcid_names(orcid: str, timeout: int = 10) -> Optional[Dict[str, str]]:
    """
    Public names of an ORCID record: `given`, `family` and `credit` (published name), each possibly empty, or None if
    the record has no public name.

    Raises `OrcidNotFound` if the ORCID does not exist, `OrcidDeactivated` for locked (HTTP 409) or deactivated records,
    `requests.exceptions.RequestException` on network errors and `ValueError` for unexpected responses.
    """
    response = requests.get(ORCID_API_URL.format(orcid=orcid), headers={"Accept": "application/json"},
                            timeout=timeout)
    if response.status_code == 404:
        raise OrcidNotFound(orcid)
    if response.status_code == 409:
        raise OrcidDeactivated(orcid)
    response.raise_for_status()
    record = response.json()
    if not isinstance(record, dict) or not isinstance(record.get("name") or {}, dict):
        raise ValueError(f"unexpected response from orcid.org for {orcid}")
    name = record.get("name") or {}

    def value(key):
        return ((name.get(key) or {}).get("value") or "").strip()

    names = {"given": value("given-names"), "family": value("family-name"), "credit": value("credit-name")}
    if all(names[k] == v for k, v in DEACTIVATED_NAMES.items()):
        raise OrcidDeactivated(orcid)
    return names if any(names.values()) else None


# results of `lookup()`
FOUND, NO_PUBLIC_NAME, NOT_FOUND, DEACTIVATED, UNAVAILABLE = (
    "found", "no public name", "not found", "locked or deactivated", "unavailable")


def lookup(orcid: str, timeout: int = 10) -> Tuple[str, Optional[Dict[str, str]], Optional[Exception]]:
    """(status, names, error) of an ORCID: one of the statuses above, the names if found, the error if unavailable."""
    try:
        names = fetch_orcid_names(orcid, timeout=timeout)
    except OrcidNotFound:
        return NOT_FOUND, None, None
    except OrcidDeactivated:
        return DEACTIVATED, None, None
    except (requests.exceptions.RequestException, ValueError) as e:  # network, rate limit, unexpected response
        return UNAVAILABLE, None, e
    return (FOUND, names, None) if names else (NO_PUBLIC_NAME, None, None)


def display_name(names: Dict[str, str]) -> str:
    """The published (credit) name of an ORCID record, otherwise given and family name."""
    return names["credit"] or f"{names['given']} {names['family']}".strip()


def words(text: str) -> List[str]:
    """Normalised words of a name (case, diacritics and punctuation do not matter)."""
    return re.findall(r"\w+", normalise(text))


def name_matches(name: str, names: Dict[str, str]) -> bool:
    """
    Whether a name from `codecheck.yml` matches the names of an ORCID record: all words of the family name are in the
    name, in any order, and one of the given names or its initial (`Daniel Nüst`, `Nust, Daniel` and `D. Nüst` match
    given `Daniel`, family `Nüst`), or the name is the published (credit) name.
    """
    name_words = set(words(name))
    family, given = set(words(names.get("family", ""))), words(names.get("given", ""))
    given_ok = not given or any(g in name_words or g[0] in name_words for g in given)
    if family and family <= name_words and given_ok:
        return True
    credit = set(words(names.get("credit", "")))
    return bool(credit) and credit == name_words
