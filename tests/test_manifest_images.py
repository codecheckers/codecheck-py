"""
Tests for image files in the manifest, using one base PNG converted to other formats (see conftest.py)
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from .conftest import RASTER_WITH_DIMENSIONS, SUPPORTED_IMAGES, section

ROOT = Path(__file__).parent.parent
from codecheck import Codecheck


def make_workspace(tmp_path, monkeypatch, image_dir, names, subdir='.codecheck'):
    """Repository with the given images in `<subdir>/outputs/` and all of them in the manifest."""
    outputs = tmp_path / subdir / 'outputs'
    outputs.mkdir(parents=True)
    for name in names:
        shutil.copy2(image_dir / name, outputs / name)
    (tmp_path / 'codecheck.yml').write_text(yaml.dump({
        'manifest': [{'file': name, 'comment': f'image {name}'} for name in names],
    }))
    monkeypatch.chdir(tmp_path / subdir)
    return tmp_path


@pytest.mark.parametrize('name', SUPPORTED_IMAGES)
def test_supported_formats_are_embedded(tmp_path, monkeypatch, image_dir, name):
    make_workspace(tmp_path, monkeypatch, image_dir, [name])
    sec = section(Codecheck().manifest_files().data, name)
    assert f"![image {name}](<outputs/{name}>)" in sec
    assert "SHA-256 | `" in sec
    assert "No preview available" not in sec


@pytest.mark.parametrize('name', RASTER_WITH_DIMENSIONS)
def test_raster_images_report_dimensions(tmp_path, monkeypatch, image_dir, name):
    make_workspace(tmp_path, monkeypatch, image_dir, [name])
    assert "Dimensions | 24 x 16 px" in section(Codecheck().manifest_files().data, name)


@pytest.mark.parametrize('name', ['vector.svg', 'doc.pdf'])
def test_svg_and_pdf_have_no_pixel_dimensions(tmp_path, monkeypatch, image_dir, name):
    make_workspace(tmp_path, monkeypatch, image_dir, [name])
    assert "Dimensions" not in section(Codecheck().manifest_files().data, name)


def test_pdf_says_that_first_page_is_shown(tmp_path, monkeypatch, image_dir):
    make_workspace(tmp_path, monkeypatch, image_dir, ['doc.pdf'])
    assert "Preview | first page" in section(Codecheck().manifest_files().data, 'doc.pdf')


@pytest.mark.parametrize('name,hint', [('scan.tiff', 'TIFF images'), ('web.webp', 'WEBP images'),
                                       ('old.bmp', 'BMP images'), ('figure.eps', 'EPS files')])
def test_formats_typst_cannot_include_only_show_info_and_hint(tmp_path, monkeypatch, image_dir, name, hint):
    make_workspace(tmp_path, monkeypatch, image_dir, [name])
    sec = section(Codecheck().manifest_files().data, name)
    assert f"Typst cannot include {hint}" in sec and "convert the figure to" in sec
    assert "![" not in sec and "SHA-256 | `" in sec


def test_postscript_is_not_called_eps(tmp_path, monkeypatch, image_dir):
    make_workspace(tmp_path, monkeypatch, image_dir, ['figure.eps'])
    shutil.copy2(image_dir / 'figure.eps', tmp_path / '.codecheck' / 'outputs' / 'figure.ps')
    (tmp_path / 'codecheck.yml').write_text(yaml.dump({'manifest': [{'file': 'figure.ps'}]}))
    sec = section(Codecheck().manifest_files().data, 'figure.ps')
    assert "No preview available for this file type" in sec and "EPS" not in sec


def test_image_without_pillow_still_embedded(tmp_path, monkeypatch, image_dir):
    """Pillow is optional: without it only the dimensions row is missing."""
    make_workspace(tmp_path, monkeypatch, image_dir, ['base.png'])
    monkeypatch.setitem(sys.modules, 'PIL', None)
    monkeypatch.setitem(sys.modules, 'PIL.Image', None)
    sec = section(Codecheck().manifest_files().data, 'base.png')
    assert "Dimensions" not in sec and "(<outputs/base.png>)" in sec


def test_alt_text_cannot_break_markdown(tmp_path, monkeypatch, image_dir):
    make_workspace(tmp_path, monkeypatch, image_dir, ['base.png'])
    (tmp_path / 'codecheck.yml').write_text(yaml.dump({
        'manifest': [{'file': 'base.png', 'comment': 'a [bracket]\nand a newline'}],
    }))
    sec = section(Codecheck().manifest_files().data, 'base.png')
    assert "![a  bracket  and a newline](<outputs/base.png>)" in sec


def test_latex_figures_includes_pdf_and_eps_only(tmp_path, monkeypatch, image_dir):
    make_workspace(tmp_path, monkeypatch, image_dir, ['doc.pdf', 'figure.eps', 'base.png'])
    md = Codecheck().latex_figures().data
    assert "outputs/doc.pdf" in md and "outputs/figure.eps" in md and "base.png" not in md
    assert "base.png" in Codecheck().latex_figures(extensions=('.png',)).data


@pytest.mark.skipif(
    shutil.which('typst') is None or shutil.which('jupyter') is None,
    reason="typst and jupyter are required",
)
def test_all_supported_formats_in_pdf(tmp_path, image_dir):
    """Build a real certificate with every supported format (and a file name with a space) and check the PDF."""
    names = SUPPORTED_IMAGES + ['scan.tiff', 'figure.eps']
    repo = tmp_path / 'repo'
    outputs = repo / '.codecheck' / 'outputs'
    outputs.mkdir(parents=True)
    for name in ['codecheck.ipynb', 'codecheck.typ', 'codecheck_logo.svg', 'notebook_to_pdf.sh']:
        shutil.copy2(ROOT / '.codecheck' / name, repo / '.codecheck' / name)
    for src in (ROOT / '.codecheck').glob('*.py'):
        shutil.copy2(src, repo / '.codecheck' / src.name)
    for name in names:
        shutil.copy2(image_dir / name, outputs / name)
    shutil.copy2(image_dir / 'base.png', outputs / 'with space.png')

    (repo / 'codecheck.yml').write_text(yaml.dump({
        'version': 'https://codecheck.org.uk/spec/config/1.0/',
        'certificate': '2025-001',
        'report': 'https://doi.org/10.5281/zenodo.1234567',
        'paper': {'title': 'A paper', 'authors': [{'name': 'Author', 'ORCID': '0000-0002-0024-5046'}],
                  'reference': 'https://doi.org/10.1234/paper'},
        'repository': 'https://github.com/example/repo',
        'check_time': '2025-01-02T10:00:00',
        'summary': 'Everything reproduced.',
        'codechecker': [{'name': 'Checker', 'ORCID': '0000-0001-8607-8025'}],
        'manifest': [{'file': n, 'comment': f'image {n}'} for n in names + ['with space.png']],
    }))

    result = subprocess.run(['sh', 'notebook_to_pdf.sh'], cwd=repo / '.codecheck',
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    pdf = repo / '.codecheck' / 'codecheck.pdf'
    assert pdf.read_bytes().startswith(b'%PDF')
    # every image is embedded as an image object in the PDF (guard against silently dropped images)
    data = pdf.read_bytes()
    # png, jpg, jpeg, gif and 'with space.png' are raster images, each of them must be in the PDF
    assert data.count(b'/Subtype /Image') + data.count(b'/Subtype/Image') >= 5
