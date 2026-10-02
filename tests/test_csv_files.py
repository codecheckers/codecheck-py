"""
Tests for Codecheck.csv_files() with large/wide CSV files (issue #16)
"""
import sys
from pathlib import Path

import pytest
import yaml

# Add .codecheck to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / '.codecheck'))
from codecheck import Codecheck


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Workspace with a wide CSV (2000 cols), a long CSV (5000 rows) and a small one."""
    codecheck_dir = tmp_path / 'codecheck'
    outputs = codecheck_dir / 'outputs'
    outputs.mkdir(parents=True)

    wide = ",".join(f"c{i}" for i in range(2000)) + "\n"
    wide += "\n".join(",".join(str(r * i) for i in range(2000)) for r in range(20))
    (outputs / 'wide.csv').write_text(wide)
    (outputs / 'long.csv').write_text("a,b\n" + "\n".join(f"{i},{i * 2}" for i in range(5000)))
    (outputs / 'small.csv').write_text("a,b\n1,2\n3,4\n")

    (tmp_path / 'codecheck.yml').write_text(yaml.dump({
        'manifest': [
            {'file': 'wide.csv', 'comment': 'wide'},
            {'file': 'long.csv', 'comment': 'long'},
            {'file': 'small.csv', 'comment': 'small'},
        ]
    }))
    monkeypatch.chdir(codecheck_dir)
    return codecheck_dir


def test_wide_csv_output_is_bounded(workspace):
    md = Codecheck().csv_files(max_cols=10, max_rows=5).data
    assert md.count("| c") <= 10  # at most 10 columns of the wide file are summarised
    assert "c10 " not in md
    assert len(md) < 5000


def test_header_none_and_index_col_false(workspace):
    md = Codecheck().csv_files(index_col=False, header=None, max_cols=50, max_rows=50).data
    assert len(md) < 20000


def test_file_with_fewer_columns_than_max_cols(workspace):
    md = Codecheck().csv_files(max_cols=50).data
    assert "small.csv" in md


def test_row_limit_applies(workspace):
    md = Codecheck().csv_files(max_rows=7).data
    long_section = md.split("### `long.csv`")[1].split("### `small.csv`")[0]
    row_a = [l for l in long_section.splitlines() if l.startswith("| a ")][0]
    assert row_a.split("|")[2].strip() == "7"  # `count` column of describe()


def test_nrows_in_kwds_does_not_raise(workspace):
    """Passing nrows via **kwds (as users did in #16) used to raise a TypeError."""
    md = Codecheck().csv_files(nrows=3).data
    assert "long.csv" in md
