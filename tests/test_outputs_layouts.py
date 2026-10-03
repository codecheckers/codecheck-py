"""
The outputs directory can be `.codecheck/outputs/` or `codecheck/outputs/`: validation, manifest processing and the
Codecheck class have to work with both.
"""

import shutil

import pytest
import yaml

from codecheck import Codecheck
from manifest import ManifestProcessor, find_outputs_dir, output_path
from validation import CodecheckValidator

LAYOUTS = ['.codecheck', 'codecheck']
MANIFEST = [{'file': 'data/a.csv', 'comment': 'table'}]


@pytest.fixture(params=LAYOUTS)
def layout(request, tmp_path, monkeypatch):
    """Repository with the reproduced file in `<layout>/outputs/data/a.csv` and the original in `data/a.csv`."""
    name = request.param
    (tmp_path / name / 'outputs' / 'data').mkdir(parents=True)
    (tmp_path / name / 'outputs' / 'data' / 'a.csv').write_text('x,y\n1,2\n3,4\n')
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'a.csv').write_text('x,y\n1,2\n')
    (tmp_path / 'codecheck.yml').write_text(yaml.dump({'manifest': MANIFEST}))
    monkeypatch.chdir(tmp_path / name)
    return tmp_path, name


def test_find_outputs_dir(tmp_path):
    assert find_outputs_dir(tmp_path) == tmp_path / '.codecheck' / 'outputs'  # neither exists: default
    (tmp_path / 'codecheck' / 'outputs').mkdir(parents=True)
    assert find_outputs_dir(tmp_path) == tmp_path / 'codecheck' / 'outputs'
    (tmp_path / '.codecheck' / 'outputs').mkdir(parents=True)
    assert find_outputs_dir(tmp_path) == tmp_path / '.codecheck' / 'outputs'  # both exist: .codecheck first


def test_layout_is_found_before_outputs_dir_exists(tmp_path):
    """`codecheck/` without `outputs/` (not created yet): files are copied there, not into a new `.codecheck/`."""
    (tmp_path / 'codecheck').mkdir()
    assert find_outputs_dir(tmp_path) == tmp_path / 'codecheck' / 'outputs'
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'a.csv').write_text('x\n1\n')
    ManifestProcessor([{'file': 'data/a.csv'}], tmp_path).copy_manifest_files()
    assert (tmp_path / 'codecheck' / 'outputs' / 'data' / 'a.csv').exists()
    assert not (tmp_path / '.codecheck').exists()


def test_directory_without_outputs_is_not_used(tmp_path):
    (tmp_path / '.codecheck').mkdir()  # e.g. only the template files, outputs/ is in codecheck/
    (tmp_path / 'codecheck' / 'outputs').mkdir(parents=True)
    assert find_outputs_dir(tmp_path) == tmp_path / 'codecheck' / 'outputs'


def test_validator_finds_outputs(layout):
    root, name = layout
    validator = CodecheckValidator(str(root / 'codecheck.yml'))
    assert validator.validate_yaml_syntax()
    assert validator.validate_manifest_files() is True and not validator.issues


def test_validator_reports_missing_file_with_used_directory(layout):
    root, name = layout
    (root / name / 'outputs' / 'data' / 'a.csv').unlink()
    validator = CodecheckValidator(str(root / 'codecheck.yml'))
    validator.validate_yaml_syntax()
    assert validator.validate_manifest_files() is False
    assert f'{name}/outputs/' in validator.issues[0].suggestion


def test_validator_without_any_outputs_dir(tmp_path):
    (tmp_path / 'codecheck.yml').write_text(yaml.dump({'manifest': MANIFEST}))
    validator = CodecheckValidator(str(tmp_path / 'codecheck.yml'))
    validator.validate_yaml_syntax()
    assert validator.validate_manifest_files() is False
    assert '.codecheck/outputs/ (or codecheck/outputs/)' in validator.issues[0].suggestion


def test_manifest_processor(layout):
    root, name = layout
    processor = ManifestProcessor(MANIFEST, root)
    assert processor.outputs_dir == root / name / 'outputs'
    assert processor.validate_output_files_exist() == (True, [])
    assert processor.get_file_sizes() == {'data/a.csv': 12}
    assert processor.get_manifest_summary()['total_size'] == 12
    assert processor.compare_sizes() == []


def test_manifest_processor_copies_into_existing_layout(layout):
    root, name = layout
    (root / name / 'outputs' / 'data' / 'a.csv').unlink()
    processor = ManifestProcessor(MANIFEST, root)
    assert len(processor.copy_manifest_files()) == 1
    assert (root / name / 'outputs' / 'data' / 'a.csv').read_text() == 'x,y\n1,2\n'
    other = 'codecheck' if name == '.codecheck' else '.codecheck'
    assert not (root / other).exists()


def test_codecheck_class(layout):
    root, name = layout
    check = Codecheck()
    assert check.validate_manifest_files() == (True, [])
    assert 'Total size**: 12 bytes' in check.manifest_summary().data
    assert '`a.csv` | table | 12' in check.files().data
    assert 'Lines | 3' in check.manifest_files().data  # file info is read from outputs/ (cwd is the layout dir)
    passed, issues = check.validate(check_register=False)
    assert not [i for i in issues if i.field == 'manifest' and i.level == 'error' and 'outputs' in i.message]


def test_codecheck_class_from_repository_root(layout, monkeypatch):
    """E.g. on Binder: the notebook runs in the repository root, files and links still point into `<layout>/outputs`."""
    root, name = layout
    (root / name / 'outputs' / 'b.png').write_bytes(b'')
    (root / 'codecheck.yml').write_text(yaml.dump({'manifest': MANIFEST + [{'file': 'b.png'}]}))
    monkeypatch.chdir(root)
    check = Codecheck('codecheck.yml')
    assert check.outputs_dir == (root / name / 'outputs').resolve()
    assert check.outputs_link == f'{name}/outputs'
    assert '`a.csv` | table | 12' in check.files().data
    md = check.manifest_files().data
    assert 'Lines | 3' in md
    assert f'(<{name}/outputs/b.png>)' in md


def test_codecheck_class_prefers_outputs_in_working_directory(layout, monkeypatch, tmp_path_factory):
    """The notebook runs in the template directory: its `outputs/` is used, whatever its name or other layouts."""
    root, _ = layout
    other = tmp_path_factory.mktemp('cert')
    (other / 'outputs' / 'data').mkdir(parents=True)
    (other / 'outputs' / 'data' / 'a.csv').write_text('x\n1\n')
    monkeypatch.chdir(other)
    check = Codecheck(str(root / 'codecheck.yml'))
    assert check.outputs_link == 'outputs'
    assert '`a.csv` | table | 4' in check.files().data


def test_symlinked_outputs_dir_keeps_link(layout, monkeypatch, tmp_path_factory):
    """`outputs/` may be a symlink to another disk: links stay inside the template directory (Typst root)."""
    root, name = layout
    target = tmp_path_factory.mktemp('disk') / 'outputs'
    (root / name / 'outputs').rename(target)
    (root / name / 'outputs').symlink_to(target)
    check = Codecheck()
    assert check.outputs_link == 'outputs'
    assert '`a.csv` | table | 12' in check.files().data


def test_symlinked_file_in_outputs(layout):
    """A file in `outputs/` may be a symlink to the original file in the repository."""
    root, name = layout
    (root / name / 'outputs' / 'data' / 'a.csv').unlink()
    (root / name / 'outputs' / 'data' / 'a.csv').symlink_to(root / 'data' / 'a.csv')
    check = Codecheck()
    assert '`a.csv` | table | 8' in check.files().data
    assert 'Lines | 2' in check.manifest_files().data


def test_missing_file_message_uses_link(layout, monkeypatch):
    root, name = layout
    (root / name / 'outputs' / 'data' / 'a.csv').unlink()
    assert '`outputs/data/a.csv` does not exist' in Codecheck().manifest_files().data
    monkeypatch.chdir(root)
    md = Codecheck('codecheck.yml').manifest_files().data
    assert f'`{name}/outputs/data/a.csv` does not exist' in md
    assert '`a.csv` | table | **missing**' in Codecheck('codecheck.yml').files().data


def test_output_path(tmp_path):
    (tmp_path / 'outputs').mkdir()
    assert output_path(tmp_path / 'outputs', 'a/b.csv') == (tmp_path / 'outputs' / 'a' / 'b.csv').resolve()
    assert output_path(tmp_path / 'outputs', '../x.csv') is None
    assert output_path(tmp_path / 'outputs', '/etc/passwd') is None
    assert output_path(tmp_path / 'outputs', 'v1..2.txt') == tmp_path / 'outputs' / 'v1..2.txt'


def test_manifest_processor_uses_given_outputs_dir(tmp_path):
    assert ManifestProcessor([], tmp_path, tmp_path / 'elsewhere').outputs_dir == tmp_path / 'elsewhere'


def test_validate_paths_allows_dots_in_names(tmp_path):
    assert ManifestProcessor([{'file': 'v1..2.txt'}, {'file': '../x'}], tmp_path).validate_paths() == (False, ['../x'])


def test_latex_figures_tolerates_entries_without_comment(layout):
    root, name = layout
    (root / 'codecheck.yml').write_text(yaml.dump({'manifest': [{'file': 'f.pdf'}, 'bad', {'comment': 'x'}]}))
    assert '](<outputs/f.pdf>)' in Codecheck().latex_figures().data


def test_paths_outside_outputs(layout):
    """`../` paths are treated alike everywhere: not found in outputs/, never copied, reported by the validator."""
    root, name = layout
    escape = '../../data/a.csv'  # exists as <root>/data/a.csv, but is not inside outputs/
    (root / 'codecheck.yml').write_text(yaml.dump({'manifest': [{'file': escape}]}))
    processor = ManifestProcessor([{'file': escape}], root)
    assert processor.validate_output_files_exist() == (False, [escape])
    assert processor.get_file_sizes() == {}
    assert processor.copy_manifest_files(source_dir=root / name) == []  # <root>/name/../../data is outside the source
    validator = CodecheckValidator(str(root / 'codecheck.yml'))
    validator.validate_yaml_syntax()
    assert validator.validate_manifest_files() is False
    assert [i.message for i in validator.issues] == [f'Manifest path(s) outside of the outputs directory: {escape}']


def test_copy_skips_directories(layout):
    root, name = layout
    processor = ManifestProcessor([{'file': 'data'}], root)
    assert processor.copy_manifest_files() == []


def test_source_files_outside_base_count_as_missing(layout):
    root, name = layout
    processor = ManifestProcessor([{'file': '../data/a.csv'}], root / name)  # <root>/data/a.csv exists
    assert processor.validate_files_exist() == (False, ['../data/a.csv'])
    assert ManifestProcessor(MANIFEST, root).validate_files_exist() == (True, [])


def test_copy_into_symlinked_directory(layout):
    """outputs/data may link to the original data/: copying neither fails (same file) nor writes outside outputs/."""
    root, name = layout
    shutil.rmtree(root / name / 'outputs' / 'data')
    (root / name / 'outputs' / 'data').symlink_to(root / 'data')
    processor = ManifestProcessor(MANIFEST, root)
    assert processor.validate_output_files_exist() == (True, [])
    assert processor.copy_manifest_files() == []  # same file
    (root / 'other' / 'data').mkdir(parents=True)
    (root / 'other' / 'data' / 'a.csv').write_text('other\n')
    assert processor.copy_manifest_files(source_dir=root / 'other') == []  # would write through the link into data/
    assert (root / 'data' / 'a.csv').read_text() == 'x,y\n1,2\n'


def test_directories_are_not_manifest_files(layout):
    root, name = layout
    (root / 'codecheck.yml').write_text(yaml.dump({'manifest': [{'file': '.'}, {'file': 'data'}]}))
    processor = ManifestProcessor([{'file': '.'}, {'file': 'data'}], root)
    assert processor.validate_output_files_exist() == (False, ['.', 'data'])
    assert processor.get_file_sizes() == {}
    validator = CodecheckValidator(str(root / 'codecheck.yml'))
    validator.validate_yaml_syntax()
    assert validator.validate_manifest_files() is False


def test_outside_paths_reported_without_outputs_dir(tmp_path):
    (tmp_path / 'codecheck.yml').write_text(yaml.dump({'manifest': [{'file': '../secret.csv'}]}))
    validator = CodecheckValidator(str(tmp_path / 'codecheck.yml'))
    validator.validate_yaml_syntax()
    assert validator.validate_manifest_files() is False
    messages = [i.message for i in validator.issues]
    assert any('Outputs directory does not exist' in m for m in messages)
    assert 'Manifest path(s) outside of the outputs directory: ../secret.csv' in messages


def test_non_string_file_paths(layout):
    """`file: 2024` in YAML is an int: reported by the structure check, no crash elsewhere."""
    root, name = layout
    (root / 'codecheck.yml').write_text('manifest:\n  - file: 2024\n')
    validator = CodecheckValidator(str(root / 'codecheck.yml'))
    validator.validate_yaml_syntax()
    assert validator.validate_manifest_structure() is False
    assert validator.validate_manifest_files() is False  # missing, no TypeError
    processor = ManifestProcessor([{'file': 2024}], root)
    assert processor.validate_output_files_exist() == (False, [2024])
    assert processor.get_manifest_summary()['total_files'] == 1
    assert '2024' in Codecheck().manifest_files().data


def test_output_file_status_is_shared_by_validator_and_processor(layout):
    root, name = layout
    manifest = MANIFEST + [{'file': '../../data/a.csv'}, {'file': 'missing.csv'}, {'file': 'data'}]
    (root / 'codecheck.yml').write_text(yaml.dump({'manifest': manifest}))
    processor = ManifestProcessor(manifest, root)
    assert processor.output_file_status() == {'outside': ['../../data/a.csv'], 'missing': ['missing.csv', 'data']}
    assert processor.validate_output_files_exist() == (False, ['../../data/a.csv', 'missing.csv', 'data'])
    validator = CodecheckValidator(str(root / 'codecheck.yml'))
    validator.validate_yaml_syntax()
    assert validator.validate_manifest_files() is False
    assert [i.message for i in validator.issues] == [
        'Manifest path(s) outside of the outputs directory: ../../data/a.csv',
        'Missing 2 file(s) in outputs/: missing.csv, data']
