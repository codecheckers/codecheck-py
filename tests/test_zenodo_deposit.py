"""
Tests for publishing the certificate on Zenodo (zenodo_deposit.py) with a mocked InvenioRDM API, no network
"""
import io
import os
import re
import subprocess
import zipfile
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import pytest
import yaml

import zenodo_deposit as zd
from config_io import _guess_indent, write_config_fields
from validation_config import split_name

CONF = {
    'certificate': '2026-001',
    'report': 'https://doi.org/10.5281/zenodo.TODO',
    'summary': 'All <results> reproduced.',
    'repository': 'https://github.com/codecheckers/demo-check',
    'check_time': '2026-02-03T10:00:00',
    'paper': {'title': 'A paper', 'reference': 'https://doi.org/10.1234/abcd'},
    'codechecker': [{'name': 'Daniel Nüst', 'ORCID': '0000-0002-0024-5046', 'affiliation': 'TU Dresden'},
                    {'name': 'Eglen, Stephen J.', 'ORCID': '0000-0001-8607-8025'},
                    {'name': 'CODECHECK'}],
    'manifest': [{'file': 'figures/a.png'}, {'file': 'b.csv'}],
}

CONFIG_TEXT = """%YAML 1.1
---
# CODECHECK configuration
manifest:
  - file: figures/a.png
  - file: b.csv
paper:
  title: A paper  # comment kept
  reference: https://doi.org/10.1234/abcd
certificate: 2026-001
# reserved on Zenodo
report: https://doi.org/10.5281/zenodo.TODO
check_time: "2026-02-03T10:00:00"
codechecker:
  - name: Daniel Nüst
    ORCID: 0000-0002-0024-5046
"""


@pytest.fixture(autouse=True)
def no_tokens(monkeypatch):
    for name in zd.TOKENS.values():
        monkeypatch.delenv(name, raising=False)


# --- configuration ---

def test_load_env(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('# comment\nZENODO_API_TOKEN_SANDBOX="sandbox-token"\nZENODO_API_TOKEN=\nnot a line\n')
    monkeypatch.setenv('ZENODO_API_TOKEN', 'from-environment')
    assert zd.load_env([tmp_path / 'missing', env]) == env
    assert os.environ['ZENODO_API_TOKEN_SANDBOX'] == 'sandbox-token'
    assert os.environ['ZENODO_API_TOKEN'] == 'from-environment'  # the environment wins
    assert zd.load_env([tmp_path / 'missing']) is None


def test_token(monkeypatch):
    with pytest.raises(zd.ZenodoError, match='ZENODO_API_TOKEN_SANDBOX.*sandbox.zenodo.org'):
        zd.token(True)
    monkeypatch.setenv('ZENODO_API_TOKEN', ' secret ')
    assert zd.token(False) == 'secret'


def git(path, *args):
    subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True)


def test_env_must_be_ignored_by_git(tmp_path):
    env = tmp_path / '.env'
    env.write_text('ZENODO_API_TOKEN=x\n')
    zd.check_env_ignored(env)  # not a repository: fine
    zd.check_env_ignored(None)
    git(tmp_path, 'init', '-q')
    with pytest.raises(zd.ZenodoError, match='not ignored by git'):
        zd.check_env_ignored(env)
    (tmp_path / '.gitignore').write_text('.env\n')
    zd.check_env_ignored(env)


@pytest.mark.parametrize('report,sandbox,expected', [
    ('https://doi.org/10.5281/zenodo.14900193', False, '14900193'),
    ('10.5072/zenodo.145250', True, '145250'),
    ('https://doi.org/10.5281/zenodo.TODO', False, None),
    ('https://doi.org/10.5281/zenodo.XXXXXX', False, None),
    ('https://doi.org/10.1234/other', False, None),
    ('', False, None), (None, True, None),
])
def test_record_id(report, sandbox, expected):
    assert zd.record_id(report, sandbox) == expected


@pytest.mark.parametrize('report,sandbox,message', [
    ('10.5072/zenodo.1', False, 'is from the Zenodo sandbox: use --sandbox'),
    ('10.5281/zenodo.1', True, 'is from Zenodo: leave out --sandbox')])
def test_record_id_instance_mismatch(report, sandbox, message):
    with pytest.raises(zd.ZenodoError, match=message):
        zd.record_id(report, sandbox)


# --- metadata ---

def test_build_metadata():
    metadata, warnings = zd.build_metadata(CONF)
    assert warnings == []
    assert metadata['title'] == 'CODECHECK Certificate 2026-001'
    assert metadata['publication_date'] == '2026-02-03'
    assert metadata['creators'] == [
        {'person_or_org': {'type': 'personal', 'family_name': 'Nüst', 'given_name': 'Daniel',
                           'identifiers': [{'scheme': 'orcid', 'identifier': '0000-0002-0024-5046'}]},
         'affiliations': [{'name': 'TU Dresden'}]},
        {'person_or_org': {'type': 'personal', 'family_name': 'Eglen', 'given_name': 'Stephen J.',
                           'identifiers': [{'scheme': 'orcid', 'identifier': '0000-0001-8607-8025'}]}},
        {'person_or_org': {'type': 'organizational', 'name': 'CODECHECK'}}]
    assert metadata['resource_type'] == {'id': 'publication-report'}
    assert metadata['rights'] == [{'id': 'cc-by-4.0'}]
    assert '<strong>Summary:</strong> All &lt;results&gt; reproduced.' in metadata['description']
    assert '<a href="https://github.com/codecheckers/demo-check">' in metadata['description']
    assert metadata['related_identifiers'] == [
        {'identifier': '10.1234/abcd', 'scheme': 'doi', 'relation_type': {'id': 'reviews'},
         'resource_type': {'id': 'publication-article'}},
        {'identifier': 'https://github.com/codecheckers/demo-check', 'scheme': 'url',
         'relation_type': {'id': 'issupplementedby'}, 'resource_type': {'id': 'software'}}]
    assert metadata['identifiers'] == [{'identifier': 'http://cdchck.science/register/certs/2026-001', 'scheme': 'url'},
                                       {'identifier': 'cdchck.science/register/certs/2026-001', 'scheme': 'other'}]


def test_build_metadata_placeholders_and_variants():
    conf = {'certificate': '2026-NNN', 'check_time': 'YYYY-MM-DDTHH:MM:SS', 'summary': 'TODO add summary',
            'codechecker': {'name': 'Jane Doe', 'ORCID': '0123-4567-8910-1112'},  # single, invalid ORCID
            'paper': {'title': 'FIXME', 'reference': 'not a link'},
            'repository': ['https://doi.org/10.5281/zenodo.1', 'https://github.com/example/repo']}
    metadata, warnings = zd.build_metadata(conf, outputs_license='mit')
    assert warnings[0] == "certificate '2026-NNN' is a placeholder"
    assert warnings[1] == ("ORCID '0123-4567-8910-1112' of Jane Doe is not valid (plain 0000-0000-0000-0000), it is "
                           "left out")
    assert warnings[2].startswith("check_time 'YYYY-MM-DDTHH:MM:SS' is not a date: the publication date is today")
    assert warnings[3:] == ['no summary', 'paper.reference is not a DOI or URL']
    assert metadata['creators'] == [{'person_or_org': {'type': 'personal', 'family_name': 'Doe',
                                                       'given_name': 'Jane'}}]
    assert 'identifiers' not in metadata and metadata['description'].count('Repository') == 1
    assert metadata['related_identifiers'] == [
        {'identifier': '10.5281/zenodo.1', 'scheme': 'doi', 'relation_type': {'id': 'issupplementedby'},
         'resource_type': {'id': 'dataset'}}]
    assert metadata['rights'] == [{'id': 'cc-by-4.0'}, {'id': 'mit'}]
    assert 'codecheck-outputs.zip' in metadata['additional_descriptions'][0]['description']
    assert zd.build_metadata({})[1][:2] == ["certificate '' is a placeholder", 'no codechecker with a name']
    assert zd.build_metadata({**CONF, 'repository': 'https://gitlab.com/a/b'})[0]['related_identifiers'][1][
        'identifier'] == 'https://gitlab.com/a/b'  # a single URL


# --- API, with a fake Zenodo ---

class FakeZenodo:
    """Answers `requests.request` like the InvenioRDM API of Zenodo for one draft, and records the calls."""

    def __init__(self, community=True):
        self.calls = []
        self.files = {}
        self.draft = {'id': '123', 'metadata': {'title': 'old'}, 'access': {'record': 'public'},
                      'custom_fields': {'x': 1}, 'pids': {}, 'files': {'enabled': True}}
        self.community = community
        self.put = self.review = None
        self.version = None  # the draft of a new version (record 124), once created

    def __call__(self, method, url, headers=None, json=None, data=None, timeout=None):
        path = url.split('/api', 1)[1]
        self.calls.append((method, path))
        assert headers['Authorization'] == 'Bearer secret' and 'inveniordm' in headers['Accept']
        assert 'publish' not in path and 'submit-review' not in path  # never published or submitted
        if method == 'POST' and path == '/records':
            self.draft['metadata'] = json['metadata']
            return self.response(201, self.draft)
        if path == '/records/123/versions' and method == 'POST':  # an existing new version is returned again
            self.version = self.version or {'id': '124', 'is_published': False, 'versions': {'index': 2},
                                            'pids': {}, 'parent': {'communities': {}}}
            return self.response(201, self.version)
        if path == '/records/124/draft/pids/doi':
            self.version['pids'] = {'doi': {'identifier': '10.5072/zenodo.124'}}
            return self.response(201, self.version)
        if path == '/records/123/draft/pids/doi':
            self.draft['pids'] = {'doi': {'identifier': '10.5072/zenodo.123', 'provider': 'datacite'}}
            return self.response(201, self.draft)
        if path == '/records/123/draft':
            if method == 'PUT':
                self.put = json
                self.draft.update(json)
                if any(r.get('icon') for r in json['metadata'].get('rights', [])):  # expanded vocabulary entry
                    return self.response(200, {**self.draft, 'errors': [
                        {'field': 'metadata.rights.0.icon', 'messages': ['Unknown field.']}]})
            return self.response(200, self.draft)
        if path == '/records/123/draft/files':
            if method == 'POST':
                self.files[json[0]['key']] = None
                return self.response(201, {})
            return self.response(200, {'entries': [{'key': k} for k in self.files]})
        if path.startswith('/records/123/draft/files/'):
            key = unquote(path.split('/')[5])
            if method == 'DELETE':
                del self.files[key]
                return self.response(204, None)
            if path.endswith('/content'):
                self.files[key] = data.read()
            return self.response(200, {})
        if path.startswith('/vocabularies/licenses/'):
            return self.response(200, {'id': 'mit'}) if path.endswith('/mit') else self.response(404, {'message': 'x'})
        if path.startswith('/communities/'):
            self.community_slug = path.split('/')[2]
            return self.response(200, {'id': 'uuid-1', 'slug': 'codecheck-sandbox'}) if self.community else \
                self.response(404, {'message': 'x'})
        if path == '/records/123/draft/review':
            if method == 'GET':
                return self.response(200, {'status': 'created', 'receiver': {'community': 'uuid-1'}}) \
                    if self.review else self.response(404, {'message': 'none'})
            self.review = json
            return self.response(200, {})
        if path == '/me':
            return self.response(200, {'id': 31, 'email': 'codechecker@example.org'})
        return self.response(404, {'message': f'unexpected {method} {path}'})

    @staticmethod
    def response(status, body):
        resp = MagicMock(status_code=status, content=b'' if body is None else b'{}')
        resp.json.return_value = body
        return resp


@pytest.fixture
def fake(monkeypatch):
    fake = FakeZenodo()
    monkeypatch.setattr(zd.requests, 'request', fake)
    return fake


@pytest.fixture
def zenodo():
    return zd.Zenodo(sandbox=True, api_token='secret')


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Repository with codecheck.yml and the template directory as working directory."""
    (tmp_path / 'codecheck.yml').write_text(CONFIG_TEXT)
    template = tmp_path / '.codecheck'
    (template / 'outputs' / 'figures').mkdir(parents=True)
    (template / 'outputs' / 'figures' / 'a.png').write_bytes(b'png')
    (template / 'outputs' / 'b.csv').write_text('x\n1\n')
    monkeypatch.chdir(template)
    return tmp_path / 'codecheck.yml'


def quiet(line):
    pass


@pytest.fixture
def reserved(fake, zenodo, workspace):
    """Workspace whose codecheck.yml has the reserved sandbox record 123."""
    zd.cmd_reserve(zenodo, workspace, yes=True, out=quiet)
    return workspace


@pytest.fixture
def certified(reserved):
    """Reserved workspace with a certificate built after the reservation."""
    build_certificate(reserved)
    return reserved


def build_certificate(config):
    """codecheck.md and codecheck.pdf with the report DOI, newer than the configuration."""
    report = yaml.safe_load(config.read_text())['report']
    zd.Path('codecheck.md').write_text(f'# CODECHECK certificate\n{report}\n')
    zd.Path('codecheck.pdf').write_bytes(b'%PDF-1.7')
    zd.Path('codecheck.ipynb').write_text('{}')
    later = config.stat().st_mtime + 10
    os.utime('codecheck.pdf', (later, later))


def test_reserve(fake, zenodo, workspace):
    lines = []
    assert zd.cmd_reserve(zenodo, workspace, yes=True, out=lines.append) == '10.5072/zenodo.123'
    assert fake.calls == [('POST', '/records'), ('POST', '/records/123/draft/pids/doi'),
                          ('GET', '/communities/codecheck-sandbox'), ('PUT', '/records/123/draft/review')]
    assert fake.draft['metadata']['title'] == 'CODECHECK Certificate 2026-001'
    assert fake.review == {'receiver': {'community': 'uuid-1'}, 'type': 'community-submission'}
    text = workspace.read_text()
    assert 'report: https://doi.org/10.5072/zenodo.123\n' in text
    assert text == CONFIG_TEXT.replace('10.5281/zenodo.TODO', '10.5072/zenodo.123')  # nothing else changed
    assert 'sandbox.zenodo.org/uploads/123' in lines[0]
    # again: the record exists, nothing is created
    fake.calls.clear()
    assert zd.cmd_reserve(zenodo, workspace, yes=True, out=lines.append) is None
    assert fake.calls == [('GET', '/records/123/draft')] and 'already has a record' in lines[-1]  # nothing created
    assert 'new-version' not in lines[-1]  # not published


def test_reserve_asks_first(fake, zenodo, workspace, monkeypatch):
    monkeypatch.setattr('builtins.input', lambda prompt: 'n')
    lines = []
    assert zd.cmd_reserve(zenodo, workspace, out=lines.append) is None
    assert fake.calls == [] and lines == ['Nothing reserved.']
    monkeypatch.setattr('builtins.input', MagicMock(side_effect=EOFError))  # not interactive
    assert zd.cmd_reserve(zenodo, workspace, out=lines.append) is None and fake.calls == []


def test_reserve_without_community(fake, zenodo, workspace):
    fake.community = False
    lines = []
    zd.cmd_reserve(zenodo, workspace, yes=True, out=lines.append)
    assert any("community 'codecheck-sandbox' does not exist" in line for line in lines)


def test_all(fake, zenodo, certified):
    workspace = certified
    fake.calls.clear()
    lines = []
    zd.cmd_all(zenodo, workspace, include_config=True, include_outputs=True, outputs_license='mit',
               out=lines.append)
    assert list(fake.files) == ['codecheck.pdf', 'codecheck.ipynb', 'codecheck.yml', 'codecheck-outputs.zip']
    assert fake.files['codecheck.pdf'] == b'%PDF-1.7'
    with zipfile.ZipFile(io.BytesIO(fake.files['codecheck-outputs.zip'])) as z:
        assert sorted(z.namelist()) == ['b.csv', 'figures/a.png']
    assert fake.put['files']['default_preview'] == 'codecheck.pdf'
    assert fake.put['access'] == {'record': 'public'} and fake.put['custom_fields'] == {'x': 1}  # kept
    assert fake.put['pids']['doi']['identifier'] == '10.5072/zenodo.123'
    assert fake.put['metadata']['rights'] == [{'id': 'cc-by-4.0'}, {'id': 'mit'}]
    assert len([c for c in fake.calls if c[0] == 'POST' and c[1].endswith('/commit')]) == 4
    assert 'publish it yourself' in lines[-1]
    # again: the outputs zip on the draft needs its license in the metadata
    with pytest.raises(zd.ZenodoError, match='draft has codecheck-outputs.zip: pass --outputs-license'):
        zd.cmd_all(zenodo, workspace, out=quiet)
    with pytest.raises(zd.ZenodoError, match='draft has codecheck-outputs.zip'):
        zd.cmd_metadata(zenodo, workspace, out=quiet)
    # existing files are replaced, files from earlier uploads are reported
    fake.calls.clear()
    lines = []
    zd.cmd_all(zenodo, workspace, include_outputs=True, outputs_license='mit', out=lines.append)
    assert ('DELETE', '/records/123/draft/files/codecheck.pdf') in fake.calls
    assert any('earlier uploads: codecheck.yml' in line for line in lines)


def test_all_refuses_outdated_certificate(fake, zenodo, reserved):
    workspace = reserved
    with pytest.raises(zd.ZenodoError, match='missing: build the certificate'):
        zd.cmd_all(zenodo, workspace, out=quiet)
    build_certificate(workspace)
    zd.Path('codecheck.md').write_text('certificate without its DOI')
    with pytest.raises(zd.ZenodoError, match='does not contain the DOI 10.5072/zenodo.123'):
        zd.cmd_all(zenodo, workspace, out=quiet)
    os.utime('codecheck.pdf', (0, 0))
    with pytest.raises(zd.ZenodoError, match='older than'):
        zd.cmd_all(zenodo, workspace, out=quiet)
    zd.cmd_all(zenodo, workspace, force=True, out=quiet)
    assert 'codecheck.pdf' in fake.files


def test_all_needs_record_and_outputs_license(fake, zenodo, workspace):
    with pytest.raises(zd.ZenodoError, match='reserve one first'):
        zd.cmd_all(zenodo, workspace, out=quiet)
    with pytest.raises(zd.ZenodoError, match='--outputs-license'):
        zd.cmd_all(zenodo, workspace, include_outputs=True, out=quiet)


def test_outputs_zip_needs_all_manifest_files(workspace, tmp_path):
    (zd.Path('outputs') / 'b.csv').unlink()
    with pytest.raises(zd.ZenodoError, match='missing in outputs: b.csv'):
        zd.outputs_zip(workspace, zd.load_config(workspace), tmp_path / 'o.zip')


def test_extra_files(fake, zenodo, certified):
    workspace = certified
    zd.Path('notes.txt').write_text('notes')
    zd.cmd_all(zenodo, workspace, extra=['notes.txt'], out=quiet)
    assert 'notes.txt' in fake.files
    with pytest.raises(zd.ZenodoError, match='missing.txt does not exist'):
        zd.cmd_all(zenodo, workspace, extra=['missing.txt'], out=quiet)


def test_metadata_and_status(fake, zenodo, workspace):
    lines = []
    zd.cmd_status(zenodo, workspace, out=lines.append)
    assert lines == ['Account: codechecker@example.org (user 31) on https://sandbox.zenodo.org',
                     'No Zenodo record in `report` of codecheck.yml.']
    with pytest.raises(zd.ZenodoError, match='reserve one first'):
        zd.cmd_metadata(zenodo, workspace, out=lines.append)
    zd.cmd_reserve(zenodo, workspace, yes=True, out=quiet)
    zd.cmd_metadata(zenodo, workspace, out=lines.append)
    assert fake.put['metadata']['title'] == 'CODECHECK Certificate 2026-001'
    zd.cmd_status(zenodo, workspace, out=lines.append)
    assert lines[-5:] == ['Account: codechecker@example.org (user 31) on https://sandbox.zenodo.org',
                          'Record 123: draft (not published), DOI 10.5072/zenodo.123, https://sandbox.zenodo.org/uploads/123',
                          'Title: CODECHECK Certificate 2026-001', 'Files: none',
                          'Community request: created (codecheck-sandbox, not submitted unless done on Zenodo)']
    zd.cmd_metadata(None, workspace, dry_run=True, out=lines.append)
    assert 'title: CODECHECK Certificate 2026-001' in lines[-1]


def test_published_record_has_no_draft(fake, zenodo, workspace, monkeypatch):
    zd.cmd_reserve(zenodo, workspace, yes=True, out=quiet)
    original = fake.__call__

    def published(method, url, **kwargs):
        if url.endswith('/records/123/draft'):
            return FakeZenodo.response(404, {'message': 'not found'})
        if url.endswith('/records/123'):
            return FakeZenodo.response(200, {'pids': {'doi': {'identifier': 'x'}}, 'metadata': {'title': 'T'}})
        return original(method, url, **kwargs)
    monkeypatch.setattr(zd.requests, 'request', published)
    with pytest.raises(zd.ZenodoError, match='Record 123 is published'):
        zd.cmd_metadata(zenodo, workspace, out=quiet)
    lines = []
    zd.cmd_status(zenodo, workspace, out=lines.append)
    assert 'published' in lines[1] and 'draft' not in lines[1]


def test_api_errors_and_review_exists(monkeypatch, zenodo):
    monkeypatch.setattr(zd.requests, 'request', lambda *a, **k: FakeZenodo.response(403, {'message': 'denied'}))
    with pytest.raises(zd.ZenodoError, match='POST /records: HTTP 403: denied'):
        zenodo.create_draft({})
    text = MagicMock(status_code=500, content=b'x', text='Server error')
    text.json.side_effect = ValueError
    monkeypatch.setattr(zd.requests, 'request', lambda *a, **k: text)
    with pytest.raises(zd.ZenodoError, match='HTTP 500: Server error'):
        zenodo.get_draft('1')

    def review(method, url, **kwargs):
        if 'communities' in url:
            return FakeZenodo.response(200, {'id': 'u'})
        return FakeZenodo.response(400, {'message': 'A review request already exists.'})
    monkeypatch.setattr(zd.requests, 'request', review)
    assert zenodo.request_review('1') is True


def test_reserve_doi_fails(monkeypatch, zenodo):
    monkeypatch.setattr(zd.requests, 'request', lambda *a, **k: FakeZenodo.response(201, {'pids': {}}))
    with pytest.raises(zd.ZenodoError, match='No DOI reserved'):
        zenodo.reserve_doi('1')


# --- command line ---

def test_main(fake, workspace, monkeypatch, tmp_path):
    (workspace.parent / '.env').write_text('ZENODO_API_TOKEN_SANDBOX=secret\n')
    lines = []
    assert zd.main(['reserve', '--sandbox', '--yes'], out=lines.append) == 0
    assert 'Reserved DOI 10.5072/zenodo.123' in lines[0]
    assert zd.main(['status', '--sandbox'], out=lines.append) == 0
    assert zd.main(['metadata', '--sandbox'], out=lines.append) == 0
    build_certificate(workspace)
    assert zd.main(['all', '--sandbox', '--file', 'codecheck.md'], out=lines.append) == 0
    assert 'codecheck.md' in fake.files
    assert zd.main(['status'], out=lines.append) == 1  # sandbox DOI without --sandbox: before the missing token
    assert lines[-1] == 'Error: The report DOI 10.5072/zenodo.123 is from the Zenodo sandbox: use --sandbox'
    assert zd.main(['status', '--config', 'missing.yml'], out=lines.append) == 1
    assert 'missing.yml not found' in lines[-1]
    assert zd.main(['metadata', '--dry-run'], out=lines.append) == 0


def test_main_refuses_unignored_env(workspace):
    git(workspace.parent, 'init', '-q')
    (workspace.parent / '.env').write_text('ZENODO_API_TOKEN_SANDBOX=secret\n')
    lines = []
    assert zd.main(['status', '--sandbox'], out=lines.append) == 1
    assert 'not ignored by git' in lines[0]


# --- writing codecheck.yml ---

@pytest.mark.parametrize('text,expected', [
    (CONFIG_TEXT, (2, 2)),
    ('a:\n- x: 1\nb:\n    c: 2\n', (4, 0)),
    ('# only comments\nkey: value\n', (2, 0)),
    ('list:\n    -   a\nmap:\n  # comment\n  b: 1\n', (2, 4)),
])
def test_guess_indent(text, expected):
    assert _guess_indent(text) == expected


def test_write_config_fields_top_level_and_section(tmp_path):
    path = tmp_path / 'codecheck.yml'
    path.write_text(CONFIG_TEXT)
    conf = write_config_fields(path, {'report': 'https://doi.org/10.5072/zenodo.1'})
    assert conf['report'] == 'https://doi.org/10.5072/zenodo.1'
    assert path.read_text() == CONFIG_TEXT.replace('10.5281/zenodo.TODO', '10.5072/zenodo.1')
    write_config_fields(path, {'title': 'New'}, section='paper')
    assert re.search(r'\n  title: New +# comment kept\n', path.read_text())  # comment stays in its column


def test_update_draft_raises_field_errors(fake, zenodo):
    with pytest.raises(zd.ZenodoError, match='saved with errors: metadata.rights.0.icon: Unknown field.'):
        zenodo.update_draft('123', {'rights': [{'id': 'cc-by-4.0', 'icon': 'cc-by-icon'}]})


def test_unknown_outputs_license(fake, zenodo, certified):
    workspace = certified
    with pytest.raises(zd.ZenodoError, match="Unknown license 'MIT License'"):
        zd.cmd_all(zenodo, workspace, include_outputs=True, outputs_license='MIT License', out=quiet)
    assert fake.files == {}  # nothing uploaded


@pytest.mark.parametrize('name,expected', [('Daniel Nüst', ('Daniel', 'Nüst')), ('Eglen, Stephen J.', ('Stephen J.', 'Eglen')),
                                           ('Anna van der Berg', ('Anna van der', 'Berg')), ('CODECHECK', ('', 'CODECHECK')),
                                           ('', ('', '')), (None, ('', ''))])
def test_split_name(name, expected):
    assert split_name(name) == expected


def test_write_config_fields_keeps_unusual_indentation(tmp_path):
    """The indentation guess is verified: a file that it does not describe is still reproduced."""
    text = 'list:\n    - a: 1\n      b: 2\nmap:\n    x: 1\nreport: old\n'
    path = tmp_path / 'codecheck.yml'
    path.write_text(text)
    write_config_fields(path, {'report': 'new'})
    assert path.read_text() == text.replace('old', 'new')


def test_outputs_license_without_outputs(fake, zenodo, certified):
    with pytest.raises(zd.ZenodoError, match='--outputs-license without codecheck-outputs.zip'):
        zd.cmd_all(zenodo, certified, outputs_license='mit', out=quiet)
    assert fake.files == {}


def test_reserve_refuses_to_replace_another_report(fake, zenodo, workspace):
    workspace.write_text(CONFIG_TEXT.replace('https://doi.org/10.5281/zenodo.TODO', 'https://doi.org/10.17605/OSF.IO/ABCDE'))
    with pytest.raises(zd.ZenodoError, match='already set .*10.17605/OSF.IO/ABCDE.* not a Zenodo record'):
        zd.cmd_reserve(zenodo, workspace, yes=True, out=quiet)
    assert fake.calls == []


def test_record_id_ignores_case():
    assert zd.record_id('https://doi.org/10.5281/ZENODO.123', False) == '123'


def test_reserve_shows_the_doi_when_writing_fails(fake, zenodo, workspace, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError('duplicate key')
    monkeypatch.setattr(zd, 'write_config_fields', fail)
    lines = []
    with pytest.raises(zd.ZenodoError, match=r'set `report: https://doi.org/10.5072/zenodo.123` yourself'):
        zd.cmd_reserve(zenodo, workspace, yes=True, out=lines.append)
    assert lines == ['Reserved DOI 10.5072/zenodo.123 for the draft https://sandbox.zenodo.org/uploads/123.']


def test_reserve_survives_a_failing_community_request(fake, zenodo, workspace, monkeypatch):
    def review(*args, **kwargs):
        raise zd.ZenodoError('PUT /records/123/draft/review: HTTP 503: down', 503)
    monkeypatch.setattr(zd.Zenodo, 'request_review', review)
    lines = []
    assert zd.cmd_reserve(zenodo, workspace, yes=True, out=lines.append) == '10.5072/zenodo.123'
    assert 'report: https://doi.org/10.5072/zenodo.123' in workspace.read_text()
    assert lines[-2].startswith('Warning: no community request')


def test_published_record_with_open_edit_draft(fake, zenodo, reserved):
    fake.draft['is_published'] = True
    lines = []
    zd.cmd_status(zenodo, reserved, out=lines.append)
    assert 'published, with changes not yet published' in lines[1]
    build_certificate(reserved)
    with pytest.raises(zd.ZenodoError, match='Record 123 is published'):
        zd.cmd_all(zenodo, reserved, out=quiet)
    assert fake.files == {}


def test_file_names_are_quoted_in_urls(fake, zenodo, certified):
    zd.Path('results#1.txt').write_text('x')
    zd.cmd_all(zenodo, certified, extra=['results#1.txt'], out=quiet)
    assert ('PUT', '/records/123/draft/files/results%231.txt/content') in fake.calls
    assert fake.files['results#1.txt'] == b'x'


@pytest.mark.parametrize('body', [['an', 'error', 'list'], 'Bad gateway'])
def test_error_bodies_that_are_no_objects(monkeypatch, zenodo, body):
    monkeypatch.setattr(zd.requests, 'request', lambda *a, **k: FakeZenodo.response(502, body))
    with pytest.raises(zd.ZenodoError, match='HTTP 502') as error:
        zenodo.get_draft('1')
    assert error.value.status == 502


def test_main_reports_unexpected_errors(workspace):
    workspace.write_text('report: [unclosed\n')
    lines = []
    assert zd.main(['status', '--sandbox'], out=lines.append) == 1
    assert lines[0].startswith('Error: ') and 'Error' in lines[0][7:]


def test_status_without_account_and_community_request(fake, zenodo, workspace, monkeypatch):
    fake.community = False
    zd.cmd_reserve(zenodo, workspace, yes=True, out=quiet)
    original = zd.requests.request
    monkeypatch.setattr(zd.requests, 'request', lambda method, url, **kwargs: FakeZenodo.response(
        403, {'message': 'forbidden'}) if url.endswith('/me') else original(method, url, **kwargs))
    lines = []
    zd.cmd_status(zenodo, workspace, out=lines.append)
    assert lines[0] == 'Account: unknown (GET /me: HTTP 403: forbidden)'
    assert lines[-1] == 'Community request: none'


def test_community_option(fake, workspace):
    (workspace.parent / '.env').write_text('ZENODO_API_TOKEN_SANDBOX=secret\n')
    assert zd.main(['reserve', '--sandbox', '--yes', '--community', 'my-community'], out=quiet) == 0
    assert fake.community_slug == 'my-community'
    assert zd.Zenodo(sandbox=False, api_token='x').community == 'codecheck'


@pytest.mark.parametrize('repository,warned', [
    ('https://github.com/codecheckers/demo-check', False), ('https://gitlab.com/cdchck/demo', False),
    ('https://github.com/someone/paper-code', True), ('https://gitlab.com/someone/code', True),
    ('https://doi.org/10.5281/zenodo.1', False), ('https://codeberg.org/someone/code', False)])
def test_repository_location_warning(repository, warned):
    warnings = zd.build_metadata({**CONF, 'repository': repository})[1]
    assert any('codecheckers organisation' in w for w in warnings) is warned


def test_consent_note_for_further_files(fake, zenodo, certified):
    lines = []
    zd.cmd_all(zenodo, certified, out=lines.append)
    assert not any('consent' in line for line in lines)
    zd.cmd_all(zenodo, certified, include_outputs=True, outputs_license='mit', out=lines.append)
    assert any('explicit consent of the copyright holder' in line for line in lines)


def test_codechecker_with_wrong_structure():
    warnings = zd.build_metadata({**CONF, 'codechecker': 'Jane Doe'})[1]
    assert 'codechecker must be a mapping or a list of mappings with name and ORCID' in warnings
    assert 'no codechecker with a name' not in warnings
    named = zd.build_metadata({**CONF, 'codechecker': [{'ORCID': '0123-4567-8910-1112'}, {'name': 'A'}]})[1]
    assert "ORCID '0123-4567-8910-1112' of Codechecker 1 is not valid" in ' '.join(named)


@pytest.fixture
def published(fake, reserved):
    """Record 123 is published (in a community)."""
    fake.draft['is_published'] = True
    fake.draft['parent'] = {'communities': {'ids': ['uuid-1']}}
    fake.calls.clear()
    return reserved


def test_new_version(fake, zenodo, published):
    lines = []
    assert zd.cmd_new_version(zenodo, published, yes=True, out=lines.append) == '10.5072/zenodo.124'
    assert fake.calls == [('GET', '/records/123/draft'), ('POST', '/records/123/versions'),
                          ('POST', '/records/124/draft/pids/doi')]  # no community request
    assert 'report: https://doi.org/10.5072/zenodo.124\n' in published.read_text()
    assert lines == ['Reserved DOI 10.5072/zenodo.124 for the draft https://sandbox.zenodo.org/uploads/124.',
                     f'Wrote it to `report` in {published}.',
                     'New version 2 of record 123. Next: update the certificate (e.g. check_time, notes), rebuild it '
                     '(sh notebook_to_pdf.sh) and upload it (all).']


def test_new_version_returns_the_existing_draft(fake, zenodo, published):
    """As Zenodo does: asking again returns the unpublished new version with its DOI, no further DOI."""
    zd.cmd_new_version(zenodo, published, yes=True, out=quiet)
    published.write_text(published.read_text().replace('zenodo.124', 'zenodo.123'))  # e.g. writing had failed
    fake.calls.clear()
    lines = []
    assert zd.cmd_new_version(zenodo, published, yes=True, out=lines.append) == '10.5072/zenodo.124'
    assert ('POST', '/records/124/draft/pids/doi') not in fake.calls
    assert lines[0] == ('The new version exists already, DOI 10.5072/zenodo.124 for the draft '
                        'https://sandbox.zenodo.org/uploads/124.')


def test_new_version_asks_first(fake, zenodo, published, monkeypatch):
    monkeypatch.setattr('builtins.input', lambda prompt: 'n')
    lines = []
    assert zd.cmd_new_version(zenodo, published, out=lines.append) is None
    assert lines == ['No new version.'] and ('POST', '/records/123/versions') not in fake.calls


def test_new_version_warns_without_community(fake, zenodo, published):
    fake.draft['parent'] = {'communities': {}}
    lines = []
    zd.cmd_new_version(zenodo, published, yes=True, out=lines.append)
    assert lines[-1].startswith('Warning: the published record is not in a community')


def test_new_version_of_an_unpublished_draft(fake, zenodo, reserved):
    lines = []
    assert zd.cmd_new_version(zenodo, reserved, yes=True, out=lines.append) is None
    assert 'is not published yet' in lines[0]
    reserved.write_text(CONFIG_TEXT)  # no record in `report`
    with pytest.raises(zd.ZenodoError, match='reserve one first'):
        zd.cmd_new_version(zenodo, reserved, yes=True, out=quiet)


def test_new_version_of_a_missing_record(fake, zenodo, reserved, monkeypatch):
    original = fake.__call__
    monkeypatch.setattr(zd.requests, 'request', lambda method, url, **kwargs: FakeZenodo.response(
        404, {'message': 'not found'}) if url.endswith('/records/123/draft') or url.endswith('/records/123')
        else original(method, url, **kwargs))
    with pytest.raises(zd.ZenodoError, match='Record 123 .* does not exist'):
        zd.cmd_new_version(zenodo, reserved, yes=True, out=quiet)
    lines = []
    zd.cmd_reserve(zenodo, reserved, yes=True, out=lines.append)
    assert 'does not exist (any more)' in lines[0]


def test_all_on_a_new_version(fake, zenodo, published, monkeypatch):
    zd.cmd_new_version(zenodo, published, yes=True, out=quiet)
    build_certificate(published)
    fake.draft = fake.version  # the draft endpoints of the fake (record 123) answer for the new version 124
    monkeypatch.setattr(zd.requests, 'request',
                        lambda method, url, **kwargs: fake(method, url.replace('/records/124/', '/records/123/'),
                                                           **kwargs))
    fake.calls.clear()
    lines = []
    zd.cmd_all(zenodo, published, out=lines.append)
    assert not any('review' in path or 'communities' in path for _, path in fake.calls)
    assert any('(new version)' in line for line in lines)
    assert 'Warning: the record is not in a community: request the inclusion on Zenodo.' in lines


def test_reserve_hint_does_not_fail(fake, zenodo, reserved, monkeypatch):
    monkeypatch.setattr(zd.Zenodo, 'record_state', MagicMock(side_effect=zd.ZenodoError('HTTP 401', 401)))
    lines = []
    assert zd.cmd_reserve(zenodo, reserved, yes=True, out=lines.append) is None
    assert lines[0].endswith('nothing reserved.')


def test_reserve_on_published_record_points_to_new_version(fake, zenodo, published):
    lines = []
    assert zd.cmd_reserve(zenodo, published, yes=True, out=lines.append) is None
    assert 'use new-version for a corrected certificate' in lines[0]


def test_main_new_version(fake, published):
    (published.parent / '.env').write_text('ZENODO_API_TOKEN_SANDBOX=secret\n')
    lines = []
    assert zd.main(['new-version', '--sandbox', '--yes'], out=lines.append) == 0
    assert 'Reserved DOI 10.5072/zenodo.124' in lines[0]
