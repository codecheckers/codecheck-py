"""
The outputs directory can be `.codecheck/outputs/` or `codecheck/outputs/`: validation, manifest processing and the
Codecheck class have to work with both.
"""

import pytest
import yaml

from codecheck import Codecheck
from manifest import ManifestProcessor, find_outputs_dir
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
