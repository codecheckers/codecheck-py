"""
Tests for the ORCID checks: check digit (offline) and the public ORCID records (mocked API)
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml

from codecheck import Codecheck
from orcid_records import OrcidDeactivated, OrcidNotFound, check_digit_ok, fetch_orcid_names, name_matches
from validation import CodecheckValidator


@pytest.mark.parametrize('orcid', ['0000-0002-1825-0097', '0000-0002-0024-5046', '0000-0001-8607-8025',
                                   '0000-0002-1694-233X'])
def test_check_digit_valid(orcid):
    assert check_digit_ok(orcid)


@pytest.mark.parametrize('orcid', ['0000-0002-1825-0098', '0000-0002-1852-0097',  # typo, swapped digits
                                   '0123-4567-8910-1112', '0000-0000-0000-0000',  # placeholders
                                   '0000-0002-1694-2330', '0000-0002-1825', 'abcd'])
def test_check_digit_invalid(orcid):
    assert not check_digit_ok(orcid)


def api_response(status=200, name=None):
    resp = MagicMock(status_code=status)
    resp.json.return_value = {'name': name}
    if status >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(str(status))
    return resp


def person(given='Daniel', family='Nüst', credit=None):
    return {'given-names': {'value': given} if given else None, 'family-name': {'value': family} if family else None,
            'credit-name': {'value': credit} if credit else None}


def test_fetch_names():
    with patch('orcid_records.requests.get', return_value=api_response(name=person())) as get:
        assert fetch_orcid_names('0000-0002-0024-5046') == {'given': 'Daniel', 'family': 'Nüst', 'credit': ''}
    assert get.call_args.args[0] == 'https://pub.orcid.org/v3.0/0000-0002-0024-5046/person'
    assert get.call_args.kwargs['headers'] == {'Accept': 'application/json'}


def test_fetch_not_found():
    with patch('orcid_records.requests.get', return_value=api_response(404)), pytest.raises(OrcidNotFound):
        fetch_orcid_names('0000-0002-1825-0097')


@pytest.mark.parametrize('resp', [api_response(409), api_response(
    name=person('Given Names Deactivated', 'Family Name Deactivated'))])
def test_fetch_locked_or_deactivated(resp):
    with patch('orcid_records.requests.get', return_value=resp), pytest.raises(OrcidDeactivated):
        fetch_orcid_names('0000-0002-1825-0097')


@pytest.mark.parametrize('body', [['a list'], {'name': 'not a mapping'}])
def test_fetch_unexpected_response(body):
    resp = api_response()
    resp.json.return_value = body
    with patch('orcid_records.requests.get', return_value=resp), pytest.raises(ValueError):
        fetch_orcid_names('0000-0002-1825-0097')


def test_fetch_server_error():
    with patch('orcid_records.requests.get', return_value=api_response(503)), pytest.raises(requests.exceptions.HTTPError):
        fetch_orcid_names('0000-0002-1825-0097')


@pytest.mark.parametrize('name', [None, person(None, None, None)])
def test_fetch_private_name(name):
    with patch('orcid_records.requests.get', return_value=api_response(name=name)):
        assert fetch_orcid_names('0000-0002-1825-0097') is None


@pytest.mark.parametrize('name,expected', [
    ('Daniel Nüst', True), ('Nust, Daniel', True), ('daniel nüst', True), ('Daniel A. Nüst', True),
    ('D. Nüst', True), ('Nüst, D.', True), ('A. Nüst', False), ('Stephen Eglen', False), ('Daniel', False),
    ('', False),
])
def test_name_matches(name, expected):
    assert name_matches(name, {'given': 'Daniel', 'family': 'Nüst', 'credit': ''}) is expected


def test_name_matches_multi_word_names_and_credit_name():
    assert name_matches('Anna María García Hurtado', {'given': 'Anna María', 'family': 'García Hurtado', 'credit': ''})
    assert not name_matches('Anna García', {'given': 'Anna María', 'family': 'García Hurtado', 'credit': ''})
    assert name_matches('Ana G. Hurtado', {'given': 'Anna', 'family': 'García Hurtado', 'credit': 'Ana G. Hurtado'})
    assert not name_matches('Anyone', {'given': '', 'family': '', 'credit': ''})
    assert name_matches('Stephen Eglen', {'given': 'J. Stephen', 'family': 'Eglen', 'credit': ''})
    assert name_matches('Lukasz Orsted', {'given': 'Łukasz', 'family': 'Ørsted', 'credit': ''})
    assert name_matches('Mononym', {'given': '', 'family': 'Mononym', 'credit': ''})


CONFIG = {
    'codechecker': [{'name': 'Daniel Nüst', 'ORCID': '0000-0002-0024-5046'}],
    'paper': {'authors': [
        {'name': 'Stephen Eglen', 'ORCID': '0000-0001-8607-8025'},
        {'name': 'Daniel Nüst', 'ORCID': '0000-0002-0024-5046'},  # same ORCID again: requested once
        {'name': 'Typo', 'ORCID': '0000-0002-0024-5047'},  # wrong check digit: offline error, not requested
        {'name': 'No ORCID'},
    ]},
}


def validator_with(config):
    validator = CodecheckValidator('dummy.yml')
    validator.config = config
    return validator


def test_offline_check_digit_error():
    validator = validator_with(CONFIG)
    assert validator.validate_orcids() is False
    [issue] = validator.issues
    assert issue.level == 'error' and issue.field == 'paper.authors[2].ORCID' and 'check digit' in issue.message


def test_offline_template_placeholder_orcid_is_an_error():
    validator = CodecheckValidator(str(Path(__file__).parent.parent / 'codecheck.yml'))  # the example config
    validator.validate_yaml_syntax()
    validator.validate_orcids()
    assert {i.message for i in validator.issues} >= {"Codechecker ORCID '0123-4567-8910-1112' has a wrong check "
                                                      "digit (last character), it is not a valid ORCID"}


def test_offline_non_string_orcid():
    validator = validator_with({'paper': {'authors': [{'name': 'A', 'ORCID': 218250097}]}})  # 0000000218250097
    assert validator.validate_orcids() is False
    assert validator.issues[0].message == 'Author 1 ORCID 218250097 is not text'
    assert 'in quotes' in validator.issues[0].suggestion


def test_several_codecheckers_get_indexed_fields():
    validator = validator_with({'codechecker': [{'name': 'A', 'ORCID': '0000-0002-1825-0098'},
                                                {'name': 'B', 'ORCID': '0000-0002-1825-0098'}]})
    validator.validate_orcids()
    assert [(i.field, i.message[:13]) for i in validator.issues] == [
        ('codechecker[0].ORCID', 'Codechecker 1'), ('codechecker[1].ORCID', 'Codechecker 2')]


def names_by_orcid(responses):
    def get(url, **kwargs):
        return responses[url.split('/')[-2]]
    return get


def test_online_all_match():
    responses = {'0000-0002-0024-5046': api_response(name=person()),
                 '0000-0001-8607-8025': api_response(name=person('Stephen', 'Eglen'))}
    validator = validator_with(CONFIG)
    with patch('orcid_records.requests.get', side_effect=names_by_orcid(responses)) as get:
        assert validator.validate_orcids_online() is True
    assert validator.issues == []
    assert get.call_count == 2  # each valid ORCID once


def test_online_not_found_mismatch_and_private():
    responses = {'0000-0002-0024-5046': api_response(name=None),  # private name
                 '0000-0001-8607-8025': api_response(404)}
    config = {'paper': {'authors': [{'name': 'Stephen Eglen', 'ORCID': '0000-0001-8607-8025'},
                                    {'name': 'Daniel Nüst', 'ORCID': '0000-0002-0024-5046'}]},
              'codechecker': {'name': 'Someone Else', 'ORCID': '0000-0002-1825-0097'}}
    responses['0000-0002-1825-0097'] = api_response(name=person('Josiah', 'Carberry'))
    validator = validator_with(config)
    with patch('orcid_records.requests.get', side_effect=names_by_orcid(responses)):
        assert validator.validate_orcids_online() is False
    assert [(i.level, i.field) for i in validator.issues] == [
        ('warning', 'codechecker.ORCID'), ('error', 'paper.authors[0].ORCID'), ('info', 'paper.authors[1].ORCID')]
    assert "name 'Someone Else' does not match the name 'Josiah Carberry'" in validator.issues[0].message
    assert 'Author 1 ORCID 0000-0001-8607-8025 does not exist' == validator.issues[1].message


def test_online_network_error_stops_the_lookups():
    validator = validator_with(CONFIG)
    with patch('orcid_records.requests.get', side_effect=requests.exceptions.ConnectionError('offline')) as get:
        assert validator.validate_orcids_online() is True
    [warning] = validator.issues
    assert warning.level == 'warning' and 'remaining ORCIDs were skipped' in warning.message
    assert get.call_count == 1  # no timeout per ORCID when offline


def test_online_locked_record_is_an_error():
    validator = validator_with({'paper': {'authors': [{'name': 'A', 'ORCID': '0000-0002-1825-0097'}]}})
    with patch('orcid_records.requests.get', return_value=api_response(409)):
        assert validator.validate_orcids_online() is False
    assert validator.issues[0].message == 'Author 1 ORCID 0000-0002-1825-0097 is locked or deactivated'


def test_codecheck_init_can_check_orcids_online(tmp_path):
    config = tmp_path / 'codecheck.yml'
    config.write_text(yaml.dump(CONFIG))
    with patch('orcid_records.requests.get', return_value=api_response(404)), pytest.raises(ValueError):
        Codecheck(str(config), validate=True, strict=True, online='orcid')


def test_validate_all_checks_orcids_online_only_when_asked(tmp_path):
    config = tmp_path / 'codecheck.yml'
    config.write_text(yaml.dump(CONFIG))
    with patch('orcid_records.requests.get', side_effect=requests.exceptions.ConnectionError('offline')) as get:
        CodecheckValidator(str(config)).validate_all(check_manifest=False, online=False)
        get.assert_not_called()
        Codecheck(str(config)).validate(check_manifest=False, online=['orcid'])
        assert get.call_count == 1
