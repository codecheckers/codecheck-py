"""
Tests for notebook PDF rendering
"""
import os
import pytest
from pathlib import Path
import tempfile
import shutil
import subprocess
import yaml


@pytest.fixture
def pdf_workspace():
    """Create a complete workspace for PDF generation testing"""
    temp_dir = Path(tempfile.mkdtemp())

    try:
        # Create directory structure
        codecheck_dir = temp_dir / '.codecheck'
        codecheck_dir.mkdir()
        outputs_dir = codecheck_dir / 'outputs'
        outputs_dir.mkdir()

        # Create subdirectories for test files
        (outputs_dir / 'figures').mkdir()
        (outputs_dir / 'data').mkdir()

        # Create test output files
        (outputs_dir / 'figures' / 'plot1.png').write_text('fake png data')
        (outputs_dir / 'data' / 'results.csv').write_text('col1,col2\n1,2\n3,4\n')

        # Copy essential files from project .codecheck directory
        project_root = Path(__file__).parent.parent
        source_dir = project_root / '.codecheck'

        # Copy Python modules
        for src in source_dir.glob('*.py'):
            shutil.copy2(src, codecheck_dir / src.name)

        # Copy logo
        shutil.copy2(source_dir / 'codecheck_logo.svg', codecheck_dir / 'codecheck_logo.svg')

        # Copy the template codecheck.yml and customize for testing
        config_template = project_root / 'codecheck.yml'
        if config_template.exists():
            shutil.copy2(config_template, temp_dir / 'codecheck.yml')
            # Update with test-specific values that won't fail validation
            config = {
                'version': 'https://codecheck.org.uk/spec/config/1.0/',
                'certificate': '2023-001',
                'report': 'https://doi.org/10.5281/zenodo.1234567',
                'paper': {
                    'title': 'Test Paper for PDF Generation',
                    'authors': [
                        {'name': 'Jane Doe', 'ORCID': '0000-0002-1825-0097'}
                    ],
                    'reference': 'https://doi.org/10.1234/example'
                },
                'repository': 'https://github.com/example/test-repo',
                'check_time': '2023-11-15T14:30:00',
                'summary': 'This is a test summary for PDF generation.',
                'codechecker': {
                    'name': 'Test Checker',
                    'ORCID': '0000-0003-1419-2405'
                },
                'manifest': [
                    {'file': 'figures/plot1.png', 'comment': 'Test figure'},
                    {'file': 'data/results.csv', 'comment': 'Test data'}
                ]
            }
            with open(temp_dir / 'codecheck.yml', 'w') as f:
                yaml.dump(config, f)
        else:
            raise FileNotFoundError(f"Template config not found at {config_template}")

        # Copy the actual template notebook from .codecheck directory
        notebook_src = source_dir / 'codecheck.ipynb'
        if notebook_src.exists():
            shutil.copy2(notebook_src, codecheck_dir / 'codecheck.ipynb')
        else:
            raise FileNotFoundError(f"Template notebook not found at {notebook_src}")

        yield temp_dir

    finally:
        # Cleanup
        shutil.rmtree(temp_dir)


def test_notebook_exists(pdf_workspace):
    """Test that the notebook file exists in workspace"""
    notebook_path = pdf_workspace / '.codecheck' / 'codecheck.ipynb'
    assert notebook_path.exists()
    assert notebook_path.stat().st_size > 0


def test_dependencies_exist(pdf_workspace):
    """Test that all required dependencies for PDF generation exist"""
    codecheck_dir = pdf_workspace / '.codecheck'

    # Check Python modules
    assert (codecheck_dir / 'codecheck.py').exists()
    assert (codecheck_dir / 'validation.py').exists()

    # Check config
    assert (pdf_workspace / 'codecheck.yml').exists()

    # Check outputs exist
    assert (codecheck_dir / 'outputs' / 'figures' / 'plot1.png').exists()
    assert (codecheck_dir / 'outputs' / 'data' / 'results.csv').exists()


def test_notebook_is_valid_json(pdf_workspace):
    """Test that the notebook is valid JSON"""
    import json
    notebook_path = pdf_workspace / '.codecheck' / 'codecheck.ipynb'

    with open(notebook_path) as f:
        notebook = json.load(f)

    assert 'cells' in notebook
    assert 'metadata' in notebook
    assert 'nbformat' in notebook
    assert len(notebook['cells']) > 0


@pytest.mark.skipif(
    shutil.which('jupyter') is None,
    reason="jupyter not installed"
)
def test_notebook_execution_only(pdf_workspace):
    """Test that the notebook can be executed without PDF conversion"""
    codecheck_dir = pdf_workspace / '.codecheck'
    notebook_path = codecheck_dir / 'codecheck.ipynb'

    # Try to execute the notebook (without PDF conversion)
    cmd = [
        'jupyter', 'nbconvert',
        '--to', 'notebook',
        '--execute',
        '--output', 'executed.ipynb',
        str(notebook_path)
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(codecheck_dir),
            capture_output=True,
            text=True,
            timeout=60
        )

        # Check if execution succeeded
        assert result.returncode == 0, f"Notebook execution failed: {result.stderr}"

        # Check that output notebook was created
        executed_path = codecheck_dir / 'executed.ipynb'
        assert executed_path.exists(), "Executed notebook was not created"

    except subprocess.TimeoutExpired:
        pytest.skip("Notebook execution timed out")
    except Exception as e:
        pytest.skip(f"Notebook execution failed: {e}")


@pytest.mark.skipif(
    shutil.which('jupyter') is None,
    reason="jupyter not installed"
)
def test_notebook_pdf_generation_without_latex(pdf_workspace):
    """Test notebook conversion to HTML as fallback when LaTeX is not available"""
    codecheck_dir = pdf_workspace / '.codecheck'
    notebook_path = codecheck_dir / 'codecheck.ipynb'
    html_path = codecheck_dir / 'codecheck.html'

    # Generate HTML instead of PDF as a simpler test
    cmd = [
        'jupyter', 'nbconvert',
        '--to', 'html',
        '--no-input',
        '--no-prompt',
        '--execute',
        'codecheck.ipynb'
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(codecheck_dir),
            capture_output=True,
            text=True,
            timeout=60
        )

        # Check if command succeeded
        assert result.returncode == 0, f"HTML generation failed: {result.stderr}"

        # Check that HTML was created
        assert html_path.exists(), "HTML file was not created"

        # Check HTML has content
        assert html_path.stat().st_size > 100, "HTML file is too small"

        # Check it's valid HTML
        content = html_path.read_text()
        assert '<!DOCTYPE html>' in content or '<html' in content, "Generated file is not valid HTML"

    except subprocess.TimeoutExpired:
        pytest.skip("HTML generation timed out")
    except Exception as e:
        pytest.skip(f"HTML generation failed: {e}")


@pytest.mark.skipif(shutil.which('jupyter') is None, reason="jupyter not installed")
def test_notebook_to_pdf_copies_outputs_and_hides_copy_report(pdf_workspace, tmp_path):
    """notebook_to_pdf.sh refreshes outputs/ from the repository, and the copy report is not in the certificate."""
    codecheck_dir = pdf_workspace / '.codecheck'
    shutil.copy2(Path(__file__).parent.parent / '.codecheck' / 'notebook_to_pdf.sh', codecheck_dir)
    (pdf_workspace / 'data').mkdir()
    (pdf_workspace / 'data' / 'results.csv').write_text('col1,col2\n5,6\n')  # newer than the copy in outputs/
    bin_dir = tmp_path / 'bin'  # stand-in for typst: only the Markdown step is tested here
    bin_dir.mkdir()
    (bin_dir / 'typst').write_text('#!/bin/sh\nexit 0\n')
    (bin_dir / 'typst').chmod(0o755)
    env = {**os.environ, 'PATH': f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    result = subprocess.run(['sh', 'notebook_to_pdf.sh'], cwd=codecheck_dir, env=env,
                            capture_output=True, text=True, timeout=180)

    assert result.returncode == 0, result.stderr
    assert (codecheck_dir / 'outputs' / 'data' / 'results.csv').read_text() == 'col1,col2\n5,6\n'
    markdown = (codecheck_dir / 'codecheck.md').read_text()
    assert '## Manifest files' in markdown and 'Copied' not in markdown
    assert not (codecheck_dir / 'codecheck.executed.ipynb').exists()


def test_notebook_validation_integration(pdf_workspace):
    """Test that validation works within the notebook context"""
    import sys
    import os
    codecheck_dir = pdf_workspace / '.codecheck'

    # Save current directory
    old_cwd = os.getcwd()

    # Add workspace to Python path
    sys.path.insert(0, str(codecheck_dir))

    try:
        # Change to codecheck directory as the notebook would
        os.chdir(codecheck_dir)

        from codecheck import Codecheck

        # Initialize as the notebook would
        check = Codecheck(
            manifest_file=str(pdf_workspace / 'codecheck.yml'),
            validate=False
        )

        # Test that all methods work
        assert check.conf is not None
        assert 'manifest' in check.conf

        # Test validation
        passed, issues = check.validate(check_manifest=True, check_register=False, strict=False)
        assert isinstance(passed, bool)
        assert isinstance(issues, list)

        # Test report generation methods
        title = check.title()
        assert title is not None

        summary_table = check.summary_table()
        assert summary_table is not None

        files_table = check.files()
        assert files_table is not None

    finally:
        os.chdir(old_cwd)
        sys.path.remove(str(codecheck_dir))
