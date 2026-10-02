"""
Tests that follow the README quick start (issue #16): the documented files must
exist in `.codecheck/` and the documented workflow must produce a PDF.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
README = (ROOT / 'README.md').read_text()


def documented_template_files():
    """File names matched by the `cp .../.codecheck/*.{a,b,c} .codecheck/` line in the README."""
    match = re.search(r'\.codecheck/\*\.\{([^}]+)\} \.codecheck/', README)
    assert match, "README must document which .codecheck/ files to copy"
    return sorted(p.name for ext in match.group(1).split(',') for p in (ROOT / '.codecheck').glob(f'*.{ext}'))


def test_documented_files_include_the_template():
    assert {'codecheck.py', 'codecheck.ipynb', 'codecheck.typ', 'codecheck_logo.svg', 'notebook_to_pdf.sh',
            'register.py'} <= set(documented_template_files())


def test_readme_run_command_points_to_existing_script():
    assert 'sh notebook_to_pdf.sh' in README
    assert (ROOT / '.codecheck' / 'notebook_to_pdf.sh').is_file()


def test_typst_is_in_environment():
    env = yaml.safe_load((ROOT / 'environment.yml').read_text())
    assert any(str(d).split()[0].startswith('typst') for d in env['dependencies'])


@pytest.mark.skipif(
    shutil.which('typst') is None or shutil.which('jupyter') is None,
    reason="typst and jupyter are required",
)
def test_quickstart_creates_pdf(tmp_path):
    """Copy only the documented files into <repo>/.codecheck/ and build the PDF."""
    repo = tmp_path / 'repo'
    outputs = repo / '.codecheck' / 'outputs'
    outputs.mkdir(parents=True)
    for name in documented_template_files():
        shutil.copy2(ROOT / '.codecheck' / name, repo / '.codecheck' / name)

    (outputs / 'results.csv').write_text('a,b\n1,2\n3,4\n')
    (outputs / 'results.tsv').write_text('a\tb\n1\t2\n')
    (outputs / 'run.log').write_text('started\n' * 200)
    (outputs / 'stats.json').write_text('{"mean": 1.5}')
    (outputs / 'plot.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"><rect width="20" height="10" fill="red"/></svg>')
    (repo / 'codecheck.yml').write_text(yaml.dump({
        'version': 'https://codecheck.org.uk/spec/config/2.0/',
        'certificate': '2025-001',
        'report': 'https://doi.org/10.5281/zenodo.1234567',
        'paper': {
            'title': 'A paper',
            'authors': [{'name': 'Author', 'ORCID': '0000-0002-0024-5046'}],
            'reference': 'https://doi.org/10.1234/paper',
        },
        'repository': 'https://github.com/example/repo',
        'check_time': '2025-01-02T10:00:00',
        'summary': 'Everything reproduced.',
        'codechecker': [{'name': 'Checker', 'ORCID': '0000-0001-8607-8025'}],
        'manifest': [
            {'file': 'results.csv', 'comment': 'results'},
            {'file': 'results.tsv', 'comment': 'tab separated'},
            {'file': 'run.log', 'comment': 'terminal output'},
            {'file': 'stats.json', 'comment': 'statistics'},
            {'file': 'plot.svg', 'comment': 'a figure'},
            {'file': 'not_reproduced.png', 'comment': 'this file is missing'},
        ],
    }))

    result = subprocess.run(
        ['sh', 'notebook_to_pdf.sh'], cwd=repo / '.codecheck',
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / '.codecheck' / 'codecheck.pdf').stat().st_size > 0

    if os.getenv('CI') == 'true':  # keep the certificate as CI artifact
        artifact_dir = ROOT / 'test-artifacts'
        artifact_dir.mkdir(exist_ok=True)
        shutil.copy2(repo / '.codecheck' / 'codecheck.pdf', artifact_dir / 'test-codecheck-certificate.pdf')
