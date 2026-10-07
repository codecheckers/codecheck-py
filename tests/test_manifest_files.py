"""
Tests for Codecheck.manifest_files() (renderers by file type) and Codecheck.git_info()
"""
import json
import shutil

import pytest
import yaml

from codecheck import Codecheck

from .conftest import BASE_IMAGE, git_commit_all, requires_git, section


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    codecheck_dir = tmp_path / 'codecheck'
    outputs = codecheck_dir / 'outputs'
    (outputs / 'sub').mkdir(parents=True)

    (outputs / 'data.csv').write_text('a,b\n1,2\n3,4\n')
    (outputs / 'data.tsv').write_text('x\ty\n5\t6\n7\t8\n')
    (outputs / 'long.log').write_text("\n".join(f"line {i}" for i in range(500)) + "\n")
    (outputs / 'wide.txt').write_text("x" * 5000 + "\n~~~~\nafter fence\n")
    (outputs / 'result.json').write_text(json.dumps({'k': list(range(100))}))
    (outputs / 'broken.json').write_text('{not json')
    (outputs / 'sub' / 'plot.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (outputs / 'archive.zip').write_bytes(b'PK\x05\x06' + b'\x00' * 18)
    (outputs / 'figure.eps').write_text('%!PS-Adobe-3.0 EPSF-3.0')
    shutil.copy2(BASE_IMAGE, outputs / 'plot.png')

    import pandas as pd
    pd.DataFrame({'p': [1, 2], 'q': ['u', 'v']}).to_excel(outputs / 'table.xlsx', index=False)
    (outputs / 'bad.xlsx').write_text('this is not an excel file')

    files = ['data.csv', 'data.tsv', 'long.log', 'wide.txt', 'result.json', 'broken.json', 'sub/plot.svg',
             'archive.zip', 'figure.eps', 'plot.png', 'table.xlsx', 'bad.xlsx', 'does_not_exist.csv']
    (tmp_path / 'codecheck.yml').write_text(yaml.dump({
        'repository': 'https://github.com/example/repo',
        'manifest': [{'file': f, 'comment': f'comment {f}'} for f in files],
    }))
    monkeypatch.chdir(codecheck_dir)
    return codecheck_dir


def test_every_file_gets_a_section_and_nothing_raises(workspace):
    md = Codecheck().manifest_files().data
    for name in ['data.csv', 'data.tsv', 'long.log', 'plot.png', 'archive.zip', 'does_not_exist.csv']:
        assert f"### `{name}`" in md


def test_file_info_for_every_type(workspace):
    md = Codecheck().manifest_files(file_info=True).data
    for name in ['data.csv', 'long.log', 'plot.png', 'archive.zip', 'figure.eps', 'sub/plot.svg']:
        sec = section(md, name)
        assert "SHA-256 | `" in sec and "Size (b) |" in sec and "Modified |" in sec


def test_file_info_is_not_shown_by_default(workspace):
    md = Codecheck().manifest_files().data
    assert "Item | Value" not in md and "SHA-256" not in md
    sec = section(md, 'long.log')
    assert sec.startswith("\nComment: *comment long.log*") and "~~~" in sec


def test_missing_file_is_marked_not_raised(workspace):
    sec = section(Codecheck().manifest_files().data, 'does_not_exist.csv')
    assert "File missing" in sec


def test_files_table_marks_missing_file(workspace):
    md = Codecheck().files().data
    last_row = md.strip().splitlines()[-1]
    assert last_row.startswith("`does_not_exist.csv`") and last_row.endswith("**missing**")


def test_tsv_is_split_into_columns(workspace):
    sec = section(Codecheck().manifest_files(file_info=True).data, 'data.tsv')
    assert "Columns | 2" in sec and "|   x |   y |" in sec and "|   7 |   8 |" in sec


def test_excel_summary(workspace):
    sec = section(Codecheck().manifest_files(file_info=True).data, 'table.xlsx')
    assert "Sheets | `Sheet1`" in sec and "Columns (first sheet) | 2" in sec and "Complete table" in sec


def test_broken_excel_reports_error_box(workspace):
    sec = section(Codecheck().manifest_files().data, 'bad.xlsx')
    assert "Could not display this file" in sec


def test_text_is_truncated_with_note(workspace):
    sec = section(Codecheck().manifest_files(max_lines=10, file_info=True).data, 'long.log')
    assert "line 9" in sec and "line 10\n" not in sec
    assert "490 more lines omitted" in sec and "Lines | 500" in sec


def test_long_lines_are_cut_and_fence_is_safe(workspace):
    sec = section(Codecheck().manifest_files().data, 'wide.txt')
    assert "x" * 201 not in sec and "[...]" in sec
    assert "~~~~~\n" in sec  # fence is longer than the "~~~~" inside the file


def test_json_is_pretty_printed_and_truncated(workspace):
    sec = section(Codecheck().manifest_files(max_lines=5).data, 'result.json')
    assert '"k": [' in sec and "more lines omitted" in sec


def test_invalid_json_falls_back_to_text(workspace):
    sec = section(Codecheck().manifest_files().data, 'broken.json')
    assert "{not json" in sec


def test_images_are_embedded(workspace):
    md = Codecheck().manifest_files(file_info=True).data
    assert "![comment plot.png](<outputs/plot.png>)" in section(md, 'plot.png')
    assert "Dimensions | 24 x 16 px" in section(md, 'plot.png')
    assert "(<outputs/sub/plot.svg>)" in section(md, 'sub/plot.svg')


def test_unsupported_types_only_show_info(workspace):
    md = Codecheck().manifest_files().data
    assert "No preview available for this file type" in section(md, 'archive.zip')
    assert "Typst cannot include EPS" in section(md, 'figure.eps')


def test_output_size_is_bounded(workspace):
    big = workspace / 'outputs' / 'big.log'
    big.write_text("some log line\n" * 200000)
    entry_file = workspace.parent / 'codecheck.yml'
    conf = yaml.safe_load(entry_file.read_text())
    conf['manifest'] = [{'file': 'big.log'}]
    entry_file.write_text(yaml.dump(conf))
    assert len(Codecheck().manifest_files(max_lines=50).data) < 5000


def test_csv_files_only_shows_csv(workspace):
    md = Codecheck().csv_files().data
    assert "### `data.csv`" in md and "data.tsv" not in md and "plot.png" not in md


@requires_git
def test_git_info_in_repository(workspace):
    repo = workspace.parent
    sha = git_commit_all(repo, 'codecheck.yml')

    assert f"based on the commit `{sha}`" in Codecheck().git_info().data
    assert "uncommitted" not in Codecheck().git_info().data

    # the codechecker's own files do not count as changes of the checked code
    (repo / 'codecheck.yml').write_text((repo / 'codecheck.yml').read_text() + "\n# changed\n")
    assert "uncommitted" not in Codecheck().git_info().data

    (repo / 'analysis.py').write_text('print(1)\n')
    git_commit_all(repo, 'analysis.py')
    (repo / 'analysis.py').write_text('print(2)\n')
    assert "uncommitted changes" in Codecheck().git_info().data


def test_git_info_without_repository(workspace, monkeypatch):
    # a directory outside of any git repository
    monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(workspace.parent.parent))
    assert "not available" in Codecheck().git_info().data


def test_malformed_manifest_entries_do_not_raise(workspace):
    conf = workspace.parent / 'codecheck.yml'
    conf.write_text(yaml.dump({'manifest': [
        'a string', {'comment': 'no file'}, {'file': ''},
        {'file': 'data.csv', 'comment': 42},          # comment that is not a string
        {'file': 'data.tsv', 'comment': None},
    ]}))
    check = Codecheck()
    md = check.manifest_files().data
    assert "### `data.csv`" in md and "Comment: *42*" in md and "### `data.tsv`" in md
    assert md.count("### `") == 2
    rows = [line for line in check.files().data.splitlines() if line.startswith("`")]
    assert len(rows) == 2 and rows[0].startswith("`data.csv` | 42 |")


def test_path_outside_of_outputs_is_not_read(workspace):
    (workspace.parent / 'secret.txt').write_text('top secret')
    (workspace / 'outputs' / '..' / 'also_secret.txt').write_text('top secret')
    conf = workspace.parent / 'codecheck.yml'
    conf.write_text(yaml.dump({'manifest': [{'file': '../../secret.txt'}, {'file': '../also_secret.txt'},
                                            {'file': str(workspace.parent / 'secret.txt')}]}))
    md = Codecheck().manifest_files().data
    assert "top secret" not in md
    assert md.count("is not inside the `outputs/` directory") == 3


def test_user_nrows_and_delimiter_are_honoured(workspace):
    check = Codecheck()
    assert "Columns (first sheet) | 2" in section(check.manifest_files(nrows=1, head=5, file_info=True).data, 'table.xlsx')
    (workspace / 'outputs' / 'semi.csv').write_text('a;b\n1;2\n')
    conf = workspace.parent / 'codecheck.yml'
    conf.write_text(yaml.dump({'manifest': [{'file': 'semi.csv'}]}))
    assert "|   a |   b |" in Codecheck().manifest_files(delimiter=";").data


def test_excel_file_is_closed(workspace, monkeypatch):
    import pandas as pd
    closed = []
    original = pd.ExcelFile.close
    monkeypatch.setattr(pd.ExcelFile, 'close', lambda self: (closed.append(1), original(self))[1])
    Codecheck().manifest_files()
    assert closed
