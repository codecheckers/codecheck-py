"""
Publish the CODECHECK certificate on Zenodo (https://zenodo.org), as a command line tool:

    python zenodo_deposit.py reserve [--sandbox]   # draft record, reserved DOI -> `report` in codecheck.yml
    sh notebook_to_pdf.sh                          # rebuild the certificate, now with its DOI
    python zenodo_deposit.py all [--sandbox]       # upload certificate and notebook, set the metadata
    python zenodo_deposit.py status [--sandbox]

Run in the template directory (`.codecheck/`). The record is never published: check the draft on Zenodo and publish it
yourself. Uses the InvenioRDM API of Zenodo (https://inveniordm.docs.cern.ch/reference/rest_api_drafts_records/).
The API token is read from the environment or a `.env` file (`ZENODO_API_TOKEN`, `ZENODO_API_TOKEN_SANDBOX`).
"""

import argparse
import html
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
import yaml

from config_io import write_config_fields
from doi_metadata import doi_from
from manifest import existing_file, find_outputs_dir, manifest_file_paths
from orcid_records import check_digit_ok
from validation_config import (as_list, is_placeholder, is_placeholder_certificate, is_placeholder_check_time,
                               split_name)

URLS = {False: "https://zenodo.org", True: "https://sandbox.zenodo.org"}
TOKENS = {False: "ZENODO_API_TOKEN", True: "ZENODO_API_TOKEN_SANDBOX"}
DOI_PREFIXES = {False: "10.5281", True: "10.5072"}  # Zenodo and Zenodo sandbox
RECORD_DOI = re.compile(r"^(10\.\d{4,9})/zenodo\.(\d+)$", re.IGNORECASE)  # DOIs are case-insensitive
COMMUNITIES = {False: "codecheck", True: "codecheck-sandbox"}  # default community on Zenodo and the sandbox
PUBLISHER = "CODECHECK Community on Zenodo"
CERTIFICATE = "codecheck.pdf"
NOTEBOOK = "codecheck.ipynb"
OUTPUTS_ZIP = "codecheck-outputs.zip"
NOTES = ("See file LICENSE for license of the contained code. The report document codecheck.pdf is published under "
         "CC-BY 4.0 International.")
TIMEOUT = 60  # seconds, uploads use more


class ZenodoError(Exception):
    """An error of the Zenodo API (with its HTTP `status`) or of the configuration for it."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


# --- configuration ---------------------------------------------------------------------------------------------------

def load_env(paths) -> Optional[Path]:
    """
    Read `KEY=VALUE` lines of the first existing `.env` file in `paths` into the environment (variables that are
    already set win) and return its path.
    """
    for path in map(Path, paths):
        if path.is_file():
            for line in path.read_text().splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip() and not key.strip().startswith("#"):
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))
            return path
    return None


def check_env_ignored(path: Optional[Path]):
    """Raise if a `.env` file is in a git repository but not ignored by git, so that a token is never committed."""
    if path is None:
        return
    try:
        result = subprocess.run(["git", "-C", str(path.parent.resolve()), "check-ignore", "-q", path.name],
                                capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return  # no git: nothing can be committed by accident
    if result.returncode == 1:  # in a repository, not ignored (128: not a repository)
        raise ZenodoError(f"{path} is not ignored by git: add `.env` to .gitignore so the token is never committed")


def token(sandbox: bool) -> str:
    value = os.environ.get(TOKENS[sandbox], "").strip()
    if not value:
        raise ZenodoError(f"No Zenodo API token: set {TOKENS[sandbox]} in the environment or a .env file "
                          f"(token with the scopes deposit:write and deposit:actions from "
                          f"{URLS[sandbox]}/account/settings/applications/tokens/new/)")
    return value


def record_id(report, sandbox: bool) -> Optional[str]:
    """
    Zenodo record ID from the `report` DOI in codecheck.yml, or None if there is no record yet (missing, placeholder or
    another DOI). Raises if the DOI is from Zenodo but not from the selected instance (sandbox or not).
    """
    if not report or is_placeholder(report):
        return None
    match = RECORD_DOI.match(doi_from(report) or "")
    if not match:
        return None
    if match.group(1) != DOI_PREFIXES[sandbox]:
        other = "the Zenodo sandbox" if match.group(1) == DOI_PREFIXES[True] else "Zenodo"
        raise ZenodoError(f"The report DOI {doi_from(report)} is from {other}: "
                          f"{'leave out' if sandbox else 'use'} --sandbox")
    return match.group(2)


# --- metadata --------------------------------------------------------------------------------------------------------

def creator(person) -> Optional[Dict]:
    """InvenioRDM creator from a codechecker entry (`Given Family` or `Family, Given`; one word: organisation)."""
    name = str(person.get("name") or "").strip() if isinstance(person, dict) else ""
    if not name or is_placeholder(name):
        return None
    given, family = split_name(name)
    if given:
        entity = {"type": "personal", "family_name": family, "given_name": given}
    else:
        entity = {"type": "organizational", "name": name}
    orcid = str(person.get("ORCID") or "")
    if orcid and check_digit_ok(orcid):
        entity["identifiers"] = [{"scheme": "orcid", "identifier": orcid}]
    result = {"person_or_org": entity}
    if isinstance(person.get("affiliation"), str) and person["affiliation"].strip():
        result["affiliations"] = [{"name": person["affiliation"].strip()}]
    return result


def related_identifier(value, relation: str, resource_type: str, resource_type_doi: Optional[str] = None):
    """Related identifier for a DOI or URL (DOIs with `resource_type_doi` if given), None for placeholders."""
    if not value or is_placeholder(value):
        return None
    doi = doi_from(value)
    if doi:
        identifier, scheme, resource_type = doi, "doi", resource_type_doi or resource_type
    elif re.match(r"^https?://", str(value)):
        identifier, scheme = str(value), "url"
    else:
        return None
    return {"identifier": identifier, "scheme": scheme, "relation_type": {"id": relation},
            "resource_type": {"id": resource_type}}


def build_metadata(conf: Dict, outputs_license: Optional[str] = None) -> Tuple[Dict, List[str]]:
    """
    InvenioRDM metadata of the certificate record from codecheck.yml, following the curation policy of the CODECHECK
    community (https://zenodo.org/communities/codecheck/curation-policy), and a list of warnings.
    """
    warnings = []
    certificate = str(conf.get("certificate") or "")
    if not certificate or is_placeholder_certificate(certificate):
        warnings.append(f"certificate '{certificate}' is a placeholder")
    codecheckers = as_list(conf.get("codechecker")) or []
    creators = [c for c in map(creator, codecheckers) if c]
    if not creators:
        warnings.append("no codechecker with a name")
    for person in codecheckers:
        if isinstance(person, dict) and person.get("ORCID") and not check_digit_ok(str(person["ORCID"])):
            warnings.append(f"ORCID '{person['ORCID']}' of {person.get('name')} is not valid (plain 0000-0000-0000-0000)"
                            f", it is left out")
    check_time = str(conf.get("check_time") or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}", check_time) and not is_placeholder_check_time(check_time):
        publication_date = check_time[:10]
    else:
        publication_date = date.today().isoformat()
        warnings.append(f"check_time '{check_time}' is not a date: the publication date is today ({publication_date})")

    paper = conf.get("paper") if isinstance(conf.get("paper"), dict) else {}
    repository = conf.get("repository")  # a URL or a list of URLs
    repositories = [r for r in (repository if isinstance(repository, list) else [repository])
                    if r and not is_placeholder(r)]
    description = []
    if conf.get("summary") and not is_placeholder(conf.get("summary")):
        description.append(f"<p><strong>Summary:</strong> {html.escape(' '.join(str(conf['summary']).split()))}</p>")
    else:
        warnings.append("no summary")
    if paper.get("title") and not is_placeholder(paper["title"]):
        description.append(f"<p><strong>Paper:</strong> {html.escape(str(paper['title']))}</p>")
    for repo in repositories:
        description.append(f'<p><strong>Repository:</strong> <a href="{html.escape(str(repo))}">'
                           f'{html.escape(str(repo))}</a></p>')

    for repo in repositories:
        if re.match(r"^https?://(www\.)?(github|gitlab)\.com/", str(repo)) and \
                not re.match(r"^https?://(www\.)?(github\.com/codecheckers|gitlab\.com/cdchck)/", str(repo)):
            warnings.append(f"repository {repo}: the curation policy asks for links to GitHub repositories in the "
                            f"codecheckers organisation or to GitLab in cdchck (fork it there, or use a DOI)")
    paper_relation = related_identifier(paper.get("reference"), "reviews", "publication-article")
    if not paper_relation:
        warnings.append("paper.reference is not a DOI or URL")
    related = [paper_relation] + [related_identifier(r, "issupplementedby", "software", "dataset")
                                  for r in repositories]

    rights = [{"id": "cc-by-4.0"}]
    notes = NOTES
    if outputs_license:
        rights.append({"id": outputs_license})
        notes += (f" The reproduced output files in {OUTPUTS_ZIP} are works of the authors of the paper, published "
                  f"under their license ({outputs_license}).")

    metadata = {
        "title": f"CODECHECK Certificate {certificate}",
        "creators": creators,
        "publication_date": publication_date,
        "publisher": PUBLISHER,
        "resource_type": {"id": "publication-report"},
        "languages": [{"id": "eng"}],
        "rights": rights,
        "description": "\n".join(description),
        "subjects": [{"subject": "CODECHECK"}],
        "additional_descriptions": [{"description": notes, "type": {"id": "notes"}, "lang": {"id": "eng"}}],
        "related_identifiers": [r for r in related if r],
    }
    if certificate and not is_placeholder_certificate(certificate):
        metadata["identifiers"] = [  # both forms as required by the curation policy
            {"identifier": f"http://cdchck.science/register/certs/{certificate}", "scheme": "url"},
            {"identifier": f"cdchck.science/register/certs/{certificate}", "scheme": "other"}]
    return metadata, warnings


# --- API -------------------------------------------------------------------------------------------------------------

class Zenodo:
    """Minimal client for the draft records of the Zenodo InvenioRDM API."""

    def __init__(self, sandbox: bool = False, api_token: Optional[str] = None, community: Optional[str] = None):
        self.sandbox = sandbox
        self.url = URLS[sandbox]
        self.community = community or COMMUNITIES[sandbox]
        self.headers = {"Authorization": f"Bearer {api_token or token(sandbox)}",
                        "Accept": "application/vnd.inveniordm.v1+json"}

    def call(self, method: str, path: str, ok=(200, 201, 202, 204), **kwargs):
        """JSON of an API response (None without content); raises `ZenodoError` for other statuses."""
        headers = {**self.headers, **kwargs.pop("headers", {})}
        response = requests.request(method, f"{self.url}/api{path}", headers=headers,
                                    timeout=kwargs.pop("timeout", TIMEOUT), **kwargs)
        if response.status_code not in ok:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:500]
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("errors") or detail
            raise ZenodoError(f"{method} {path}: HTTP {response.status_code}: {detail}", response.status_code)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def draft_url(self, rid) -> str:
        return f"{self.url}/uploads/{rid}"

    def create_draft(self, metadata: Dict) -> Dict:
        return self.call("POST", "/records", json={"metadata": metadata, "files": {"enabled": True},
                                                   "access": {"record": "public", "files": "public"}})

    def get_draft(self, rid) -> Optional[Dict]:
        """The draft of a record, None if it has none (published record without open draft)."""
        try:
            return self.call("GET", f"/records/{rid}/draft")
        except ZenodoError as e:
            if e.status == 404:
                return None
            raise

    def editable_draft(self, rid) -> Dict:
        """The draft of a record that has not been published yet; raises for published records."""
        draft = self.get_draft(rid)
        if draft is None or draft.get("is_published"):
            raise ZenodoError(f"Record {rid} is published: change it on Zenodo ({self.draft_url(rid)}) or create a "
                              f"new version there")
        return draft

    def reserve_doi(self, rid) -> str:
        record = self.call("POST", f"/records/{rid}/draft/pids/doi") or self.get_draft(rid) or {}
        doi = ((record.get("pids") or {}).get("doi") or {}).get("identifier")
        if not doi:
            raise ZenodoError(f"No DOI reserved for record {rid}")
        return doi

    def update_draft(self, rid, metadata: Dict, default_preview: Optional[str] = None) -> Dict:
        """
        Replace the metadata (and set the default preview file) of a draft. The API replaces the whole draft, so the
        other parts of the current draft are sent back. The metadata cannot be sent back as read: the API returns
        vocabulary entries (licenses, types) expanded, and rejects them in that form. Field errors are raised.
        """
        draft = self.editable_draft(rid)
        body = {key: draft[key] for key in ("access", "custom_fields", "pids") if key in draft}
        body["metadata"] = metadata
        body["files"] = {"enabled": True, **{k: v for k, v in (draft.get("files") or {}).items()
                                             if k in ("enabled", "default_preview", "order")}}
        if default_preview:
            body["files"]["default_preview"] = default_preview
        result = self.call("PUT", f"/records/{rid}/draft", json=body) or {}
        if result.get("errors"):
            raise ZenodoError("The draft was saved with errors: " + "; ".join(
                f"{e.get('field')}: {' '.join(e.get('messages') or [])}" for e in result["errors"]))
        return result

    def check_license(self, license_id: str):
        """Raise if a license ID is not in the license vocabulary of Zenodo (e.g. `mit`, `cc-by-4.0`)."""
        try:
            self.call("GET", f"/vocabularies/licenses/{license_id}")
        except ZenodoError as e:
            if e.status == 404:
                raise ZenodoError(f"Unknown license '{license_id}', see {self.url}/api/vocabularies/licenses?q=")
            raise

    def file_keys(self, rid) -> List[str]:
        entries = (self.call("GET", f"/records/{rid}/draft/files") or {}).get("entries") or []
        entries = entries.values() if isinstance(entries, dict) else entries
        return [e.get("key") for e in entries]

    def upload(self, rid, path: Path, key: Optional[str] = None, existing: Optional[List[str]] = None):
        """
        Upload a file into a draft (replacing a file with the same name, `existing`: the file names of the draft if
        known): initialise, upload content, commit.
        """
        key = key or path.name
        url = f"/records/{rid}/draft/files/{quote(key, safe='')}"  # e.g. `#` in a file name
        if key in (self.file_keys(rid) if existing is None else existing):
            self.call("DELETE", url)
        self.call("POST", f"/records/{rid}/draft/files", json=[{"key": key}])
        with open(path, "rb") as f:
            self.call("PUT", f"{url}/content", data=f, timeout=600,
                      headers={"Content-Type": "application/octet-stream"})
        self.call("POST", f"{url}/commit")

    def account(self) -> Dict:
        """The account of the token (`email`, `id`)."""
        return self.call("GET", "/me") or {}

    def review(self, rid) -> Optional[Dict]:
        """The community request of a draft, None if there is none."""
        try:
            return self.call("GET", f"/records/{rid}/draft/review")
        except ZenodoError as e:
            if e.status == 404:
                return None
            raise

    def request_review(self, rid) -> bool:
        """
        Create the request to include the draft in the community; it is not submitted, the draft stays editable.
        Returns False if the community does not exist.
        """
        try:
            uuid = self.call("GET", f"/communities/{self.community}")["id"]
        except ZenodoError as e:
            if e.status == 404:
                return False
            raise
        try:
            self.call("PUT", f"/records/{rid}/draft/review",
                      json={"receiver": {"community": uuid}, "type": "community-submission"})
        except ZenodoError as e:
            if not re.search(r"already|exists", str(e), re.IGNORECASE):
                raise
        return True


# --- commands --------------------------------------------------------------------------------------------------------

def load_config(path) -> Dict:
    with open(path) as f:
        conf = yaml.safe_load(f)
    if not isinstance(conf, dict):
        raise ZenodoError(f"{path} is not a CODECHECK configuration")
    return conf


def require_record(conf: Dict, sandbox: bool) -> str:
    rid = record_id(conf.get("report"), sandbox)
    if not rid:
        raise ZenodoError("No Zenodo record in `report` of codecheck.yml: reserve one first (reserve)")
    return rid


def check_outputs_license(outputs_license: Optional[str], with_outputs: bool):
    """The license of the outputs belongs in the metadata exactly if the draft has (or gets) the outputs zip."""
    if with_outputs and not outputs_license:
        raise ZenodoError(f"The draft has {OUTPUTS_ZIP}: pass --outputs-license with the license ID of the outputs, "
                          f"or delete the file on Zenodo")
    if outputs_license and not with_outputs:
        raise ZenodoError(f"--outputs-license without {OUTPUTS_ZIP}: use it with --include-outputs")


def print_warnings(warnings: List[str], out):
    for warning in warnings:
        out(f"Warning: {warning}")


def confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:  # not interactive
        return False


def cmd_reserve(zenodo: Zenodo, config: Path, yes: bool = False, out=print) -> Optional[str]:
    """Create a draft record with a reserved DOI, request the CODECHECK community, write the DOI to `report`."""
    conf = load_config(config)
    report = conf.get("report")
    rid = record_id(report, zenodo.sandbox)
    if rid:
        out(f"codecheck.yml already has a record: {report} ({zenodo.draft_url(rid)}), nothing reserved.")
        return None
    if report and not is_placeholder(report):
        raise ZenodoError(f"`report` in {config} is already set ({report}) and not a Zenodo record: remove it or "
                          f"replace it with a placeholder to reserve a new DOI")
    if not confirm(f"Create a new record on {zenodo.url} and reserve a DOI? DOIs cannot be deleted.", yes):
        out("Nothing reserved.")
        return None
    metadata, _ = build_metadata(conf)
    rid = zenodo.create_draft(metadata)["id"]
    doi = zenodo.reserve_doi(rid)
    out(f"Reserved DOI {doi} for the draft {zenodo.draft_url(rid)}.")  # shown before anything else can fail
    try:
        write_config_fields(config, {"report": f"https://doi.org/{doi}"})
    except Exception as e:
        raise ZenodoError(f"Could not write the DOI to {config} ({type(e).__name__}: {e}): set "
                          f"`report: https://doi.org/{doi}` yourself, do not reserve again")
    out(f"Wrote it to `report` in {config}.")
    try:
        if zenodo.request_review(rid):
            out(f"Requested the inclusion in the community '{zenodo.community}' (not submitted).")
        else:
            out(f"The community '{zenodo.community}' does not exist on {zenodo.url}: no community request.")
    except (ZenodoError, requests.exceptions.RequestException) as e:
        out(f"Warning: no community request ({e}), it is tried again by `all`.")
    out("Next: rebuild the certificate (sh notebook_to_pdf.sh) so it carries the DOI, then upload it (all).")
    return doi


def upload_files(config: Path, conf: Dict, workdir: Path, include_config: bool = False, include_outputs: bool = False,
                 extra: Tuple[str, ...] = (), force: bool = False) -> List[Tuple[Path, str]]:
    """
    (path, key) of the files to upload (a zip of the outputs is written to `workdir`); raises if the certificate is
    missing or looks outdated: older than its configuration, or without the report DOI (in `codecheck.md`, built with
    the PDF).
    """
    pdf = Path(CERTIFICATE)
    if not pdf.is_file():
        raise ZenodoError(f"{pdf.resolve()} is missing: build the certificate first (sh notebook_to_pdf.sh)")
    if not force:
        report, markdown = doi_from(conf.get("report")), Path("codecheck.md")
        if pdf.stat().st_mtime < config.stat().st_mtime:
            raise ZenodoError(f"{pdf} is older than {config}: rebuild it (sh notebook_to_pdf.sh) or use --force")
        if report and markdown.is_file() and report not in markdown.read_text(errors="replace"):
            raise ZenodoError(f"The certificate does not contain the DOI {report}: rebuild it or use --force")
    files = [(pdf, pdf.name)]
    if Path(NOTEBOOK).is_file():
        files.append((Path(NOTEBOOK), NOTEBOOK))
    if include_config:
        files.append((config, config.name))
    if include_outputs:
        files.append((outputs_zip(config, conf, workdir / OUTPUTS_ZIP), OUTPUTS_ZIP))
    for name in extra:
        if not Path(name).is_file():
            raise ZenodoError(f"{name} does not exist")
        files.append((Path(name), Path(name).name))
    return files


def outputs_zip(config: Path, conf: Dict, target: Path) -> Path:
    """
    Zip file of the manifest files in the outputs directory (paths as in the manifest): `outputs/` of the template
    directory (the working directory, as in the notebook), else the one next to `codecheck.yml`.
    """
    outputs = Path("outputs") if Path("outputs").is_dir() else find_outputs_dir(config.parent)
    paths = manifest_file_paths(conf.get("manifest"))
    found = [(existing_file(outputs, p), str(p)) for p in paths]
    if not paths or not all(path for path, _ in found):
        missing = [name for path, name in found if not path]
        raise ZenodoError(f"Manifest files missing in {outputs}: {', '.join(missing) or 'empty manifest'}")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path, name in found:
            z.write(path, name)
    return target


def cmd_all(zenodo: Zenodo, config: Path, include_config=False, include_outputs=False, outputs_license=None,
            extra=(), force=False, out=print):
    """Upload the certificate (and further files), set the metadata and the preview, request the community."""
    if include_outputs and not outputs_license:
        raise ZenodoError("--include-outputs needs --outputs-license with the license ID of the outputs (e.g. mit)")
    conf = load_config(config)
    rid = require_record(conf, zenodo.sandbox)
    zenodo.editable_draft(rid)
    existing = zenodo.file_keys(rid)
    if include_outputs or extra:
        out("Note: further files must be created by the codechecker or published with the explicit consent of the "
            "copyright holder, e.g. the authors of the paper (CODECHECK curation policy).")
    check_outputs_license(outputs_license, include_outputs or OUTPUTS_ZIP in existing)
    metadata, warnings = build_metadata(conf, outputs_license)
    print_warnings(warnings, out)
    if outputs_license:
        zenodo.check_license(outputs_license)
    with tempfile.TemporaryDirectory() as workdir:
        files = upload_files(config, conf, Path(workdir), include_config, include_outputs, tuple(extra), force)
        for path, key in files:
            out(f"Uploading {key} ...")
            zenodo.upload(rid, path, key, existing)
    others = sorted(set(existing) - {key for _, key in files})
    if others:
        out(f"Warning: the draft also has files from earlier uploads: {', '.join(others)} "
            f"(delete them on Zenodo if they are outdated)")
    zenodo.update_draft(rid, metadata, default_preview=CERTIFICATE)
    in_community = zenodo.request_review(rid)  # again: for drafts reserved before the request was possible
    out(f"Updated the draft {zenodo.draft_url(rid)}: {len(files)} file(s), metadata"
        f"{f', community request ({zenodo.community})' if in_community else ''}.")
    if not in_community:
        out(f"Warning: the community '{zenodo.community}' does not exist on {zenodo.url}: no community request.")
    out("Check the record on Zenodo (metadata, files, preview), then publish it yourself.")


def cmd_metadata(zenodo: Zenodo, config: Path, dry_run=False, outputs_license=None, out=print):
    conf = load_config(config)
    metadata, warnings = build_metadata(conf, outputs_license)
    print_warnings(warnings, out)
    if dry_run:
        out(yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True))
        return
    rid = require_record(conf, zenodo.sandbox)
    zenodo.editable_draft(rid)
    check_outputs_license(outputs_license, OUTPUTS_ZIP in zenodo.file_keys(rid))
    zenodo.update_draft(rid, metadata)
    out(f"Updated the metadata of the draft {zenodo.draft_url(rid)}.")


def cmd_status(zenodo: Zenodo, config: Path, out=print):
    try:
        me = zenodo.account()
        out(f"Account: {me.get('email') or me.get('username')} (user {me.get('id')}) on {zenodo.url}")
    except ZenodoError as e:  # the endpoint is not documented, it may change
        out(f"Account: unknown ({e})")
    rid = record_id(load_config(config).get("report"), zenodo.sandbox)
    if not rid:
        out("No Zenodo record in `report` of codecheck.yml.")
        return
    draft = zenodo.get_draft(rid)
    record = draft or zenodo.call("GET", f"/records/{rid}")
    published = draft is None or bool(draft.get("is_published"))
    state = ("published" + (", with changes not yet published" if draft else "")) if published else \
        "draft (not published)"
    doi = ((record.get("pids") or {}).get("doi") or {}).get("identifier")
    out(f"Record {rid}: {state}, DOI {doi}, {zenodo.draft_url(rid)}")
    out(f"Title: {(record.get('metadata') or {}).get('title')}")
    if draft:
        out(f"Files: {', '.join(zenodo.file_keys(rid)) or 'none'}")
        request = zenodo.review(rid)
        if request:
            receiver = (request.get("receiver") or {}).get("community")
            try:  # the request names the community by its UUID
                receiver = zenodo.call("GET", f"/communities/{receiver}").get("slug") or receiver
            except ZenodoError:
                pass
            out(f"Community request: {request.get('status')} ({receiver}, not submitted unless done on Zenodo)")
        else:
            out("Community request: none")


def main(argv=None, out=print) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("command", choices=["reserve", "all", "metadata", "status"])
    parser.add_argument("--sandbox", action="store_true", help="use the Zenodo sandbox (test first!)")
    parser.add_argument("--config", default=os.path.join("..", "codecheck.yml"), help="default: ../codecheck.yml")
    parser.add_argument("--yes", action="store_true", help="do not ask before reserving a DOI")
    parser.add_argument("--include-config", action="store_true", help="also upload codecheck.yml")
    parser.add_argument("--include-outputs", action="store_true",
                        help=f"also upload the manifest files from outputs/ as {OUTPUTS_ZIP} (only with the "
                             f"consent of the copyright holders, e.g. the authors)")
    parser.add_argument("--outputs-license", help="license ID of the output files, e.g. mit or cc-by-4.0")
    parser.add_argument("--file", action="append", default=[], help="upload a further file (repeatable)")
    parser.add_argument("--force", action="store_true", help="upload even if the certificate looks outdated")
    parser.add_argument("--dry-run", action="store_true", help="metadata: only print it")
    parser.add_argument("--community", help="community to request (default: codecheck, with --sandbox "
                                            "codecheck-sandbox)")
    args = parser.parse_args(argv)
    config = Path(args.config)
    try:
        if not config.is_file():
            raise ZenodoError(f"{config} not found: run in the template directory or use --config")
        check_env_ignored(load_env([Path(".env"), config.parent / ".env"]))
        if args.command == "metadata" and args.dry_run:
            cmd_metadata(None, config, dry_run=True, outputs_license=args.outputs_license, out=out)
            return 0
        record_id(load_config(config).get("report"), args.sandbox)  # wrong instance: say so before asking for a token
        zenodo = Zenodo(sandbox=args.sandbox, community=args.community)
        if args.command == "reserve":
            cmd_reserve(zenodo, config, args.yes, out=out)
        elif args.command == "all":
            cmd_all(zenodo, config, args.include_config, args.include_outputs, args.outputs_license, args.file,
                    args.force, out=out)
        elif args.command == "metadata":
            cmd_metadata(zenodo, config, outputs_license=args.outputs_license, out=out)
        else:
            cmd_status(zenodo, config, out=out)
    except (ZenodoError, requests.exceptions.RequestException, OSError) as e:
        out(f"Error: {e}")
        return 1
    except Exception as e:  # e.g. invalid YAML, unexpected API responses: a message, not a traceback
        out(f"Error: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
