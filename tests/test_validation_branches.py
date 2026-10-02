"""
Tests for the error branches of the validator (wrong types, empty sections, report formatting)
"""

import pytest
import yaml

from validation import CodecheckValidator, ValidationIssue


def make(tmp_path, config):
    """Validator for a config given as dict (dumped to YAML) or as text; the YAML is already loaded."""
    path = tmp_path / 'codecheck.yml'
    path.write_text(config if isinstance(config, str) else yaml.dump(config))
    validator = CodecheckValidator(str(path))
    assert validator.validate_yaml_syntax()
    return validator


def issues(validator, level=None):
    return {(i.level, i.field) for i in validator.issues if level is None or i.level == level}


def test_empty_yaml_file(tmp_path):
    path = tmp_path / 'codecheck.yml'
    path.write_text('')
    validator = CodecheckValidator(str(path))
    assert validator.validate_yaml_syntax() is False
    assert ('error', 'syntax') in issues(validator)


def test_field_completeness_without_config():
    assert CodecheckValidator('nonexistent.yml').validate_field_completeness() is False


@pytest.mark.parametrize('field,value', [('manifest', []), ('paper', {}), ('summary', '')])
def test_empty_values_count_as_missing(tmp_path, field, value):
    validator = make(tmp_path, {field: value})
    assert validator.validate_field_completeness() is False
    assert ('error', field) in issues(validator)


def test_is_placeholder_ignores_non_strings(tmp_path):
    validator = make(tmp_path, {'a': 1})
    assert validator.is_placeholder(123) is False
    assert validator.is_placeholder(None) is False
    assert validator.is_placeholder('FIXME later') is True


def test_certificate_must_be_string(tmp_path):
    validator = make(tmp_path, {'certificate': 2023001})
    assert validator.validate_certificate_id() is False
    assert ('error', 'certificate') in issues(validator)


def test_report_must_be_string(tmp_path):
    validator = make(tmp_path, {'report': 12345})
    assert validator.validate_report_doi() is False
    assert ('error', 'report') in issues(validator)


def test_report_must_be_url_or_doi(tmp_path):
    validator = make(tmp_path, {'report': 'just some text'})
    assert validator.validate_report_doi() is False
    assert ('warning', 'report') in issues(validator)


@pytest.mark.parametrize('report', ['https://doi.org/10.5281/zenodo.1234567', 'doi:10.5281/zenodo.1234567',
                                    '10.5281/zenodo.1234567'])
def test_valid_report_forms(tmp_path, report):
    assert make(tmp_path, {'report': report}).validate_report_doi() is True


def test_codechecker_and_author_orcids_are_checked(tmp_path):
    validator = make(tmp_path, {
        'codechecker': [{'name': 'A', 'ORCID': 'nope'}, {'name': 'B', 'ORCID': '0000-0002-0024-5046'}],
        'paper': {'authors': [{'name': 'C', 'ORCID': '1234'}]},
    })
    assert validator.validate_orcids() is False
    assert ('error', 'codechecker.ORCID') in issues(validator)
    assert ('error', 'paper.authors[0].ORCID') in issues(validator)


def test_check_time_must_be_string(tmp_path):
    validator = make(tmp_path, "check_time: 2023-11-15T14:30:00\n")  # YAML turns this into a datetime
    assert validator.validate_check_time() is False
    assert ('error', 'check_time') in issues(validator)


def test_paper_missing_is_fine_here(tmp_path):
    assert make(tmp_path, {'paper': {}}).validate_paper_structure() is True


def test_paper_must_be_dictionary(tmp_path):
    validator = make(tmp_path, {'paper': 'a title'})
    assert validator.validate_paper_structure() is False
    assert ('error', 'paper') in issues(validator)


def test_authors_must_be_list(tmp_path):
    validator = make(tmp_path, {'paper': {'title': 't', 'reference': 'r', 'authors': 'Jane Doe'}})
    assert validator.validate_paper_structure() is False
    assert ('error', 'paper.authors') in issues(validator)


def test_empty_authors_list_warns(tmp_path):
    validator = make(tmp_path, {'paper': {'title': 't', 'reference': 'r', 'authors': []}})
    validator.validate_paper_structure()
    assert ('warning', 'paper.authors') in issues(validator)


def test_author_entries_must_be_dictionaries_with_name(tmp_path):
    validator = make(tmp_path, {'paper': {'title': 't', 'reference': 'r', 'authors': ['Jane', {'ORCID': 'x'}]}})
    assert validator.validate_paper_structure() is False
    assert ('error', 'paper.authors[0]') in issues(validator)
    assert ('error', 'paper.authors[1].name') in issues(validator)


def test_codechecker_must_be_dict_or_list(tmp_path):
    validator = make(tmp_path, {'codechecker': 'Jane Doe'})
    assert validator.validate_codechecker_structure() is False
    assert ('error', 'codechecker') in issues(validator)


def test_codechecker_list_entries_must_be_dictionaries(tmp_path):
    validator = make(tmp_path, {'codechecker': ['Jane', {'name': 'John'}]})
    assert validator.validate_codechecker_structure() is False
    assert ('error', 'codechecker[0]') in issues(validator)
    assert ('warning', 'codechecker[1].ORCID') in issues(validator)


def test_missing_codechecker_is_left_to_mandatory_check(tmp_path):
    assert make(tmp_path, {'x': 1}).validate_codechecker_structure() is False


def test_manifest_must_be_list(tmp_path):
    validator = make(tmp_path, {'manifest': 'a.csv'})
    assert validator.validate_manifest_structure() is False
    assert ('error', 'manifest') in issues(validator)


def test_missing_manifest_is_left_to_mandatory_check(tmp_path):
    assert make(tmp_path, {'x': 1}).validate_manifest_structure() is False


def test_manifest_entries_need_file(tmp_path):
    validator = make(tmp_path, {'manifest': ['a.csv', {'comment': 'no file'}, {'file': 'ok.csv'}]})
    assert validator.validate_manifest_structure() is False
    assert ('error', 'manifest[0]') in issues(validator)
    assert ('error', 'manifest[1].file') in issues(validator)
    assert ('error', 'manifest[2].file') not in issues(validator)


def test_manifest_files_without_manifest(tmp_path):
    assert make(tmp_path, {'x': 1}).validate_manifest_files() is False


def test_manifest_files_outputs_dir_missing(tmp_path):
    validator = make(tmp_path, {'manifest': [{'file': 'a.csv'}]})
    assert validator.validate_manifest_files() is False
    assert any('.codecheck/outputs' in i.suggestion for i in validator.issues)


def test_manifest_files_found_in_dot_codecheck_outputs(tmp_path):
    """Regression test: outputs are searched in `.codecheck/outputs/` like the README says."""
    (tmp_path / '.codecheck' / 'outputs').mkdir(parents=True)
    (tmp_path / '.codecheck' / 'outputs' / 'a.csv').write_text('x\n1\n')
    validator = make(tmp_path, {'manifest': [{'file': 'a.csv'}]})
    assert validator.validate_manifest_files() is True
    assert not validator.issues


def test_manifest_files_missing_are_listed_and_truncated(tmp_path):
    (tmp_path / '.codecheck' / 'outputs').mkdir(parents=True)
    names = [f'f{i}.csv' for i in range(7)]
    validator = make(tmp_path, {'manifest': [{'file': 'present.csv'}, 'not a dict', {'comment': 'no file'}]
                                + [{'file': n} for n in names]})
    (tmp_path / '.codecheck' / 'outputs' / 'present.csv').write_text('a\n1\n')
    assert validator.validate_manifest_files() is False
    message = validator.issues[0].message
    assert 'Missing 7 file(s)' in message and 'f0.csv' in message and 'f4.csv' in message
    assert 'f5.csv' not in message and message.endswith('...')


def test_register_check_skips_non_string_certificate(tmp_path):
    assert make(tmp_path, {'certificate': 2023001}).validate_register_issue() is True


def test_report_formats(tmp_path):
    validator = make(tmp_path, {'x': 1})
    assert validator.format_report() == "## ✓ All validations passed!"
    assert validator.format_report(markdown=False) == "✓ All validations passed!"

    validator.issues = [
        ValidationIssue('error', 'e', 'an error', 'fix it'),
        ValidationIssue('warning', 'w', 'a warning'),
        ValidationIssue('info', 'i', 'some info', 'maybe'),
    ]
    markdown = validator.format_report(markdown=True)
    assert "## ❌ Errors (1)" in markdown and "*Suggestion*: fix it" in markdown
    assert "## ⚠️  Warnings (1)" in markdown and "## ℹ️  Information (1)" in markdown
    text = validator.format_report(markdown=False)
    assert "ERRORS (1):" in text and "→ fix it" in text
    assert "WARNINGS (1):" in text and "INFORMATION (1):" in text and "[i] some info" in text
    assert str(validator.issues[0]) == "[ERROR] e: an error\n  → Suggestion: fix it"


def test_validate_all_stops_after_syntax_error(tmp_path):
    path = tmp_path / 'codecheck.yml'
    path.write_text('a: [unclosed')
    passed, found = CodecheckValidator(str(path)).validate_all(check_register=False)
    assert passed is False and len(found) == 1


def test_validate_all_strict_fails_on_warnings(tmp_path):
    config = {
        'version': 'https://codecheck.org.uk/spec/config/1.0/',
        'certificate': '2023-001',
        'report': 'https://doi.org/10.5281/zenodo.1234567',
        'paper': {'title': 'T', 'reference': 'https://doi.org/10.1234/x',
                  'authors': [{'name': 'A', 'ORCID': '0000-0002-0024-5046'}]},
        'repository': 'https://github.com/octocat/hello-world',
        'check_time': '2023-11-15T14:30:00',
        'summary': 'All reproduced.',
        'codechecker': {'name': 'A'},  # no ORCID: a warning, not an error
        'manifest': [{'file': 'a.csv'}],
    }
    (tmp_path / '.codecheck' / 'outputs').mkdir(parents=True)
    (tmp_path / '.codecheck' / 'outputs' / 'a.csv').write_text('a\n1\n')
    path = tmp_path / 'codecheck.yml'
    path.write_text(yaml.dump(config))
    passed, found = CodecheckValidator(str(path)).validate_all(check_register=False, strict=False)
    assert passed is True, [str(i) for i in found if i.level == 'error']
    assert ('warning', 'codechecker.ORCID') in {(i.level, i.field) for i in found}
    passed, _ = CodecheckValidator(str(path)).validate_all(check_register=False, strict=True)
    assert passed is False
