"""
Tests for reading the CODECHECK register issues (pagination, token) and finding the certificate ID of a check
"""
from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml

from codecheck import Codecheck
from register import certificate_candidates, fetch_register_issues, find_issue, first_author_surname, surname
from validation_config import normalise
from validation import CodecheckValidator


def issue(number, title, state='open', assignees=('editor',)):
    return {'number': number, 'title': title, 'state': state, 'html_url': f'https://github.com/x/{number}',
            'assignees': [{'login': a} for a in assignees]}


PAGE_1 = [issue(221, 'Kaya et al. | 2026-NNN'), issue(214, 'Dewi, Holtrop, DeVito et al | 2026-026'),
          {'number': 220, 'title': 'Add Kaya pages', 'pull_request': {}}]
PAGE_2 = [issue(196, 'Tabandeh and Spitschan | 2026-019', state='closed'),
          issue(195, 'Granell, Ostermann, Nüst, et al. | 2026-018', state='closed', assignees=())]


def response(issues, next_url=None):
    resp = MagicMock()
    resp.json.return_value = issues
    resp.links = {'next': {'url': next_url}} if next_url else {}
    return resp


@pytest.fixture(autouse=True)
def no_token(monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('GITHUB_PAT', raising=False)


@pytest.fixture
def api():
    """Mocked GitHub API with two pages of register issues."""
    with patch('register.requests.get') as get:
        get.side_effect = [response(PAGE_1, 'https://api.github.com/next?page=2'), response(PAGE_2)]
        yield get


def test_fetch_follows_pagination_and_skips_pull_requests(api):
    issues = fetch_register_issues()
    assert [i['number'] for i in issues] == [221, 214, 196, 195]
    assert api.call_count == 2
    assert api.call_args_list[1].args[0] == 'https://api.github.com/next?page=2'
    assert api.call_args_list[1].kwargs['params'] is None


def test_fetch_raises_after_max_pages():
    """A truncated scan must not look complete (a missing certificate would become an error)."""
    with patch('register.requests.get', return_value=response(PAGE_1, 'https://next')) as get:
        with pytest.raises(requests.exceptions.RequestException, match='more than 3 pages'):
            fetch_register_issues(max_pages=3)
        assert get.call_count == 3


def test_register_check_warns_on_truncated_scan():
    validator = validator_with({'certificate': '2001-001'})
    with patch('register.requests.get', return_value=response(PAGE_1, 'https://next')):
        assert validator.validate_register_issue() is True
    assert [i.level for i in validator.issues] == ['warning']


@pytest.mark.parametrize('variable', ['GITHUB_TOKEN', 'GITHUB_PAT'])
def test_fetch_uses_token(api, monkeypatch, variable):
    monkeypatch.setenv(variable, 'secret')
    fetch_register_issues()
    assert api.call_args.kwargs['headers']['Authorization'] == 'Bearer secret'


def test_fetch_without_token(api):
    fetch_register_issues()
    assert 'Authorization' not in api.call_args.kwargs['headers']


def test_fetch_raises_on_rate_limit():
    resp = response([])
    resp.raise_for_status.side_effect = requests.exceptions.HTTPError('403 rate limit exceeded')
    with patch('register.requests.get', return_value=resp), pytest.raises(requests.exceptions.HTTPError):
        fetch_register_issues()


@pytest.mark.parametrize('name,expected', [('Daniel Nüst', 'Nüst'), ('Nüst, Daniel', 'Nüst'), ('Kaya', 'Kaya'),
                                           ('', ''), ('  ', ''), ('Anna van der Berg', 'Berg')])
def test_surname(name, expected):
    assert surname(name) == expected


@pytest.mark.parametrize('config,expected', [
    ({'paper': {'authors': [{'name': 'Lukas Tabandeh'}, {'name': 'Manuel Spitschan'}]}}, 'Tabandeh'),
    ({'paper': {'authors': {'name': 'Single Author'}}}, None),  # authors must be a list
    ({'paper': {'authors': []}}, None),
    ({'paper': {'authors': ['no mapping']}}, None),
    ({'paper': {'authors': [{'name': ''}]}}, None),
    ({'paper': 'no mapping'}, None),
    ({}, None),
    (None, None),
])
def test_first_author_surname(config, expected):
    assert first_author_surname(config) == expected


def test_normalise():
    assert normalise('Nüst') == normalise('NUST') == 'nust'


def test_candidates_one_match():
    candidates = certificate_candidates(PAGE_1 + PAGE_2, 'Tabandeh')
    assert candidates == [{'certificate': '2026-019', 'number': 196, 'title': 'Tabandeh and Spitschan | 2026-019',
                           'url': 'https://github.com/x/196', 'state': 'closed', 'assignees': ['editor']}]


def test_candidates_several_matches_open_first():
    issues = PAGE_2 + [issue(211, 'Tabandeh, Veitch, Spitschan | 2026-025'), issue(203, 'Schneider, Spitschan')]
    assert [c['number'] for c in certificate_candidates(issues, 'Spitschan')] == [211, 203, 196]


def test_candidates_without_diacritics_and_without_id():
    assert [c['certificate'] for c in certificate_candidates(PAGE_2, 'Nust')] == ['2026-018']
    assert certificate_candidates(PAGE_1, 'kaya')[0]['certificate'] is None  # 2026-NNN: not assigned yet


def test_candidates_name_ending_with_punctuation():
    assert [c['number'] for c in certificate_candidates([issue(5, 'King Jr. et al. | 2025-001')], 'Jr.')] == [5]


def test_candidates_whole_words_only():
    assert certificate_candidates(PAGE_1 + PAGE_2, 'Granel') == []
    assert certificate_candidates(PAGE_1 + PAGE_2, '') == []


def test_find_issue_exact_id():
    issues = [issue(1, 'A | 2023-0011'), issue(2, 'B | 2023-001')]
    assert find_issue(issues, '2023-001')['number'] == 2
    assert find_issue(issues, '2023-002') is None


def validator_with(config):
    validator = CodecheckValidator('dummy.yml')
    validator.config = config
    return validator


def test_register_check_stops_at_first_page_with_the_certificate(api):
    validator = validator_with({'certificate': '2026-026'})
    assert validator.validate_register_issue() is True
    assert api.call_count == 1


def test_register_check_finds_certificate_on_second_page(api):
    validator = validator_with({'certificate': '2026-018'})
    assert validator.validate_register_issue() is True
    assert [i.message for i in validator.issues] == [
        'Register issue for certificate 2026-018 is closed (issue #195)',
        'Register issue for certificate 2026-018 is unassigned (issue #195)']


def test_placeholder_certificate_suggests_ids(api):
    validator = validator_with({'certificate': 'YYYY-001', 'paper': {'authors': [{'name': 'Lukas Tabandeh'}]}})
    assert validator.validate_register_issue() is True
    [info] = validator.issues
    assert info.level == 'info'
    assert "'Tabandeh' (first author)" in info.message and '2026-019: #196' in info.message


def test_placeholder_certificate_without_match(api):
    validator = validator_with({'certificate': '0000-001', 'paper': {'authors': [{'name': 'Jane Unknown'}]}})
    assert validator.validate_register_issue() is True
    [info] = validator.issues
    assert info.level == 'info' and 'No issue' in info.message


def test_placeholder_certificate_offline():
    validator = validator_with({'certificate': 'YYYY-001', 'paper': {'authors': [{'name': 'Lukas Tabandeh'}]}})
    with patch('register.requests.get', side_effect=requests.exceptions.ConnectionError('offline')):
        assert validator.validate_register_issue() is True
    [info] = validator.issues
    assert info.level == 'info' and "Could not look up 'Tabandeh'" in info.message


def test_placeholder_certificate_without_authors_makes_no_request(api):
    validator = validator_with({'certificate': 'YYYY-001', 'paper': {'title': 'x'}})
    assert validator.validate_register_issue() is True
    assert validator.issues == []
    api.assert_not_called()


def test_suggestions_do_not_fail_strict_validation(api, tmp_path):
    config = tmp_path / 'codecheck.yml'
    config.write_text(yaml.dump({'certificate': 'YYYY-001', 'paper': {'authors': [{'name': 'Lukas Tabandeh'}]}}))
    validator = CodecheckValidator(str(config))
    validator.validate_yaml_syntax()
    validator.validate_register_issue()
    assert '2026-019' in validator.format_report()
    assert not [i for i in validator.issues if i.level != 'info']


@pytest.fixture
def check(tmp_path, monkeypatch):
    (tmp_path / 'codecheck.yml').write_text(yaml.dump({'paper': {'authors': [{'name': 'Anna Granell'}]}}))
    monkeypatch.chdir(tmp_path)
    return Codecheck('codecheck.yml')


def test_find_certificate_id(api, check):
    md = check.find_certificate_id().data
    assert 'Register issues with `Granell` in the title' in md
    assert '2026-018 | [#195](https://github.com/x/195) Granell, Ostermann, Nüst, et al. \\| 2026-018 | closed | \n' in md + '\n'
    header, _, row = md.splitlines()[-3:]
    assert len(header.split(' | ')) == len(row.replace('\\|', '').split(' | ')) == 4


def test_find_certificate_id_other_name(api, check):
    md = check.find_certificate_id(name='Kaya').data
    assert '*not assigned yet* | [#221]' in md and 'editor' in md


def test_find_certificate_id_no_match(api, check):
    assert 'No issue in the CODECHECK register has `Nobody`' in check.find_certificate_id(name='Nobody').data


@pytest.mark.parametrize('error', [requests.exceptions.ConnectionError('offline'), ValueError('offline')])
def test_find_certificate_id_offline(check, error):
    with patch('register.requests.get', side_effect=error):
        assert 'Could not read the CODECHECK register issues: offline' in check.find_certificate_id().data


def test_find_certificate_id_without_authors(tmp_path, monkeypatch):
    (tmp_path / 'codecheck.yml').write_text(yaml.dump({'certificate': 'YYYY-001'}))
    monkeypatch.chdir(tmp_path)
    with patch('register.requests.get') as get:
        assert 'No name to search for' in Codecheck('codecheck.yml').find_certificate_id().data
        get.assert_not_called()
