"""
Access to the issues of the CODECHECK register (https://github.com/codecheckers/register) via the GitHub API
"""

import os
import re
from typing import Dict, Iterable, Iterator, List, Optional

import requests

from validation_config import CERTIFICATE_ID, as_list, normalise

REGISTER_ISSUES_URL = "https://api.github.com/repos/codecheckers/register/issues"
MAX_PAGES = 20  # 100 issues per page
CERTIFICATE_IN_TITLE = re.compile(rf"\b({CERTIFICATE_ID})\b")


def _headers() -> Dict[str, str]:
    """Request headers; a token from `GITHUB_TOKEN` or `GITHUB_PAT` raises the API rate limit (60 requests/hour)."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def iter_register_issues(timeout: int = 10, max_pages: int = MAX_PAGES) -> Iterator[Dict]:
    """
    Open and closed issues of the register, newest first (pull requests are skipped). Pages are requested while the
    issues are consumed, so stopping early saves requests.

    Raises `requests.exceptions.RequestException` on network errors, timeouts and rate limits.
    """
    url = REGISTER_ISSUES_URL
    params = {"state": "all", "per_page": 100}
    headers = _headers()
    for _ in range(max_pages):
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        yield from (i for i in response.json() if "pull_request" not in i)
        url = response.links.get("next", {}).get("url")
        if not url:
            return
        params = None  # the next URL contains the parameters
    # not all issues were read: never pretend that the register was searched completely
    raise requests.exceptions.RequestException(f"the register has more than {max_pages} pages of issues")


def fetch_register_issues(timeout: int = 10, max_pages: int = MAX_PAGES) -> List[Dict]:
    """All issues of the register, see `iter_register_issues()`."""
    return list(iter_register_issues(timeout, max_pages))


def surname(name: str) -> str:
    """
    Surname from a name as `First Last` or `Last, First`. A heuristic: for `First van der Last` it is `Last`, which is
    still a word of the register issue titles (`Surname et al. | YYYY-NNN`).
    """
    name = str(name).strip()
    if "," in name:
        return name.split(",")[0].strip()
    return name.split()[-1] if name else ""


def first_author_surname(config) -> Optional[str]:
    """Surname of the first author of the paper in a `codecheck.yml` configuration, or None."""
    paper = config.get("paper") if isinstance(config, dict) else None
    authors = as_list(paper.get("authors")) if isinstance(paper, dict) else []
    name = authors[0].get("name") if authors and isinstance(authors[0], dict) else None
    return (surname(name) or None) if isinstance(name, str) else None


def certificate_candidates(issues: Iterable[Dict], name: str) -> List[Dict]:
    """
    Register issues with `name` (e.g. the surname of the first author) as a word in the title, open issues first.

    Each candidate has the certificate ID from the title (None if not assigned yet, e.g. `2026-NNN`), the issue number,
    title, URL, state and the logins of the assignees.
    """
    if not name:
        return []
    pattern = re.compile(rf"(?<!\w){re.escape(normalise(name))}(?!\w)")  # whole word, also for `Jr.`
    candidates = []
    for issue in issues:
        title = issue.get("title", "")
        if not pattern.search(normalise(title)):
            continue
        match = CERTIFICATE_IN_TITLE.search(title)
        candidates.append({
            "certificate": match.group(1) if match else None,
            "number": issue.get("number"),
            "title": title,
            "url": issue.get("html_url"),
            "state": issue.get("state"),
            "assignees": [a.get("login") for a in issue.get("assignees") or []],
        })
    return sorted(candidates, key=lambda c: (c["state"] != "open", -(c["number"] or 0)))


NO_ID = "not assigned yet"


def describe(candidate: Dict) -> str:
    """One-line description of a candidate from `certificate_candidates()`."""
    return f"{candidate['certificate'] or NO_ID}: #{candidate['number']} {candidate['title']} ({candidate['state']})"


def markdown_row(candidate: Dict) -> str:
    """Row of a Markdown table `Certificate | Issue | State | Assignees` for a candidate (`|` in titles escaped)."""
    cells = [candidate['certificate'] or f"*{NO_ID}*", f"[#{candidate['number']}]({candidate['url']}) {candidate['title']}",
             candidate['state'], ", ".join(candidate['assignees'])]
    return " | ".join(str(c).replace("|", "\\|") for c in cells)


def find_issue(issues: Iterable[Dict], certificate: str) -> Optional[Dict]:
    """The first register issue with `certificate` in its title, or None (stops consuming `issues` at the match)."""
    return next((i for i in issues if certificate in CERTIFICATE_IN_TITLE.findall(i.get("title", ""))), None)
