"""
Tests for Codecheck.csv_files() with large/wide CSV files (issue #16)
"""

import pytest
import yaml

from codecheck import Codecheck
from .conftest import section


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
    long_section = section(md, 'long.csv')
    row_a = [l for l in long_section.splitlines() if l.startswith("| a ")][0]
    assert row_a.split("|")[2].strip() == "7"  # `count` column of describe()


def test_nrows_in_kwds_does_not_raise(workspace):
    """Passing nrows via **kwds (as users did in #16) used to raise a TypeError."""
    md = Codecheck().csv_files(nrows=3).data
    assert "long.csv" in md


def test_file_info_table(workspace):
    import hashlib
    md = Codecheck().csv_files(file_info=True).data
    small = section(md, 'small.csv')
    assert hashlib.sha256((workspace / 'outputs' / 'small.csv').read_bytes()).hexdigest() in small
    assert "Lines | 3" in small
    assert "Columns | 2" in small
    assert "Size (b) | 12" in small


def test_wide_csv_reports_total_columns(workspace):
    wide = section(Codecheck().csv_files(max_cols=10, file_info=True).data, 'wide.csv')
    assert "Columns | 2,000" in wide
    assert "Lines | 21" in wide


def test_describe_can_be_disabled_and_head_enabled(workspace):
    md = Codecheck().csv_files(describe=False, head=2, max_cols=3).data
    assert "Column summary statistics" not in md
    assert "First 2 rows" in md
    assert len(md) < 6000


def test_info_without_header_and_with_usecols(workspace):
    md = Codecheck().csv_files(header=None, usecols=[0, 1]).data
    assert "### `small.csv`" in md


def test_short_table_is_shown_completely_without_statistics(workspace):
    small = section(Codecheck().csv_files().data, 'small.csv')
    assert "**Complete table**" in small and "|   1 |   2 |" in small and "|   3 |   4 |" in small
    assert "summary statistics" not in small and "First" not in small


def test_long_table_shows_first_rows_and_statistics(workspace):
    long_section = section(Codecheck().csv_files(head=3).data, 'long.csv')
    assert "**First 3 rows**" in long_section and "|   2 |   4 |" in long_section
    assert "Column summary statistics" in long_section and "Complete table" not in long_section


@pytest.mark.parametrize('n,complete', [(19, True), (20, False)])
def test_full_rows_threshold(workspace, n, complete):
    (workspace / 'outputs' / 'small.csv').write_text("a,b\n" + "".join(f"{i},{i}\n" for i in range(n)))
    small = section(Codecheck().csv_files().data, 'small.csv')
    assert ("**Complete table**" in small) is complete
    assert ("Column summary statistics" in small) is not complete


def test_user_nrows_never_claims_a_complete_table(workspace):
    long_section = section(Codecheck().csv_files(nrows=3).data, 'long.csv')
    assert "Complete table" not in long_section and "**First 3 rows**" in long_section


def test_user_nrows_is_used_for_the_statistics(workspace):
    long_section = section(Codecheck().csv_files(nrows=30).data, 'long.csv')
    assert "Column summary statistics** (first 30 rows" in long_section
