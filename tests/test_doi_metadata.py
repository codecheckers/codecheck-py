"""
Tests for the paper metadata from a DOI (Crossref, OpenAlex; mocked API) and updating codecheck.yml with it
"""
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml

import doi_metadata
from codecheck import Codecheck
from doi_metadata import (DoiNotFound, add_missing_orcids, doi_from, fetch_paper_metadata, parse_crossref,
                          parse_openalex)

DOI = '10.1038/s41562-016-0021'

CROSSREF = {'message': {
    'title': ['A manifesto for\n reproducible science'],
    'author': [{'given': 'Marcus R.', 'family': 'Munafò'},
               {'given': 'Brian A.', 'family': 'Nosek', 'ORCID': 'http://orcid.org/0000-0001-6797-5476'},
               {'name': 'The Consortium'}, {'given': 'Anna', 'family': 'Other'}],
    'published': {'date-parts': [[2017, 1, 10]]},
}}
OPENALEX = {
    'display_name': 'A manifesto for reproducible science',
    'publication_date': '2017-01-10',
    'authorships': [{'author': {'display_name': 'Marcus Robert Munafo', 'orcid': 'https://orcid.org/0000-0002-4049-993X'}},
                    {'author': {'display_name': 'Brian A. Nosek', 'orcid': 'https://orcid.org/0000-0001-6797-5476'}},
                    {'author': {'display_name': 'The Consortium', 'orcid': None}},
                    {'author': {'display_name': 'Somebody Else', 'orcid': 'https://orcid.org/0000-0002-1825-0097'}}],
}
AUTHORS = [{'name': 'Marcus R. Munafò', 'ORCID': '0000-0002-4049-993X'},
           {'name': 'Brian A. Nosek', 'ORCID': '0000-0001-6797-5476'},
           {'name': 'The Consortium'}, {'name': 'Anna Other'}]


def response(status=200, body=None):
    resp = MagicMock(status_code=status)
    resp.json.return_value = body
    if status >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(str(status))
    return resp


def api(crossref=None, openalex=None):
    """Mocked `requests.get` answering Crossref and OpenAlex URLs (an exception is raised, None is a 404)."""
    def get(url, **kwargs):
        result = crossref if 'crossref' in url else openalex
        if isinstance(result, Exception):
            raise result
        return response(404) if result is None else response(body=result)
    return patch('doi_metadata.requests.get', side_effect=get)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(doi_metadata, '_cache', {})
    monkeypatch.delenv('CODECHECK_MAILTO', raising=False)


@pytest.mark.parametrize('text,expected', [
    (DOI, DOI), (f'https://doi.org/{DOI}', DOI), (f'doi:{DOI}.', DOI), (f'[paper](https://doi.org/{DOI})', DOI),
    (f'<https://doi.org/{DOI}>', DOI), ('10.1002/(SICI)1097-4636(199706)35', '10.1002/(SICI)1097-4636(199706)35'), ('10.48550/arXiv.2305.10401', '10.48550/arXiv.2305.10401'),
    ('https://example.org/paper', None), (None, None),
])
def test_doi_from(text, expected):
    assert doi_from(text) == expected


def test_parse_crossref():
    assert parse_crossref(CROSSREF['message']) == {
        'title': 'A manifesto for reproducible science', 'date': '2017-01-10', 'source': 'Crossref',
        'authors': [{'name': 'Marcus R. Munafò'}, {'name': 'Brian A. Nosek', 'ORCID': '0000-0001-6797-5476'},
                    {'name': 'The Consortium'}, {'name': 'Anna Other'}]}


@pytest.mark.parametrize('message,date', [({'issued': {'date-parts': [[2020]]}}, '2020'),
                                          ({'published': {'date-parts': [[None]]}}, None), ({}, None)])
def test_parse_crossref_dates(message, date):
    assert parse_crossref(message)['date'] == date


def test_parse_openalex():
    metadata = parse_openalex(OPENALEX)
    assert metadata['authors'][0] == {'name': 'Marcus Robert Munafo', 'ORCID': '0000-0002-4049-993X'}
    assert metadata['authors'][2] == {'name': 'The Consortium'}
    assert metadata['date'] == '2017-01-10' and metadata['source'] == 'OpenAlex'


def test_add_missing_orcids_only_for_the_same_person():
    crossref = parse_crossref(CROSSREF['message'])['authors']
    assert add_missing_orcids(crossref, parse_openalex(OPENALEX)['authors']) == AUTHORS  # not Anna Other's
    assert add_missing_orcids(crossref, []) == crossref
    assert add_missing_orcids(crossref + [{'name': 'Extra Author'}], parse_openalex(OPENALEX)['authors'])[-1] == \
        {'name': 'Extra Author'}


def test_fetch_crossref_with_openalex_orcids():
    with api(CROSSREF, OPENALEX) as get:
        metadata = fetch_paper_metadata(f'https://doi.org/{DOI}')
    assert metadata == {'title': 'A manifesto for reproducible science', 'authors': AUTHORS, 'date': '2017-01-10',
                        'source': 'Crossref', 'reference': f'https://doi.org/{DOI}'}
    assert [c.args[0] for c in get.call_args_list] == [f'https://api.crossref.org/works/{DOI}',
                                                        f'https://api.openalex.org/works/https://doi.org/{DOI}']


def test_fetch_falls_back_to_openalex():
    with api(None, OPENALEX):
        metadata = fetch_paper_metadata(DOI)
    assert metadata['source'] == 'OpenAlex' and metadata['authors'][0]['name'] == 'Marcus Robert Munafo'


def test_fetch_crossref_when_openalex_is_unavailable():
    with api(CROSSREF, requests.exceptions.ConnectionError('openalex down')):
        assert fetch_paper_metadata(DOI)['authors'][0] == {'name': 'Marcus R. Munafò'}


def test_fetch_unknown_doi():
    with api(None, None), pytest.raises(DoiNotFound):
        fetch_paper_metadata(DOI)


@pytest.mark.parametrize('crossref,openalex', [
    (requests.exceptions.ConnectionError('crossref down'), requests.exceptions.ConnectionError('openalex down')),
    (None, requests.exceptions.ConnectionError('openalex down'))])
def test_fetch_network_errors(crossref, openalex):
    with api(crossref, openalex), pytest.raises(requests.exceptions.ConnectionError, match=r'(crossref|openalex) down'):
        fetch_paper_metadata(DOI)


def test_fetch_openalex_when_crossref_fails():
    with api(requests.exceptions.HTTPError('503'), OPENALEX):
        assert fetch_paper_metadata(DOI)['source'] == 'OpenAlex'


def test_fetch_quotes_the_doi_in_urls():
    doi = '10.1002/(SICI)1097-4636(199706)35:4<401::AID-JBM1>3.0.CO;2-#'
    with api(CROSSREF, OPENALEX) as get:
        assert fetch_paper_metadata(doi)['reference'] == f'https://doi.org/{doi}'
    assert get.call_args_list[0].args[0].endswith('/works/10.1002/%28SICI%291097-4636%28199706%2935%3A4%3C401%3A%3A'
                                                  'AID-JBM1%3E3.0.CO%3B2-%23')


def test_parse_crossref_markup_and_subtitle():
    message = {'title': ['Gene regulation in <i>Drosophila</i> &amp; flies'], 'subtitle': ['A <b>review</b>']}
    assert parse_crossref(message)['title'] == 'Gene regulation in Drosophila & flies: A review'
    assert parse_crossref({'title': ['Title: Sub'], 'subtitle': ['Sub']})['title'] == 'Title: Sub'


def test_fetch_is_cached():
    with api(CROSSREF, OPENALEX) as get:
        first = fetch_paper_metadata(DOI)
        first['authors'].pop()  # changing a result does not change the cache
        assert fetch_paper_metadata(f'https://doi.org/{DOI.upper()}')['authors'] == AUTHORS
    assert get.call_count == 2


@pytest.mark.parametrize('mailto,env,params', [('me@example.org', 'env@example.org', {'mailto': 'me@example.org'}),
                                                (None, 'env@example.org', {'mailto': 'env@example.org'}),
                                                (None, None, {})])
def test_fetch_sends_mailto(monkeypatch, mailto, env, params):
    if env:
        monkeypatch.setenv('CODECHECK_MAILTO', env)
    with api(CROSSREF, OPENALEX) as get:
        fetch_paper_metadata(DOI, mailto=mailto)
    assert [c.kwargs['params'] for c in get.call_args_list] == [params, params]


def test_fetch_skips_openalex_when_all_orcids_are_known():
    body = {'message': {**CROSSREF['message'], 'author': [CROSSREF['message']['author'][1]]}}
    with api(body, OPENALEX) as get:
        assert fetch_paper_metadata(DOI)['authors'] == [AUTHORS[1]]
    assert get.call_count == 1


TEMPLATE = f"""version: https://codecheck.org.uk/spec/config/1.0/
certificate: 2025-023

# the checked paper
paper:
  title: FIXME add title  # from the journal
  authors:
    - name: TODO
      ORCID: 0123-4567-8910-1112
  reference: https://doi.org/{DOI}

check_time: "2023-11-15T14:30:00"
summary: TODO add summary
"""


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / 'codecheck.yml'
    path.write_text(TEMPLATE)
    monkeypatch.chdir(tmp_path)
    return path


def test_fetch_paper_metadata_uses_reference(config):
    with api(CROSSREF, OPENALEX):
        assert Codecheck('codecheck.yml').fetch_paper_metadata()['title'] == 'A manifesto for reproducible science'


def test_fetch_paper_metadata_without_doi(config):
    config.write_text(TEMPLATE.replace(f'https://doi.org/{DOI}', 'https://doi.org/10.1234/example'))
    with pytest.raises(ValueError, match='No DOI'):
        Codecheck('codecheck.yml').fetch_paper_metadata()


def test_update_dry_run(config):
    with api(CROSSREF, OPENALEX):
        md = Codecheck('codecheck.yml').update_config_from_doi().data
    assert f'Metadata from Crossref (https://doi.org/{DOI}, published 2017-01-10)' in md
    assert 'paper.title | FIXME add title | A manifesto for reproducible science | update' in md
    assert 'paper.authors | TODO (ORCID: 0123-4567-8910-1112) | Marcus R. Munafò (ORCID: 0000-0002-4049-993X)' in md
    assert 'paper.reference' not in md  # unchanged
    assert 'Dry run' in md
    assert config.read_text() == TEMPLATE


def test_update_apply_keeps_comments_and_quotes(config):
    with api(CROSSREF, OPENALEX):
        check = Codecheck('codecheck.yml')
        assert 'Updated `codecheck.yml`' in check.update_config_from_doi(apply=True).data
    text = config.read_text()
    assert '# the checked paper' in text and '# from the journal' in text and 'check_time: "2023-11-15T14:30:00"' in text
    written = yaml.safe_load(text)
    assert written['paper']['title'] == 'A manifesto for reproducible science'
    assert written['paper']['authors'] == AUTHORS
    assert written['summary'] == 'TODO add summary'  # other fields unchanged
    assert check.conf == written  # reloaded
    with api(CROSSREF, OPENALEX):
        assert 'already matches' in check.update_config_from_doi().data


def test_update_keeps_real_values_unless_overwrite(config):
    config.write_text(TEMPLATE.replace('FIXME add title', 'My own title').replace(
        'name: TODO\n      ORCID: 0123-4567-8910-1112', 'name: Marcus Munafo'))
    with api(CROSSREF, OPENALEX):
        check = Codecheck('codecheck.yml')
        md = check.update_config_from_doi(apply=True).data
        assert 'paper.title | My own title | A manifesto for reproducible science | kept (overwrite=True to replace)' in md
        assert 'Dry run' not in md and 'Updated' not in md  # nothing to write
        assert 'Updated' in check.update_config_from_doi(apply=True, overwrite=True).data
    assert yaml.safe_load(config.read_text())['paper']['title'] == 'A manifesto for reproducible science'


def test_update_other_doi_and_missing_paper(config):
    config.write_text('certificate: 2025-023\n')
    with api(CROSSREF, OPENALEX):
        check = Codecheck('codecheck.yml')
        md = check.update_config_from_doi(doi=DOI, apply=True).data
    assert 'paper.reference | *missing* |' in md
    assert yaml.safe_load(config.read_text())['paper']['reference'] == f'https://doi.org/{DOI}'


def test_update_escapes_table_cells(config):
    body = {'message': {**CROSSREF['message'], 'title': ['Left | right']}}
    config.write_text(TEMPLATE.replace("    - name: TODO\n      ORCID: 0123-4567-8910-1112\n", "    - TODO\n"))
    with api(body, OPENALEX):
        md = Codecheck('codecheck.yml').update_config_from_doi().data
    assert 'Left \\| right' in md and "paper.authors | ['TODO'] |" in md


@pytest.mark.parametrize('crossref,message', [
    (requests.exceptions.ConnectionError('offline'), 'ConnectionError: offline'),
    (None, f'DoiNotFound: {DOI}'),
])
def test_update_reports_problems(config, crossref, message):
    with api(crossref, None):
        assert f'Could not get the metadata of the paper: {message}' in Codecheck('codecheck.yml').update_config_from_doi().data


def test_update_without_ruamel(config, monkeypatch):
    monkeypatch.setitem(sys.modules, 'ruamel.yaml', None)  # import fails
    with api(CROSSREF, OPENALEX):
        md = Codecheck('codecheck.yml').update_config_from_doi(apply=True).data
    assert 'Not written: `ruamel.yaml` is needed' in md
    assert config.read_text() == TEMPLATE


def test_update_keeps_the_formatting(config):
    long_summary = 'word ' * 40
    config.write_text(TEMPLATE.replace('    - name: TODO\n      ORCID: 0123-4567-8910-1112\n',
                                       '  - name: TODO\n').replace('  authors:\n', '  authors:\n') +
                      f'manifest:\n- file: a.txt\nnote: {long_summary.strip()}\n')
    with api(CROSSREF, OPENALEX):
        Codecheck('codecheck.yml').update_config_from_doi(apply=True)
    text = config.read_text()
    assert '\n- file: a.txt\n' in text  # sequences not re-indented
    assert f'note: {long_summary.strip()}\n' in text  # long lines not folded
    assert '  - name: Marcus R. Munafò\n' in text


def test_update_keeps_a_single_real_author(config):
    config.write_text(TEMPLATE.replace('    - name: TODO\n      ORCID: 0123-4567-8910-1112\n',
                                       '    name: Jane Todorov\n    ORCID: 0000-0002-1825-0097\n'))
    with api(CROSSREF, OPENALEX):
        md = Codecheck('codecheck.yml').update_config_from_doi().data
    assert 'paper.authors | Jane Todorov (ORCID: 0000-0002-1825-0097) |' in md and 'kept (overwrite=True' in md


def test_update_overwrite_keeps_known_orcids(config):
    config.write_text(TEMPLATE.replace('    - name: TODO\n      ORCID: 0123-4567-8910-1112\n',
                                       '    - name: M. Munafo\n    - name: B. Nosek\n    - name: Consortium\n'
                                       '    - name: Anna Other\n      ORCID: 0000-0002-1825-0097\n'))
    with api(CROSSREF, OPENALEX):
        Codecheck('codecheck.yml').update_config_from_doi(apply=True, overwrite=True)
    assert yaml.safe_load(config.read_text())['paper']['authors'][3] == {'name': 'Anna Other',
                                                                         'ORCID': '0000-0002-1825-0097'}


@pytest.mark.parametrize('content', ['', '# only a comment\n'])
def test_update_empty_config(config, content):
    config.write_text(content)
    with api(CROSSREF, OPENALEX):
        md = Codecheck('codecheck.yml').update_config_from_doi(doi=DOI, apply=True).data
    assert 'Updated' in md
    assert yaml.safe_load(config.read_text())['paper']['title'] == 'A manifesto for reproducible science'


def test_update_write_error_keeps_the_file(config, monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError('read-only')
    monkeypatch.setattr(doi_metadata, 'write_paper_fields', fail)
    with api(CROSSREF, OPENALEX):
        assert 'Not written: PermissionError: read-only' in Codecheck('codecheck.yml').update_config_from_doi(
            apply=True).data
    assert config.read_text() == TEMPLATE


def test_update_duplicate_keys_keep_the_file(config):
    config.write_text(TEMPLATE + 'summary: again\n')
    with api(CROSSREF, OPENALEX):
        assert 'Not written: DuplicateKeyError' in Codecheck('codecheck.yml').update_config_from_doi(apply=True).data
    assert config.read_text() == TEMPLATE + 'summary: again\n'
