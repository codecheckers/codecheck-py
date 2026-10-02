"""
Tests for the helper functions and the report methods of the Codecheck class
"""

import pytest
import yaml

import codecheck as cc
from codecheck import Codecheck

from .conftest import git_commit_all, requires_git

VALID = {
    'version': 'https://codecheck.org.uk/spec/config/1.0/',
    'certificate': '2023-001',
    'report': 'https://doi.org/10.5281/zenodo.1234567',
    'paper': {'title': 'A title', 'reference': 'https://doi.org/10.1234/x',
              'authors': [{'name': 'Ann Author', 'ORCID': '0000-0002-0024-5046'}, {'name': 'No Orcid'}]},
    'repository': 'https://github.com/octocat/hello-world',
    'check_time': '2023-11-15T14:30:00',
    'summary': 'All\n  figures   reproduced.\n',
    'codechecker': [{'name': 'Chris Checker', 'ORCID': '0000-0001-8607-8025'}],
    'manifest': [{'file': 'data/a.csv', 'comment': 'a table'}],
}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / '.codecheck' / 'outputs' / 'data').mkdir(parents=True)
    (tmp_path / '.codecheck' / 'outputs' / 'data' / 'a.csv').write_text('x,y\n1,2\n3,4\n')
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'a.csv').write_text('x,y\n1,2\n3,4\n')
    (tmp_path / 'codecheck.yml').write_text(yaml.dump(VALID))
    monkeypatch.chdir(tmp_path / '.codecheck')
    return tmp_path


def test_name_and_link_helpers():
    assert cc.name_orcid({'name': 'A', 'ORCID': '0000-0002-0024-5046'}) == 'A (ORCID: 0000-0002-0024-5046)'
    assert cc.name_orcid({'name': 'A'}) == 'A'
    assert cc.multiple_name_orcid({'name': 'A'}) == 'A'  # a single person instead of a list
    assert cc.multiple_name([{'name': 'A'}, {'name': 'B'}]) == 'A, B'
    assert cc.url_link('https://x.org/a') == '[https://x.org/a](https://x.org/a)'
    assert cc.short_link('https://x.org/a') == '[x.org/a](https://x.org/a)'


def test_report_parts(workspace):
    check = Codecheck()
    assert check.get_formatted_summary() == 'All   figures   reproduced.'
    assert 'CODECHECK certificate 2023-001' in check.title().data
    table = check.summary_table().data
    assert 'Ann Author (ORCID: 0000-0002-0024-5046), No Orcid' in table and '2023-11-15' in table
    assert check.summary().data == 'All   figures   reproduced.'
    assert 'Chris Checker (2023). CODECHECK Certificate 2023-001.' in check.citation().data
    assert 'independently reproduce' in check.about_codecheck().data
    assert check.session_info().data.startswith('```bash')
    files = check.files().data
    assert '`a.csv` | a table | 12' in files
    assert 'data/a.csv' in check.files(remove_dirname=False).data


def test_validate_and_report(workspace):
    check = Codecheck()
    passed, found = check.validate(check_register=False)
    assert passed is True and not [i for i in found if i.level == 'error']
    assert isinstance(check.validation_report(), cc.Markdown)
    assert isinstance(check.validation_report(markdown=False), str)


def test_strict_validation_on_init_raises(tmp_path, monkeypatch):
    (tmp_path / 'codecheck.yml').write_text(yaml.dump({'manifest': [{'file': 'a.csv'}]}))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match='Validation failed'):
        Codecheck(str(tmp_path / 'codecheck.yml'), validate=True, strict=True)
    Codecheck(str(tmp_path / 'codecheck.yml'), validate=True, strict=False)  # does not raise


def test_manifest_helpers(workspace):
    check = Codecheck()
    assert check.validate_manifest_files() == (True, [])
    summary = check.manifest_summary().data
    assert 'Total files**: 1' in summary and '`.csv`: 1 file(s)' in summary


def test_copy_manifest_files(workspace):
    (workspace / '.codecheck' / 'outputs' / 'data' / 'a.csv').unlink()
    check = Codecheck()
    assert check.validate_manifest_files() == (False, ['data/a.csv'])
    assert 'Copied 1 file(s)' in check.copy_manifest_files(dry_run=True).data
    assert not (workspace / '.codecheck' / 'outputs' / 'data' / 'a.csv').exists()
    assert 'data/a.csv' in check.copy_manifest_files().data
    assert (workspace / '.codecheck' / 'outputs' / 'data' / 'a.csv').exists()
    assert 'No files copied' in check.copy_manifest_files(source_dir=workspace / 'nowhere').data


@requires_git
def test_copy_manifest_files_notes_files_unchanged_in_git(workspace):
    git_commit_all(workspace, 'data/a.csv', 'codecheck.yml')
    check = Codecheck()
    report = check.copy_manifest_files().data
    assert 'Copied 1 file(s)' in report and 'Unchanged since commit' in report  # the committed original
    report = check.copy_manifest_files(update=True).data  # nothing to copy, the note stays
    assert 'No files copied' in report and 'Unchanged since commit' in report and '`data/a.csv`' in report
    (workspace / 'data' / 'a.csv').write_text('x,y\n5,6\n')  # reproduced: differs from the commit
    report = check.copy_manifest_files().data
    assert 'Copied 1 file(s)' in report and 'Unchanged since commit' not in report


@requires_git
def test_copy_manifest_files_with_numeric_manifest_path(workspace):
    """A manifest path that YAML reads as a number (`file: 2020`) works with the git check."""
    (workspace / 'codecheck.yml').write_text(yaml.dump({**VALID, 'manifest': [{'file': 2020}]}))
    (workspace / '2020').write_text('result\n')
    git_commit_all(workspace, '2020')
    report = Codecheck().copy_manifest_files().data
    assert 'Copied 1 file(s)' in report and 'Unchanged since commit' in report and '`2020`' in report


def test_methods_without_manifest(tmp_path, monkeypatch):
    (tmp_path / 'codecheck.yml').write_text(yaml.dump({'certificate': '2023-001'}))
    monkeypatch.chdir(tmp_path)
    check = Codecheck(str(tmp_path / 'codecheck.yml'))
    assert check.validate_manifest_files() == (False, [])
    assert 'No manifest found' in check.manifest_summary().data
    assert 'No manifest found' in check.copy_manifest_files().data
